import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
DB_PATH = Path(tempfile.gettempdir()) / "kelembingo-query-adapter.sqlite3"
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

from firestore_db import MockFirestoreClient


db = MockFirestoreClient()
db.collection("rounds").document("r1").set({"status": "selecting", "stake": 10, "created_at": "2026-01-01T00:00:00+00:00"})
db.collection("rounds").document("r2").set({"status": "playing", "stake": 20, "created_at": "2026-01-02T00:00:00+00:00"})
db.collection("users").document("u1").set({"is_playing": True})

selecting = db.collection("rounds").where("status", "==", "selecting").get()
recent = db.collection("rounds").where("stake", "==", 10).order_by("created_at", "DESCENDING").limit(1).get()
playing_users = db.collection("users").where("is_playing", "==", True).get()

assert [doc.id for doc in selecting] == ["r1"]
assert [doc.id for doc in recent] == ["r1"]
assert [doc.id for doc in playing_users] == ["u1"]
print("sqlite query adapter regression test: PASS")
try:
    DB_PATH.unlink()
except FileNotFoundError:
    pass
