from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
page_loader = (ROOT / 'dashboard/js/page-loader.js').read_text()
auth = (ROOT / 'dashboard/js/auth.js').read_text()
card_select = (ROOT / 'dashboard/js/card-select.js').read_text()
admin_api = (ROOT / 'api/admin_api.py').read_text()
game_html = (ROOT / 'dashboard/game.html').read_text()

assert "const PAGE_ASSET_VERSION = 'pay-1'" in page_loader
assert "const deferredMap" in page_loader
assert "this.inflight[cacheKey]" in page_loader
assert "await PageLoader.loadComponent('card-select-screen', 'card-select.html')" in card_select
assert "'/api/public/stats'" in auth
assert "setInterval(refreshCompletedStats, 30000)" in auth
assert "db.collection('rounds').where('status', '==', 'completed').get()" not in auth
assert "@app.get(\"/api/public/stats\")" in admin_api
assert "jsonb_extract_path_text(CAST(data AS JSONB), 'status')" in admin_api
assert 'js/auth.js?v=stake-1' in game_html
assert 'js/card-select.js?v=grid-1' in game_html
assert 'js/page-loader.js?v=pay-1' in game_html

print('stake-selection performance regression check: PASS')
