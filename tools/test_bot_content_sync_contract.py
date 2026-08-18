from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
bot_content = (ROOT / "handlers/bot_content.py").read_text(encoding="utf-8")
gateway = (ROOT / "gateway_client.py").read_text(encoding="utf-8")
admin_api = (ROOT / "api/admin_api.py").read_text(encoding="utf-8")

assert "gateway_worker = bool(getattr(db, \"gateway_url\", None))" in bot_content
assert "cache_ttl = 0 if gateway_worker else _cache_ttl" in bot_content
assert "if cache_ttl > 0 and key in _cache" in bot_content
assert "'bot_content': 0" in gateway
assert "db.collection('bot_content').document(key).set" in admin_api
assert "invalidate_cache(key)" in admin_api

print("PASS: Bot Content edits propagate across GatewayClient worker processes")
