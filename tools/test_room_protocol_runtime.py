import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api import admin_api


async def main():
    admin_api._room_intent_results.clear()
    admin_api._room_intent_locks.clear()
    admin_api.ROOM_PROTOCOL_ENABLED = True

    async def fake_state(round_id, user_id, round_data=None, sid=None):
        return {
            "type": "room_state",
            "round_id": round_id,
            "exists": True,
            "status": "selecting",
            "pending_revision": 0,
            "selected_cartelas": [],
            "round": {"id": round_id, "status": "selecting"},
        }

    mutation_calls = []

    def fake_mutation(round_id, user_id, cartela_number, selecting, request_id):
        mutation_calls.append((round_id, user_id, cartela_number, selecting, request_id))
        return {
            "ok": True,
            "play_wallet": 90,
            "selected_cartelas": [cartela_number] if selecting else [],
            "reserved_cartelas": [cartela_number] if selecting else [],
            "_taken": [],
            "_pending": {user_id: [cartela_number]} if selecting else {user_id: []},
            "_pc": 1,
            "_derash": 8,
            "_revision": len(mutation_calls),
        }

    with patch.object(admin_api, "_socket_identity", return_value={"kind": "player", "user_id": 77}), \
         patch.object(admin_api, "_emit_room_state", new=AsyncMock(side_effect=fake_state)), \
         patch.object(admin_api, "_emit_room_compat_updates", new=AsyncMock()), \
         patch.object(admin_api.sio, "enter_room", new=AsyncMock()), \
         patch.object(admin_api.sio, "leave_room", new=AsyncMock()), \
         patch.object(admin_api.sio, "emit", new=AsyncMock()), \
         patch.object(admin_api, "_mutate_pending_selection_sync", side_effect=fake_mutation):
        joined = await admin_api.room_join("sid-1", {"round_id": "round-1", "user_id": "77", "player_token": "test"})
        assert joined["ok"] is True

        payload = {
            "round_id": "round-1",
            "user_id": "77",
            "intent_id": "intent-1",
            "action": "select",
            "cartela_number": 12,
            "player_token": "test",
        }
        first = await admin_api.room_intent("sid-1", payload)
        second = await admin_api.room_intent("sid-1", payload)
        assert first["ok"] is True
        assert second["ok"] is True
        assert first["intent_id"] == second["intent_id"] == "intent-1"
        assert len(mutation_calls) == 1, mutation_calls

        late = dict(payload, intent_id="intent-2", action="unselect")
        third = await admin_api.room_intent("sid-1", late)
        assert third["ok"] is True
        assert len(mutation_calls) == 2

    print("room protocol runtime contract check: PASS")


if __name__ == "__main__":
    asyncio.run(main())
