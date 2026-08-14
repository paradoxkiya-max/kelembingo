from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
wallet = (ROOT / 'dashboard/js/wallet.js').read_text()
firebase = (ROOT / 'dashboard/js/firebase.js').read_text()
withdraw_modal = (ROOT / 'dashboard/components/withdraw-modal.html').read_text()
deposit_modal = (ROOT / 'dashboard/components/deposit-modal.html').read_text()
admin_api = (ROOT / 'api/admin_api.py').read_text()
page_loader = (ROOT / 'dashboard/js/page-loader.js').read_text()
game_html = (ROOT / 'dashboard/game.html').read_text()

assert '_withdrawSubmitInFlight' in wallet
assert 'X-Idempotency-Key' in wallet
assert '/api/validate-withdrawal/' not in wallet
assert "orderBy('createdAt', 'desc').limit(20)" in wallet
assert "id=\"withdraw-submit\"" in withdraw_modal
assert 'min="50"' in withdraw_modal
assert 'id="deposit-submit"' in deposit_modal
assert 'extraHeaders' in firebase
assert 'return {"ok": False, "error": "system_error"}' in admin_api
assert 'asyncio.create_task(_notify_admin_deposit_web' in admin_api
assert 'asyncio.create_task(_notify_admin_withdrawal_web' in admin_api
assert "const PAGE_ASSET_VERSION = 'pay-1'" in page_loader
assert 'js/firebase.js?v=pay-1' in game_html
assert 'js/wallet.js?v=pay-1' in game_html

print('payment UI hardening regression check: PASS')
