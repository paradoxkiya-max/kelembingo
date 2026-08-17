"""
GatewayClient — REST bridge so kelembingo-bots can read/write
the Gateway's SQLite database over HTTP.

Supports every DB pattern the bot code uses:
  db.collection('x').document('y').get()
  db.collection('x').document('y').get(transaction=txn)
  db.collection('x').document('y').set({...})
  db.collection('x').document('y').update({...})
  db.collection('x').where(...).order_by(...).limit(N).get()
  db.collection('x').where(...).order_by(...).limit(N).stream()
  db.transaction()  /  @firestore.transactional
"""
import os
import json
import time
import hashlib
import threading
import logging
import requests
from urllib.parse import quote

logger = logging.getLogger(__name__)


class GatewayUnavailableError(Exception):
    """The Gateway could not be reached (connection error, timeout, or 5xx).

    Raised after bounded retries so callers distinguish a real outage from a
    missing document instead of silently treating every failure as 'not exists'
    (which could trigger destructive merge=False writes).
    """


_RETRYABLE_STATUS = {500, 502, 503, 504}
_MAX_RETRIES = 3
_RETRY_BACKOFF = [0.5, 1.0, 2.0]

_gateway_down = False
_gw_lock = threading.Lock()


def _set_gateway_down(down: bool):
    global _gateway_down
    with _gw_lock:
        _gateway_down = down


def is_gateway_down() -> bool:
    global _gateway_down
    with _gw_lock:
        return _gateway_down


def _request_with_retry(method: str, url: str, *, json=None, headers=None, timeout=15):
    """Issue a request with bounded retries on connection errors/timeouts/5xx.

    Returns the final Response on success (HTTP < 500). Raises
    GatewayUnavailableError after exhausting retries.
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = requests.request(method, url, json=json, headers=headers, timeout=timeout)
            if r.status_code < 500:
                _set_gateway_down(False)
                return r
            last_exc = GatewayUnavailableError(
                f"Gateway {method} {url} -> HTTP {r.status_code}"
            )
            logger.warning(f"Gateway {method} {url} -> HTTP {r.status_code} (attempt {attempt + 1}/{_MAX_RETRIES})")
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = GatewayUnavailableError(f"Gateway {method} {url} unreachable: {e}")
            logger.warning(f"Gateway {method} {url} error (attempt {attempt + 1}/{_MAX_RETRIES}): {e}")
        if attempt < _MAX_RETRIES - 1:
            time.sleep(_RETRY_BACKOFF[attempt])
    _set_gateway_down(True)
    raise last_exc


class CacheStore:
    """Thread-safe TTL cache used to cut HTTP round-trips to the Gateway.

    - Entries expire after a per-collection TTL (in seconds).
    - Writes invalidate the affected doc + all query results for that collection.
    - Bounded size: expired entries are purged first, then the oldest entry.
    """

    def __init__(self, max_entries: int = 2000, log_interval: int = 500):
        self._max = max_entries
        self._log_interval = log_interval
        self._lock = threading.Lock()
        self._data = {}  # key -> (expires_at, value)
        self._hits = 0
        self._misses = 0
        self._ops = 0

    def get(self, key):
        with self._lock:
            self._ops += 1
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires_at, value = entry
            if expires_at < time.time():
                del self._data[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key, value, ttl: float):
        if ttl <= 0:
            return
        with self._lock:
            self._data[key] = (time.time() + ttl, value)
            if len(self._data) > self._max:
                self._evict_locked()

    def _evict_locked(self):
        now = time.time()
        expired = [k for k, (exp, _) in self._data.items() if exp < now]
        for k in expired:
            del self._data[k]
        while len(self._data) > self._max:
            oldest = min(self._data.items(), key=lambda kv: kv[1][0])
            del self._data[oldest[0]]

    def invalidate_prefix(self, prefix: str):
        with self._lock:
            keys = [k for k in self._data if k.startswith(prefix)]
            for k in keys:
                del self._data[k]

    def invalidate_collection(self, collection: str, doc_id: str = None):
        self.invalidate_prefix(f"doc:{collection}:{doc_id}" if doc_id else f"doc:{collection}:")
        self.invalidate_prefix(f"query:{collection}:")

    def clear(self):
        with self._lock:
            self._data.clear()

    def stats(self):
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._data),
                "hit_rate": (self._hits / self._ops) if self._ops else 0.0,
            }

    def maybe_log_stats(self):
        if self._log_interval <= 0:
            return
        with self._lock:
            if self._ops < self._log_interval:
                return
            self._ops = 0
            hits, misses = self._hits, self._misses
            self._hits, self._misses = 0, 0
        total = hits + misses
        if total:
            logger.info(f"🛰️  Gateway cache: {hits} hits / {misses} misses ({100.0 * hits / total:.0f}% hit rate)")


def _cache_key_for_doc(collection: str, doc_id: str):
    return f"doc:{collection}:{doc_id}"


def normalize_doc(data):
    if isinstance(data, dict):
        if ('__type' in data or '_type' in data) and 'value' in data:
            val = data['value']
            return float(val) if isinstance(val, (int, float)) else val
        return {k: normalize_doc(v) for k, v in data.items()}
    if isinstance(data, list):
        return [normalize_doc(v) for v in data]
    return data


# ── Snapshot ──────────────────────────────────────────────────────
class GatewayDocSnapshot:
    def __init__(self, doc_id: str, data: dict, exists: bool = True):
        self.id = str(doc_id)
        self._data = normalize_doc(data or {})
        self.exists = exists

    def to_dict(self):
        return self._data

    def get(self, field, default=None):
        return self._data.get(field, default)


# ── Transaction (simple sequential read-then-write) ──────────────
class GatewayTransaction:
    """Lightweight transaction facade.
    The admin_bot uses @firestore.transactional which passes a
    transaction object.  Our implementation just does normal
    REST calls sequentially (acceptable for low-concurrency bot ops).
    """

    class _NoOpSession:
        """Fake session so firestore_db.transactional()'s commit/rollback/close calls are safe."""
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    def __init__(self, gateway_url: str, api_key: str):
        self._gw = gateway_url
        self._key = api_key
        self._session = self._NoOpSession()

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self._key:
            h["X-Internal-Key"] = self._key
        return h

    def get(self, ref):
        """Read doc inside transaction — bypasses the read cache for correctness."""
        return ref.get(transaction=self)

    def update(self, ref, data):
        """Write doc inside transaction — just delegates to ref.update()."""
        return ref.update(data)

    def set(self, ref, data, merge=False):
        return ref.set(data, merge=merge)


