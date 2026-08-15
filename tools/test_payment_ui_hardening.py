from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
wallet = (ROOT / 'dashboard-react/client/src/pages/Wallet.tsx').read_text()
gateway = (ROOT / 'dashboard-react/client/src/lib/gateway.ts').read_text()
admin_api = (ROOT / 'api/admin_api.py').read_text()
context = (ROOT / 'dashboard-react/client/src/contexts/PlayerContext.tsx').read_text()
realtime = (ROOT / 'dashboard-react/client/src/lib/realtime.ts').read_text()

assert 'crypto.randomUUID' in wallet
assert 'createWithdrawal' in wallet
assert 'X-Idempotency-Key' in gateway
assert '/api/validate-withdrawal/' not in wallet
assert 'limit_n=20' in gateway
assert 'amount < 10' in wallet
assert 'normalizeTransaction' in gateway
assert 'document.data' in gateway and 'createdAt' in gateway
assert 'amount < 50' not in wallet
assert 'The bot will apply the live minimum' in wallet
assert 'Open the Telegram bot, choose Register Now' in wallet
assert 'Use the same three steps as the KelemBingo bot' in wallet
assert 'playerApi.validateWithdrawal' in wallet
assert 'validation.message' in wallet
assert "botText('name_prompt'" in wallet
assert "config.minimum_amount" in wallet
assert "get_bot_text('deposit_send_to'" in admin_api
assert "get_config_value('cfg_min_withdraw'" in admin_api
assert "def _wallet_validation_message" in admin_api
assert '"message": _wallet_validation_message' in admin_api
assert "validateWithdrawal:" in gateway
assert 'user_id: int' not in admin_api.split('class DepositSubmitRequest', 1)[1].split('# ═', 1)[0]
assert "phone = str(user.get('phone') or '').strip()" in admin_api
assert 'return {"ok": False, "error": "system_error"}' in admin_api
assert 'asyncio.create_task(_notify_admin_deposit_web' in admin_api
assert 'asyncio.create_task(_notify_admin_withdrawal_web' in admin_api
assert 'observePlayer' in context and 'playerApi.reconcile' in context
assert 'subscribeDocument("users", userId' in realtime
assert 'event === "payment_update" ? "payments"' in realtime
withdraw_approval = admin_api[admin_api.index('async def admin_approve_withdrawal'):admin_api.index('async def admin_reject_withdrawal')]
assert 'await broadcast_event("users", user_id)' in withdraw_approval

print('payment UI hardening regression check: PASS')
