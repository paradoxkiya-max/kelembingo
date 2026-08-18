from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text(encoding="utf-8")

# Visual contract: reference layout and immediate selected-card rendering.
assert 'Select Cartela' in select
assert 'card-select-grid' in select
assert 'CARTELA NO:' in select
assert 'Tap to remove' not in select
assert 'onRemove' not in select
assert 'Total Cost:' in select
assert 'Starting…' in select
assert 'bg-gradient-to-br from-emerald-500 to-emerald-600' in select

# Interaction contract: taps update local state immediately and do not render a
# per-card request spinner or disable cards while a reservation is pending.
assert 'const next = selecting ? [...current, number] : current.filter((item) => item !== number)' in select
assert 'publishSelected(next)' in select
assert 'lastTapRef' in select and 'now - lastTapRef.current < 300' in select
assert 'mutationTailsRef' in select
assert 'mutating' not in select
assert 'Updating' not in select
assert 'inFlightRef' not in select
assert 'pendingOperationsRef' not in select

# Lifecycle contract: one active round listener/timer, cleanup before every
# transition, and one authoritative join at the deadline.
assert 'cleanupSelection' in select
assert 'observeRound' in select and 'observeCartelaPool' in select
assert 'finishSelection(epoch, selectedRef.current, onRetry)' in select
assert 'await Promise.allSettled(tails)' in select
assert 'playerApi.joinRound' in select
assert 'requirePending: true' in select
assert 'navigateToGame' in select
assert 'requestPlayNow' in select

# Current backend requirements must remain intact.
assert '0.8' in select
assert 'playerApi.selectCartela(roundId, userId, number, requestId())' in select
assert 'playerApi.unselectCartela(roundId, userId, number, requestId())' in select
assert 'if (response.pending_selections)' in select
assert 'if (response.taken_cartelas)' in select
assert 'if (Number.isFinite(Number(response.play_wallet))' in select
assert 'const optimisticPending = { ...pendingRef.current, [userId]: next }' in select
assert 'setDerashPool(calcDerash(Number(roundRef.current?.player_count || 0), optimisticPending, stake))' in select
assert 'selecting\n        ? await playerApi.selectCartela' in select
assert ': await playerApi.unselectCartela' in select

print('reference cartela UI contract: PASS')
