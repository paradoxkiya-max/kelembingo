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
assert "function roundSelectionExpired" in gateway
assert "!roundSelectionExpired(cached.round)" in gateway
assert "export async function prewarmSelectionRound" in gateway
assert "prewarmSelectionRound" in game
assert "SELECTION_DURATION = 45" in select
assert "secondsLeft" in select
assert "refreshHandoff" not in select
assert "hasPlayerEntry(latest, userId)" in select
assert "cleanupSelection()" in select
assert "requestPlayNow" in select
assert "latest.status === \"playing\"" in select and "navigateToGame(latest)" in select
assert "lastTapRef" in select and "mutationTailsRef" in select

print("realtime selection stability contract check: PASS")
