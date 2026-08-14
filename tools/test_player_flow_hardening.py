from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
game = (ROOT / "dashboard-react/client/src/pages/GameBoard.tsx").read_text()
select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text()
wallet = (ROOT / "dashboard-react/client/src/pages/Wallet.tsx").read_text()
realtime = (ROOT / "dashboard-react/client/src/lib/realtime.ts").read_text()
gateway = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text()
context = (ROOT / "dashboard-react/client/src/contexts/PlayerContext.tsx").read_text()
round_engine = (ROOT / "game/round_engine.py").read_text()

assert 'navigate("/", { replace: true })' in game
assert '"Syncing…"' in game and '"Starting…"' in game
assert "window.setInterval(syncClock, 1000)" in game
assert "Spectating mode" in game
assert "playerApi.cartela(number)" in game
assert "prize_per_winner" in game
assert "fetchInitial" in realtime
assert 'setAuthError(""); setPlayer(null)' not in context
assert 'navigate(`/game?round=${encodeURIComponent(String(nextRound.id))}`, { replace: true })' in select
assert "CARTELA_POOL" in select and "playerApi.cartelas" not in select
assert "DialogContent" in wallet and "Input" in wallet
assert "role=\"alert\"" in wallet
assert "formatGatewayError" in wallet and "formatGatewayError(response.error" in wallet
assert "export function formatGatewayError" in gateway
assert 'detail?: unknown }).detail' not in gateway
assert "prize_per_winner': total_pool * 0.75" in round_engine

print("player flow hardening contract check: PASS")
