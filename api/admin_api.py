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
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import json
import datetime
import urllib.parse
from config import db, BOT_TOKEN
from firestore_db import MockFirestoreClient, SessionLocal, SystemEvent, FieldFilter, Increment, ArrayUnion, run_idempotent, engine as db_engine
from startup_state import is_database_ready

from game.round_engine import (RoundEngine, DEFAULT_STAKE, VALID_STAKES, SELECTION_DURATION, GAME_LENGTH_RANGE, TOTAL_CARTELAS, MAX_CARTELAS_PER_PLAYER, DERASH_RATIO, ADMIN_CUT_RATIO, _parse_dt, _grid_next_number_at)
from handlers.user_manager import UserManager
from handlers.bot_content import get_bot_text, get_config_value
from datetime import datetime, date, timedelta, timezone
from sqlalchemy import and_, or_, text as sql_text
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


def _read_user_sync(user_id: int):
    snap = db.collection('users').document(str(user_id)).get()
    return snap.to_dict() if snap.exists else None


FRONTEND_ORIGIN = os.getenv(
    "FRONTEND_URL",
    "https://kelembingo-frontend-i8yy-9m27.onrender.com",
).rstrip("/")
ALLOWED_ORIGINS = list(dict.fromkeys([
    FRONTEND_ORIGIN,
    "https://kelembingo-frontend-i8yy-9m27.onrender.com",
    "https://kelembingo-ncqv.onrender.com",
    "http://localhost:5173",
    "http://localhost:3000",
]))
ALLOWED_ORIGIN_SUFFIXES = []


# ─── Socket.IO Server ───
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins=ALLOWED_ORIGINS)

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
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
AUTH_SECRET = os.getenv("ADMIN_AUTH_SECRET", "").strip() or _secrets.token_hex(32)
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
AUTH_TOKEN_TTL = int(os.getenv("ADMIN_AUTH_TTL_HOURS", "12")) * 3600
PROTECTED_DB_COLLECTIONS = {"admins", "system", "settings", "bot_content"}
PUBLIC_ADMIN_PATHS = {"/api/admin/login"}
PUBLIC_DB_READ_COLLECTIONS = {"rounds", "cartelas_master", "cartelas"}
DATABASE_GATED_PREFIXES = (
    "/api/player",
    "/api/rounds",
    "/api/cartelas",
    "/api/deposits",
    "/api/withdrawals",
    "/api/wallet",
    "/api/users",
    "/api/history",
)
DATABASE_GATED_EXACT_PATHS = {"/api/auth/login", "/api/auth/me"}
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
        if admin and admin.get("role") in {"admin", "super_admin", "internal"}:
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


@app.post("/api/player/reconcile-state")
async def reconcile_player_state(request: Request):
    """Reconcile a player's active-round pointer without changing funds.

    A pointer is cleared only when its round is missing, cancelled, or fully
    paid/refunded without the player remaining in the round. Valid active and
    still-settling rounds are preserved so a player cannot double-join.
    """
    user_id = _require_player(request)

    def _reconcile():
        user_ref = db.collection("users").document(str(user_id))
        user_snap = user_ref.get()
        if not user_snap.exists:
            return {"ok": False, "error": "User not found"}
        user_data = user_snap.to_dict()
        active_id = user_data.get("active_round_id")
        if not user_data.get("is_playing") or not active_id:
            return {"ok": True, "active": False, "user": user_data}

        round_snap = db.collection("rounds").document(str(active_id)).get()
        round_data = round_snap.to_dict() if round_snap.exists else None
        player_key = str(user_id)
        member = bool(round_data and player_key in (round_data.get("players", {}) or {}))
        status = round_data.get("status") if round_data else None
        fully_settled = bool(round_data and round_data.get("payout_processed"))
        clear_stale = (
            not round_data
            or status == "cancelled"
            or (status == "completed" and fully_settled)
            or not member
        )
        if clear_stale:
            user_ref.update({
                "is_playing": False,
                "active_round_id": None,
                "updated_at": datetime.now(tz=timezone.utc),
            })
            user_data["is_playing"] = False
            user_data["active_round_id"] = None
            return {"ok": True, "active": False, "cleared": True, "user": user_data}

        return {
            "ok": True,
            "active": True,
            "active_round_id": str(active_id),
            "round_status": status,
            "settling": status == "completed" and not fully_settled,
            "user": user_data,
        }

    return await asyncio.to_thread(_reconcile)


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

    requires_admin = False
    if path.startswith("/api/admin"):
        if path not in PUBLIC_ADMIN_PATHS:
            needs_auth = True
            requires_admin = True
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

    if (
        path in DATABASE_GATED_EXACT_PATHS
        or path.startswith(DATABASE_GATED_PREFIXES)
        or path.startswith("/api/admin")
        or path.startswith("/api/db")
    ) and not is_database_ready():
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is still initializing; try again shortly.", "ready": False},
        )
    if needs_auth:
        identity = _auth_ok(request) if requires_admin else _auth_any(request)
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
ROOM_PROTOCOL_ENABLED = os.getenv("ROOM_PROTOCOL_ENABLED", "true").lower() == "true"
_room_intent_locks = {}  # round_id -> asyncio.Lock
_room_intent_results = {}  # round_id -> bounded intent_id -> ack payload
_ROOM_INTENT_RESULT_LIMIT = 1024

# Realtime delivery state. Direct request handlers and the durable event bridge can
# observe the same write; identical snapshots are emitted only once per process.
_realtime_state_lock = asyncio.Lock()
_last_broadcast_fingerprints = {}
_BROADCAST_FINGERPRINT_LIMIT = 4096

BINGO_NUMBERS = list(range(1, 76))
NUMBER_CALL_INTERVAL = 5  # seconds

# Cartela generation progress tracking
_cartela_gen_progress = {"status": "idle", "generated": 0, "total": 500, "error": None}


