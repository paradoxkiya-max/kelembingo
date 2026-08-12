import os
import math
import random
import asyncio
import logging
import time
import socketio
import hmac
import hashlib
import secrets as _secrets
import base64
from fastapi import FastAPI, HTTPException, Query as FastAPIQuery, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import json
import datetime
import urllib.parse
from config import db, BOT_TOKEN
from firestore_db import MockFirestoreClient, SessionLocal, SystemEvent, FieldFilter, Increment, ArrayUnion

from game.round_engine import RoundEngine, DEFAULT_STAKE, VALID_STAKES, SELECTION_DURATION, GAME_LENGTH_RANGE, _parse_dt, _grid_next_number_at
from handlers.user_manager import UserManager
from handlers.bot_content import get_bot_text
from datetime import datetime, date, timedelta, timezone
from telegram import Bot
# Firebase replaced by SQLAlchemy emulator (firestore_db.py)

logger = logging.getLogger(__name__)
# Only the designated gateway service may own round progression. The existing
# in-memory task map cannot coordinate separate Render services by itself.
GAME_ENGINE_ENABLED = os.getenv("GAME_ENGINE_ENABLED", "true").lower() == "true"

# ─── Async DB Helper ───
async def _db(call):
    """Run a synchronous MockFirestore call in a thread to avoid blocking the event loop."""
    return await asyncio.to_thread(call)


ALLOWED_ORIGINS = [
    "*",
    "https://kelembingo-frontend-i8yy.onrender.com",
    "https://kelembingo-sqnv.onrender.com",
]

# Additional origins that match by suffix
ALLOWED_ORIGIN_SUFFIXES = [
    ".onrender.com",
]


# ─── Socket.IO Server ───
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

app = FastAPI(title="Kelem Bingo Admin API", version="2.0.0")



