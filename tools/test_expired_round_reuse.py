import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("RENDER_API_ONLY", None)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'expired-round.sqlite3'}"

    from firestore_db import MockFirestoreClient
    from game.round_engine import RoundEngine, SELECTION_DURATION

    db = MockFirestoreClient()
    engine = RoundEngine(db)
    expired_id = "expired-empty-round"
    db.collection("rounds").document(expired_id).set({
        "status": "selecting",
        "stake": 10,
        "players": {},
        "player_count": 0,
        "taken_cartelas": [],
        "pending_selections": {},
        "pending_reservations": {},
        "selection_deadline": datetime.now(tz=timezone.utc) - timedelta(seconds=1),
    })

    replacement = asyncio.run(engine.create_round(10))
    assert replacement["id"] != expired_id, replacement
    assert replacement["status"] == "selecting", replacement
    deadline = replacement["selection_deadline"]
    if isinstance(deadline, str):
        deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    assert deadline > datetime.now(tz=timezone.utc) + timedelta(seconds=SELECTION_DURATION - 5), replacement

    expired = db.collection("rounds").document(expired_id).get().to_dict()
    assert expired["status"] == "completed", expired
    assert expired["winner_name"] == "No players", expired
    assert expired["payout_processed"] is True, expired

    active = asyncio.run(engine.get_active_round(10))
    assert active and active["id"] == replacement["id"], active

print("expired selecting round replacement regression check: PASS")
