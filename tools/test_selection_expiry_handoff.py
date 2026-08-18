from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
gateway = (ROOT / "api/admin_api.py").read_text(encoding="utf-8")
select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text(encoding="utf-8")
game = (ROOT / "dashboard-react/client/src/pages/GameBoard.tsx").read_text(encoding="utf-8")
realtime = (ROOT / "dashboard-react/client/src/lib/realtime.ts").read_text(encoding="utf-8")
client = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text(encoding="utf-8")
admin = (ROOT / "dashboard-react/client/src/pages/admin/AdminDashboard.tsx").read_text(encoding="utf-8")

# Backend finalizer remains the authority at the selection deadline.
assert "async def _finalize_pending_selections" in gateway
assert "await _finalize_pending_selections(round_id, post_start.to_dict())" in gateway
assert "await _finalize_pending_selections(round_id, recheck_data)" in gateway
assert "async def _start_playing_round" in gateway
assert "_start_game_loop(round_id)" in gateway
assert "Cartela already joined; opening the game board" in gateway

# Reference-style React lifecycle: one active round, explicit cleanup, and one
# deadline join using the local snapshot with server pending fallback.
assert "const cleanupSelection" in select
assert "const requestPlayNow" in select
assert "const finishSelection = useCallback" in select
assert "const snapshot = normalizeNumbers(selectedAtDeadline)" in select
assert "const serverSnapshot = roundSelections(latest, userId)" in select
assert "const joinSelection = (serverSnapshot.length ? serverSnapshot : snapshot)" in select
assert "requirePending: true" in select and "pendingRevision" in select
assert "await Promise.allSettled(tails)" in select
assert "observeRound" in select and "observeCartelaPool" in select
assert "navigateToGame" in select
assert "Starting…" in select
assert "playerApi.createRound(stake)" in select
assert "Updating" not in select
assert "inFlightRef" not in select
assert "pendingOperationsRef" not in select

# Realtime and game-board behavior remain protected.
assert "roundEventRevisionWatermarks" in realtime
assert "playerCartelaNumbers.length === 0" in game
assert "A delayed pre-join snapshot must not erase" in game
assert "previousCartelas.length > 0 && nextCartelas.length === 0" in game
assert "cartelaCache" in client
assert "AlertDialog" in admin and "toast." in admin

print("selection expiry, reference-style handoff, and cleanup regression check: PASS")