# ─── Outer CORS ASGI Middleware ───
# Wraps the ENTIRE app (including Socket.IO) so that preflight OPTIONS
# and CORS response headers work for ALL paths, not just FastAPI routes.
class CORSASGIMiddleware:
    """ASGI middleware that adds CORS headers to ALL responses.

    The Starlette CORSMiddleware only covers the inner FastAPI app,
    but socketio.ASGIApp wraps FastAPI, so preflight/OPTIONS requests
    to /socket.io/* and sometimes /api/* never reach FastAPI's middleware.
    This outer wrapper guarantees every HTTP response carries the
    correct Access-Control-* headers.
    """

    def __init__(self, app, allowed_origins, allowed_suffixes=None):
        self.app = app
        self.allowed_origins = set(allowed_origins)
        self.allowed_suffixes = tuple(allowed_suffixes or [])

    def _origin_allowed(self, origin: str) -> bool:
        if not origin:
            return False
        if origin in self.allowed_origins:
            return True
        if self.allowed_suffixes and origin.endswith(self.allowed_suffixes):
            return True
        return False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # WebSocket / lifespan — pass through unchanged
            await self.app(scope, receive, send)
            return

        # Extract Origin header from the request
        origin = ""
        for key, val in scope.get("headers", []):
            if key == b"origin":
                origin = val.decode("latin-1")
                break

        if not self._origin_allowed(origin):
            # No origin or not allowed — pass through without CORS headers
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")

        # ── Handle preflight OPTIONS ──
        if method == "OPTIONS":
            cors_headers = [
                (b"access-control-allow-origin", origin.encode()),
                (b"access-control-allow-methods", b"GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD"),
                (b"access-control-allow-headers", b"content-type, authorization, x-player-token, x-internal-key, x-requested-with, accept, origin"),
                (b"access-control-allow-credentials", b"true"),
                (b"access-control-max-age", b"86400"),
                (b"content-length", b"0"),
            ]
            await send({"type": "http.response.start", "status": 200, "headers": cors_headers})
            await send({"type": "http.response.body", "body": b""})
            return

        # ── Normal requests — inject CORS headers if not already present ──
        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}
                if b"access-control-allow-origin" not in existing:
                    headers.append((b"access-control-allow-origin", origin.encode()))
                if b"access-control-allow-credentials" not in existing:
                    headers.append((b"access-control-allow-credentials", b"true"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cors)


# Mount Socket.IO on the FastAPI app, then wrap with outer CORS
_raw_socket_app = socketio.ASGIApp(sio, app)
socket_app = CORSASGIMiddleware(_raw_socket_app, ALLOWED_ORIGINS, ALLOWED_ORIGIN_SUFFIXES)

engine = RoundEngine(db)
user_manager = UserManager(db)
MAX_SMART_CALLS = GAME_LENGTH_RANGE[1]

# ─── Auth (C1) ───
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "paradox")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "12345678")
AUTH_SECRET = os.getenv("ADMIN_AUTH_SECRET") or os.getenv("INTERNAL_API_KEY") or _secrets.token_hex(32)
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
AUTH_TOKEN_TTL = int(os.getenv("ADMIN_AUTH_TTL_HOURS", "12")) * 3600
PROTECTED_DB_COLLECTIONS = {"admins", "system", "settings", "bot_content"}
PUBLIC_ADMIN_PATHS = {"/api/admin/login"}
PUBLIC_DB_READ_COLLECTIONS = {"rounds", "cartelas_master", "cartelas"}
PLAYER_DB_QUERY_COLLECTIONS = {"deposits", "withdrawals"}


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _create_token(username: str, role: str, display_name: str = "") -> str:
    payload = {
        "u": username,
        "r": role,
        "d": display_name,
        "exp": int(time.time()) + AUTH_TOKEN_TTL,
    }
    body = _b64e(json.dumps(payload).encode())
    sig = hmac.new(AUTH_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify_token(token: str) -> Optional[dict]:
    try:
        body, sig = token.split(".")
        expected = hmac.new(AUTH_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64d(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return {"username": payload.get("u"), "role": payload.get("r", "admin"),
                "display_name": payload.get("d", "")}
    except Exception:
        return None


def _auth_ok(request: Request) -> Optional[dict]:
    ik = request.headers.get("x-internal-key", "")
    if INTERNAL_API_KEY and ik and hmac.compare_digest(ik, INTERNAL_API_KEY):
        return {"username": "internal", "role": "internal", "display_name": "Internal"}
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        admin = _verify_token(auth[7:].strip())
        if admin:
            return admin
    return None


async def require_auth(request: Request):
    admin = _auth_ok(request)
    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return admin


# ─── Player Auth (Telegram WebApp initData) ───
PLAYER_AUTH_TTL = int(os.getenv("PLAYER_AUTH_TTL_HOURS", "24")) * 3600
PLAYER_INITDATA_MAX_AGE = int(os.getenv("PLAYER_INITDATA_MAX_AGE_SECONDS", "86400"))
# Fields a player may never write directly (server-owned money/stats)
PLAYER_IMMUTABLE_USER_FIELDS = {"play_wallet", "balance", "bonus", "wins", "losses",
                                "total_games", "is_playing", "user_id"}
# Collections players may write, and only their own doc
PLAYER_WRITABLE_COLLECTIONS = {"users"}


def _verify_telegram_init_data(init_data: str) -> Optional[dict]:
    """Validate Telegram WebApp initData and return the parsed `user` dict.

    Per Telegram's official algorithm: secret_key = HMAC_SHA256("WebAppData", bot_token),
    then check_string = sorted "key=value" lines (excluding hash), verified against `hash`.
    When BOT_TOKEN is not configured (local/dev), returns the parsed user for testing.
    """
    if not init_data:
        return None
    try:
        params = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    received_hash = params.pop("hash", None)
    if not received_hash:
        return None
    auth_date_raw = params.get("auth_date")
    try:
        auth_date = int(auth_date_raw)
    except (TypeError, ValueError):
        return None
    age = time.time() - auth_date
    if age < -300 or age > PLAYER_INITDATA_MAX_AGE:
        logger.warning("[PlayerAuth] Telegram initData is outside the allowed auth_date window")
        return None
    if not BOT_TOKEN:
        allow_unverified = os.getenv("ALLOW_UNVERIFIED_INITDATA", "false").lower() == "true"
        if not allow_unverified:
            logger.error("[PlayerAuth] BOT_TOKEN is not configured; refusing unverified initData")
            return None
        logger.warning("[PlayerAuth] Accepting unverified initData because ALLOW_UNVERIFIED_INITDATA=true")
        try:
            user = json.loads(params.get("user", "{}"))
        except Exception:
            return None
        return user if user.get("id") else None
    try:
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, received_hash):
            return None
        user = json.loads(params.get("user", "{}"))
    except Exception:
        return None
    return user if user.get("id") else None


def _create_player_token(user_id: int) -> str:
    return _create_token(str(user_id), "player", "Player")


def _player_ok(request: Request) -> Optional[dict]:
    token = request.headers.get("x-player-token", "").strip()
    if not token:
        return None
    info = _verify_token(token)
    if info and info.get("role") == "player":
        try:
            uid = int(info["username"])
        except (TypeError, ValueError):
            return None
        return {"user_id": uid, "username": info["username"]}
    return None


def _auth_any(request: Request) -> Optional[dict]:
    """Accept admin/internal token OR player token. Returns an identity dict."""
    player = _player_ok(request)
    if player:
        return {"kind": "player", **player}
    admin = _auth_ok(request)
    if admin:
        return {"kind": "admin", **admin}
    return None


def _require_internal(request: Request) -> dict:
    """Require the server-to-server key; browser admin sessions are not enough."""
    identity = _auth_ok(request)
    if not identity or identity.get("role") != "internal":
        raise HTTPException(status_code=403, detail="Internal service access required")
    return identity


def _require_admin_or_internal(request: Request) -> dict:
    """Require an admin session or the server-to-server internal key."""
    identity = _auth_any(request)
    if not identity:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if identity.get("kind") != "admin" or identity.get("role") not in {"internal", "admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="Admin or internal access required")
    return identity


def _get_user_operation_lock(user_id: int) -> asyncio.Lock:
    lock = _user_operation_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_operation_locks[user_id] = lock
    return lock


def _is_banned_user(data: Optional[dict]) -> bool:
    if not isinstance(data, dict):
        return False
    return bool(data.get("banned")) or str(data.get("status", "")).lower() == "banned"


def _ensure_player_active(user_id: int) -> None:
    snap = db.collection("users").document(str(user_id)).get()
    if snap.exists and _is_banned_user(snap.to_dict()):
        raise HTTPException(status_code=403, detail="Account is banned")


def _require_player(request: Request) -> int:
    """Require a valid player token and return the verified user_id."""
    player = _player_ok(request)
    if not player:
        raise HTTPException(status_code=401, detail="Unauthorized")
    _ensure_player_active(player["user_id"])
    return player["user_id"]


def _actor_user_id(request: Request, fallback: int) -> int:
    """Return the acting user_id: player token wins; admin/internal falls back to body value."""
    identity = _auth_any(request)
    if not identity:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if identity.get("kind") == "player":
        _ensure_player_active(identity["user_id"])
        return identity["user_id"]
    return fallback


def _upsert_player_user(user: dict) -> dict:
    """Server-side create/refresh of a player's user doc (money fields untouched)."""
    uid = int(user.get("id"))
    uid_str = str(uid)
    now = datetime.now(tz=timezone.utc)
    user_ref = db.collection("users").document(uid_str)
    snap = user_ref.get()
    if snap.exists:
        existing = snap.to_dict()
        user_ref.update({
            "first_name": user.get("first_name") or existing.get("first_name", "Player"),
            "username": user.get("username") or existing.get("username", ""),
            "updated_at": now,
        })
        return existing
    user_data = {
        "user_id": uid,
        "first_name": user.get("first_name", "Player"),
        "username": user.get("username", "") or f"player{uid}",
        "phone": "",
        "balance": 0,
        "play_wallet": 0,
        "bonus": 0,
        "registered": False,
        "total_games": 0,
        "wins": 0,
        "losses": 0,
        "is_playing": False,
        "active_round_id": None,
        "created_at": now,
        "updated_at": now,
    }
    user_ref.set(user_data)
    return user_data


class PlayerAuthRequest(BaseModel):
    initData: str


@app.post("/api/player/auth")
async def player_auth(req: PlayerAuthRequest):
    """Verify Telegram initData and issue a short-lived player token."""
    user = _verify_telegram_init_data((req.initData or "").strip())
    if not user:
        raise HTTPException(status_code=401, detail="Invalid Telegram session")
    user_data = await _db(lambda: _upsert_player_user(user))
    if _is_banned_user(user_data):
        raise HTTPException(status_code=403, detail="Account is banned")
    token = _create_player_token(int(user["id"]))
    await broadcast_event("users", str(user["id"]))
    return {
        "ok": True,
        "token": token,
        "expires_in": PLAYER_AUTH_TTL,
        "user": {"id": int(user["id"]), **user_data},
    }


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    username = (req.username or "").strip()
    password = req.password or ""
    if ADMIN_PASSWORD and username == ADMIN_USERNAME and hmac.compare_digest(password, ADMIN_PASSWORD):
        return {"ok": True, "token": _create_token(username, "super_admin", "Super Admin"),
                "username": username, "role": "super_admin", "display_name": "Super Admin"}
    try:
        admins = list(db.collection("admins").where("username", "==", username).limit(1).get())
        if admins:
            ad = admins[0].to_dict()
            stored = str(ad.get("password", ""))
            pw_hash = hashlib.sha256(password.encode()).hexdigest()
            if stored and (hmac.compare_digest(stored, pw_hash) or hmac.compare_digest(stored, password)):
                role = ad.get("role", "admin")
                dn = ad.get("displayName", "") or ad.get("display_name", "") or username
                return {"ok": True, "token": _create_token(username, role, dn),
                        "username": username, "role": role, "display_name": dn}
    except Exception as e:
        logger.warning(f"Auth: admins collection check failed: {e}")
    raise HTTPException(status_code=401, detail="Invalid username or password")


@app.get("/api/auth/me")
async def auth_me(request: Request):
    admin = _auth_ok(request)
    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"ok": True, **admin}


@app.post("/api/auth/logout")
async def auth_logout():
    return {"ok": True}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    method = request.method
    needs_auth = False

    if method == "OPTIONS":
        return await call_next(request)

    if path.startswith("/api/admin"):
        if path not in PUBLIC_ADMIN_PATHS:
            needs_auth = True
    elif path.startswith("/api/rounds") and method in ("POST", "PUT", "DELETE"):
        if path.endswith(("/start", "/call", "/end")):
            needs_auth = True
        elif path.endswith(("/join", "/select", "/unselect", "/close-empty")):
            needs_auth = True
    elif path in ("/api/cartelas/generate", "/api/cartelas/reset") and method == "POST":
        needs_auth = True
    elif path.startswith("/api/notify") and method == "POST":
        needs_auth = True
    elif path == "/api/withdrawals/create" and method == "POST":
        needs_auth = True
    elif path == "/api/deposits/submit" and method == "POST":
        needs_auth = True
    elif path.startswith("/api/db") and method in ("POST", "PATCH", "PUT", "DELETE"):
        needs_auth = True

    if needs_auth:
        identity = _auth_any(request)
        if not identity:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    return await call_next(request)


@app.get("/api/time")
def get_server_time():
    """Returns the current server time in ISO format for client sync."""
    return {"iso": datetime.now(tz=timezone.utc).isoformat()}

# ─── Background game loop state ───
_active_game_tasks = {}  # round_id -> asyncio.Task
_user_operation_locks = {}  # user_id -> asyncio.Lock for wallet operations in this process
BINGO_NUMBERS = list(range(1, 76))
NUMBER_CALL_INTERVAL = 5  # seconds

# Cartela generation progress tracking
_cartela_gen_progress = {"status": "idle", "generated": 0, "total": 500, "error": None}


# ─── Models ───
class JoinRoundRequest(BaseModel):
    user_id: int
    cartela_numbers: List[int]
    user_name: str = "Player"


class SelectRequest(BaseModel):
    user_id: int
    cartela_number: int


class BingoCheckRequest(BaseModel):
    user_id: int


class EndRoundRequest(BaseModel):
    winner_ids: List[int]

class NotifyRequest(BaseModel):
    user_id: int
    text: str


class DepositConfigResponse(BaseModel):
    ok: bool
    phone: str
    admin_online: bool
    pending_count: int
    pending_limit: int
    error: Optional[str] = None


class DepositSubmitRequest(BaseModel):
    user_id: int
    telebirr_name: str
    amount: float
    transaction_id: str


# ═══════════════════════════════════════════════════════════════
# Server-Side Game Loop
# ═══════════════════════════════════════════════════════════════
async def _game_loop(round_id: str):
    """Background task: wait for selection deadline, then start if players exist."""
    try:
        while True:
            round_doc = await _db(lambda: db.collection('rounds').document(round_id).get())
            if not round_doc.exists:
                return
            data = round_doc.to_dict()
            status = data.get('status')

            if status == 'completed' or status is None:
                return

            if status == 'playing':
                break

            # Wait for selection deadline to expire before starting
            deadline = data.get('selection_deadline')
            if deadline:
                if isinstance(deadline, datetime):
                    dl_dt = deadline
                elif isinstance(deadline, str):
                    try:
                        dl_dt = datetime.fromisoformat(deadline)
                    except:
                        dl_dt = datetime.now(tz=timezone.utc)
                else:
                    dl_dt = datetime.now(tz=timezone.utc)
                
                if dl_dt.tzinfo is None:
                    dl_dt = dl_dt.replace(tzinfo=timezone.utc)
                
                # Give an extra 5 seconds grace period for large batches of queued auto-join HTTP requests to finish executing
                if datetime.now(tz=timezone.utc) >= dl_dt + timedelta(seconds=5):
                    # Timer expired — start game if players exist
                    player_count = data.get('player_count', 0)
                    if player_count > 0:
                        now = datetime.now(tz=timezone.utc)
                        round_stake = data.get('stake', DEFAULT_STAKE)
                        total_pool = player_count * round_stake
                        derash = total_pool * 0.75
                        await _db(lambda: db.collection('rounds').document(round_id).update({
                            'status': 'playing',
                            'derash': derash,
                            'game_started_at': now,
                            'next_number_at': now + timedelta(seconds=NUMBER_CALL_INTERVAL),
                            'pending_selections': {},
                        }))
                        await broadcast_event('rounds', round_id)
                        break
                    else:
                        # Grace period: wait 5s for late joins before cancelling
                        await asyncio.sleep(5)
                        recheck = await _db(lambda: db.collection('rounds').document(round_id).get())
                        if not recheck.exists:
                            return
                        recheck_data = recheck.to_dict()
                        if recheck_data.get('status') != 'selecting':
                            # Status changed (e.g. player joined via transaction), re-enter loop
                            continue
                        recheck_pc = recheck_data.get('player_count', 0)
                        if recheck_pc > 0:
                            # Player joined during grace period — start the game
                            now = datetime.now(tz=timezone.utc)
                            round_stake = recheck_data.get('stake', DEFAULT_STAKE)
                            total_pool = recheck_pc * round_stake
                            derash = total_pool * 0.75
                            await _db(lambda: db.collection('rounds').document(round_id).update({
                                'status': 'playing',
                                'derash': derash,
                                'game_started_at': now,
                                'next_number_at': now + timedelta(seconds=NUMBER_CALL_INTERVAL),
                                'pending_selections': {},
                            }))
                            await broadcast_event('rounds', round_id)
                            break
                        # Still no players — cancel
                        await _db(lambda: db.collection('rounds').document(round_id).update({
                            'status': 'completed',
                            'winners': [],
                            'winner_name': 'No players',
                            'prize_per_winner': 0,
                            'admin_profit': 0,
                            'payout_processed': True,
                            'completed_at': datetime.now(tz=timezone.utc),
                        }))
                        await broadcast_event('rounds', round_id)
                        return

            await asyncio.sleep(1)

        # Now call numbers every 5 seconds
        called = []
        while True:
            round_doc = await _db(lambda: db.collection('rounds').document(round_id).get())
            if not round_doc.exists:
                return
            data = round_doc.to_dict()

            if data.get('status') != 'playing':
                winners = data.get('winners', [])
                if winners and not data.get('payout_processed'):
                    try:
                        result = await engine.end_round(round_id, [int(w) for w in winners])
                        if isinstance(result, dict) and result.get('error'):
                            logger.error(f"[GameLoop] Payout skipped for {round_id}: {result['error']}")
                            return
                    except Exception as e:
                        logger.error(f"[GameLoop] Error distributing prizes for {round_id}: {e}")
                        return
                    for uid in winners:
                        try: await broadcast_event('users', str(uid))
                        except: pass
                    # payout_processed already set atomically inside end_round
                    await broadcast_event('rounds', round_id)
                return

            # Sleep until the strict 5s grid deadline (anchored to game_started_at).
            # This keeps the cadence exact across the whole round and across devices —
            # no drift from CPU/DB latency. If the grid fell far behind (e.g. after a
            # long outage) re-anchor it to now so the game doesn't burst-fire numbers.
            started = _parse_dt(data.get('game_started_at'))
            called_count = len(data.get('called_numbers', []))
            if started:
                deadline = started + timedelta(seconds=(called_count + 1) * NUMBER_CALL_INTERVAL)
                delay = (deadline - datetime.now(tz=timezone.utc)).total_seconds()
                if delay > NUMBER_CALL_INTERVAL:
                    new_start = datetime.now(tz=timezone.utc)
                    await _db(lambda: db.collection('rounds').document(round_id).update({
                        'game_started_at': new_start,
                        'next_number_at': new_start + timedelta(seconds=(called_count + 1) * NUMBER_CALL_INTERVAL),
                    }))
                    deadline = new_start + timedelta(seconds=(called_count + 1) * NUMBER_CALL_INTERVAL)
                    delay = (deadline - datetime.now(tz=timezone.utc)).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)
            else:
                next_at = data.get('next_number_at')
                if next_at:
                    if isinstance(next_at, str):
                        next_at = datetime.fromisoformat(next_at.replace('Z', '+00:00'))
                    elif isinstance(next_at, datetime):
                        if next_at.tzinfo is None:
                            next_at = next_at.replace(tzinfo=timezone.utc)
                    delay = (next_at - datetime.now(tz=timezone.utc)).total_seconds()
                    if delay > 0:
                        await asyncio.sleep(delay)

            already_called = set(data.get('called_numbers', []))
            available = [n for n in BINGO_NUMBERS if n not in already_called]

            if not available:
                from settlement import refund_no_winner
                result = await _db(lambda: refund_no_winner(
                    db,
                    round_id,
                    data.get('players', {}),
                    data.get('stake', DEFAULT_STAKE),
                ))
                if result.get('ok'):
                    logger.info(
                        f"[GameLoop] {round_id}: all 75 numbers called with no winner — "
                        f"refunded {result.get('amount', 0)} ETB"
                    )
                else:
                    logger.error(f"[GameLoop] No-winner refund failed for {round_id}: {result}")
                await broadcast_event('rounds', round_id)
                return

            try:
                number = await engine.call_number(round_id)
                await broadcast_event('rounds', round_id)
            except Exception as e:
                logger.warning(f"Smart predictor error for {round_id}: {e}")
                import random
                number = random.choice(available)
                called = list(data.get('called_numbers', []))
                called.append(number)
                now = datetime.now(tz=timezone.utc)
                await _db(lambda: db.collection('rounds').document(round_id).update({
                    'called_numbers': called,
                    'last_called_number': number,
                    'last_called_at': now,
                    'next_number_at': _grid_next_number_at(data.get('game_started_at'), len(called)),
                }))
                await broadcast_event('rounds', round_id)

            if number is None:
                continue

            # ── SERVER-SIDE WINNER CHECK ──
            round_doc = await _db(lambda: db.collection('rounds').document(round_id).get())
            if not round_doc.exists:
                return
            rd_after = round_doc.to_dict()
            if rd_after.get('status') != 'playing':
                winners = rd_after.get('winners', [])
                if winners and not rd_after.get('payout_processed'):
                    try:
                        result = await engine.end_round(round_id, [int(w) for w in winners])
                        if isinstance(result, dict) and result.get('error'):
                            logger.error(f"[GameLoop] Payout skipped for {round_id}: {result['error']}")
                            return
                    except Exception as e:
                        logger.error(f"[GameLoop] Error distributing prizes: {e}")
                # payout_processed already set atomically inside end_round
                await broadcast_event('rounds', round_id)
                logger.info(f"[GameLoop] ROUND COMPLETE {round_id}: winner={winner_id} cartela={winning_cartela} calls={len(called_now)} reason={completion_reason} natural_winners={len(winner_entries)}")
                return

            called_now = rd_after.get('called_numbers', [])
            players = rd_after.get('players', {})
            player_cartelas = await asyncio.to_thread(engine.build_player_cartelas, players)
            winner_entries = await asyncio.to_thread(engine.evaluate_winners, player_cartelas, called_now)
            chosen_winner = None
            completion_reason = None

            if winner_entries:
                chosen_winner = await asyncio.to_thread(engine.choose_single_winner, winner_entries, players)
                completion_reason = 'smart_single_winner' if len(winner_entries) == 1 else 'smart_tie_break_single_winner'
            elif len(called_now) >= MAX_SMART_CALLS:
                completion_reason = 'no_winner_max_30'

            if chosen_winner:
                now = datetime.now(tz=timezone.utc)
                player_count = rd_after.get('player_count', 1)
                round_stake = rd_after.get('stake', DEFAULT_STAKE)
                total_prize = player_count * round_stake * 0.75
                winner_id = str(chosen_winner.get('user_id'))
                winning_cartela = int(chosen_winner.get('cartela_number', 0))
                prize_per_winner = total_prize
                winner_name = players.get(winner_id, {}).get('name', 'Player')
                await _db(lambda: db.collection('rounds').document(round_id).update({
                    'status': 'completed',
                    'winners': [winner_id],
                    'winner_name': winner_name,
                    'winning_cartela': winning_cartela,
                    'prize_per_winner': prize_per_winner,
                    'completion_reason': completion_reason,
                    'completed_at': now,
                }))
                await broadcast_event('rounds', round_id)
                try:
                    result = await engine.end_round(round_id, [int(winner_id)])
                    if isinstance(result, dict) and result.get('error'):
                        logger.error(f"[GameLoop] Payout skipped for {round_id}: {result['error']}")
                        return
                except Exception as e:
                    logger.error(f"[GameLoop] Error distributing prizes: {e}")
                for uid in set(list(players.keys()) + [winner_id]):
                    try: await broadcast_event('users', str(uid))
                    except: pass
                # payout_processed already set atomically inside end_round
                return

            if completion_reason == 'no_winner_max_30':
                from settlement import refund_no_winner
                logger.info(
                    f"[GameLoop] No real winner for {round_id} after "
                    f"{len(called_now)} calls — ending with no winner"
                )
                result = await _db(lambda: refund_no_winner(
                    db,
                    round_id,
                    players,
                    rd_after.get('stake', DEFAULT_STAKE),
                ))
                if result.get('ok'):
                    logger.info(
                        f"[GameLoop] {round_id}: no_winner_max_30 — "
                        f"refunded {result.get('amount', 0)} ETB to players"
                    )
                else:
                    logger.error(f"[GameLoop] No-winner refund failed for {round_id}: {result}")
                await broadcast_event('rounds', round_id)
                return

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"[GameLoop] Error for round {round_id}: {e}", exc_info=True)
    finally:
        _active_game_tasks.pop(round_id, None)


