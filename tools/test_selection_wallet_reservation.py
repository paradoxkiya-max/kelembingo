import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("RENDER_API_ONLY", None)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'selection-reservation.sqlite3'}"

    from firestore_db import MockFirestoreClient
    from api import admin_api
    from settlement import join_round

    original_db = admin_api.db
    db = MockFirestoreClient()
    admin_api.db = db
    try:
        round_id = "selection-reservation"
        db.collection("users").document("77").set({
            "play_wallet": 100,
            "is_playing": False,
            "active_round_id": None,
        })
        db.collection("rounds").document(round_id).set({
            "status": "selecting",
            "stake": 10,
            "players": {},
            "player_count": 0,
            "taken_cartelas": [],
            "pending_selections": {},
            "pending_reservations": {},
        })

        first = admin_api._mutate_pending_selection_sync(round_id, "77", 12, True, "first")
        assert first["ok"] and first["play_wallet"] == 90 and first["_derash"] == 8 and first["selected_cartelas"] == [12], first
        assert db.collection("users").document("77").get().to_dict()["play_wallet"] == 90

        duplicate = admin_api._mutate_pending_selection_sync(round_id, "77", 12, True, "second-request")
        assert duplicate["ok"] and duplicate["play_wallet"] == 90, duplicate
        assert db.collection("users").document("77").get().to_dict()["play_wallet"] == 90

        second = admin_api._mutate_pending_selection_sync(round_id, "77", 35, True, "third")
        assert second["ok"] and second["play_wallet"] == 80 and second["_derash"] == 16 and second["selected_cartelas"] == [12, 35], second

        released = admin_api._mutate_pending_selection_sync(round_id, "77", 35, False, "fourth")
        assert released["ok"] and released["play_wallet"] == 90 and released["_derash"] == 8 and released["selected_cartelas"] == [12], released

        joined = join_round(db, round_id, 77, [12], "Player 77", idempotency_key="finalize")
        assert joined["status"] == "joined" and joined["cost"] == 0 and joined["reserved_cost"] == 10, joined
        assert db.collection("users").document("77").get().to_dict()["play_wallet"] == 90

        round_data = db.collection("rounds").document(round_id).get().to_dict()
        assert round_data["players"]["77"]["cartelas"] == [12], round_data
        assert round_data["pending_reservations"]["77"] == [], round_data

        cancelled_round = "cancelled-before-finalizer"
        db.collection("users").document("88").set({
            "play_wallet": 100,
            "is_playing": False,
            "active_round_id": None,
        })
        db.collection("rounds").document(cancelled_round).set({
            "status": "selecting",
            "stake": 10,
            "players": {},
            "player_count": 0,
            "taken_cartelas": [],
            "pending_selections": {"88": []},
            "pending_reservations": {"88": []},
        })
        stale_finalizer = join_round(
            db, cancelled_round, 88, [11], "Player 88",
            idempotency_key="stale-finalizer", require_pending=True,
        )
        assert stale_finalizer.get("error") == "Cartela selection was cancelled before round finalization", stale_finalizer
        cancelled_data = db.collection("rounds").document(cancelled_round).get().to_dict()
        assert cancelled_data["players"] == {} and cancelled_data["player_count"] == 0, cancelled_data
        assert db.collection("users").document("88").get().to_dict()["play_wallet"] == 100
    finally:
        admin_api.db = original_db

gateway = (ROOT / "api" / "admin_api.py").read_text()
selection = (ROOT / "dashboard-react" / "client" / "src" / "pages" / "CartelaSelect.tsx").read_text()
context = (ROOT / "dashboard-react" / "client" / "src" / "contexts" / "PlayerContext.tsx").read_text()

assert "pending_reservations" in gateway
assert 'lock_keys=[f"round:{round_id}", f"user:{user_id}"]' in gateway
assert "await broadcast_event('users', uid_str)" in gateway
assert "derash_pool" in gateway
assert "require_pending=True" in gateway
assert "selected_cartelas" in gateway and "pending_revision" in gateway
assert 'if collection == "rounds" and doc_id:' in gateway
assert '}, to=sid)' in gateway and '"pending_revision": int(round_data.get("pending_revision", 0) or 0)' in gateway
assert '"pending_revision": int(rd.get(\'pending_revision\', 0) or 0)' in gateway
assert "applyPlayWallet" in context
assert "walletPreview" in selection and "optimisticPool" in selection
assert "liveDerashPool" in selection
assert "pendingRevision" in selection and "setSelected(normalizeCartelas(result.selected_cartelas" in selection

print("selection wallet reservation regression check: PASS")