# ─── Models ───
class JoinRoundRequest(BaseModel):
    user_id: int
    cartela_numbers: List[int]
    user_name: str = "Player"
    require_pending: bool = False
    pending_revision: int = 0


class SelectRequest(BaseModel):
    user_id: int
    cartela_number: int
    request_id: Optional[str] = None


class BingoCheckRequest(BaseModel):
    user_id: int
    winning_cartela: Optional[int] = None


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
    minimum_amount: float = 10
    texts: dict[str, str] = {}
    error: Optional[str] = None


class DepositSubmitRequest(BaseModel):
    # The player identity comes from X-Player-Token, never from the request body.
    telebirr_name: str
    amount: float
    transaction_id: str


# ═══════════════════════════════════════════════════════════════
# Server-Side Game Loop
# ═══════════════════════════════════════════════════════════════
async def _finalize_pending_selections(round_id: str, round_data: dict) -> None:
    """Durably join the cartelas a player already selected before closing a round.

    The selection UI publishes each tap to ``pending_selections``. At the
    deadline this gateway-side finalizer is the source of truth, so a slow
    Telegram WebView or an in-flight client request cannot strand a selected
    player on a completed round.
    """
    pending = round_data.get('pending_selections') or {}
    if not isinstance(pending, dict):
        return
    for user_id_text, numbers in pending.items():
        try:
            user_id = int(user_id_text)
            selected = [int(number) for number in (numbers or [])]
        except (TypeError, ValueError):
            continue
        selected = list(dict.fromkeys(number for number in selected if 1 <= number <= 500))[:2]
        if not selected:
            continue
        user = await _db(lambda: _read_user_sync(user_id))
        user_name = (user or {}).get('first_name') or (user or {}).get('username') or 'Player'
        result = await engine.join_round(
            round_id, user_id, selected, user_name,
            require_pending=True,
            pending_revision=int(round_data.get('pending_revision', 0) or 0),
        )
        if result.get('error') and result.get('error') != 'You already joined this round':
            logger.info('[GameLoop] pending join skipped for round %s user %s: %s', round_id, user_id, result.get('error'))


async def _start_playing_round(round_id: str, round_data: dict) -> bool:
    """Transition a selecting round with players to playing and broadcast once."""
    player_count = int(round_data.get('player_count', 0) or 0)
    if player_count <= 0:
        return False
    now = datetime.now(tz=timezone.utc)
    round_stake = round_data.get('stake', DEFAULT_STAKE)
    total_pool = player_count * float(round_stake or 0)
    derash = round(total_pool * DERASH_RATIO, 2)
    await _db(lambda: db.collection('rounds').document(round_id).update({
        'status': 'playing',
        'derash': derash,
        'game_started_at': now,
        'selection_finalized_at': now,
        'next_number_at': now + timedelta(seconds=NUMBER_CALL_INTERVAL),
        'pending_selections': {},
    }))
    await broadcast_event('rounds', round_id)
    return True


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
                
                if datetime.now(tz=timezone.utc) >= dl_dt:
                    # Finalize selections on the gateway rather than waiting for
                    # slow Telegram WebView requests to reach /join after 0s.
                    post_start = await _db(lambda: db.collection('rounds').document(round_id).get())
                    if not post_start.exists:
                        return
                    await _finalize_pending_selections(round_id, post_start.to_dict())
                    refreshed_data = post_start.to_dict()
                    if refreshed_data.get('status') != 'selecting':
                        continue
                    if await _start_playing_round(round_id, refreshed_data):
                        break
                    # A short final grace period covers a tap arriving at the
                    # exact deadline without adding the former 10-second delay.
                    await asyncio.sleep(1)
                    recheck = await _db(lambda: db.collection('rounds').document(round_id).get())
                    if not recheck.exists:
                        return
                    recheck_data = recheck.to_dict()
                    if recheck_data.get('status') != 'selecting':
                        continue
                    await _finalize_pending_selections(round_id, recheck_data)
                    final_check = await _db(lambda: db.collection('rounds').document(round_id).get())
                    if not final_check.exists:
                        return
                    final_data = final_check.to_dict()
                    if final_data.get('status') != 'selecting':
                        continue
                    if await _start_playing_round(round_id, final_data):
                        break
                    # Still no players — cancel
                    if int(final_data.get('player_count', 0) or 0) <= 0:
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

            # Keep a visible five-second countdown between calls. Prefer the
            # durable deadline written with the previous number. If computation or
            # database work caused that deadline to pass, re-anchor the next call to
            # now + 5s instead of broadcasting a nearly-expired 0s/1s deadline.
            now = datetime.now(tz=timezone.utc)
            called_count = len(data.get('called_numbers', []))
            deadline = _parse_dt(data.get('next_number_at'))
            if deadline is None:
                started = _parse_dt(data.get('game_started_at'))
                if started:
                    deadline = started + timedelta(seconds=(called_count + 1) * NUMBER_CALL_INTERVAL)

            if deadline is None or deadline <= now:
                deadline = now + timedelta(seconds=NUMBER_CALL_INTERVAL)
                await _db(lambda: db.collection('rounds').document(round_id).update({
                    'next_number_at': deadline,
                }))

            delay = (deadline - datetime.now(tz=timezone.utc)).total_seconds()
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
                # Never fall back to an ordinary update based on the stale
                # pre-delay snapshot. The serialized engine call is the only
                # safe writer for called_numbers across gateway processes.
                logger.warning(f"Serialized number call failed for {round_id}: {e}")
                await asyncio.sleep(0.25)
                continue

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
                logger.info(
                    f"[GameLoop] ROUND COMPLETE {round_id}: "
                    f"winners={winners} calls={len(rd_after.get('called_numbers', []) or [])}"
                )
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
                winner_id = str(chosen_winner.get('user_id'))
                winning_cartela = int(chosen_winner.get('cartela_number', 0))
                completion = await engine.complete_round(
                    round_id,
                    int(winner_id),
                    winning_cartela,
                    completion_reason or 'smart_single_winner',
                    len(called_now),
                )
                if not completion.get('ok') and not completion.get('already_completed'):
                    logger.warning(
                        f"[GameLoop] Winner completion rejected for {round_id}: "
                        f"{completion.get('error', 'unknown error')}"
                    )
                    return

                # The completion transaction is the authority. If another
                # process won first, use its winner rather than this stale
                # loop's candidate when finalizing payout.
                authoritative_ids = completion.get('winner_ids') or [int(winner_id)]
                await broadcast_event('rounds', round_id)
                try:
                    result = await engine.end_round(round_id, authoritative_ids)
                    if isinstance(result, dict) and result.get('error'):
                        logger.error(f"[GameLoop] Payout skipped for {round_id}: {result['error']}")
                        return
                except Exception as e:
                    logger.error(f"[GameLoop] Error distributing prizes: {e}")
                for uid in set(list(players.keys()) + [str(w) for w in authoritative_ids]):
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
    """Start round monitoring only after database initialization has completed."""
    if not GAME_ENGINE_ENABLED:
        logger.info("[GameEngine] disabled for this service; gateway owns round progression")
        return

    async def _start_when_ready():
        while not is_database_ready():
            await asyncio.sleep(1)

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

    asyncio.create_task(_start_when_ready())


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
async def get_active_round(stake: int = FastAPIQuery(default=DEFAULT_STAKE)):
    """Get the current active round for the requested stake."""
    round_data = await engine.get_active_round(stake=stake)
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
        round_id,
        user_id,
        req.cartela_numbers,
        req.user_name,
        require_pending=bool(req.require_pending),
        pending_revision=int(req.pending_revision or 0),
    )
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    _start_game_loop(round_id)
    # Broadcast real-time cartela pool update
    await broadcast_cartela_pool(round_id)
    await broadcast_event('rounds', round_id)
    latest = await _db(lambda: db.collection('rounds').document(round_id).get())
    if latest.exists:
        return {**result, 'round': {'id': round_id, **(latest.to_dict() or {})}}
    return result