def _start_game_loop(round_id: str):
    """Start a background game loop for a round if one isn't already running.

    The task map prevents duplicates inside one process. The environment gate
    prevents non-owner Render services from creating their own loops.
    """
    if not GAME_ENGINE_ENABLED:
        return
    if round_id in _active_game_tasks:
        return  # already running
    task = asyncio.create_task(_game_loop(round_id))
    _active_game_tasks[round_id] = task


@app.on_event("startup")
async def start_background_monitor():
    """Startup: ensures system docs exist, monitors rounds, broadcasts WS events."""
    if not GAME_ENGINE_ENABLED:
        logger.info("[GameEngine] disabled for this service; gateway owns round progression")
        return
    # Ensure admin_status document exists (prevents 404 on onSnapshot)
    try:
        status_doc = await _db(lambda: db.collection('system').document('admin_status').get())
        if not status_doc.exists:
            await _db(lambda: db.collection('system').document('admin_status').set({'online': False}))
    except Exception:
        pass

    async def _monitor():
        while True:
            try:
                # Find all currently active rounds (selecting or playing)
                def _read_rounds():
                    selecting = list(db.collection('rounds').where('status', '==', 'selecting').get())
                    playing = list(db.collection('rounds').where('status', '==', 'playing').get())
                    return selecting, playing
                selecting_docs, playing_docs = await asyncio.to_thread(_read_rounds)
                
                # Start game loops for any selecting rounds that haven't been started
                for doc in selecting_docs:
                    rid = doc.id
                    if rid not in _active_game_tasks:
                        _start_game_loop(rid)

                # H1: Resume game loops for playing rounds orphaned by a restart
                for doc in playing_docs:
                    rid = doc.id
                    if rid not in _active_game_tasks:
                        logger.info(f"[Monitor] Resuming orphaned playing round {rid}")
                        _start_game_loop(rid)
                        
                # ── Continuous Loop Enforcement ──
                # Ensure every stake has an active round (selecting or playing).
                active_stakes = set()
                for doc in selecting_docs + playing_docs:
                    rd = doc.to_dict()
                    s = rd.get('stake', DEFAULT_STAKE)
                    active_stakes.add(s)
                for stake_val in VALID_STAKES:
                    if stake_val not in active_stakes:
                        result = await engine.create_round(stake=stake_val)
                        if 'id' in result:
                            _start_game_loop(result['id'])
                        
            except Exception as e:
                logger.warning(f"Error in background monitor: {e}")
            await asyncio.sleep(5)
    asyncio.create_task(_monitor())
    asyncio.create_task(_event_broadcast_loop())


# ═══════════════════════════════════════════════════════════════
# Cartela Management
# ═══════════════════════════════════════════════════════════════
@app.post("/api/cartelas/generate")
async def generate_cartelas(request: Request):
    _require_admin_or_internal(request)
    global _cartela_gen_progress
    import threading
    logger.info(f"[CART-DBG] ENDPOINT ENTERED thread={threading.current_thread().name}")
    
    # If already generating, return current status
    if _cartela_gen_progress["status"] == "generating":
        logger.info("[CART-DBG] Already generating, returning current progress")
        return {"status": "generating", "generated": _cartela_gen_progress["generated"], "total": _cartela_gen_progress["total"]}
    
    # Check if cartelas already exist
    existing = list(engine.master_ref.limit(1).get())
    if existing:
        count = len(list(engine.master_ref.get()))
        logger.info(f"[CART-DBG] Cartelas already exist, count={count}")
        return {"status": "already_exists", "count": count}
    
    # Start background generation
    _cartela_gen_progress = {"status": "generating", "generated": 0, "total": 500, "error": None}
    logger.info("[CART-DBG] Starting background cartela generation")
    
    def _run_generation():
        global _cartela_gen_progress
        try:
            result = engine._generate_all_cartelas_sync()
            _cartela_gen_progress["status"] = "done"
            _cartela_gen_progress["generated"] = result.get("count", 0)
            logger.info(f"[CART-DBG] Background generation complete: {result}")
            # Schedule broadcast
            try:
                asyncio.get_event_loop().call_soon_threadsafe(
                    lambda: asyncio.ensure_future(broadcast_cartelas_update())
                )
            except Exception as broadcast_err:
                logger.warning(f"[CART-DBG] Failed to schedule broadcast: {broadcast_err}")
        except Exception as e:
            _cartela_gen_progress["status"] = "error"
            _cartela_gen_progress["error"] = str(e)
            logger.error(f"[CART-DBG] Background generation FAILED: {e}", exc_info=True)
    
    thread = threading.Thread(target=_run_generation, daemon=True)
    thread.start()
    
    return {"status": "generating", "generated": 0, "total": 500}


