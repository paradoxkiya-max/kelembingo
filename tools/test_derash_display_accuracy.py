from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
game_board = (ROOT / "dashboard/js/game-board.js").read_text()
card_select_html = (ROOT / "dashboard/components/card-select.html").read_text()
game_board_html = (ROOT / "dashboard/pages/game-board.html").read_text()
win_modal_html = (ROOT / "dashboard/components/win-modal.html").read_text()
profile_html = (ROOT / "dashboard/pages/profile.html").read_text()
game_html = (ROOT / "dashboard/game.html").read_text()
page_loader = (ROOT / "dashboard/js/page-loader.js").read_text()
round_engine = (ROOT / "game/round_engine.py").read_text()

# Both gameplay refresh paths must prefer the server-stored Derash value.
assert game_board.count("var storedDerash = Number(data.derash);") == 1
assert game_board.count("var storedDerash = Number(roundData.derash);") == 1
assert game_board.count("Math.round(storedDerash * 10) / 10") == 2

# The final result must continue to display the server-provided per-winner payout.
assert "data.prize_per_winner" in game_board

# Labels must distinguish estimates, the round pool, and the actual winner payout.
assert ">EST. DERASH<" in card_select_html
assert ">DERASH POOL<" in game_board_html
assert ">PRIZE PER WINNER<" in win_modal_html
assert ">Estimated Earnings<" in profile_html

# Cache-busting must load the changed JavaScript and HTML fragments.
assert "js/game-board.js?v=derash-1" in game_html
assert "js/page-loader.js?v=derash-1" in game_html
assert "const PAGE_ASSET_VERSION = 'derash-1'" in page_loader

# The display fix must not alter the authoritative 75% settlement rule.
assert "derash = total_pool * 0.75" in round_engine
assert "prize_per_winner = derash / len(valid_winner_ids)" in round_engine

print("Derash display accuracy regression check: PASS")