def _selection_deadline_expired(round_data: dict, now: Optional[datetime] = None) -> bool:
    raw_deadline = round_data.get('selection_deadline') if isinstance(round_data, dict) else None
    if not raw_deadline:
        return False
    if isinstance(raw_deadline, datetime):
        deadline = raw_deadline
    elif isinstance(raw_deadline, str):
        try:
            deadline = datetime.fromisoformat(raw_deadline.replace('Z', '+00:00'))
        except ValueError:
            return False
    else:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    current = now or datetime.now(tz=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current >= deadline


def _cartela_pool_snapshot(round_data: dict) -> dict:
    """Calculate the public pool from committed and pending unique cartelas."""
    cartelas = set()
    for number in round_data.get('taken_cartelas', []) or []:
        try:
            parsed = int(number)
        except (TypeError, ValueError):
            continue
        if 1 <= parsed <= TOTAL_CARTELAS:
            cartelas.add(parsed)
    pending = round_data.get('pending_selections') or {}
    if isinstance(pending, dict):
        for numbers in pending.values():
            for number in numbers or []:
                try:
                    parsed = int(number)
                except (TypeError, ValueError):
                    continue
                if 1 <= parsed <= TOTAL_CARTELAS:
                    cartelas.add(parsed)
    try:
        stake = float(round_data.get('stake', DEFAULT_STAKE) or 0)
    except (TypeError, ValueError):
        stake = 0.0
    count = max(int(round_data.get('player_count', 0) or 0), len(cartelas))
    if round_data.get('status') == 'playing':
        # Recompute active rounds from the policy constant so stale rounds that
        # were started by the former 75/25 code cannot display 7.5 for a 10 ETB card.
        derash = count * stake * DERASH_RATIO
    else:
        try:
            derash = float(round_data.get('derash')) if round_data.get('derash') is not None else count * stake * DERASH_RATIO
        except (TypeError, ValueError):
            derash = count * stake * DERASH_RATIO
    return {'player_count': count, 'derash_pool': round(derash, 2)}


def _mutate_pending_selection_sync(round_id: str, user_id: str, cartela_number: int, selecting: bool, request_id: Optional[str] = None) -> dict:
    """Atomically reserve or release one pending cartela and its stake."""
    action = 'select' if selecting else 'unselect'
    safe_request_id = str(request_id or _secrets.token_urlsafe(18))[:96]
    operation_key = f'pending-{action}:{round_id}:{user_id}:{cartela_number}:{safe_request_id}'

    def _apply(transaction):
        round_ref = db.collection('rounds').document(str(round_id))
        snap = transaction.get(round_ref)
        if not snap.exists:
            return {'error': 'Round not found'}
        round_data = snap.to_dict() or {}
        try:
            cartela_number_int = int(cartela_number)
        except (TypeError, ValueError):
            return {'error': 'Invalid cartela number'}
        if not 1 <= cartela_number_int <= TOTAL_CARTELAS:
            return {'error': 'Invalid cartela number'}
        uid_str = str(user_id)
        joined_player = (round_data.get('players', {}) or {}).get(uid_str, {}) or {}
        joined_cartelas = {int(number) for number in (joined_player.get('cartelas', []) or []) if str(number).isdigit() and 1 <= int(number) <= TOTAL_CARTELAS}
        if joined_cartelas:
            return {'error': 'Cartela already joined; opening the game board', 'joined_cartelas': sorted(joined_cartelas)}
        if round_data.get('status') not in ('selecting', None):
            return {'error': 'Round not in selecting phase'}
        if _selection_deadline_expired(round_data):
            return {'error': 'Selection window closed; waiting for round transition'}
        user_ref = db.collection('users').document(uid_str)
        user_doc = transaction.get(user_ref)
        if not user_doc.exists:
            return {'error': 'Player account not found'}
        user_data = user_doc.to_dict() or {}
        # A player may participate in more than one active round. Wallet
        # reservations are scoped by round and settlement tracks active_round_ids.
        try:
            wallet = float(user_data.get('play_wallet', 0) or 0)
            stake = float(round_data.get('stake', DEFAULT_STAKE) or 0)
        except (TypeError, ValueError):
            return {'error': 'Wallet or round stake is invalid'}
        if not math.isfinite(wallet) or not math.isfinite(stake) or stake <= 0:
            return {'error': 'Wallet or round stake is invalid'}
        raw_pending = round_data.get('pending_selections', {}) or {}
        pending = {str(uid): list(numbers) if isinstance(numbers, list) else [] for uid, numbers in raw_pending.items()} if isinstance(raw_pending, dict) else {}
        selected = list(dict.fromkeys(int(number) for number in pending.get(uid_str, []) if str(number).isdigit() and 1 <= int(number) <= TOTAL_CARTELAS))
        raw_reservations = round_data.get('pending_reservations', {}) or {}
        reservations = {str(uid): list(numbers) if isinstance(numbers, list) else [] for uid, numbers in raw_reservations.items()} if isinstance(raw_reservations, dict) else {}
        reserved = list(dict.fromkeys(int(number) for number in reservations.get(uid_str, []) if str(number).isdigit() and 1 <= int(number) <= TOTAL_CARTELAS))
        wallet_changed = False
        if selecting:
            if cartela_number_int not in selected:
                if len(selected) >= MAX_CARTELAS_PER_PLAYER:
                    return {'error': f'Maximum {MAX_CARTELAS_PER_PLAYER} cartelas allowed'}
                if cartela_number_int in {int(value) for value in (round_data.get('taken_cartelas', []) or [])}:
                    return {'error': f'Cartela #{cartela_number_int} is already taken'}
                for other_uid, numbers in pending.items():
                    if other_uid != uid_str and cartela_number_int in {int(value) for value in numbers if str(value).isdigit()}:
                        return {'error': f'Cartela #{cartela_number_int} is already being selected'}
                if wallet < stake:
                    return {'error': f'Not enough balance. Need {stake:g} ETB, have {wallet:g} ETB'}
                selected.append(cartela_number_int)
                if cartela_number_int not in reserved:
                    reserved.append(cartela_number_int)
                    wallet -= stake
                    wallet_changed = True
        elif cartela_number_int in selected:
            selected = [number for number in selected if number != cartela_number_int]
            if cartela_number_int in reserved:
                reserved = [number for number in reserved if number != cartela_number_int]
                wallet += stake
                wallet_changed = True
        pending[uid_str] = selected
        reservations[uid_str] = reserved
        revision = int(round_data.get('pending_revision', 0) or 0) + 1
        transaction.update(round_ref, {'pending_selections': pending, 'pending_reservations': reservations, 'pending_revision': revision})
        if wallet_changed:
            transaction.update(user_ref, {'play_wallet': round(wallet, 2), 'updated_at': datetime.now(tz=timezone.utc)})
        pool = _cartela_pool_snapshot({**round_data, 'pending_selections': pending})
        return {'ok': True, '_pending': pending, '_taken': round_data.get('taken_cartelas', []), '_pc': pool['player_count'], '_derash': pool['derash_pool'], '_revision': revision, 'play_wallet': round(wallet, 2), 'selected_cartelas': selected, 'reserved_cartelas': reserved}

    return run_idempotent(operation_key, f'pending_{action}', _apply, lock_keys=[f"round:{round_id}", f"user:{user_id}"], lock_timeout_ms=2500, statement_timeout_ms=5000)


@app.post("/api/rounds/{round_id}/select")
async def select_cartela(round_id: str, req: SelectRequest, request: Request):
    """Atomically reserve one cartela and its stake for this player."""
    uid_str = str(_actor_user_id(request, req.user_id))
    result = await asyncio.to_thread(_mutate_pending_selection_sync, round_id, uid_str, req.cartela_number, True, req.request_id)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    pool_snapshot = {
        "type": "cartela_pool",
        "round_id": round_id,
        "taken_cartelas": result.get('_taken', []),
        "player_count": result.get('_pc', 0),
        "derash_pool": result.get('_derash', 0),
        "pending_revision": result.get('_revision', 0),
        "pending_selections": result.get('_pending', {}),
    }
    await sio.emit('cartela_pool', pool_snapshot, room=f"rounds:{round_id}")
    await broadcast_event('users', uid_str)
    return {"ok": True, "play_wallet": result.get('play_wallet'), "selected_cartelas": result.get("selected_cartelas", []), "reserved_cartelas": result.get('reserved_cartelas', []), **pool_snapshot}


@app.post("/api/rounds/{round_id}/unselect")
async def unselect_cartela(round_id: str, req: SelectRequest, request: Request):
    """Atomically release one pending cartela and refund its reservation."""
    uid_str = str(_actor_user_id(request, req.user_id))
    result = await asyncio.to_thread(_mutate_pending_selection_sync, round_id, uid_str, req.cartela_number, False, req.request_id)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    pool_snapshot = {
        "type": "cartela_pool",
        "round_id": round_id,
        "taken_cartelas": result.get('_taken', []),
        "player_count": result.get('_pc', 0),
        "derash_pool": result.get('_derash', 0),
        "pending_revision": result.get('_revision', 0),
        "pending_selections": result.get('_pending', {}),
    }
    await sio.emit('cartela_pool', pool_snapshot, room=f"rounds:{round_id}")
    await broadcast_event('users', uid_str)
    return {"ok": True, "play_wallet": result.get('play_wallet'), "selected_cartelas": result.get("selected_cartelas", []), "reserved_cartelas": result.get('reserved_cartelas', []), **pool_snapshot}


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


@app.post("/api/rounds/{round_id}/claim-bingo")
async def claim_bingo(round_id: str, req: BingoCheckRequest, request: Request):
    """Atomically validate one card and award the first valid Bingo claim."""
    user_id = _actor_user_id(request, req.user_id)
    result = await engine.claim_bingo(round_id, user_id, req.winning_cartela)
    if result.get('ok') and result.get('winner'):
        await broadcast_event('rounds', round_id)
        for uid in result.get('winner_ids', []):
            await broadcast_event('users', str(uid))
    if result.get('error') and not result.get('already_completed'):
        raise HTTPException(status_code=400, detail=result['error'])
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
async def get_rounds(limit: int = 20, status: Optional[str] = None, winners_only: bool = False):
    """Get recent rounds, with optional player-facing status/winner filters.

    The admin console keeps the unfiltered operational list. Player History
    can request completed rounds containing winners without changing the
    admin history semantics.
    """
    requested_limit = max(1, min(int(limit), 500))
    fetch_limit = requested_limit if not (status or winners_only) else min(500, max(requested_limit * 5, 50))
    rounds = await engine.get_recent_rounds(fetch_limit)
    if status:
        rounds = [round_data for round_data in rounds if str(round_data.get("status", "")).lower() == status.lower()]
    if winners_only:
        rounds = [round_data for round_data in rounds if isinstance(round_data.get("winners"), list) and len(round_data.get("winners") or []) > 0]
    rounds = rounds[:requested_limit]
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


_PUBLIC_STATS_CACHE = None
_PUBLIC_STATS_CACHE_EXPIRES = 0.0


def _public_stats_sync():
    """Return small public aggregates without materializing every round document."""
    global _PUBLIC_STATS_CACHE, _PUBLIC_STATS_CACHE_EXPIRES
    now_mono = time.monotonic()
    if _PUBLIC_STATS_CACHE is not None and now_mono < _PUBLIC_STATS_CACHE_EXPIRES:
        return dict(_PUBLIC_STATS_CACHE)
    today_iso = datetime.now(tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    if db_engine.dialect.name == 'postgresql':
        statement = sql_text("""
            SELECT
                COALESCE(SUM(CASE
                    WHEN jsonb_extract_path_text(CAST(data AS JSONB), 'status') IN ('selecting', 'playing')
                    THEN COALESCE(NULLIF(jsonb_extract_path_text(CAST(data AS JSONB), 'player_count'), '')::BIGINT, 0)
                    ELSE 0
                END), 0) AS active_cartelas,
                COALESCE(SUM(CASE
                    WHEN jsonb_extract_path_text(CAST(data AS JSONB), 'status') = 'completed'
                     AND COALESCE(NULLIF(jsonb_extract_path_text(CAST(data AS JSONB), 'player_count'), '')::BIGINT, 0) > 0
                    THEN 1 ELSE 0
                END), 0) AS games_played,
                COALESCE(SUM(CASE
                    WHEN jsonb_extract_path_text(CAST(data AS JSONB), 'status') = 'completed'
                     AND jsonb_extract_path_text(CAST(data AS JSONB), 'completed_at') >= :today_iso
                    THEN CASE
                        WHEN jsonb_typeof(CAST(data AS JSONB)->'winners') = 'array'
                        THEN jsonb_array_length(CAST(data AS JSONB)->'winners')
                        ELSE 0
                    END
                    ELSE 0
                END), 0) AS winners_today
            FROM firestore_documents
            WHERE collection = 'rounds'
        """)
        with SessionLocal() as session:
            row = session.execute(statement, {'today_iso': today_iso}).mappings().one()
            _PUBLIC_STATS_CACHE = {
                'active_cartelas': int(row['active_cartelas'] or 0),
                'games_played': int(row['games_played'] or 0),
                'winners_today': int(row['winners_today'] or 0),
            }
            _PUBLIC_STATS_CACHE_EXPIRES = now_mono + 5.0
            return dict(_PUBLIC_STATS_CACHE)

    # Local SQLite fallback for development/tests only.
    active_cartelas = games_played = winners_today = 0
    today = datetime.now(tz=timezone.utc).date()
    for doc in db.collection('rounds').get():
        data = doc.to_dict() or {}
        status = data.get('status')
        if status in ('selecting', 'playing'):
            active_cartelas += int(data.get('player_count') or 0)
        elif status == 'completed' and int(data.get('player_count') or 0) > 0:
            games_played += 1
            completed_at = _parse_dt(data.get('completed_at'))
            if completed_at and completed_at.date() == today:
                winners_today += len(data.get('winners') or [])
    _PUBLIC_STATS_CACHE = {
        'active_cartelas': active_cartelas,
        'games_played': games_played,
        'winners_today': winners_today,
    }
    _PUBLIC_STATS_CACHE_EXPIRES = now_mono + 5.0
    return dict(_PUBLIC_STATS_CACHE)


@app.get("/api/public/stats")
async def public_stats():
    """Fast, non-sensitive home-screen statistics."""
    return await asyncio.to_thread(_public_stats_sync)


@app.get("/api/health")
async def health_check():
    """Fast liveness check with a non-secret database readiness signal."""
    ready = is_database_ready()
    return {
        "status": "healthy" if ready else "starting",
        "ready": ready,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


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


async def _notify_admin_withdrawal_web(withdrawal_data: dict, withdrawal_id: str):
    try:
        from config import ADMIN_BOT_TOKEN, ADMIN_CHAT_ID
        if not ADMIN_BOT_TOKEN or not ADMIN_CHAT_ID:
            return
        text = (
            f"🎰 *New Withdrawal Request*\n\n"
            f"👤 User: {withdrawal_data.get('firstName', 'Unknown')} (@{withdrawal_data.get('username', '')})\n"
            f"🆔 ID: `{withdrawal_data.get('userId')}`\n"
            f"💰 Amount: *{withdrawal_data.get('amount', 0)} ETB*\n"
            f"📱 Phone: {withdrawal_data.get('phone', '')}\n"
            f"📛 TeleBirr: {withdrawal_data.get('telebirrName', '')}\n"
            f"🔗 ID: `{withdrawal_id}`"
        )
        bot = Bot(token=ADMIN_BOT_TOKEN)
        await bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=text, parse_mode='Markdown')
    except Exception as exc:
        logger.warning("[NotifyAdminWithdrawal] Error: %s", exc)


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
        result = await asyncio.to_thread(
            lambda: asyncio.run(um.validate_withdrawal(int(user_id), amount))
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Withdrawal validation failed for user %s: %s", user_id, exc)
        return {"ok": False, "error": "system_error"}


@app.get("/api/deposits/config/{user_id}", response_model=DepositConfigResponse)
async def get_deposit_config(user_id: int, request: Request):
    """Return the live web deposit settings and guardrails used by the Telegram bot flow."""
    if _actor_user_id(request, user_id) != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    user, pending_count, admin_online, phone, minimum_amount, name_prompt, amount_prompt, minimum_text, send_to = await asyncio.gather(
        asyncio.to_thread(_read_user_sync, user_id),
        asyncio.to_thread(_get_pending_deposit_count, user_id),
        asyncio.to_thread(_is_admin_online_sync),
        asyncio.to_thread(get_bot_text, 'deposit_phone', db),
        asyncio.to_thread(get_config_value, 'cfg_min_deposit', db, int),
        asyncio.to_thread(get_bot_text, 'deposit_ask_name', db),
        asyncio.to_thread(get_bot_text, 'deposit_ask_amount', db),
        asyncio.to_thread(get_bot_text, 'deposit_min_amount', db),
        asyncio.to_thread(get_bot_text, 'deposit_send_to', db, amount='{amount}', phone='{phone}'),
    )
    minimum_amount = float(minimum_amount or 10)
    texts = {
        'name_prompt': name_prompt,
        'amount_prompt': amount_prompt,
        'minimum_amount': minimum_text,
        'send_to': send_to,
    }
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    pending_limit = 3

    if pending_count >= pending_limit:
        return DepositConfigResponse(
            ok=False,
            phone=phone,
            admin_online=admin_online,
            pending_count=pending_count,
            pending_limit=pending_limit,
            minimum_amount=minimum_amount,
            texts=texts,
            error='too_many_pending',
        )

    if not admin_online:
        return DepositConfigResponse(
            ok=False,
            phone=phone,
            admin_online=admin_online,
            pending_count=pending_count,
            pending_limit=pending_limit,
            minimum_amount=minimum_amount,
            texts=texts,
            error='admin_offline',
        )

    return DepositConfigResponse(
        ok=True,
        phone=phone,
        admin_online=admin_online,
        pending_count=pending_count,
        pending_limit=pending_limit,
        minimum_amount=minimum_amount,
        texts=texts,
    )
@app.post("/api/deposits/submit")

async def submit_deposit(req: DepositSubmitRequest, request: Request):
    """Submit a pending deposit request using the same core rules as the Telegram bot flow.
    The user is verified from the player token, never trusted from the body."""
    user_id = _require_player(request)
    user, pending_count, admin_online = await asyncio.gather(
        asyncio.to_thread(_read_user_sync, user_id),
        asyncio.to_thread(_get_pending_deposit_count, user_id),
        asyncio.to_thread(_is_admin_online_sync),
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    pending_limit = 3
    if pending_count >= pending_limit:
        raise HTTPException(status_code=400, detail=get_bot_text('deposit_too_many', db))

    if not admin_online:
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

    asyncio.create_task(_notify_admin_deposit_web(deposit_data, deposit_id))

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
    user = await asyncio.to_thread(_read_user_sync, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        amount = float(req.amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_amount")
    if not math.isfinite(amount) or amount <= 0:
        raise HTTPException(status_code=400, detail="invalid_amount")

    validation = await asyncio.to_thread(
        lambda: asyncio.run(user_manager.validate_withdrawal(user_id, amount))
    )
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

    asyncio.create_task(_notify_admin_withdrawal_web(withdrawal_data, result['withdrawal_id']))

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
            if collection == "player_payments":
                if str(data.get("user_id") or "") != str(identity.get("user_id") or ""):
                    return {"ok": False, "error": "Forbidden"}
            elif collection != "users" or str(doc_id) != str(identity.get("user_id")):
                return {"ok": False, "error": "Forbidden"}
    room = (f"player_payments:{data.get('user_id')}" if collection == "player_payments" else (f"{collection}:{doc_id}" if doc_id else collection))
    await sio.enter_room(sid, room)
    return {"ok": True}

@sio.event
async def unsubscribe(sid, data):
    """Client unsubscribes from a collection/doc."""
    collection = data.get('collection')
    doc_id = data.get('doc_id')
    room = (f"player_payments:{data.get('user_id')}" if collection == "player_payments" else (f"{collection}:{doc_id}" if doc_id else collection))
    await sio.leave_room(sid, room)

def _room_intent_lock(round_id: str) -> asyncio.Lock:
    lock = _room_intent_locks.get(str(round_id))
    if lock is None:
        lock = asyncio.Lock()
        _room_intent_locks[str(round_id)] = lock
    return lock


def _room_state_payload(round_id: str, user_id: str, round_data: Optional[dict] = None) -> dict:
    if round_data is None:
        snap = db.collection('rounds').document(str(round_id)).get()
        if not snap.exists:
            return {'type': 'room_state', 'round_id': str(round_id), 'exists': False, 'status': 'missing', 'user_id': str(user_id)}
        round_data = snap.to_dict() or {}
    pool = _cartela_pool_snapshot(round_data)
    player = (round_data.get('players', {}) or {}).get(str(user_id), {}) or {}
    pending_for_user = (round_data.get('pending_selections', {}) or {}).get(str(user_id), []) or {}
    selected_cartelas = list(player.get('cartelas', []) or []) or list(pending_for_user)
    round_payload = {'id': str(round_id), **round_data}
    if round_data.get('status') == 'playing':
        round_payload['derash'] = pool.get('derash_pool', 0)
    return {
        'type': 'room_state',
        'round_id': str(round_id),
        'exists': True,
        'status': round_data.get('status'),
        'selection_deadline': round_data.get('selection_deadline'),
        'game_started_at': round_data.get('game_started_at'),
        'next_number_at': round_data.get('next_number_at'),
        'called_numbers': round_data.get('called_numbers', []) or [],
        'last_called_number': round_data.get('last_called_number'),
        'player_count': pool.get('player_count', 0),
        'derash_pool': pool.get('derash_pool', 0),
        'taken_cartelas': round_data.get('taken_cartelas', []) or [],
        'pending_selections': round_data.get('pending_selections', {}) or {},
        "pending_revision": int(round_data.get("pending_revision", 0) or 0),
        'selected_cartelas': selected_cartelas,
        'player': player,
        'round': round_payload,
        'user_id': str(user_id),
    }


async def _emit_room_state(round_id: str, user_id: str, round_data: Optional[dict] = None, sid: Optional[str] = None):
    payload = await asyncio.to_thread(_room_state_payload, str(round_id), str(user_id), round_data)
    if sid:
        await sio.emit("room_state", {
            **payload,
        }, to=sid)
    else:
        await sio.emit("room_state", payload, room=f'rounds:{round_id}')
    return payload


async def _emit_room_compat_updates(round_id: str, user_id: str, result: dict):
    pool_snapshot = {
        'type': 'cartela_pool',
        'round_id': str(round_id),
        'taken_cartelas': result.get('_taken', []),
        'player_count': result.get('_pc', 0),
        'derash_pool': result.get('_derash', 0),
        'pending_revision': result.get('_revision', 0),
        'pending_selections': result.get('_pending', {}),
    }
    await sio.emit('cartela_pool', pool_snapshot, room=f'rounds:{round_id}')
    asyncio.create_task(broadcast_event('users', str(user_id)))
    asyncio.create_task(broadcast_event('rounds', str(round_id)))


@sio.event
async def room_join(sid, data):
    data = data or {}
    round_id = str(data.get('round_id') or '').strip()
    identity = _socket_identity(data)
    requested_user = str(data.get('user_id') or '').strip()
    if not round_id or not identity or identity.get('kind') != 'player':
        return {'ok': False, 'error': 'Unauthorized room join'}
    user_id = str(identity.get('user_id'))
    if requested_user and requested_user != user_id:
        return {'ok': False, 'error': 'Forbidden room join'}
    await sio.enter_room(sid, f'rounds:{round_id}')
    payload = await _emit_room_state(round_id, user_id, sid=sid)
    return {'ok': bool(payload.get('exists')), **payload}


@sio.event
async def room_leave(sid, data):
    round_id = str((data or {}).get('round_id') or '').strip()
    if round_id:
        await sio.leave_room(sid, f'rounds:{round_id}')
    return {'ok': True}


@sio.event
async def room_intent(sid, data):
    data = data or {}
    round_id = str(data.get('round_id') or '').strip()
    intent_id = str(data.get('intent_id') or data.get('request_id') or '').strip()[:96]
    action = str(data.get('action') or '').strip().lower()
    try:
        cartela_number = int(data.get('cartela_number'))
    except (TypeError, ValueError):
        cartela_number = 0
    identity = _socket_identity(data)
    if not ROOM_PROTOCOL_ENABLED:
        return {'ok': False, 'error': 'room_protocol_disabled', 'intent_id': intent_id}
    if not round_id or not intent_id or action not in {'select', 'unselect'}:
        return {'ok': False, 'error': 'Invalid room intent', 'intent_id': intent_id}
    if not identity or identity.get('kind') != 'player':
        return {'ok': False, 'error': 'Unauthorized room intent', 'intent_id': intent_id}
    user_id = str(identity.get('user_id'))
    requested_user = str(data.get('user_id') or '').strip()
    if requested_user and requested_user != user_id:
        return {'ok': False, 'error': 'Forbidden room intent', 'intent_id': intent_id}
    lock = _room_intent_lock(round_id)
    async with lock:
        cache = _room_intent_results.setdefault(round_id, {})
        cached = cache.get(intent_id)
        if cached:
            if str(cached.get('user_id')) != user_id:
                return {'ok': False, 'error': 'Intent ID already used', 'intent_id': intent_id}
            await sio.emit("room_ack", cached, to=sid)
            return cached
        result = await asyncio.to_thread(_mutate_pending_selection_sync, round_id, user_id, cartela_number, action == 'select', intent_id)
        ack = {
            'type': 'room_ack',
            'ok': 'error' not in result,
            'intent_id': intent_id,
            'round_id': round_id,
            'user_id': user_id,
            'action': action,
            'cartela_number': cartela_number,
            'error': result.get('error'),
            'play_wallet': result.get('play_wallet'),
            'selected_cartelas': result.get('selected_cartelas', result.get('joined_cartelas', [])),
            'reserved_cartelas': result.get('reserved_cartelas', []),
            'taken_cartelas': result.get('_taken', []),
            'pending_selections': result.get('_pending', {}),
            'pending_revision': result.get('_revision', 0),
            'player_count': result.get('_pc', 0),
            'derash_pool': result.get('_derash', 0),
        }
        cache[intent_id] = ack
        while len(cache) > _ROOM_INTENT_RESULT_LIMIT:
            cache.pop(next(iter(cache)))
        await sio.emit("room_ack", ack, to=sid)
        if 'error' not in result:
            await _emit_room_compat_updates(round_id, user_id, result)
        asyncio.create_task(_emit_room_state(round_id, user_id))
        state = await asyncio.to_thread(_room_state_payload, round_id, user_id)
        ack['status'] = state.get('status')
        ack['round'] = state.get('round')
        return ack


def _snapshot_fingerprint(collection: str, doc_id: str, exists: bool, data):
    """Build a stable, bounded-cost identity for an emitted document snapshot."""
    return json.dumps(
        {
            "collection": collection,
            "id": str(doc_id),
            "exists": bool(exists),
            "data": data,
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )


async def broadcast_event(collection: str, doc_id: str):
    """Emit one current snapshot, suppressing duplicate observations of one write."""
    room_exact = f"{collection}:{doc_id}"
    room_collection = collection

    def _read_doc():
        return db.collection(collection).document(doc_id).get()

    cache_key = f"{collection}:{doc_id}"

    # Direct route broadcasts and the durable event bridge can see the same
    # committed write. Read only after acquiring the small fanout lock so a
    # queued older observation cannot emit a stale snapshot after a newer one.
    async with _realtime_state_lock:
        snap = await asyncio.to_thread(_read_doc)
        snapshot_data = snap.to_dict() if snap.exists else None
        if collection == 'rounds' and isinstance(snapshot_data, dict) and snapshot_data.get('status') == 'playing':
            pool = _cartela_pool_snapshot(snapshot_data)
            snapshot_data = {**snapshot_data, 'derash': pool.get('derash_pool', 0)}
        fingerprint = _snapshot_fingerprint(collection, doc_id, snap.exists, snapshot_data)
        if _last_broadcast_fingerprints.get(cache_key) == fingerprint:
            return False
        _last_broadcast_fingerprints[cache_key] = fingerprint
        while len(_last_broadcast_fingerprints) > _BROADCAST_FINGERPRINT_LIMIT:
            _last_broadcast_fingerprints.pop(next(iter(_last_broadcast_fingerprints)))

        payload = {
            "type": "snapshot",
            "collection": collection,
            "id": doc_id,
            "data": snapshot_data,
            "exists": snap.exists,
        }
        await sio.emit('snapshot', payload, room=room_exact)

        # Collection listeners receive only the changed document. The client
        # applies its own query filters before invoking the listener callback.
        query_payload = {
            "type": "query_snapshot",
            "collection": collection,
            "docs": [{"id": doc_id, "data": snapshot_data}],
        }
        await sio.emit('query_snapshot', query_payload, room=room_collection)

        if collection == "rounds" and doc_id:
            pool = _cartela_pool_snapshot(snapshot_data or {})
            await sio.emit('cartela_pool', {
                'type': 'cartela_pool',
                'round_id': str(doc_id),
                'taken_cartelas': (snapshot_data or {}).get('taken_cartelas', []) or [],
                'player_count': pool.get('player_count', 0),
                'derash_pool': pool.get('derash_pool', 0),
                'pending_revision': int((snapshot_data or {}).get('pending_revision', 0) or 0),
                'pending_selections': (snapshot_data or {}).get('pending_selections', {}) or {},
            }, room=f'rounds:{doc_id}')

        # Player wallet screens subscribe to a private aggregate room instead of
        # exposing deposit/withdrawal collections to a player token.
        if collection in {"deposits", "withdrawals"} and isinstance(snapshot_data, dict):
            payment_user_id = snapshot_data.get("userId") or snapshot_data.get("user_id")
            if payment_user_id:
                await sio.emit("query_snapshot", {
                    "type": "query_snapshot",
                    "collection": "player_payments",
                    "id": doc_id,
                    "docs": [{"id": doc_id, "data": snapshot_data}],
                }, room=f"player_payments:{payment_user_id}")
    return True

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
            "pending_revision": int(rd.get('pending_revision', 0) or 0),
            "pending_selections": rd.get('pending_selections', {}),
        }, room=f"rounds:{round_id}")


# ─── Background event broadcaster ───
def _coalesce_events(events):
    """Keep only the newest durable event per collection/document pair."""
    latest_events = {}
    for ev in events or []:
        latest_events[(ev.collection, ev.doc_id)] = ev
    return list(latest_events.values())


def _latest_event_cursor():
    """Return the newest durable event so startup does not replay old history."""
    sess = SessionLocal()
    try:
        event = sess.query(SystemEvent).order_by(
            SystemEvent.created_at.desc(), SystemEvent.id.desc()
        ).first()
        if not event:
            return None, None
        return event.created_at, event.id
    finally:
        sess.close()


async def _event_broadcast_loop():
    """Bridge writes without direct route broadcasts using an indexed cursor."""
    last_created_at, last_event_id = await asyncio.to_thread(_latest_event_cursor)
    poll_interval = max(0.05, float(os.getenv("REALTIME_EVENT_POLL_SECONDS", "0.15")))
    while True:
        try:
            events = await asyncio.to_thread(
                _fetch_events,
                last_created_at,
                last_event_id,
            )
            for ev in events:
                last_created_at = ev.created_at
                last_event_id = ev.id
            events = _coalesce_events(events)
            for ev in events:
                try:
                    await broadcast_event(ev.collection, ev.doc_id)
                except Exception as ev_err:
                    logger.warning(f"Error broadcasting event {ev.collection}/{ev.doc_id}: {ev_err}")
        except Exception as e:
            logger.warning(f"Error in event broadcast loop: {e}")
        await asyncio.sleep(poll_interval)


def _fetch_events(last_created_at=None, last_event_id=None):
    """Query new events by (created_at, id), never by random UUID ordering alone."""
    sess = SessionLocal()
    try:
        events = sess.query(SystemEvent)
        if last_created_at is not None:
            events = events.filter(or_(
                SystemEvent.created_at > last_created_at,
                and_(
                    SystemEvent.created_at == last_created_at,
                    SystemEvent.id > (last_event_id or ""),
                ),
            ))
        return events.order_by(
            SystemEvent.created_at.asc(), SystemEvent.id.asc()
        ).limit(100).all()
    finally:
        sess.close()


# The canonical /api/db/* routes are defined above with the shared auth middleware.
# Do not add a second bridge implementation here: duplicate route registration is
# order-dependent and can silently bypass the intended request contract.


# (startup merged into start_background_monitor above)


# ─── Frontend separation ───────────────────────────────────────────────
# The player/admin UI is now built by the separate React static service.
# The gateway intentionally does not serve legacy dashboard files or UI assets.
logger.info("🔒 React frontend is served by the separate static service; gateway UI routes are disabled")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(socket_app, host="0.0.0.0", port=port)