@app.get("/api/cartelas/status")
async def cartela_status():
    """Check cartela generation progress."""
    return _cartela_gen_progress


@app.post("/api/cartelas/reset")
async def reset_cartela_status(request: Request):
    """Reset cartela generation status (admin use)."""
    _require_admin_or_internal(request)
    global _cartela_gen_progress
    _cartela_gen_progress = {"status": "idle", "generated": 0, "total": 500, "error": None}
    return {"status": "reset"}


@app.get("/api/cartelas")
async def get_cartelas():
    """Get all 500 master cartelas."""
    cartelas = await engine.get_all_cartelas()
    return {"cartelas": cartelas, "count": len(cartelas)}


@app.get("/api/cartelas/{number}")
async def get_cartela(number: int):
    """Get a single cartela by number."""
    if number < 1 or number > 500:
        raise HTTPException(status_code=400, detail="Cartela number must be 1-500")
    cartela = await engine.get_cartela(number)
    if not cartela:
        raise HTTPException(status_code=404, detail="Cartela not found")
    return {"cartela": cartela}


# ═══════════════════════════════════════════════════════════════
# Round Management
# ═══════════════════════════════════════════════════════════════
@app.get("/api/rounds/active")
async def get_active_round():
    """Get the current active round."""
    round_data = await engine.get_active_round()
    if not round_data:
        return {"round": None}
    return {"round": round_data}


@app.post("/api/rounds/create")
async def create_round(stake: int = FastAPIQuery(default=DEFAULT_STAKE)):
    """Create a new round (or return existing active one) for a given stake."""
    result = await engine.create_round(stake=stake)
    if 'id' in result:
        _start_game_loop(result['id'])
    return {"round": result}


@app.post("/api/rounds/{round_id}/join")
async def join_round(round_id: str, req: JoinRoundRequest, request: Request):
    """Player joins a round with chosen cartelas (user verified from player token)."""
    user_id = _actor_user_id(request, req.user_id)
    result = await engine.join_round(
        round_id, user_id, req.cartela_numbers, req.user_name
    )
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    # Broadcast real-time cartela pool update
    await broadcast_cartela_pool(round_id)
    await broadcast_event('rounds', round_id)
    return result


@app.post("/api/rounds/{round_id}/select")
async def select_cartela(round_id: str, req: SelectRequest, request: Request):
    """Player taps a cartela during selection phase — mark as pending for others to see."""
    uid_str = str(_actor_user_id(request, req.user_id))
    def _do_select():
        snap = db.collection('rounds').document(round_id).get()
        if not snap.exists:
            return {"error": "Round not found"}
        rd = snap.to_dict()
        if rd.get('status') not in ('selecting', None):
            return {"error": "Round not in selecting phase"}
        pending = rd.get('pending_selections', {})
        if not isinstance(pending, dict):
            pending = {}
        user_list = pending.get(uid_str, [])
        if not isinstance(user_list, list):
            user_list = []
        if req.cartela_number not in user_list:
            user_list.append(req.cartela_number)
        pending[uid_str] = user_list
        db.collection('rounds').document(round_id).update({'pending_selections': pending})
        return {"ok": True, "_pending": pending, "_taken": rd.get('taken_cartelas', []), "_pc": rd.get('player_count', 0)}
    result = await asyncio.to_thread(_do_select)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    # Broadcast directly with data we already have — no extra DB read
    await sio.emit('cartela_pool', {
        "type": "cartela_pool",
        "round_id": round_id,
        "taken_cartelas": result.pop('_taken', []),
        "player_count": result.pop('_pc', 0),
        "pending_selections": result.pop('_pending', {}),
    }, room=f"rounds:{round_id}")
    return result


@app.post("/api/rounds/{round_id}/unselect")
async def unselect_cartela(round_id: str, req: SelectRequest, request: Request):
    """Player deselects a cartela — remove from pending."""
    uid_str = str(_actor_user_id(request, req.user_id))
    def _do_unselect():
        snap = db.collection('rounds').document(round_id).get()
        if not snap.exists:
            return {"error": "Round not found"}
        rd = snap.to_dict()
        pending = rd.get('pending_selections', {})
        if not isinstance(pending, dict):
            pending = {}
        user_list = pending.get(uid_str, [])
        if not isinstance(user_list, list):
            user_list = []
        if req.cartela_number in user_list:
            user_list.remove(req.cartela_number)
        pending[uid_str] = user_list
        db.collection('rounds').document(round_id).update({'pending_selections': pending})
        return {"ok": True, "_pending": pending, "_taken": rd.get('taken_cartelas', []), "_pc": rd.get('player_count', 0)}
    result = await asyncio.to_thread(_do_unselect)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    await sio.emit('cartela_pool', {
        "type": "cartela_pool",
        "round_id": round_id,
        "taken_cartelas": result.pop('_taken', []),
        "player_count": result.pop('_pc', 0),
        "pending_selections": result.pop('_pending', {}),
    }, room=f"rounds:{round_id}")
    return result


@app.post("/api/rounds/{round_id}/close-empty")
async def close_empty_round(round_id: str, request: Request):
    """Close a stale empty round from an admin or the internal engine only."""
    _require_admin_or_internal(request)

    def _do_close():
        snap = db.collection('rounds').document(round_id).get()
        if not snap.exists:
            return {"error": "Round not found"}
        rd = snap.to_dict()
        if rd.get('player_count', 0) > 0:
            return {"error": "Round has players"}
        if rd.get('status') not in ('selecting', 'playing'):
            return {"error": "Round not active"}
        db.collection('rounds').document(round_id).update({
            'status': 'completed',
            'winners': [],
            'winner_name': 'No players',
            'prize_per_winner': 0,
            'admin_profit': 0,
            'payout_processed': True,
            'completed_at': datetime.now(tz=timezone.utc),
        })
        return {"ok": True}

    result = await asyncio.to_thread(_do_close)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    await broadcast_event('rounds', round_id)
    return result
async def start_round(round_id: str):
    """Start the round (transition from selecting to playing)."""
    result = await engine.start_round(round_id)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    _start_game_loop(round_id)
    return result


@app.post("/api/rounds/{round_id}/call")
async def call_number(round_id: str, request: Request):
    """Call the next random number from an admin or internal engine only."""
    _require_admin_or_internal(request)
    number = await engine.call_number(round_id)
    if number is None:
        raise HTTPException(status_code=400, detail="No more numbers to call or round not playing")
    return {"number": number}


@app.post("/api/rounds/{round_id}/check-bingo")
async def check_bingo(round_id: str, req: BingoCheckRequest, request: Request):
    """Check bingo only for the verified player or an admin/internal caller."""
    user_id = _actor_user_id(request, req.user_id)
    result = await engine.check_bingo(round_id, user_id)
    return result


@app.post("/api/rounds/{round_id}/end")
async def end_round(round_id: str, req: EndRoundRequest, request: Request):
    """End the round and distribute prizes from an admin or internal engine only."""
    _require_admin_or_internal(request)
    # Cancel game loop if running
    task = _active_game_tasks.pop(round_id, None)
    if task:
        task.cancel()
    result = await engine.end_round(round_id, req.winner_ids)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    return result


@app.get("/api/rounds/{round_id}")
async def get_round(round_id: str):
    """Get round details."""
    round_data = await engine.get_round(round_id)
    if not round_data:
        raise HTTPException(status_code=404, detail="Round not found")
    return {"round": round_data}


@app.get("/api/rounds")
async def get_rounds(limit: int = 20):
    """Get recent rounds."""
    rounds = await engine.get_recent_rounds(limit)
    return {"rounds": rounds, "count": len(rounds)}


# ═══════════════════════════════════════════════════════════════
# Dashboard / Stats
# ═══════════════════════════════════════════════════════════════
@app.get("/api/dashboard")
async def get_dashboard(request: Request):
    """Get dashboard overview for admins/internal callers."""
    _require_admin_or_internal(request)
    users = await user_manager.get_all_users()
    total_play = sum(u.get('play_wallet', 0) for u in users)
    total_balance = total_play
    total_wins = sum(u.get('wins', 0) for u in users)
    active_playing = sum(1 for u in users if u.get('is_playing'))

    # Count rounds
    try:
        all_rounds = list(db.collection('rounds').get())
        completed = sum(1 for r in all_rounds if r.to_dict().get('status') == 'completed')
        total_admin_profit = sum(r.to_dict().get('admin_profit', 0) for r in all_rounds if r.to_dict().get('status') == 'completed')
    except Exception:
        completed = 0
        total_admin_profit = 0

    # Count cartelas
    try:
        cartela_count = len(list(db.collection('cartelas_master').limit(501).get()))
    except Exception:
        cartela_count = 0

    return {
        "total_users": len(users),
        "total_balance": total_balance,
        "total_play_wallets": total_play,
        "total_wins": total_wins,
        "active_players": active_playing,
        "completed_rounds": completed,
        "total_admin_profit": total_admin_profit,
        "cartela_count": cartela_count,
    }


@app.get("/api/users")
async def get_users(limit: int = 100, request: Request = None):
    """Get all users for admins/internal callers."""
    _require_admin_or_internal(request)
    users = await user_manager.get_all_users(limit)
    return {"users": users}


@app.get("/api/users/{user_id}")
async def get_user(user_id: int, request: Request):
    """Get a specific user for admins/internal callers."""
    _require_admin_or_internal(request)
    user = await user_manager.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": user}

@app.post("/api/notify")
async def notify_user(req: NotifyRequest, request: Request):
    _require_admin_or_internal(request)
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=req.user_id, text=req.text)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health_check():
    """Health check."""
    return {"status": "healthy", "timestamp": datetime.now(tz=timezone.utc).isoformat()}


