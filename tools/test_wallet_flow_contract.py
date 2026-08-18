from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
admin_api = (ROOT / "api/admin_api.py").read_text(encoding="utf-8")
realtime = (ROOT / "dashboard-react/client/src/lib/realtime.ts").read_text(encoding="utf-8")
wallet = (ROOT / "dashboard-react/client/src/pages/Wallet.tsx").read_text(encoding="utf-8")

assert 'collection == "player_payments"' in admin_api
assert 'data.get("user_id")' in admin_api
assert 'room=f"player_payments:{payment_user_id}"' in admin_api
assert '"collection": "player_payments"' in admin_api
assert 'subscribeCollection("player_payments"' in realtime
assert '{ user_id: String(userId) }' in realtime
assert 'observePlayerPayments(userId' in wallet
assert 'cacheAt.current = 0; void loadTransactions()' in wallet

print("PASS: game-wallet payment creation and player-scoped realtime contract")
