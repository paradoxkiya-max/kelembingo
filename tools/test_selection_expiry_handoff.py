from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
gateway = (ROOT / "api/admin_api.py").read_text()
select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text()
game = (ROOT / "dashboard-react/client/src/pages/GameBoard.tsx").read_text()
realtime = (ROOT / "dashboard-react/client/src/lib/realtime.ts").read_text()
client = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text()
admin = (ROOT / "dashboard-react/client/src/pages/admin/AdminDashboard.tsx").read_text()

assert "async def _finalize_pending_selections" in gateway
assert "await _finalize_pending_selections(round_id, data)" in gateway
assert "async def _start_playing_round" in gateway
assert "async def _provision_next_round" in gateway
assert "await _provision_next_round" in gateway
assert "timedelta(seconds=5)" not in gateway[gateway.index("async def _game_loop"):gateway.index("# Now call numbers every 5 seconds")]
assert "_start_game_loop(round_id)" in gateway[gateway.index("async def join_round"):gateway.index("@app.post(\"/api/rounds/{round_id}/select\")")]

assert "confirmStarted.current = false" in select
assert "const restartSelection" in select
assert "deadlineHandoff" in select
assert "setLoadAttempt((value) => value + 1)" in select
assert "const latest = await playerApi.round(activeRoundId)" in select
assert "requirePending: true" in select and "pendingRevision" in select
assert 'latest.status === "completed"' in select
assert 'latest.status === "playing"' in select
assert 'joinedCartelas.length > 0' in select
assert 'navigate(`/game?round=${encodeURIComponent(targetId)}`' in select
assert 'Cartela already joined; opening the game board' in gateway
assert 'attempts >= 30' not in select
assert 'setExpired(true)' in select
assert 'latest.status !== "selecting"' not in select
assert "primeRoundSnapshot" in select and "primeRoundSnapshot" in realtime
assert "const serverRound = await playerApi.round" not in select
assert "cartelaCache" in client
assert '"SYNCING…"' not in select and '"GO"' in select
assert "observeRealtimeReconnect" in select and "Unable to start the next round. Please try again." in select
assert "playerApi.createRound(stake)" in select
assert "const interval = window.setInterval(sync, 30000)" in select
assert "restartSelection();" in select
assert "committedWallet" in select and "setCommittedWallet(balance)" in select
assert "authoritativeSelectedRef" in select and "applyPoolSnapshot" in select
assert "const pendingSelection = selectedRef.current" in select
assert "STARTING…" in select
assert "const retryTimers = [1000, 2500, 5000]" in select
assert "avoid issuing 30 requests per player" in select
assert "active_stakes = set()" not in gateway
assert 'REALTIME_EVENT_POLL_SECONDS", "0.5"' in gateway
assert "playerCartelaNumbers.length === 0" in game
assert 'Spectating mode' in game
assert 'This round started without your cartelas' not in select
assert '"Play now"' not in select
assert "confirmOpen" not in select and "<Dialog" not in select
assert "Tap a selected cartela to remove it" in select
assert 'aria-label={`Remove selected Cartela ${number}`}' in select
assert 'onClick={() => void toggleCard(number)}' in select
assert 'previewSlotByCartela' in select and 'selected.find((candidate) => previewSlotByCartela.current.get(candidate) === slot)' in select
assert '(busy && !isSelected)' in select and 'disabled={expired}' in select
assert 'const committedSelection = normalizeCartelas(selectedRef.current)' in select
assert 'The server finalizer owns the deadline handoff' in select
assert 'shares the durable round/user lock' in select
assert 'for (;;)' not in select

assert "@/components/ui/switch" in game
assert "Auto mark" in game
assert 'className="rounded-xl border border-orange-400/30 bg-gradient-to-br' not in game

assert "window.alert" not in admin
assert "window.confirm" not in admin
assert "window.prompt" not in admin
assert "AlertDialog" in admin and "toast." in admin

print("selection expiry, auto-toggle, and direct-removal regression check: PASS")