def _prepare_data_for_json(data):
    if not isinstance(data, dict):
        return data
    cleaned = {}
    for k, v in data.items():
        if hasattr(v, 'value') and type(v).__name__ == 'Increment':
            cleaned[k] = {"_type": "Increment", "value": v.value}
        elif hasattr(v, 'isoformat'):
            cleaned[k] = v.isoformat()
        elif isinstance(v, dict):
            cleaned[k] = _prepare_data_for_json(v)
        else:
            cleaned[k] = v
    return cleaned


# ── Document Reference ───────────────────────────────────────────
class GatewayDocRef:
    def __init__(self, collection: str, doc_id: str, gateway_url: str, api_key: str = "",
                 cache: CacheStore = None, collection_ttl: dict = None):
        self.collection = collection
        self.id = str(doc_id)
        self.doc_id = str(doc_id)
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key
        self.cache = cache
        self.collection_ttl = collection_ttl or {}

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-Internal-Key"] = self.api_key
        return h

    def _ttl(self):
        return self.collection_ttl.get(self.collection, 0)

    def _invalidate(self):
        if self.cache:
            self.cache.invalidate_collection(self.collection, self.id)

    def get(self, transaction=None, **kwargs):
        """Fetch document. The `transaction` kwarg is accepted for compatibility
        with firestore transactional patterns — transactional reads bypass the cache.

        Only HTTP 404 means "not exists". Connection errors / timeouts / 5xx
        raise GatewayUnavailableError after bounded retries so callers never
        mistake an outage for a missing document.
        """
        ttl = self._ttl()
        use_cache = self.cache is not None and ttl > 0 and transaction is None
        cache_key = _cache_key_for_doc(self.collection, self.id)
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        r = _request_with_retry("GET", url, headers=self._headers(), timeout=10)
        if r.status_code == 200:
            body = r.json()
            snap = GatewayDocSnapshot(body.get("id", self.id), body.get("data", {}), True)
            if use_cache:
                self.cache.set(cache_key, snap, ttl)
            return snap
        if r.status_code == 404:
            _set_gateway_down(False)
            return GatewayDocSnapshot(self.id, {}, False)
        raise GatewayUnavailableError(
            f"Gateway GET {url} -> HTTP {r.status_code}"
        )

    def set(self, data, merge=False):
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        payload_data = _prepare_data_for_json(data)
        r = _request_with_retry(
            "POST", url,
            json={"data": payload_data, "merge": merge},
            headers=self._headers(), timeout=10,
        )
        r.raise_for_status()
        self._invalidate()

    def update(self, data):
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        payload_data = _prepare_data_for_json(data)
        r = _request_with_retry(
            "PATCH", url,
            json={"data": payload_data},
            headers=self._headers(), timeout=10,
        )
        r.raise_for_status()
        self._invalidate()

    def delete(self):
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        r = _request_with_retry("DELETE", url, headers=self._headers(), timeout=10)
        r.raise_for_status()
        self._invalidate()


