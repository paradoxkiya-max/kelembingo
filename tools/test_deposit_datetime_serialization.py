from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway_client


class FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {"ok": True, "deposit_id": "dep-test"}


captured = {}
original_request = gateway_client.requests.request


def fake_request(method, url, **kwargs):
    captured.update({"method": method, "url": url, **kwargs})
    return FakeResponse()


try:
    gateway_client.requests.request = fake_request
    client = gateway_client.GatewayClient(
        gateway_url="https://gateway.test",
        api_key="test-key",
    )
    created_at = datetime(2026, 8, 17, 18, 30, tzinfo=timezone.utc)
    result = client.create_deposit({
        "userId": "123",
        "amount": 100,
        "transactionId": "TX-123",
        "createdAt": created_at,
    })
finally:
    gateway_client.requests.request = original_request

assert result == {"ok": True, "deposit_id": "dep-test"}
assert captured["method"] == "POST"
assert captured["url"].endswith("/api/internal/deposits/create")
payload = captured["json"]
assert payload["createdAt"] == created_at.isoformat()
json.dumps(payload, allow_nan=False)
print("deposit datetime serialization regression: PASS")
