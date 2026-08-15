from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
game_board = (ROOT / "dashboard-react/client/src/pages/GameBoard.tsx").read_text()
card_select = (ROOT / "dashboard-react/client/src/pages/CartelaSelect.tsx").read_text()
profile = (ROOT / "dashboard-react/client/src/pages/Profile.tsx").read_text()
home = (ROOT / "dashboard-react/client/src/pages/Home.tsx").read_text()
round_engine = (ROOT / "game/round_engine.py").read_text()

# Both gameplay refresh paths must prefer the server-stored Derash value.
assert "round.derash || Math.round" in game_board
assert "round.player_count" in game_board

# The final result must continue to display the server-provided per-winner payout.
assert "prize_per_winner" in game_board

# Labels must distinguish estimates, the round pool, and the actual winner payout.
assert "EST. DERASH" in card_select
assert "DERASH POOL" in game_board
assert "PRIZE PER WINNER" in game_board
assert "estimated earnings" in profile.lower()

# The display fix must match the authoritative 80% Derash / 20% admin policy.
assert "DERASH_RATIO = 0.80" in round_engine
assert "ADMIN_CUT_RATIO = 0.20" in round_engine
assert "derash = total_pool * DERASH_RATIO" in round_engine
assert "prize_per_winner = derash / len(valid_winner_ids)" in round_engine
assert "0.75" not in home
assert home.count("0.80") >= 2

print("Derash display accuracy regression check: PASS")