# ── Collection Reference / Query ─────────────────────────────────
class GatewayCollectionRef:
    def __init__(self, collection: str, gateway_url: str, api_key: str = "",
                 filters=None, order_field=None, order_dir="ASCENDING", limit_n=None,
                 cache: CacheStore = None, collection_ttl: dict = None):
        self.collection = collection
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key
        self.cache = cache
        self.collection_ttl = collection_ttl or {}
        self._filters = filters or []
        self._order_field = order_field
        self._order_dir = order_dir
        self._limit_n = limit_n

    def _headers(self):
        h = {}
        if self.api_key:
            h["X-Internal-Key"] = self.api_key
        return h

    def _ttl(self):
        return self.collection_ttl.get(self.collection, 0)

    def _query_hash(self):
        return hashlib.md5(self._build_url().encode()).hexdigest()[:16]

    def document(self, doc_id: str = None):
        if not doc_id:
            import uuid
            doc_id = str(uuid.uuid4())
        return GatewayDocRef(self.collection, str(doc_id), self.gateway_url, self.api_key,
                             cache=self.cache, collection_ttl=self.collection_ttl)

    def doc(self, doc_id: str = None):
        return self.document(doc_id)

    # ── Chaining (immutable — each returns a NEW ref) ─────────────
    def where(self, field, op, value):
        new_filters = list(self._filters) + [[field, op, value]]
        return GatewayCollectionRef(
            self.collection, self.gateway_url, self.api_key,
            filters=new_filters, order_field=self._order_field,
            order_dir=self._order_dir, limit_n=self._limit_n,
            cache=self.cache, collection_ttl=self.collection_ttl,
        )

    def order_by(self, field, direction="ASCENDING"):
        d = direction
        if isinstance(d, str) and d.lower() == "descending":
            d = "DESCENDING"
        elif isinstance(d, str) and d.lower() in ("desc",):
            d = "DESCENDING"
        return GatewayCollectionRef(
            self.collection, self.gateway_url, self.api_key,
            filters=self._filters, order_field=field,
            order_dir=d, limit_n=self._limit_n,
            cache=self.cache, collection_ttl=self.collection_ttl,
        )

    def limit(self, n):
        return GatewayCollectionRef(
            self.collection, self.gateway_url, self.api_key,
            filters=self._filters, order_field=self._order_field,
            order_dir=self._order_dir, limit_n=n,
            cache=self.cache, collection_ttl=self.collection_ttl,
        )

    # ── Fetch ─────────────────────────────────────────────────────
    def _build_url(self):
        url = f"{self.gateway_url}/api/db/{self.collection}"
        params = {}
        if self._filters:
            params["filters"] = json.dumps(self._filters)
        if self._order_field:
            params["order_by"] = self._order_field
            params["order_dir"] = self._order_dir
        if self._limit_n is not None:
            params["limit_n"] = str(self._limit_n)
        if params:
            qs = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
            url = f"{url}?{qs}"
        return url

    def get(self):
        ttl = self._ttl()
        use_cache = self.cache is not None and ttl > 0
        cache_key = f"query:{self.collection}:{self._query_hash()}"
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        url = self._build_url()
        r = _request_with_retry("GET", url, headers=self._headers(), timeout=15)
        if r.status_code == 200:
            docs = r.json()
            if isinstance(docs, list):
                result = [GatewayDocSnapshot(d.get("id"), d.get("data", {}), True) for d in docs]
                if use_cache:
                    self.cache.set(cache_key, result, ttl)
                return result
            return []
        if r.status_code == 404:
            _set_gateway_down(False)
            return []
        raise GatewayUnavailableError(
            f"Gateway GET {url} -> HTTP {r.status_code}"
        )

    def stream(self):
        """Alias for get() — bots use .stream() like an iterator."""
        return self.get()


