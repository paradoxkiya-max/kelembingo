from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = (root / "dashboard-react" / "client" / "src" / "pages" / "GameBoard.tsx").read_text()
gateway = (root / "api" / "admin_api.py").read_text()
settlement = (root / "settlement.py").read_text()
checks = {
    "server_round_clock_fields": "round?.next_number_at" in source and "round?.selection_deadline" in source,
    "one_second_clock": "window.setInterval(syncClock, 1000)" in source and "setInterval(syncClock, 200)" not in source,
    "five_second_countdown_math": "Math.ceil((nextAt - now) / 1000)" in source,
    "server_clock_compensation": "playerApi.time()" in source and "serverClockOffset" in source,
    "visible_five_second_ceiling": "NUMBER_CALL_INTERVAL_SECONDS = 5" in source and "Math.min(NUMBER_CALL_INTERVAL_SECONDS" in source,
    "selection_expiry_countdown": "round?.status === \"selecting\"" in source and "round?.selection_deadline" in source,
    "called_numbers_state": "round?.called_numbers" in source and "called.size" in source,
    "playback_deduplication": "previous !== null" in source and "calledNumbers.length > previous.length" in source,
    "go_transition_label": '"Syncing…"' not in source and '"Go"' in source,
    "stale_deadline_guard": "nextCalls === previousCalls" in source and "nextDeadline < previousDeadline" in source,
    "periodic_round_resync": "playerApi.round(roundId)" in source and "setInterval(refreshRound, 10000)" in source,
    "four_second_client_warmup": "timer > 4 || timer < 1" in source and "warmNumberAudio" in source,
    "strict_server_five_seconds": "NUMBER_CALL_INTERVAL = 5" in gateway and "timedelta(seconds=5)" in settlement,
}
for name, passed in checks.items():
    print(name, "PASS" if passed else "FAIL")
assert all(checks.values())
print("mobile timer and strict cadence regression check: PASS")
