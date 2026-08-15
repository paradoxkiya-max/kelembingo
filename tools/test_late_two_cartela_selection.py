import asyncio
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("RENDER_API_ONLY", None)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'late-two-cartela.sqlite3'}"

    from firestore_db import MockFirestoreClient
    from game.round_engine import RoundEngine

    db = MockFirestoreClient()
    engine = RoundEngine(db)
    round_id = "late-two-cartela"
    db.collection("users").document("77").set({
        "play_wallet": 100,
        "is_playing": False,
        "active_round_id": None,
        "total_games": 0,
        "wins": 0,
        "losses": 0,
    })
    db.collection("rounds").document(round_id).set({
        "status": "selecting",
        "stake": 10,
        "players": {},
        "player_count": 0,
        "taken_cartelas": [],
        "pending_selections": {"77": [12, 35]},
    })

    first_join = asyncio.run(engine.join_round(round_id, 77, [12], "Player 77"))
    assert first_join["cartelas"] == [12], first_join
    from datetime import datetime, timezone
    db.collection("rounds").document(round_id).update({
        "status": "playing",
        "called_numbers": [],
        "game_started_at": datetime.now(tz=timezone.utc),
        "derash": 8,
    })
    late_union = asyncio.run(engine.join_round(round_id, 77, [12, 35], "Player 77"))
    assert late_union.get("status") == "expanded", late_union
    assert late_union["cartelas"] == [12, 35], late_union
    round_data = db.collection("rounds").document(round_id).get().to_dict()
    assert round_data["players"]["77"]["cartelas"] == [12, 35], round_data
    assert round_data["taken_cartelas"] == [12, 35], round_data
    assert round_data["player_count"] == 2, round_data
    assert round_data["derash"] == 16, round_data
    assert db.collection("users").document("77").get().to_dict()["play_wallet"] == 80

gateway = (ROOT / "api" / "admin_api.py").read_text()
assert "def _mutate_pending_selection_sync" in gateway
assert "run_idempotent(" in gateway[gateway.index("def _mutate_pending_selection_sync"):gateway.index('@app.post("/api/rounds/{round_id}/select")')]
assert "lock_key=f\"round:{round_id}\"" in gateway
assert "Maximum {MAX_CARTELAS_PER_PLAYER} cartelas allowed" in gateway
assert "selection_finalized_at" in gateway
assert "await _finalize_pending_selections(round_id, post_start.to_dict())" in gateway

print("late two-cartela selection regression check: PASS")
