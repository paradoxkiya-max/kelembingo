from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
frontend_gateway = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text(encoding="utf-8")
admin_api = (ROOT / "api/admin_api.py").read_text(encoding="utf-8")
gateway_client = (ROOT / "gateway_client.py").read_text(encoding="utf-8")
user_manager = (ROOT / "handlers/user_manager.py").read_text(encoding="utf-8")

assert "https://kelembingo-ncqv.onrender.com" in frontend_gateway
assert "https://kelembingo-frontend-i8yy-9m27.onrender.com" in admin_api
assert '"/api/player/auth"' in admin_api
assert "_http_session = requests.Session()" in gateway_client
assert "_http_session.request" in gateway_client
assert "asyncio.to_thread(self._get_user_sync, user_id)" in user_manager
assert "asyncio.to_thread(self._get_or_create_user_sync" in user_manager

print("PASS: live frontend gateway/CORS contract and nonblocking bot read path")
