"""Regression test for the Telegram Mini App launch chain."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
index_html = (ROOT / "dashboard-react/client/index.html").read_text()
bot_source = (ROOT / "bot.py").read_text()
render_source = (ROOT / "render.yaml").read_text()

assert "https://telegram.org/js/telegram-web-app.js" in index_html
assert "web_app=WebAppInfo" in bot_source
assert "kelembingo-frontend-i8yy.onrender.com/" in bot_source
assert "kelembingo-frontend-i8yy.onrender.com/" in render_source
print("Telegram WebApp launch contract check: PASS")
