from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
gateway = (ROOT / "api/admin_api.py").read_text()
realtime = (ROOT / "dashboard-react/client/src/lib/realtime.ts").read_text()
select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text()

assert 'ROOM_PROTOCOL_ENABLED = os.getenv("ROOM_PROTOCOL_ENABLED", "true")' in gateway
assert 'async def room_join(sid, data):' in gateway
assert 'async def room_leave(sid, data):' in gateway
assert 'async def room_intent(sid, data):' in gateway
assert '_room_intent_locks' in gateway and '_room_intent_results' in gateway
assert 'intent_id' in gateway and 'Intent ID already used' in gateway
assert 'await _mutate_pending_selection_sync' not in gateway
assert '_mutate_pending_selection_sync,' in gateway
assert 'await sio.emit("room_ack", ack, to=sid)' in gateway
assert 'await sio.emit("room_state", payload' in gateway
assert 'await sio.emit("room_state", {' in gateway
assert 'def _coalesce_events(events)' in gateway and 'events = _coalesce_events(events)' in gateway
assert 'asyncio.create_task(_emit_room_state(round_id, user_id))' in gateway
assert 'event === "room_state"' in realtime
assert 'roomJoin(roundId: string, userId: string)' in realtime
assert 'roomIntent(intent: RoomIntent)' in realtime
assert 'roomLeave(roundId: string)' in realtime
assert 'roomManager.roomJoin' in select
assert 'roomManager.roomIntent' in select
assert 'ROUND_SNAPSHOT_CACHE_LIMIT = 32' in realtime and 'if (cached) deliver(cached)' in realtime
assert 'playerApi.selectCartela(roundId, userId, number, intent.id)' in select
assert 'playerApi.unselectCartela(roundId, userId, number, intent.id)' in select
assert 'selectionQueue' not in select
assert 'selectionRequests' in select

print("reference-inspired room protocol contract check: PASS")
