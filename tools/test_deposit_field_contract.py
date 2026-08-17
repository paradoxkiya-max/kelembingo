import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway_client


captured = []


def fake_request(method, url, *, json=None, headers=None, timeout=15):
    captured.append(json)
    return SimpleNamespace(status_code=200, text="", json=lambda: {"ok": True})


gateway_client._request_with_retry = fake_request
client = gateway_client.GatewayClient("http://gateway.test", "internal-key")
now = datetime(2026, 8, 17, 12, 34, 56, tzinfo=timezone.utc)

client.create_deposit(
    {
        "userId": "1",
        "username": "player",
        "firstName": "Player",
        "telebirrName": "Telebirr Player",
        "amount": 100,
        "transactionId": "txn-1",
        "senderName": "Player",
        "createdAt": now,
    }
)
client.create_withdrawal(
    {
        "userId": "1",
        "firstName": "Player",
        "telebirrName": "Telebirr Player",
        "amount": 100,
        "phone": "0900000000",
        "createdAt": now,
    },
    "withdraw-key",
)

assert len(captured) == 2
assert captured[0]["user_id"] == "1"
assert captured[0]["first_name"] == "Player"
assert captured[0]["telebirr_name"] == "Telebirr Player"
assert captured[0]["transaction_id"] == "txn-1"
assert captured[0]["sender_name"] == "Player"
assert captured[0]["createdAt"] == now.isoformat()
assert not any(key in captured[0] for key in ("userId", "firstName", "telebirrName", "transactionId", "senderName"))

assert captured[1]["user_id"] == "1"
assert captured[1]["first_name"] == "Player"
assert captured[1]["telebirr_name"] == "Telebirr Player"
assert captured[1]["idempotency_key"] == "withdraw-key"
assert captured[1]["createdAt"] == now.isoformat()
assert not any(key in captured[1] for key in ("userId", "firstName", "telebirrName", "idempotencyKey"))

print("PASS: deposit and withdrawal payloads use the gateway snake_case field contract")
