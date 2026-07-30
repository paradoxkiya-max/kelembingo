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
import logging
import requests

logger = logging.getLogger(__name__)


# ── Snapshot ──────────────────────────────────────────────────────
class GatewayDocSnapshot:
    def __init__(self, doc_id: str, data: dict, exists: bool = True):
        self.id = str(doc_id)
        self._data = data or {}
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
        """Read doc inside transaction — just delegates to ref.get()."""
        return ref.get()

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
    def __init__(self, collection: str, doc_id: str, gateway_url: str, api_key: str = ""):
        self.collection = collection
        self.id = str(doc_id)
        self.doc_id = str(doc_id)
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-Internal-Key"] = self.api_key
        return h

    def get(self, transaction=None, **kwargs):
        """Fetch document. The `transaction` kwarg is accepted (and ignored)
        for compatibility with firestore transactional patterns."""
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=10)
            if r.status_code == 200:
                body = r.json()
                return GatewayDocSnapshot(body.get("id", self.id), body.get("data", {}), True)
            return GatewayDocSnapshot(self.id, {}, False)
        except Exception as e:
            logger.error(f"GatewayDocRef.get {self.collection}/{self.id}: {e}")
            return GatewayDocSnapshot(self.id, {}, False)

    def set(self, data, merge=False):
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        try:
            payload_data = _prepare_data_for_json(data)
            r = requests.post(url, json={"data": payload_data, "merge": merge}, headers=self._headers(), timeout=10)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"GatewayDocRef.set {self.collection}/{self.id}: {e}")

    def update(self, data):
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        try:
            payload_data = _prepare_data_for_json(data)
            r = requests.patch(url, json={"data": payload_data}, headers=self._headers(), timeout=10)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"GatewayDocRef.update {self.collection}/{self.id}: {e}")

    def delete(self):
        url = f"{self.gateway_url}/api/db/{self.collection}/{self.id}"
        try:
            requests.delete(url, headers=self._headers(), timeout=10)
        except Exception as e:
            logger.error(f"GatewayDocRef.delete {self.collection}/{self.id}: {e}")


# ── Collection Reference / Query ─────────────────────────────────
class GatewayCollectionRef:
    def __init__(self, collection: str, gateway_url: str, api_key: str = "",
                 filters=None, order_field=None, order_dir="ASCENDING", limit_n=None):
        self.collection = collection
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key
        self._filters = filters or []
        self._order_field = order_field
        self._order_dir = order_dir
        self._limit_n = limit_n

    def _headers(self):
        h = {}
        if self.api_key:
            h["X-Internal-Key"] = self.api_key
        return h

    def document(self, doc_id: str = None):
        if not doc_id:
            import uuid
            doc_id = str(uuid.uuid4())
        return GatewayDocRef(self.collection, str(doc_id), self.gateway_url, self.api_key)

    def doc(self, doc_id: str = None):
        return self.document(doc_id)

    # ── Chaining (immutable — each returns a NEW ref) ─────────────
    def where(self, field, op, value):
        new_filters = list(self._filters) + [[field, op, value]]
        return GatewayCollectionRef(
            self.collection, self.gateway_url, self.api_key,
            filters=new_filters, order_field=self._order_field,
            order_dir=self._order_dir, limit_n=self._limit_n,
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
        )

    def limit(self, n):
        return GatewayCollectionRef(
            self.collection, self.gateway_url, self.api_key,
            filters=self._filters, order_field=self._order_field,
            order_dir=self._order_dir, limit_n=n,
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
        url = self._build_url()
        try:
            r = requests.get(url, headers=self._headers(), timeout=15)
            if r.status_code == 200:
                docs = r.json()
                if isinstance(docs, list):
                    return [GatewayDocSnapshot(d.get("id"), d.get("data", {}), True) for d in docs]
            return []
        except Exception as e:
            logger.error(f"GatewayCollectionRef.get {self.collection}: {e}")
            return []

    def stream(self):
        """Alias for get() — bots use .stream() like an iterator."""
        return self.get()


# ── Client ───────────────────────────────────────────────────────
class GatewayClient:
    def __init__(self, gateway_url: str = None, api_key: str = None):
        self.gateway_url = (
            gateway_url or os.getenv("GATEWAY_URL", "https://kelembingo-gateway-gjfl.onrender.com")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("INTERNAL_API_KEY", "")

    def collection(self, name: str):
        return GatewayCollectionRef(name, self.gateway_url, self.api_key)

    def transaction(self):
        return GatewayTransaction(self.gateway_url, self.api_key)
