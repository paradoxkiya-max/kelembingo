import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("RENDER_API_ONLY", None)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'selection-join.sqlite3'}"
    from firestore_db import MockFirestoreClient
    from settlement import join_round

    db = MockFirestoreClient()
    db.collection("users").document("77").set({
        "play_wallet": 80,
        "is_playing": False,
        "active_round_id": None,
        "active_round_ids": [],
    })
    db.collection("rounds").document("join-contract").set({
        "status": "selecting",
        "stake": 10,
        "players": {},
        "player_count": 0,
        "taken_cartelas": [],
        "pending_selections": {"77": [12, 35]},
        "pending_reservations": {"77": [12, 35]},
        "pending_revision": 2,
    })

    joined = join_round(
        db,
        "join-contract",
        77,
        [12, 35],
        "Player 77",
        idempotency_key="join-contract-ok",
        require_pending=True,
        pending_revision=2,
    )
    assert joined["status"] == "joined", joined
    assert joined["cost"] == 0, joined
    assert joined["reserved_cost"] == 20, joined
    assert db.collection("users").document("77").get().to_dict()["play_wallet"] == 80

    db.collection("rounds").document("join-contract-stale").set({
        "status": "selecting",
        "stake": 10,
        "players": {},
        "player_count": 0,
        "taken_cartelas": [],
        "pending_selections": {"77": [12]},
        "pending_reservations": {"77": [12]},
        "pending_revision": 3,
    })
    rejected = join_round(
        db,
        "join-contract-stale",
        77,
        [12, 35],
        "Player 77",
        idempotency_key="join-contract-stale",
        require_pending=True,
        pending_revision=2,
    )
    assert "error" in rejected and "selection" in rejected["error"].lower(), rejected

admin_api = (ROOT / "api/admin_api.py").read_text(encoding="utf-8")
engine = (ROOT / "game/round_engine.py").read_text(encoding="utf-8")
settlement = (ROOT / "settlement.py").read_text(encoding="utf-8")
select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text(encoding="utf-8")
gateway = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text(encoding="utf-8")

assert "require_pending: bool = False" in admin_api
assert "pending_revision: int = 0" in admin_api
assert "require_pending=bool(req.require_pending)" in admin_api
assert "pending_revision=int(req.pending_revision or 0)" in admin_api
assert "pending_revision=pending_revision" in engine
assert "pending_revision=0" in settlement
assert "pending_revision" in settlement and "pending_selections" in settlement
assert "await Promise.allSettled(queuedOperations)" in select
assert "const latest = await playerApi.round(activeRoundId)" in select
assert "const response = await playerApi.joinRound" in select
assert "const joinedRound = response.round" in select
assert "primeRoundSnapshot(activeRoundId, handoffRound)" not in select
assert "navigate(`/game?round=${encodeURIComponent(activeRoundId)}`" in select
assert "pendingRevision: Number(latest.pending_revision || 0)" in select
assert "requirePending: true" in select

print("selection/join synchronization regression check: PASS")

