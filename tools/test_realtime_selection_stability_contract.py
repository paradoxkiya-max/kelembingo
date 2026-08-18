from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
realtime = (ROOT / "dashboard-react/client/src/lib/realtime.ts").read_text(encoding="utf-8")
gateway = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text(encoding="utf-8")
select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text(encoding="utf-8")
game = (ROOT / "dashboard-react/client/src/pages/GameBoard.tsx").read_text(encoding="utf-8")

assert "roundEventRevisionWatermarks" in realtime
assert "function isStaleRoundMessage" in realtime
assert "revision < previous" in realtime
assert "if (isStaleRoundMessage(event, message)) return;" in realtime
assert "warmedRoundCache" in gateway
assert "export async function prewarmSelectionRound" in gateway
assert "prewarmSelectionRound" in game
assert "setSeconds(SELECTION_SECONDS)" in select
assert "refreshHandoff" not in select
assert "if (joinedCartelas.length > 0 || (latest.status === \"playing\" && !confirmStarted.current))" in select

print("realtime selection stability contract check: PASS")
