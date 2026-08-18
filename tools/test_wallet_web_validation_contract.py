from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
admin_api = (ROOT / "api/admin_api.py").read_text(encoding="utf-8")
gateway = (ROOT / "dashboard-react/client/src/lib/gateway.ts").read_text(encoding="utf-8")
wallet = (ROOT / "dashboard-react/client/src/pages/Wallet.tsx").read_text(encoding="utf-8")

assert "class DepositSubmitRequest(BaseModel):" in admin_api
assert "# The player identity comes from X-Player-Token" in admin_api
assert "class DepositSubmitRequest(BaseModel):\n    user_id: int" not in admin_api
assert "minimum_amount: float = 10" in admin_api
assert "'send_to': send_to" in admin_api
assert "export function formatWithdrawalValidation" in gateway
assert "deposit_required" in gateway
assert "account_new" in gateway
assert "formatWithdrawalValidation(validation)" in wallet
assert ".replace('{phone}', config.phone" in wallet
assert "const minimumAmount = depositConfig.minimum_amount || 10" in wallet

print("PASS: web wallet deposit and withdrawal validation contract")
