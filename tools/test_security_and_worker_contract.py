import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = f"sqlite:///{Path('/tmp/kelembingo-security-contract.sqlite3')}"
os.environ["RENDER_API_ONLY"] = "false"
os.environ["ADMIN_AUTH_SECRET"] = "audit-secret"
os.environ["ADMIN_USERNAME"] = "audit-admin"
os.environ["ADMIN_PASSWORD"] = "audit-password"
os.environ["BOT_TOKEN"] = ""
os.environ["ADMIN_BOT_TOKEN"] = ""
os.environ["SUPPORT_BOT_TOKEN"] = ""
os.environ["ADMIN_SUPPORT_BOT_TOKEN"] = ""
os.environ["ADMIN_TALK_BOT_TOKEN"] = ""

import run_bots
assert run_bots._configured_token("MISSING_TOKEN") is False
os.environ["TEST_TOKEN"] = "your_bot_token_here"
assert run_bots._configured_token("TEST_TOKEN") is False
os.environ["TEST_TOKEN"] = "fresh-token"
assert run_bots._configured_token("TEST_TOKEN") is True

from startup_state import mark_database_ready
mark_database_ready()
from fastapi.testclient import TestClient
from api.admin_api import app, _create_player_token, _create_token

client = TestClient(app)
player = _create_player_token(123456)
admin = _create_token("audit-admin", "admin", "Audit Admin")
assert client.get("/api/admin/status", headers={"x-player-token": player}).status_code == 401
assert client.get("/api/admin/status", headers={"authorization": f"Bearer {admin}"}).status_code != 401
print("PASS: worker token gating and admin authorization contract")
