from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
game = (ROOT / "dashboard-react/client/src/pages/GameBoard.tsx").read_text()
winner_popup = (ROOT / "dashboard-react/client/src/components/player/WinnerAnnouncement.tsx").read_text()
select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text()
wallet = (ROOT / "dashboard-react/client/src/pages/Wallet.tsx").read_text()
realtime = (ROOT / "dashboard-react/client/src/lib/realtime.ts").read_text()
gateway = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text()
context = (ROOT / "dashboard-react/client/src/contexts/PlayerContext.tsx").read_text()
round_engine = (ROOT / "game/round_engine.py").read_text()

assert 'selectionPath' in game
assert '"Go"' in game and '"Syncing…"' in game and '"Starting…"' not in game
assert "window.setInterval(syncClock, 1000)" in game
assert "Spectating mode" in game
assert "playerApi.cartela(number)" in game
assert "prize_per_winner" in game
assert "winner_name" in game and "winning_cartela" in game
assert 'if (winnerAnnouncement && returnCountdown === 0) navigate(selectionPath, { replace: true })' in game
assert 'onReturn={() => navigate(selectionPath, { replace: true })}' in game
assert 'if (!roundId) { navigate("/", { replace: true }); return; }' in game
assert 'previous.status === "completed"' in game and 'previous.winning_cartela' in game
assert 'round?.status !== "completed"' in game and 'playerApi.round(roundId)' in game
assert 'No active round is available yet. Please try again.' in select and 'setLoadAttempt' in select
assert 'observeRealtimeReconnect' in select and 'playerApi.round(String(nextRound.id))' in select
assert 'if (!winnerId || !Number.isInteger(cartelaNumber) || cartelaNumber < 1) {\n      navigate("/", { replace: true });' in game
assert "This round is complete. The next round is open from the Game tab." not in game
assert "WinnerAnnouncement" in game and "returnCountdown" in game
assert 'setReturnCountdown(10)' in game and 'returnCountdown === 0' in game
assert 'This round closed before your cartelas could be confirmed' not in select
assert 'latest.status === "completed") navigate("/", { replace: true })' in select
assert "Returning to cartela selection in" in winner_popup and "You" in winner_popup
history = (ROOT / "dashboard-react/client/src/pages/History.tsx").read_text()
assert "My Recent Games" in history and "playerApi.history()" in history and "playerId" in history
assert "Won with Cartela" in winner_popup and "Derash" in winner_popup
assert "fetchInitial" in realtime
assert 'setAuthError(""); setPlayer(null)' not in context
assert 'navigate(`/game?round=${encodeURIComponent(targetId)}`, { replace: true })' in select
assert 'primeRoundSnapshot(targetId, nextRound)' in select
assert "CARTELA_POOL" in select and "playerApi.cartelas" not in select
assert "DialogContent" in wallet and "Input" in wallet
assert "role=\"alert\"" in wallet
assert "formatGatewayError" in wallet and "formatGatewayError(response.error" in wallet
assert "export function formatGatewayError" in gateway
assert 'detail?: unknown }).detail' not in gateway
assert "prize_per_winner': total_pool * DERASH_RATIO" in round_engine
assert "'winner_name': player_name" in round_engine

print("player flow hardening contract check: PASS")