def _is_admin_online_sync() -> bool:
    try:
        doc = db.collection('system').document('admin_status').get()
        if doc.exists:
            return bool(doc.to_dict().get('online', True))
    except Exception:
        pass
    return True


def _get_pending_deposit_count(user_id: int) -> int:
    pending = db.collection('deposits').where('userId', '==', str(user_id)).where('status', '==', 'pending').get()
    return len(list(pending))


async def _notify_admin_deposit_web(deposit_data: dict, deposit_id: str):
    try:
        from config import ADMIN_BOT_TOKEN, BOT_TOKEN, ADMIN_CHAT_ID
        if not ADMIN_CHAT_ID:
            logger.warning("[NotifyAdminDeposit] ADMIN_CHAT_ID not configured.")
            return
        token = ADMIN_BOT_TOKEN or BOT_TOKEN
        if not token:
            logger.warning("[NotifyAdminDeposit] Neither ADMIN_BOT_TOKEN nor BOT_TOKEN configured.")
            return
        
        text = get_bot_text(
            'admin_deposit_notification',
            db,
            first_name=deposit_data.get('firstName', 'Unknown'),
            username=deposit_data.get('username', ''),
            telebirr_name=deposit_data.get('telebirrName', 'N/A'),
            amount=deposit_data.get('amount', 0),
            transaction_id=deposit_data.get('transactionId', 'N/A'),
            deposit_id=deposit_id,
            timestamp=datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        )
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{deposit_id}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_{deposit_id}")]
        ])
        bot = Bot(token=token)
        await bot.send_message(
            chat_id=int(ADMIN_CHAT_ID),
            text=text,
            parse_mode='Markdown',
            reply_markup=kb,
        )
    except Exception as e:
        logger.warning(f"[NotifyAdminDeposit] Error: {e}")


@app.api_route("/", methods=["GET", "HEAD"])
async def root_ping():
    return Response(status_code=200)



# ═══════════════════════════════════════════════════════════════
# Admin-Specific Endpoints  (Dashboard → SQL directly)
# ═══════════════════════════════════════════════════════════════

class DepositActionRequest(BaseModel):
    note: str = ""

class BalanceEditRequest(BaseModel):
    new_balance: float

class UserBanRequest(BaseModel):
    banned: bool

class SystemStatusRequest(BaseModel):
    online: bool

class SettingsRequest(BaseModel):
    data: dict


class InternalDepositCreateRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    telebirr_name: str = ""
    amount: float
    transaction_id: str
    sender_name: str = "Unknown"


class InternalWithdrawalCreateRequest(BaseModel):
    user_id: str
    username: str = ""
    first_name: str = ""
    amount: float
    phone: str
    telebirr_name: str = ""
    idempotency_key: Optional[str] = None


class InternalTransferRequest(BaseModel):
    sender_id: str
    recipient_id: str
    amount: float
    idempotency_key: Optional[str] = None


class InternalBonusConversionRequest(BaseModel):
    user_id: str
    rate: float = 10
    idempotency_key: Optional[str] = None


class InternalRegisterRequest(BaseModel):
    user_id: str
    name: str
    phone: str
    telebirr_name: str = ""
    idempotency_key: Optional[str] = None


@app.post("/api/internal/accounts/transfer")
async def internal_transfer_funds(req: InternalTransferRequest, request: Request):
    """Transfer play-wallet value atomically between two users."""
    _require_internal(request)
    if not req.idempotency_key:
        raise HTTPException(status_code=400, detail="idempotency_key_required")
    from settlement import transfer_funds
    result = await _db(lambda: transfer_funds(
        db,
        req.sender_id,
        req.recipient_id,
        req.amount,
        req.idempotency_key,
    ))
    if result.get("ok"):
        await broadcast_event("users", str(req.sender_id))
        await broadcast_event("users", str(req.recipient_id))
    return result


@app.post("/api/internal/accounts/convert-bonus")
async def internal_convert_bonus(req: InternalBonusConversionRequest, request: Request):
    """Convert bonus coins into play-wallet value atomically."""
    _require_internal(request)
    from settlement import convert_bonus
    result = await _db(lambda: convert_bonus(
        db,
        req.user_id,
        req.rate,
        req.idempotency_key,
    ))
    if result.get("ok"):
        await broadcast_event("users", str(req.user_id))
    return result


@app.post("/api/internal/accounts/register")
async def internal_register_user(req: InternalRegisterRequest, request: Request):
    """Register a user and award the welcome bonus at most once."""
    _require_internal(request)
    if not req.name.strip() or not req.phone.strip():
        raise HTTPException(status_code=400, detail="name_and_phone_required")
    from settlement import register_user
    result = await _db(lambda: register_user(
        db,
        req.user_id,
        req.name.strip(),
        req.phone.strip(),
        req.telebirr_name.strip(),
        req.idempotency_key,
    ))
    if result.get("ok"):
        await broadcast_event("users", str(req.user_id))
    return result


@app.post("/api/internal/withdrawals/create")
async def internal_create_withdrawal(req: InternalWithdrawalCreateRequest, request: Request):
    """Debit and create one pending withdrawal on the gateway database."""
    _require_internal(request)
    from settlement import create_withdrawal
    data = {
        "userId": str(req.user_id),
        "username": req.username,
        "firstName": req.first_name,
        "amount": req.amount,
        "phone": req.phone.strip(),
        "telebirr_name": req.telebirr_name.strip(),
        "status": "pending",
        "createdAt": datetime.now(tz=timezone.utc),
        "processedAt": None,
        "adminNote": "",
    }
    if not data["phone"]:
        raise HTTPException(status_code=400, detail="no_phone")
    result = await _db(lambda: create_withdrawal(db, data, req.idempotency_key))
    if not result.get("ok"):
        return result
    await broadcast_event("users", str(req.user_id))
    await broadcast_event("withdrawals", result["withdrawal_id"])
    return result


@app.post("/api/internal/deposits/create")
async def internal_create_deposit(req: InternalDepositCreateRequest, request: Request):
    """Create a pending deposit exactly once on the gateway database."""
    _require_internal(request)
    from settlement import create_deposit
    data = {
        "userId": str(req.user_id),
        "username": req.username,
        "firstName": req.first_name,
        "telebirrName": req.telebirr_name,
        "amount": req.amount,
        "transactionId": req.transaction_id.strip(),
        "senderName": req.sender_name,
        "status": "pending",
        "createdAt": datetime.now(tz=timezone.utc),
        "processedAt": None,
        "adminNote": "",
    }
    result = await _db(lambda: create_deposit(db, data))
    if not result.get("ok") and result.get("error") == "duplicate_txn":
        raise HTTPException(status_code=400, detail="duplicate_transaction")
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Deposit creation failed"))
    await broadcast_event("deposits", result["deposit_id"])
    return result


@app.post("/api/internal/settlements/deposits/{deposit_id}/{status}")
async def internal_settle_deposit(deposit_id: str, status: str, request: Request, note: str = ""):
    """Atomically settle a deposit for the bot service."""
    _require_internal(request)
    if status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid deposit status")
    from settlement import settle_deposit
    result = await _db(lambda: settle_deposit(db, deposit_id, status, note))
    if result.get("user_id") is not None:
        await broadcast_event("users", str(result["user_id"]))
    await broadcast_event("deposits", deposit_id)
    return result


@app.post("/api/internal/settlements/withdrawals/{withdrawal_id}/{status}")
async def internal_settle_withdrawal(withdrawal_id: str, status: str, request: Request, note: str = ""):
    """Atomically settle a withdrawal for the bot service."""
    _require_internal(request)
    if status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid withdrawal status")
    from settlement import settle_withdrawal
    result = await _db(lambda: settle_withdrawal(db, withdrawal_id, status, note))
    if result.get("user_id") is not None:
        await broadcast_event("users", str(result["user_id"]))
    await broadcast_event("withdrawals", withdrawal_id)
    return result


@app.get("/api/validate-withdrawal/{user_id}")
async def validate_withdrawal(user_id: str, amount: float, request: Request):
    """Validate a withdrawal request from the web dashboard (user verified from token)."""
    try:
        # Player tokens may only validate their own withdrawal eligibility.
        if _actor_user_id(request, int(user_id)) != int(user_id):
            raise HTTPException(status_code=403, detail="Forbidden")
        from handlers.user_manager import UserManager
        um = UserManager(db)
        result = await um.validate_withdrawal(int(user_id), amount)
        return result
    except HTTPException:
        raise
    except Exception:
        return {"ok": True}


@app.get("/api/deposits/config/{user_id}", response_model=DepositConfigResponse)
async def get_deposit_config(user_id: int, request: Request):
    """Return the live web deposit settings and guardrails used by the Telegram bot flow."""
    if _actor_user_id(request, user_id) != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    user = await user_manager.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    pending_limit = 3
    pending_count = _get_pending_deposit_count(user_id)
    admin_online = _is_admin_online_sync()
    phone = get_bot_text('deposit_phone', db)

    if pending_count >= pending_limit:
        return DepositConfigResponse(
            ok=False,
            phone=phone,
            admin_online=admin_online,
            pending_count=pending_count,
            pending_limit=pending_limit,
            error='too_many_pending',
        )

    if not admin_online:
        return DepositConfigResponse(
            ok=False,
            phone=phone,
            admin_online=admin_online,
            pending_count=pending_count,
            pending_limit=pending_limit,
            error='admin_offline',
        )

    return DepositConfigResponse(
        ok=True,
        phone=phone,
        admin_online=admin_online,
        pending_count=pending_count,
        pending_limit=pending_limit,
    )


