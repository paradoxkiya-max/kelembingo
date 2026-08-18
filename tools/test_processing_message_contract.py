from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
bot = (ROOT / "bot.py").read_text(encoding="utf-8")

assert 'async def _send_processing_message(message):' in bot
assert 'await message.reply_text("⏳ Please wait…")' in bot
assert 'async def _remove_processing_message(message):' in bot
assert 'processing_message = await _send_processing_message(update.effective_message)' in bot
assert 'await _remove_processing_message(processing_message)' in bot
assert 'await query.edit_message_text("⏳ Please wait…")' in bot

print("PASS: Telegram temporary processing-message contract")
