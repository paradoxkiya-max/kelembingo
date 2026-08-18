import asyncio
import os
import tempfile
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("RENDER_API_ONLY", None)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'selection-deadline.sqlite3'}"

    from firestore_db import MockFirestoreClient
    from api import admin_api
    from settlement import join_round

    original_db = admin_api.db
    db = MockFirestoreClient()
    admin_api.db = db
    try:
        round_id = "selection-deadline-guard"
        user_id = "999"
        db.collection("users").document(user_id).set({
            "play_wallet": 100,
            "is_playing": False,
            "active_round_id": None,
        })
        db.collection("rounds").document(round_id).set({
            "status": "selecting",
            "stake": 10,
            "selection_deadline": datetime.now(tz=timezone.utc) - timedelta(seconds=1),
            "players": {},
            "player_count": 0,
            "taken_cartelas": [],
            "pending_selections": {},
            "pending_reservations": {},
            "pending_revision": 0,
        })

        result = admin_api._mutate_pending_selection_sync(round_id, user_id, 12, True, "late-select")
        assert result.get("error") == "Selection window closed; waiting for round transition", result
        assert db.collection("users").document(user_id).get().to_dict()["play_wallet"] == 100, result
        persisted = db.collection("rounds").document(round_id).get().to_dict()
        assert persisted["pending_selections"].get(user_id, []) == [], persisted
        assert persisted["pending_reservations"].get(user_id, []) == [], persisted

        db.collection("users").document(user_id).set({
            "play_wallet": 90,
            "is_playing": False,
            "active_round_id": None,
        })
        db.collection("rounds").document(round_id).update({
            "pending_selections": {user_id: [12]},
            "pending_reservations": {user_id: [12]},
            "pending_revision": 1,
        })
        finalized = join_round(
            db,
            round_id,
            int(user_id),
            [12],
            "Player 999",
            idempotency_key="deadline-finalizer",
            require_pending=True,
        )
        assert finalized["status"] == "joined" and finalized["reserved_cost"] == 10, finalized
        assert db.collection("users").document(user_id).get().to_dict()["play_wallet"] == 90, finalized
        finalized_round = db.collection("rounds").document(round_id).get().to_dict()
        assert finalized_round["players"][user_id]["cartelas"] == [12], finalized_round
        assert finalized_round["pending_reservations"][user_id] == [], finalized_round
    finally:
        admin_api.db = original_db

gateway = (ROOT / "api" / "admin_api.py").read_text()
selection = (ROOT / "dashboard-react" / "client" / "src" / "pages" / "CartelaSelect.tsx").read_text()
assert "def _selection_deadline_expired" in gateway
assert "Selection window closed; waiting for round transition" in gateway
assert "handoffRef" in selection
assert "const closed = Boolean(round && (round.status !== \"selecting\" || seconds <= 0));" in selection
assert "finishSelection(epoch, selectedRef.current, onRetry)" in selection
assert "selectedAtDeadline" in selection
assert "joinSelection" in selection

print("selection deadline guard regression check: PASS")