@app.post("/api/deposits/submit")
async def submit_deposit(req: DepositSubmitRequest, request: Request):
    """Submit a pending deposit request using the same core rules as the Telegram bot flow.
    The user is verified from the player token, never trusted from the body."""
    user_id = _require_player(request)
    user = await user_manager.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    pending_limit = 3
    pending_count = _get_pending_deposit_count(user_id)
    if pending_count >= pending_limit:
        raise HTTPException(status_code=400, detail=get_bot_text('deposit_too_many', db))

    if not _is_admin_online_sync():
        raise HTTPException(status_code=400, detail=get_bot_text('deposit_admin_offline', db))

    telebirr_name = (req.telebirr_name or '').strip()
    if not telebirr_name:
        raise HTTPException(status_code=400, detail=get_bot_text('deposit_ask_name', db))

    try:
        amount = float(req.amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=get_bot_text('deposit_invalid_number', db))
    if not math.isfinite(amount) or amount < 10:
        raise HTTPException(status_code=400, detail=get_bot_text('deposit_min_amount', db))

    transaction_id = (req.transaction_id or '').strip()
    if len(transaction_id) < 3:
        raise HTTPException(status_code=400, detail=get_bot_text('deposit_invalid_number', db))

    deposit_data = {
        'userId': str(user_id),
        'username': user.get('username', ''),
        'firstName': user.get('first_name', ''),
        'telebirrName': telebirr_name,
        'amount': amount,
        'transactionId': transaction_id,
        'senderName': user.get('first_name', 'Unknown'),
        'status': 'pending',
        'createdAt': datetime.now(tz=timezone.utc),
        'processedAt': None,
        'adminNote': '',
    }
    from settlement import create_deposit
    result = await _db(lambda: create_deposit(db, deposit_data))
    if not result.get("ok"):
        if result.get("error") == "duplicate_txn":
            raise HTTPException(status_code=400, detail=get_bot_text('deposit_duplicate_txn', db))
        raise HTTPException(status_code=400, detail=result.get("error", "Deposit creation failed"))
    deposit_id = result["deposit_id"]

    await _notify_admin_deposit_web(deposit_data, deposit_id)

    return {
        "ok": True,
        "deposit_id": deposit_id,
        "status": "pending",
        "phone": get_bot_text('deposit_phone', db),
        "message": get_bot_text(
            'deposit_submitted',
            db,
            amount=amount,
            telebirr_name=telebirr_name,
            transaction_id=transaction_id,
            deposit_id=deposit_id,
        ),
    }


class WithdrawalCreateRequest(BaseModel):
    amount: float
    phone: str
    telebirr_name: str


@app.post("/api/withdrawals/create")
async def create_withdrawal(req: WithdrawalCreateRequest, request: Request):
    """Create a pending withdrawal through the authoritative idempotent creator."""
    user_id = _require_player(request)
    user = await user_manager.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        amount = float(req.amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_amount")
    if not math.isfinite(amount) or amount <= 0:
        raise HTTPException(status_code=400, detail="invalid_amount")

    validation = await user_manager.validate_withdrawal(user_id, amount)
    if not validation.get('ok'):
        return {"ok": False, **validation}

    phone = (req.phone or '').strip()
    telebirr_name = (req.telebirr_name or '').strip()
    if not phone:
        raise HTTPException(status_code=400, detail="no_phone")
    if not telebirr_name:
        raise HTTPException(status_code=400, detail="no_name")

    withdrawal_data = {
        'userId': str(user_id),
        'username': user.get('username', ''),
        'firstName': user.get('first_name', 'Unknown'),
        'telebirrName': telebirr_name,
        'amount': amount,
        'phone': phone,
        'status': 'pending',
        'createdAt': datetime.now(tz=timezone.utc),
        'processedAt': None,
        'adminNote': '',
    }
    from settlement import create_withdrawal
    result = await _db(lambda: create_withdrawal(
        db,
        withdrawal_data,
        request.headers.get('X-Idempotency-Key'),
    ))
    if not result.get('ok'):
        return result

    user_id_str = str(user_id)
    await broadcast_event('users', user_id_str)
    await broadcast_event('withdrawals', result['withdrawal_id'])

    try:
        from config import ADMIN_BOT_TOKEN, ADMIN_CHAT_ID
        if ADMIN_BOT_TOKEN and ADMIN_CHAT_ID:
            text = (
                f"🎰 *New Withdrawal Request*\n\n"
                f"👤 User: {withdrawal_data['firstName']} (@{withdrawal_data['username']})\n"
                f"🆔 ID: `{user_id}`\n"
                f"💰 Amount: *{amount} ETB*\n"
                f"📱 Phone: {phone}\n"
                f"📛 TeleBirr: {telebirr_name}\n"
                f"🔗 ID: `{result['withdrawal_id']}`"
            )
            bot = Bot(token=ADMIN_BOT_TOKEN)
            await bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=text, parse_mode='Markdown')
    except Exception:
        pass

    return result


@app.get("/api/admin/deposits")
async def admin_get_deposits(status: Optional[str] = None, limit: int = 50):
    ref = db.collection('deposits')
    if status:
        ref = ref.where('status', '==', status)
    ref = ref.order_by('createdAt', 'DESCENDING').limit(limit)
    docs = ref.get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@app.post("/api/admin/deposits/{deposit_id}/approve")
async def admin_approve_deposit(deposit_id: str, req: DepositActionRequest):
    from settlement import settle_deposit
    result = await _db(lambda: settle_deposit(db, deposit_id, "approved", req.note or "Approved by admin"))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Deposit settlement failed"))
    amount = result.get("amount", 0)
    user_id = str(result.get("user_id", ""))
    await broadcast_event("users", user_id)
    await broadcast_event("deposits", deposit_id)
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=int(user_id),
            text=f"✅ Deposit approved!\n💰 {amount} ETB has been added to your wallet."
        )
    except Exception:
        pass
    return result


@app.post("/api/admin/deposits/{deposit_id}/reject")
async def admin_reject_deposit(deposit_id: str, req: DepositActionRequest):
    from settlement import settle_deposit
    note = req.note or "Rejected by admin"
    result = await _db(lambda: settle_deposit(db, deposit_id, "rejected", note))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Deposit settlement failed"))
    user_id = str(result.get("user_id", ""))
    await broadcast_event("deposits", deposit_id)
    if user_id:
        try:
            bot = Bot(token=BOT_TOKEN)
            await bot.send_message(
                chat_id=int(user_id),
                text=f"❌ Deposit rejected.\nReason: {note}\nPlease contact support if you need help."
            )
        except Exception:
            pass
    return result


class WithdrawalNotifyRequest(BaseModel):
    withdrawal_id: str
    user_id: int
    first_name: str
    username: str
    amount: int
    phone: str
    telebirr_name: str


@app.post("/api/admin/withdrawals/notify")
async def notify_admin_withdrawal(req: WithdrawalNotifyRequest):
    """Send Telegram notification to admin when withdrawal is created from web dashboard."""
    try:
        from config import ADMIN_BOT_TOKEN, ADMIN_CHAT_ID
        if ADMIN_BOT_TOKEN and ADMIN_CHAT_ID:
            import httpx
            text = (
                f"🎰 *New Withdrawal Request*\n\n"
                f"👤 User: {req.first_name} (@{req.username})\n"
                f"🆔 ID: `{req.user_id}`\n"
                f"💰 Amount: *{req.amount} ETB*\n"
                f"📱 Phone: {req.phone}\n"
                f"📛 TeleBirr: {req.telebirr_name}\n"
                f"📋 ID: `{req.withdrawal_id}`"
            )
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Approve", "callback_data": f"approve_withdraw_{req.withdrawal_id}"},
                        {"text": "❌ Reject", "callback_data": f"reject_withdraw_{req.withdrawal_id}"}
                    ]
                ]
            }
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": int(ADMIN_CHAT_ID),
                        "text": text,
                        "parse_mode": "Markdown",
                        "reply_markup": keyboard
                    },
                    timeout=10
                )
        return {"ok": True}
    except Exception as e:
        logger.warning(f"[NotifyAdmin] Error: {e}")
        return {"ok": True}


@app.get("/api/admin/withdrawals")
async def admin_get_withdrawals(status: Optional[str] = None, limit: int = 50):
    ref = db.collection('withdrawals')
    if status:
        ref = ref.where('status', '==', status)
    ref = ref.order_by('createdAt', 'DESCENDING').limit(limit)
    docs = ref.get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@app.post("/api/admin/withdrawals/{withdrawal_id}/approve")
async def admin_approve_withdrawal(withdrawal_id: str, req: DepositActionRequest):
    from settlement import settle_withdrawal
    result = await _db(lambda: settle_withdrawal(db, withdrawal_id, "approved", req.note or "Approved by admin"))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Withdrawal settlement failed"))
    amount = result.get("amount", 0)
    user_id = str(result.get("user_id", ""))
    await broadcast_event("withdrawals", withdrawal_id)
    try:
        from handlers.bot_content import get_bot_text
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=int(user_id),
            text=get_bot_text("withdraw_approved", db, amount=amount)
        )
    except Exception:
        pass
    return result


@app.post("/api/admin/withdrawals/{withdrawal_id}/reject")
async def admin_reject_withdrawal(withdrawal_id: str, req: DepositActionRequest):
    from settlement import settle_withdrawal
    note = req.note or "Rejected by admin"
    result = await _db(lambda: settle_withdrawal(db, withdrawal_id, "rejected", note))
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Withdrawal settlement failed"))
    amount = result.get("amount", 0)
    user_id = str(result.get("user_id", ""))
    await broadcast_event("withdrawals", withdrawal_id)
    if user_id:
        await broadcast_event("users", user_id)
        try:
            from handlers.bot_content import get_bot_text
            bot = Bot(token=BOT_TOKEN)
            await bot.send_message(
                chat_id=int(user_id),
                text=get_bot_text("withdraw_rejected", db, amount=amount)
            )
        except Exception:
            pass
    return result


@app.patch("/api/admin/users/{user_id}/balance")
async def admin_edit_balance(user_id: int, req: BalanceEditRequest):
    snap = db.collection('users').document(str(user_id)).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="User not found")
    new_balance = req.new_balance
    if not math.isfinite(float(new_balance)) or float(new_balance) < 0:
        raise HTTPException(status_code=400, detail="Invalid balance")
    db.collection('users').document(str(user_id)).update({
        'play_wallet': new_balance,
        'updated_at': datetime.now(tz=timezone.utc).isoformat()
    })
    await broadcast_event('users', str(user_id))
    return {"ok": True}


@app.patch("/api/admin/users/{user_id}/ban")
async def admin_ban_user(user_id: int, req: UserBanRequest):
    snap = db.collection('users').document(str(user_id)).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="User not found")
    db.collection('users').document(str(user_id)).update({
        'banned': req.banned,
        'updated_at': datetime.now(tz=timezone.utc).isoformat()
    })
    return {"ok": True}


@app.get("/api/admin/status")
async def admin_get_status():
    snap = db.collection('system').document('admin_status').get()
    if snap.exists:
        return snap.to_dict()
    return {"online": False}


@app.post("/api/admin/status")
async def admin_set_status(req: SystemStatusRequest):
    db.collection('system').document('admin_status').set({
        'online': req.online,
        'updatedAt': datetime.now(tz=timezone.utc).isoformat()
    })
    return {"ok": True, "online": req.online}