# ── Client ───────────────────────────────────────────────────────
class GatewayClient:
    # Per-collection read cache TTL (seconds). 0 = no caching.
    # Financial collections (deposits/withdrawals) are deliberately uncached.
    # Can be overridden per collection via env vars, e.g. CACHE_TTL_USERS=5.
    DEFAULT_COLLECTION_TTL = {
        'users': 10,
        'bot_content': 60,
        'system': 20,
        'support_users': 10,
        'support_tickets': 5,
        'rounds': 3,
        'cartelas_master': 3600,
        'cartelas': 3600,
        'settings': 60,
        'games': 10,
        'deposits': 0,
        'withdrawals': 0,
    }

    def __init__(self, gateway_url: str = None, api_key: str = None):
        self.gateway_url = (
            gateway_url or os.getenv("GATEWAY_URL", "https://kelembingo-sqnv.onrender.com")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("INTERNAL_API_KEY", "")
        self.cache = CacheStore(
            max_entries=int(os.getenv("GATEWAY_CACHE_MAX_ENTRIES", "2000")),
            log_interval=int(os.getenv("GATEWAY_CACHE_LOG_INTERVAL", "500")),
        )
        self.collection_ttl = dict(self.DEFAULT_COLLECTION_TTL)
        for name, ttl in self.DEFAULT_COLLECTION_TTL.items():
            env_key = f"CACHE_TTL_{name.upper()}"
            if os.getenv(env_key):
                try:
                    self.collection_ttl[name] = max(0, int(os.getenv(env_key)))
                except ValueError:
                    logger.warning(f"Invalid {env_key}: {os.getenv(env_key)}")

    def collection(self, name: str):
        return GatewayCollectionRef(name, self.gateway_url, self.api_key,
                                    cache=self.cache, collection_ttl=self.collection_ttl)

    def transaction(self):
        return GatewayTransaction(self.gateway_url, self.api_key)

    def cache_stats(self):
        return self.cache.stats()

    def is_gateway_down(self) -> bool:
        """True if the most recent request to the gateway failed with a network/5xx error."""
        return is_gateway_down()

    def _settle(self, collection: str, document_id: str, status: str, note: str = "") -> dict:
        path = f"/api/internal/settlements/{collection}/{quote(str(document_id), safe='')}/{status}"
        if note:
            path += "?note=" + quote(str(note), safe="")
        response = _request_with_retry(
            "POST",
            f"{self.gateway_url}{path}",
            headers={"Content-Type": "application/json", "X-Internal-Key": self.api_key},
            timeout=20,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"ok": False, "error": response.text[:200]}
        if response.status_code >= 400:
            raise GatewayUnavailableError(payload.get("detail", "Gateway settlement failed"))
        return payload

    def _internal_post(self, path: str, payload: dict) -> dict:
        response = _request_with_retry(
            "POST",
            f"{self.gateway_url}{path}",
            json=_prepare_data_for_json(payload),
            headers={"Content-Type": "application/json", "X-Internal-Key": self.api_key},
            timeout=20,
        )
        try:
            result = response.json()
        except ValueError:
            result = {"ok": False, "error": response.text[:200]}
        if response.status_code >= 400:
            raise GatewayUnavailableError(result.get("detail", "Gateway operation failed"))
        return result

    def transfer_funds(self, sender_id, recipient_id, amount, idempotency_key=None) -> dict:
        return self._internal_post("/api/internal/accounts/transfer", {
            "sender_id": str(sender_id),
            "recipient_id": str(recipient_id),
            "amount": amount,
            "idempotency_key": idempotency_key,
        })

    def convert_bonus(self, user_id, rate=10, idempotency_key=None) -> dict:
        return self._internal_post("/api/internal/accounts/convert-bonus", {
            "user_id": str(user_id),
            "rate": rate,
            "idempotency_key": idempotency_key,
        })

    def register_user(self, user_id, name, phone, telebirr_name="", idempotency_key=None) -> dict:
        return self._internal_post("/api/internal/accounts/register", {
            "user_id": str(user_id),
            "name": name,
            "phone": phone,
            "telebirr_name": telebirr_name,
            "idempotency_key": idempotency_key,
        })

    def create_withdrawal(self, withdrawal_data: dict, idempotency_key: str = None) -> dict:
        payload = _prepare_data_for_json(withdrawal_data)
        if idempotency_key:
            payload["idempotencyKey"] = idempotency_key
        response = _request_with_retry(
            "POST",
            f"{self.gateway_url}/api/internal/withdrawals/create",
            json=payload,
            headers={"Content-Type": "application/json", "X-Internal-Key": self.api_key},
            timeout=20,
        )
        try:
            result = response.json()
        except ValueError:
            result = {"ok": False, "error": response.text[:200]}
        if response.status_code >= 400:
            raise GatewayUnavailableError(result.get("detail", "Gateway withdrawal creation failed"))
        return result

    def create_deposit(self, deposit_data: dict) -> dict:
        # Telegram bot payloads include datetime values; normalize them before
        # requests/json encoding so deposit submission reaches the gateway.
        payload = _prepare_data_for_json(deposit_data)
        response = _request_with_retry(
            "POST",
            f"{self.gateway_url}/api/internal/deposits/create",
            json=payload,
            headers={"Content-Type": "application/json", "X-Internal-Key": self.api_key},
            timeout=20,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"ok": False, "error": response.text[:200]}
        if response.status_code >= 400:
            raise GatewayUnavailableError(payload.get("detail", "Gateway deposit creation failed"))
        return payload

    def settle_deposit(self, deposit_id: str, status: str, note: str = "") -> dict:
        return self._settle("deposits", deposit_id, status, note)

    def settle_withdrawal(self, withdrawal_id: str, status: str, note: str = "") -> dict:
        return self._settle("withdrawals", withdrawal_id, status, note)
