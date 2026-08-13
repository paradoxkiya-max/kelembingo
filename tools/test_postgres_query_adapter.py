import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from firestore_db import MockFirestoreClient


db = MockFirestoreClient()

selecting = db.collection("rounds").where("status", "==", "selecting").get()
playing = db.collection("rounds").where("status", "==", "playing").get()
recent_rounds = (
    db.collection("rounds")
    .where("status", "==", "selecting")
    .where("stake", "==", 10)
    .order_by("created_at", "DESCENDING")
    .limit(2)
    .get()
)
users_playing = db.collection("users").where("is_playing", "==", True).get()
master = db.collection("cartelas_master").order_by("number").limit(2).get()
completed = db.collection("rounds").where("status", "==", "completed").limit(2).get()

assert isinstance(selecting, list)
assert isinstance(playing, list)
assert isinstance(recent_rounds, list)
assert isinstance(users_playing, list)
assert len(master) <= 2
assert len(completed) <= 2

print({
    "selecting": len(selecting),
    "playing": len(playing),
    "recent_rounds_stake_10": len(recent_rounds),
    "users_playing": len(users_playing),
    "master_sample": [doc.id for doc in master],
    "completed_sample": len(completed),
})
print("postgres query adapter regression test: PASS")
