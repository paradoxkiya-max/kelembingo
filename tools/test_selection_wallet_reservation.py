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
    from settlement import join_round, refund_no_winner

    original_db = admin_api.db
    db = MockFirestoreClient()
    admin_api.db = db
    try:
        round_id = "selection-reservation"
        db.collection("users").document("77").set({
            "play_wallet": 100,
            "is_playing": False,
            "active_round_id": None,
            "active_round_ids": [],
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
        persisted_first = db.collection("rounds").document(round_id).get().to_dict()
        assert persisted_first["pending_selections"]["77"] == [12]
        assert persisted_first["pending_reservations"]["77"] == [12]
        assert persisted_first["pending_revision"] == first["_revision"]

        duplicate = admin_api._mutate_pending_selection_sync(round_id, "77", 12, True, "second-request")
        assert duplicate["ok"] and duplicate["play_wallet"] == 90, duplicate
        assert db.collection("users").document("77").get().to_dict()["play_wallet"] == 90

        second = admin_api._mutate_pending_selection_sync(round_id, "77", 35, True, "third")
        assert second["ok"] and second["play_wallet"] == 80 and second["_derash"] == 16 and second["selected_cartelas"] == [12, 35], second
        persisted_second = db.collection("rounds").document(round_id).get().to_dict()
        assert persisted_second["pending_selections"]["77"] == [12, 35]
        assert persisted_second["pending_reservations"]["77"] == [12, 35]
        assert persisted_second["pending_revision"] == second["_revision"]

        released_first = admin_api._mutate_pending_selection_sync(round_id, "77", 12, False, "fourth")
        assert released_first["ok"] and released_first["play_wallet"] == 90 and released_first["selected_cartelas"] == [35], released_first
        persisted_after_first_release = db.collection("rounds").document(round_id).get().to_dict()
        assert persisted_after_first_release["pending_selections"]["77"] == [35]
        assert persisted_after_first_release["pending_reservations"]["77"] == [35]

        released_second = admin_api._mutate_pending_selection_sync(round_id, "77", 35, False, "fifth")
        assert released_second["ok"] and released_second["play_wallet"] == 100 and released_second["_derash"] == 0 and released_second["selected_cartelas"] == [], released_second
        persisted_empty = db.collection("rounds").document(round_id).get().to_dict()
        assert persisted_empty["pending_selections"]["77"] == []
        assert persisted_empty["pending_reservations"]["77"] == []

        reselect_first = admin_api._mutate_pending_selection_sync(round_id, "77", 12, True, "sixth")
        reselect_second = admin_api._mutate_pending_selection_sync(round_id, "77", 35, True, "seventh")
        assert reselect_first["play_wallet"] == 90 and reselect_second["play_wallet"] == 80 and reselect_second["selected_cartelas"] == [12, 35], (reselect_first, reselect_second)
        release_again_first = admin_api._mutate_pending_selection_sync(round_id, "77", 12, False, "eighth")
        release_again_second = admin_api._mutate_pending_selection_sync(round_id, "77", 35, False, "ninth")
        assert release_again_first["selected_cartelas"] == [35] and release_again_second["selected_cartelas"] == [] and release_again_second["play_wallet"] == 100, (release_again_first, release_again_second)

        final_select = admin_api._mutate_pending_selection_sync(round_id, "77", 12, True, "tenth")
        assert final_select["play_wallet"] == 90 and final_select["selected_cartelas"] == [12], final_select
        joined = join_round(db, round_id, 77, [12], "Player 77", idempotency_key="finalize")
        assert joined["status"] == "joined" and joined["cost"] == 0 and joined["reserved_cost"] == 10, joined
        assert db.collection("users").document("77").get().to_dict()["play_wallet"] == 90

        round_data = db.collection("rounds").document(round_id).get().to_dict()
        assert round_data["players"]["77"]["cartelas"] == [12], round_data
        assert round_data["pending_reservations"]["77"] == [], round_data

        round20 = "selection-reservation-stake20"
        db.collection("rounds").document(round20).set({
            "status": "selecting",
            "stake": 20,
            "players": {},
            "player_count": 0,
            "taken_cartelas": [],
            "pending_selections": {},
            "pending_reservations": {},
        })
        cross_stake_select = admin_api._mutate_pending_selection_sync(round20, "77", 35, True, "stake20-select")
        assert cross_stake_select["ok"] and cross_stake_select["play_wallet"] == 70, cross_stake_select
        joined20 = join_round(db, round20, 77, [35], "Player 77", idempotency_key="stake20-join")
        assert joined20["status"] == "joined" and joined20["cost"] == 0 and joined20["reserved_cost"] == 20, joined20
        active_after_two = db.collection("users").document("77").get().to_dict()
        assert active_after_two["is_playing"] is True
        assert set(active_after_two["active_round_ids"]) == {round_id, round20}, active_after_two

        refund10 = refund_no_winner(db, round_id, idempotency_key="stake10-refund")
        assert refund10["ok"]
        active_after_stake10 = db.collection("users").document("77").get().to_dict()
        assert active_after_stake10["is_playing"] is True and active_after_stake10["active_round_ids"] == [round20], active_after_stake10
        refund20 = refund_no_winner(db, round20, idempotency_key="stake20-refund")
        assert refund20["ok"]
        active_after_both = db.collection("users").document("77").get().to_dict()
        assert active_after_both["is_playing"] is False and active_after_both["active_round_ids"] == [], active_after_both

        cancelled_round = "cancelled-before-finalizer"
        db.collection("users").document("88").set({
            "play_wallet": 100,
            "is_playing": False,
            "active_round_id": None,
            "active_round_ids": [],
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
assert 'active_round_ids' in gateway
assert 'active_round_ids' in (ROOT / "settlement.py").read_text()
assert 'You are already playing in another active round' not in gateway
assert 'You are already playing in an active round' not in (ROOT / "settlement.py").read_text()
assert "asyncio.create_task(broadcast_event('users', uid_str))" in gateway
assert "derash_pool" in gateway
assert "require_pending=True" in gateway
assert "selected_cartelas" in gateway and "pending_revision" in gateway
assert 'if collection == "rounds" and doc_id:' in gateway
assert '}, to=sid)' in gateway and '"pending_revision": int(round_data.get("pending_revision", 0) or 0)' in gateway
assert '"pending_revision": int(rd.get(\'pending_revision\', 0) or 0)' in gateway
assert 'lock_timeout_ms=2500' in gateway and 'statement_timeout_ms=5000' in gateway
assert 'lock_timeout_ms=None' in (ROOT / 'firestore_db.py').read_text()
assert 'pool_snapshot = {' in gateway
assert '"pending_selections": result.get(\'_pending\', {})' in gateway
assert '"selected_cartelas": result.get("selected_cartelas", [])' in gateway
assert "setMutating" in selection
assert "inFlightRef" in selection
assert "pendingOperationsRef" in selection
assert "playerApi.selectCartela(roundId, userId, number, requestId())" in selection
assert "playerApi.unselectCartela(roundId, userId, number, requestId())" in selection
assert "roomManager.roomIntent" not in selection
assert "observeCartelaPool" in selection and "observeRound" in selection
assert "await Promise.allSettled(operations)" in selection
assert "requirePending: true" in selection
assert "pendingRevision: Number(latest.pending_revision || 0)" in selection
assert "setSeconds(0)" in selection
assert "setMutating(new Set())" in selection
assert "selectionIntents" not in selection and "selectionTails" not in selection
assert "mergePendingVisual" not in selection and "applyPoolSnapshot" not in selection
assert "request_id: requestId" in (ROOT / "dashboard-react" / "client" / "src" / "lib" / "gateway.ts").read_text()

print("selection wallet reservation regression check: PASS")
