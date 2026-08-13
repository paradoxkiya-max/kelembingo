from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "dashboard" / "js" / "game-board.js").read_text()
checks = {
    "load_guard_declared": "var _myCartelasLoadInFlight = false;" in source,
    "snapshot_guard": "&& !_myCartelasLoadInFlight" in source,
    "load_guard_set": "_myCartelasLoadInFlight = true;" in source,
    "timer_restarted_after_dom_setup": (
        "setupGameBoard();" in source
        and "if (roundData.status === 'playing')" in source
        and "startGameCountdown(nextMs);" in source
    ),
    "load_guard_released": (
        "finally(function()" in source
        and "_myCartelasLoadInFlight = false;" in source
    ),
}
for name, passed in checks.items():
    print(name, "PASS" if passed else "FAIL")
assert all(checks.values())
print("mobile timer regression check: PASS")
