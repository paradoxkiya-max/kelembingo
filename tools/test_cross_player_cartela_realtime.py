from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
api = (ROOT / "api/admin_api.py").read_text()
selection_test = (ROOT / "tools/test_selection_wallet_reservation.py").read_text()

select_start = api.index('@app.post("/api/rounds/{round_id}/select")')
unselect_start = api.index('@app.post("/api/rounds/{round_id}/unselect")')
select_route = api[select_start:unselect_start]
unselect_route = api[unselect_start:api.index('@app.post("/api/rounds/{round_id}/close-empty")', unselect_start)]

for route in (select_route, unselect_route):
    assert "_mutate_pending_selection_sync" in route
    assert "pending_revision" in route
    assert "pending_selections" in route
    assert "await sio.emit('cartela_pool', pool_snapshot, room=f\"rounds:{round_id}\")" in route
    assert route.index("await sio.emit('cartela_pool'") < route.index("await broadcast_event('users', uid_str)")

mutation_start = api.index("def _mutate_pending_selection_sync(")
mutation_end = api.index('@app.post("/api/rounds/{round_id}/select")', mutation_start)
mutation = api[mutation_start:mutation_end]
assert "transaction.update(round_ref" in mutation
assert "pending_reservations" in mutation
assert "sess.commit()" in (ROOT / "firestore_db.py").read_text()
assert "persisted_first[\"pending_selections\"][\"77\"] == [12]" in selection_test
assert "persisted_after_first_release[\"pending_selections\"][\"77\"] == [35]" in selection_test
assert "persisted_empty[\"pending_selections\"][\"77\"] == []" in selection_test

print("cross-player durable select/deselect realtime contract check: PASS")