@app.get("/api/admin/settings")
async def admin_get_settings():
    snap = db.collection('settings').document('game').get()
    if snap.exists:
        return snap.to_dict()
    return {}


@app.post("/api/admin/settings")
async def admin_save_settings(req: SettingsRequest):
    db.collection('settings').document('game').set(req.data, merge=True)
    return {"ok": True}


@app.post("/api/admin/bot-content/seed")
async def seed_bot_content():
    """Seed the bot_content collection with all default messages."""
    from handlers.bot_content import DEFAULTS, invalidate_cache
    count = 0
    for key, value in DEFAULTS.items():
        cat = key.split('_')[0]
        db.collection('bot_content').document(key).set({
            'key': key,
            'content': value,
            'category': cat,
            'updatedAt': datetime.now(tz=timezone.utc).isoformat(),
        })
        count += 1
    invalidate_cache()
    return {"ok": True, "seeded": count}


@app.get("/api/admin/bot-content")
async def get_bot_content():
    """Get all bot content messages."""
    docs = db.collection('bot_content').get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@app.post("/api/admin/bot-content/{key}")
async def save_bot_content(key: str, req: SettingsRequest):
    """Save a bot content message."""
    from handlers.bot_content import invalidate_cache
    db.collection('bot_content').document(key).set(req.data, merge=True)
    invalidate_cache(key)
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# JSON Backup / Restore (survives Render's ephemeral-disk wipes)
# ═══════════════════════════════════════════════════════════════
class RestoreRequest(BaseModel):
    overwrite: bool = False
    confirm: bool = False


class BackupUploadRequest(BaseModel):
    snapshot: dict
    overwrite: bool = False
    confirm: bool = False


@app.get("/api/admin/backup/status")
def backup_status():
    """Metadata about the latest pinned backup (no download)."""
    import backup_common as bc
    status = bc.get_status()
    status["enabled"] = bool(bc.BACKUP_CHAT_ID)
    status["chat_id"] = bc.BACKUP_CHAT_ID
    status["live_documents"] = bc.firestore_db.count_documents()
    return status


@app.post("/api/admin/backup/create")
def backup_create():
    """Snapshot the DB now and pin it in the backup bot."""
    import backup_common as bc
    try:
        meta = bc.create_backup()
        return {"ok": True, **meta}
    except bc.BackupError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/backup/restore")
def backup_restore(req: RestoreRequest):
    """
    Restore from the latest pinned backup. overwrite=True (replacing live data)
    additionally requires confirm=True to guard against accidental clobbering.
    """
    import backup_common as bc
    if req.overwrite and not req.confirm:
        raise HTTPException(status_code=400, detail="Overwrite restore requires confirmation.")
    try:
        result = bc.restore_latest(overwrite=req.overwrite)
        if not result.get("restored") and result.get("reason") == "no_backup":
            raise HTTPException(status_code=404, detail="No backup found to restore.")
        return {"ok": True, **result}
    except bc.BackupError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/backup/upload")
def backup_upload(req: BackupUploadRequest):
    """
    Restore the DB from a backup JSON file uploaded by the admin.

    Accepts either a full backup snapshot ({"_meta": {...}, "data": {...}})
    as produced by create_backup, or a bare export_all()-shaped dict
    ({collection: {doc_id: data}}). This covers the case where the live DB
    was wiped but a JSON backup still exists in Telegram: download it and
    upload it here to restore. overwrite=True requires confirm=True.
    """
    import firestore_db
    snap = req.snapshot if isinstance(req.snapshot, dict) else {}
    data = snap.get("data") if ("data" in snap and "_meta" in snap) else snap
    if not isinstance(data, dict) or not any(
        isinstance(docs, dict) and docs for docs in data.values()
    ):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid backup snapshot.")
    if req.overwrite and not req.confirm:
        raise HTTPException(status_code=400, detail="Overwrite restore requires confirmation.")
    stats = firestore_db.import_all(data, overwrite=req.overwrite)
    stats["documents"] = sum(len(docs) for docs in data.values() if isinstance(docs, dict))
    return {"ok": True, **stats}





@app.post("/api/admin/wipe-all")
def wipe_all(req: RestoreRequest):
    """
    Delete every document from the DB and unpin all backup messages from the
    backup bot chat. Requires confirm=True to guard against accidents.
    """
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Wipe requires confirm=true.")
    import backup_common as bc
    import firestore_db
    result = {"backup_unpinned": False, "deleted": {}}
    try:
        bc.wipe_pinned_backup()
        result["backup_unpinned"] = True
    except Exception as e:
        result["backup_error"] = str(e)
    result["deleted"] = firestore_db.delete_all_documents()
    return {"ok": True, **result}


# ─── Dashboard & game (served from same service as API + bots) ───


