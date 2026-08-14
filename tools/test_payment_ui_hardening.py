from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
wallet = (ROOT / 'dashboard-react/client/src/pages/Wallet.tsx').read_text()
gateway = (ROOT / 'dashboard-react/client/src/lib/gateway.ts').read_text()
admin_api = (ROOT / 'api/admin_api.py').read_text()

assert 'crypto.randomUUID' in wallet
assert 'createWithdrawal' in wallet
assert 'X-Idempotency-Key' in gateway
assert '/api/validate-withdrawal/' not in wallet
assert 'limit_n=20' in gateway
assert 'amount < 50' in wallet
assert 'amount < 10' in wallet
assert 'return {"ok": False, "error": "system_error"}' in admin_api
assert 'asyncio.create_task(_notify_admin_deposit_web' in admin_api
assert 'asyncio.create_task(_notify_admin_withdrawal_web' in admin_api

print('payment UI hardening regression check: PASS')
