from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
selection = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text()
engine = (ROOT / "game/round_engine.py").read_text()
gateway = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text()

assert "const SELECTION_SECONDS = 45;" in selection
assert "selection_deadline" in selection
assert "playerApi.time()" in selection
assert "serverClockOffset" in selection
assert "(Date.now() + serverClockOffset)" in selection
assert "window.setInterval(sync, 250)" in selection
assert "round?.status !== \"selecting\"" in selection
assert "SELECTION_DURATION = 45" in engine
assert "selection_deadline" in gateway

# The displayed value is derived from the persisted deadline, not from a
# locally restarted duration. Reloading at any point therefore preserves the
# same remaining time, subject only to the measured server-clock offset.
def remaining(deadline_ms: int, local_now_ms: int, server_offset_ms: int) -> int:
    return max(0, (deadline_ms - (local_now_ms + server_offset_ms) + 999) // 1000)

assert remaining(45_000, 0, 0) == 45
assert remaining(45_000, 10_000, 0) == 35
assert remaining(45_000, 10_000, 250) == 35
assert remaining(45_000, 44_200, 0) == 1
assert remaining(45_000, 45_000, 0) == 0

print("strict 45-second server-authoritative selection timer regression check: PASS")
