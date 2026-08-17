from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
bot = (ROOT / "bot.py").read_text(encoding="utf-8")
bot_content = (ROOT / "handlers/bot_content.py").read_text(encoding="utf-8")
gateway_client = (ROOT / "gateway_client.py").read_text(encoding="utf-8")
admin_api = (ROOT / "api/admin_api.py").read_text(encoding="utf-8")

assert "preload_bot_content(db)" in bot
assert "from handlers.bot_content import get_bot_text, invalidate_cache, get_config_value, preload_bot_content" in bot
assert "await _aio.sleep(5)" not in bot
assert "def preload_bot_content(db=None)" in bot_content
assert "db.collection('bot_content').get()" in bot_content
assert "_http_session = requests.Session()" in gateway_client
assert "_http_session.request" in gateway_client
assert "latest_events = {}" in admin_api
assert "latest_events[(ev.collection, ev.doc_id)] = ev" in admin_api

print("PASS: bot startup preload and gateway connection-reuse performance contract")
