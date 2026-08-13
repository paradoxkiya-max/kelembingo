import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use a disposable local SQLite database for the route-level test.
db_path = os.path.join(tempfile.gettempdir(), "kelembingo-readiness-test.sqlite3")
try:
    os.remove(db_path)
except FileNotFoundError:
    pass
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["GAME_ENGINE_ENABLED"] = "false"
os.environ["RENDER_API_ONLY"] = "true"
os.environ["BOT_TOKEN"] = "test-token"
os.environ["ADMIN_PASSWORD"] = "test-password"

from fastapi.testclient import TestClient
from startup_state import mark_database_failed, mark_database_ready
from api.admin_api import app

mark_database_failed("test reset")
with TestClient(app) as client:
    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    assert health.json()["ready"] is False, health.text
    assert health.json()["status"] == "starting", health.text

    blocked_player = client.post("/api/player/auth", json={"initData": ""})
    assert blocked_player.status_code == 503, blocked_player.text

    blocked_admin = client.post(
        "/api/admin/login", json={"username": "test", "password": "test"}
    )
    assert blocked_admin.status_code == 503, blocked_admin.text

    mark_database_ready()
    ready_health = client.get("/api/health")
    assert ready_health.json() == {
        "status": "healthy",
        "ready": True,
        "timestamp": ready_health.json()["timestamp"],
    }

    open_player = client.post("/api/player/auth", json={"initData": ""})
    assert open_player.status_code == 401, open_player.text

print("startup readiness route test: PASS")
