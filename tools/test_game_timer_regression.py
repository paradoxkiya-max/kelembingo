from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "dashboard-react" / "client" / "src" / "pages" / "GameBoard.tsx").read_text()
checks = {
    "server_round_clock_fields": "round?.next_number_at" in source and "round?.game_started_at" in source,
    "five_second_countdown_math": "Math.ceil((nextAt - now) / 1000)" in source,
    "selection_expiry_countdown": "round.status === \"selecting\"" in source and "round.selection_deadline" in source,
    "called_numbers_state": "round?.called_numbers" in source and "called.size" in source,
    "playback_deduplication": "latest !== previousCalled.current" in source,
}
for name, passed in checks.items():
    print(name, "PASS" if passed else "FAIL")
assert all(checks.values())
print("mobile timer regression check: PASS")
