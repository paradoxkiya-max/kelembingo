from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
context = (ROOT / "dashboard-react/client/src/contexts/PlayerContext.tsx").read_text(encoding="utf-8")
gateway = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text(encoding="utf-8")
admin_api = (ROOT / "api/admin_api.py").read_text(encoding="utf-8")

assert 'PLAYER_TOKEN_KEY = "kelembingo.playerToken"' in context
assert 'PLAYER_SESSION_KEY = "kelembingo.playerSession"' in context
assert "function normalizePlayer" in context
assert "function readCachedPlayer" in context
assert "function cachePlayer" in context
assert "const hasCachedSession = Boolean(cachedToken && cachedPlayer)" in context
assert "setPlayer((current) => current || cachedPlayer)" in context
assert "const result = await playerApi.reconcile()" in context
assert "signed X-Player-Token remains the real source of authorization" in context
assert "if (status === 401 || status === 403)" in context
assert "clearPlayerSession()" in context
assert "window.localStorage.removeItem(PLAYER_SESSION_KEY)" in context
assert 'headers.set("X-Player-Token", token)' in gateway
auth_start = admin_api.index('async def player_auth(')
auth_route = admin_api[auth_start:admin_api.index('class LoginRequest', auth_start)]
assert 'asyncio.create_task(broadcast_event("users", str(user["id"])))' in auth_route
assert 'await broadcast_event("users", str(user["id"]))' not in auth_route
assert "user_id = _require_player(request)" in admin_api
assert "info and info.get(\"role\") == \"player\"" in admin_api

print("player session cache and server-token authority contract check: PASS")