def _normalize_doc(data: dict) -> dict:
    """Recursively fix any {__type: ..., value: ...} artifacts stored by old FieldValue mocks."""
    if isinstance(data, dict):
        if '__type' in data and 'value' in data:
            return data['value']
        return {k: _normalize_doc(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_normalize_doc(v) for v in data]
    return data


class DocSetRequest(BaseModel):
    data: dict
    merge: bool = False

class DocUpdateRequest(BaseModel):
    data: dict

class QueryRequest(BaseModel):
    filters: list = []
    order_by: Optional[str] = None
    order_dir: str = "ASCENDING"
    limit_n: Optional[int] = None


def _authorize_db_write(request: Request, collection: str, doc_id: Optional[str] = None) -> dict:
    """Gate /api/db/* mutations.

    - admin/internal token: full access.
    - player token: only their own `users` doc (and never money/stats fields — enforced
      by _sanitize_player_user_data at the call sites).
    """
    identity = _auth_any(request)
    if not identity:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if identity.get("kind") == "admin":
        return identity
    # Player token path
    if collection not in PLAYER_WRITABLE_COLLECTIONS:
        raise HTTPException(status_code=403, detail="Forbidden")
    if doc_id is not None and doc_id != str(identity.get("user_id")):
        raise HTTPException(status_code=403, detail="Forbidden")
    return identity


def _authorize_db_read(
    request: Request,
    collection: str,
    doc_id: Optional[str] = None,
    filters: Optional[str] = None,
) -> dict:
    """Authorize document-store reads without exposing private collections.

    Public gameplay collections contain round/card state. Players may read only
    their own user document and transaction queries constrained to their own
    userId. Admin/internal identities may read the full store.
    """
    identity = _auth_any(request)
    if collection in PUBLIC_DB_READ_COLLECTIONS:
        return identity or {"kind": "public"}
    if not identity:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if identity.get("kind") == "admin":
        return identity
    user_id = str(identity.get("user_id"))
    if collection == "users" and doc_id == user_id:
        return identity
    if collection in PLAYER_DB_QUERY_COLLECTIONS:
        try:
            parsed = json.loads(filters or "[]")
        except (TypeError, ValueError):
            parsed = []
        own_filter = any(
            isinstance(item, list)
            and len(item) == 3
            and item[0] == "userId"
            and item[1] in ("==", "equal", "equals")
            and str(item[2]) == user_id
            for item in parsed
        )
        if own_filter:
            return identity
    raise HTTPException(status_code=403, detail="Forbidden")


def _sanitize_player_user_data(data: dict) -> dict:
    """Strip server-owned money/stats fields from player-authored user writes."""
    if not isinstance(data, dict):
        return data
    return {k: v for k, v in data.items() if k not in PLAYER_IMMUTABLE_USER_FIELDS}


def _auth_player_db_set(request: Request, collection: str, doc_id: str) -> bool:
    """Return True if this write must be forced to merge=True (player bootstrap set)."""
    identity = _auth_any(request)
    return bool(identity and identity.get("kind") == "player")


@app.get("/api/db/{collection}/{doc_id}")
async def db_get_doc(collection: str, doc_id: str, request: Request):
    _authorize_db_read(request, collection, doc_id)
    snap = db.collection(collection).document(doc_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"id": snap.id, "data": _normalize_doc(snap.to_dict())}


@app.post("/api/db/{collection}/{doc_id}")
async def db_set_doc(collection: str, doc_id: str, req: DocSetRequest, request: Request):
    identity = _authorize_db_write(request, collection, doc_id)
    if identity.get("kind") == "player":
        # Player bootstrap set: sanitize money/stats and never clobber the existing doc.
        req.data = _sanitize_player_user_data(req.data)
        req.merge = True
    db.collection(collection).document(doc_id).set(req.data, merge=req.merge)
    await broadcast_event(collection, doc_id)
    return {"ok": True}


@app.patch("/api/db/{collection}/{doc_id}")
async def db_update_doc(collection: str, doc_id: str, req: DocUpdateRequest, request: Request):
    identity = _authorize_db_write(request, collection, doc_id)
    if identity.get("kind") == "player":
        req.data = _sanitize_player_user_data(req.data)
    try:
        db.collection(collection).document(doc_id).update(req.data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await broadcast_event(collection, doc_id)
    return {"ok": True}


@app.delete("/api/db/{collection}/{doc_id}")
async def db_delete_doc(collection: str, doc_id: str, request: Request):
    _authorize_db_write(request, collection, doc_id)
    db.collection(collection).document(doc_id).delete()
    return {"ok": True}


@app.get("/api/db/{collection}")
async def db_query_collection(
    collection: str,
    filters: Optional[str] = None,  # JSON string: [[field,op,val],...]
    order_by: Optional[str] = None,
    order_dir: str = "ASCENDING",
    limit_n: Optional[int] = None,
    request: Request = None,
):
    _authorize_db_read(request, collection, filters=filters)
    ref = db.collection(collection)
    if filters:
        try:
            for f in json.loads(filters):
                ref = ref.where(f[0], f[1], f[2])
        except Exception:
            pass
    if order_by:
        ref = ref.order_by(order_by, order_dir)
    if limit_n:
        ref = ref.limit(limit_n)
    docs = ref.get()
    return [{"id": d.id, "data": _normalize_doc(d.to_dict())} for d in docs]


@app.post("/api/db/{collection}")
async def db_add_doc(collection: str, req: DocSetRequest, request: Request):
    identity = _authorize_db_write(request, collection)
    if identity.get("kind") == "player":
        # No player can create a brand-new doc via add() — no ownership path.
        raise HTTPException(status_code=403, detail="Forbidden")
    ref = db.collection(collection).add(req.data)
    return {"id": ref.id}


# ─── Socket.IO Events ───
@sio.event
async def connect(sid, environ):
    """Client connected."""
    pass

@sio.event
async def disconnect(sid):
    """Client disconnected."""
    pass

def _socket_identity(data: Optional[dict]) -> Optional[dict]:
    """Validate the short-lived browser token attached to a subscription."""
    data = data or {}
    player_token = str(data.get("player_token") or "").strip()
    if player_token:
        info = _verify_token(player_token)
        if info and info.get("role") == "player":
            try:
                return {"kind": "player", "user_id": int(info.get("username"))}
            except (TypeError, ValueError):
                return None
    admin_token = str(data.get("admin_token") or "").strip()
    if admin_token:
        info = _verify_token(admin_token)
        if info and info.get("role") in {"internal", "admin", "super_admin"}:
            return {"kind": "admin", **info}
    return None


@sio.event
async def subscribe(sid, data):
    """Join only public rooms or rooms authorized for the supplied browser token."""
    data = data or {}
    collection = data.get('collection')
    doc_id = data.get('doc_id')
    if not collection or not isinstance(collection, str):
        return {"ok": False, "error": "Invalid collection"}
    if collection not in PUBLIC_DB_READ_COLLECTIONS:
        identity = _socket_identity(data)
        if not identity:
            return {"ok": False, "error": "Unauthorized"}
        if identity.get("kind") == "player":
            if collection != "users" or str(doc_id) != str(identity.get("user_id")):
                return {"ok": False, "error": "Forbidden"}
    room = f"{collection}:{doc_id}" if doc_id else collection
    await sio.enter_room(sid, room)
    return {"ok": True}

@sio.event
async def unsubscribe(sid, data):
    """Client unsubscribes from a collection/doc."""
    collection = data.get('collection')
    doc_id = data.get('doc_id')
    room = f"{collection}:{doc_id}" if doc_id else collection
    await sio.leave_room(sid, room)

async def broadcast_event(collection: str, doc_id: str):
    """Emit updated snapshot to all subscribers of this collection/doc."""
    room_exact = f"{collection}:{doc_id}"
    room_collection = collection

    def _read_doc():
        return db.collection(collection).document(doc_id).get()

    snap = await asyncio.to_thread(_read_doc)
    payload = {
        "type": "snapshot",
        "collection": collection,
        "id": doc_id,
        "data": snap.to_dict() if snap.exists else None,
        "exists": snap.exists
    }
    await sio.emit('snapshot', payload, room=room_exact)

    # For collection-level listeners, only send the changed doc
    # (client maintains local state from individual snapshots)
    query_payload = {
        "type": "query_snapshot",
        "collection": collection,
        "docs": [{"id": doc_id, "data": snap.to_dict() if snap.exists else None}]
    }
    await sio.emit('query_snapshot', query_payload, room=room_collection)

async def broadcast_cartelas_update():
    """Safely broadcast cartela pool update to all admin dashboards."""
    try:
        def _read_cartelas():
            docs = db.collection('cartelas_master').get()
            return [{"id": d.id, "data": d.to_dict()} for d in docs]
        cartela_list = await asyncio.to_thread(_read_cartelas)
        await sio.emit('query_snapshot', {
            "type": "query_snapshot",
            "collection": "cartelas_master",
            "docs": cartela_list,
        }, room="cartelas_master")
    except Exception as e:
        logger.warning(f"Error broadcasting cartelas update: {e}")


async def broadcast_cartela_pool(round_id: str):
    """Emit real-time cartela pool update to all clients watching this round."""
    round_snap = await asyncio.to_thread(lambda: db.collection('rounds').document(round_id).get())
    if round_snap.exists:
        rd = round_snap.to_dict()
        await sio.emit('cartela_pool', {
            "type": "cartela_pool",
            "round_id": round_id,
            "taken_cartelas": rd.get('taken_cartelas', []),
            "player_count": rd.get('player_count', 0),
            "pending_selections": rd.get('pending_selections', {}),
        }, room=f"rounds:{round_id}")


# ─── Background event broadcaster ───
async def _event_broadcast_loop():
    """Poll system_events table and push Socket.IO updates to subscribed clients."""
    last_id = ""
    while True:
        try:
            events = await asyncio.to_thread(_fetch_events, last_id)
            for ev in events:
                last_id = ev.id
                try:
                    await broadcast_event(ev.collection, ev.doc_id)
                except Exception as ev_err:
                    logger.warning(f"Error broadcasting event {ev.collection}/{ev.doc_id}: {ev_err}")
        except Exception as e:
            logger.warning(f"Error in event broadcast loop: {e}")
        await asyncio.sleep(0.25)


def _fetch_events(last_id: str):
    """Synchronous: query SystemEvent table for new events."""
    sess = SessionLocal()
    try:
        events = sess.query(SystemEvent)
        if last_id:
            events = events.filter(SystemEvent.id > last_id)
        return events.order_by(SystemEvent.created_at).limit(50).all()
    finally:
        sess.close()


# ─── Remote Database Bridge Endpoints for GatewayClient ───
def _serialize_db_dict(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize_db_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_db_dict(i) for i in obj]
    return obj


@app.get("/api/db/{collection}/{doc_id}")
async def gateway_db_get_doc(collection: str, doc_id: str):
    def _sync():
        ref = db.collection(collection).document(doc_id)
        snap = ref.get()
        if snap.exists:
            return {"id": snap.id, "data": _serialize_db_dict(snap.to_dict()), "exists": True}
        return None
    res = await asyncio.to_thread(_sync)
    if res is None:
        return Response(status_code=404, content=json.dumps({"exists": False}), media_type="application/json")
    return JSONResponse(res)


@app.post("/api/db/{collection}/{doc_id}")
async def gateway_db_set_doc(collection: str, doc_id: str, payload: dict = Body(...), request: Request = None):
    identity = _authorize_db_write(request, collection, doc_id)
    if identity.get("kind") == "player":
        payload = {**payload}
        data = _sanitize_player_user_data(payload.get("data", {}))
        payload["data"] = data
        payload["merge"] = True

    def _sync():
        data = payload.get("data", {})
        merge = payload.get("merge", False)
        # Parse ISO datetimes if present in payload
        ref = db.collection(collection).document(doc_id)
        ref.set(data, merge=merge)
        return {"status": "ok"}
    await asyncio.to_thread(_sync)
    return {"status": "ok"}


@app.patch("/api/db/{collection}/{doc_id}")
async def gateway_db_update_doc(collection: str, doc_id: str, payload: dict = Body(...), request: Request = None):
    identity = _authorize_db_write(request, collection, doc_id)
    if identity.get("kind") == "player":
        payload = {**payload}
        payload["data"] = _sanitize_player_user_data(payload.get("data", {}))

    def _sync():
        data = payload.get("data", {})
        ref = db.collection(collection).document(doc_id)
        # Handle special Increment field operations if passed as dict
        parsed_data = {}
        for k, v in data.items():
            if isinstance(v, dict) and v.get("_type") == "Increment":
                parsed_data[k] = Increment(v.get("value", 0))
            else:
                parsed_data[k] = v
        ref.update(parsed_data)
        return {"status": "ok"}
    await asyncio.to_thread(_sync)
    return {"status": "ok"}


@app.delete("/api/db/{collection}/{doc_id}")
async def gateway_db_delete_doc(collection: str, doc_id: str, request: Request):
    _authorize_db_write(request, collection, doc_id)

    def _sync():
        ref = db.collection(collection).document(doc_id)
        ref.delete()
    await asyncio.to_thread(_sync)
    return {"status": "ok"}


@app.get("/api/db/{collection}")
async def gateway_db_query_collection(
    collection: str,
    filters: Optional[str] = None,
    order_by: Optional[str] = None,
    order_dir: Optional[str] = "ASCENDING",
    limit_n: Optional[int] = None
):
    def _sync():
        ref = db.collection(collection)
        if filters:
            try:
                flist = json.loads(filters)
                for f in flist:
                    if len(f) == 3:
                        ref = ref.where(f[0], f[1], f[2])
            except Exception as e:
                logger.warning(f"Error parsing query filters: {e}")
        if order_by:
            ref = ref.order_by(order_by, order_dir)
        if limit_n:
            ref = ref.limit(limit_n)
        docs = list(ref.get())
        return [{"id": d.id, "data": _serialize_db_dict(d.to_dict())} for d in docs]
    res = await asyncio.to_thread(_sync)
    return JSONResponse(res)


# (startup merged into start_background_monitor above)


# ─── Dashboard & game (served from same service as API + bots) ───
# Set RENDER_API_ONLY=true to skip static files (saves RAM when frontend is on a separate service).
DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")

if not os.environ.get("RENDER_API_ONLY"):

    @app.get("/")
    async def dashboard_home():
        return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))


    @app.get("/index.html")
    async def dashboard_home_alias():
        return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))


    @app.get("/game")
    async def game_page():
        return FileResponse(os.path.join(DASHBOARD_DIR, "game.html"))


    @app.get("/game.html")
    async def game_page_alias():
        return FileResponse(os.path.join(DASHBOARD_DIR, "game.html"))


    @app.get("/login")
    async def login_page():
        return FileResponse(os.path.join(DASHBOARD_DIR, "login.html"))


    @app.get("/login.html")
    async def login_page_alias():
        return FileResponse(os.path.join(DASHBOARD_DIR, "login.html"))


    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)


    if os.path.isdir(os.path.join(DASHBOARD_DIR, "css")):
        app.mount("/css", StaticFiles(directory=os.path.join(DASHBOARD_DIR, "css")), name="css")
    if os.path.isdir(os.path.join(DASHBOARD_DIR, "js")):
        app.mount("/js", StaticFiles(directory=os.path.join(DASHBOARD_DIR, "js")), name="js")
    if os.path.isdir(os.path.join(DASHBOARD_DIR, "pages")):
        app.mount("/pages", StaticFiles(directory=os.path.join(DASHBOARD_DIR, "pages")), name="pages")
    if os.path.isdir(os.path.join(DASHBOARD_DIR, "components")):
        app.mount("/components", StaticFiles(directory=os.path.join(DASHBOARD_DIR, "components")), name="components")
    if os.path.isdir(os.path.join(DASHBOARD_DIR, "audio")):
        app.mount("/audio", StaticFiles(directory=os.path.join(DASHBOARD_DIR, "audio")), name="audio")
else:
    logger.info("🔒 RENDER_API_ONLY=true — static file serving disabled")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(socket_app, host="0.0.0.0", port=port)
