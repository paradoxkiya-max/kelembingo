import json as json_module
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway_client

captured = []


def fake_request(method, url, *, json=None, headers=None, timeout=15):
    captured.append(json)
    # Prove requests can serialize the actual payload passed to it.
    json_module.dumps(json, allow_nan=False)
    return SimpleNamespace(status_code=200, text="", json=lambda: {"ok": True})


gateway_client._request_with_retry = fake_request
client = gateway_client.GatewayClient("http://gateway.test", "internal-key")
now = datetime(2026, 8, 17, 12, 34, 56, tzinfo=timezone.utc)

client.create_deposit({"userId": "1", "amount": 100, "createdAt": now})
client.create_withdrawal({"userId": "1", "amount": 100, "createdAt": now}, "withdraw-key")

assert len(captured) == 2
assert captured[0]["createdAt"] == now.isoformat()
assert captured[1]["createdAt"] == now.isoformat()
print("PASS: deposit and withdrawal payloads serialize datetime values as ISO strings")
