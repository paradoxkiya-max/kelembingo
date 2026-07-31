import os
import logging
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError, Forbidden, RetryAfter

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from config import db, BOT_TOKEN

# Dedicated Admin Talk Bot Token (fallback to ADMIN_BOT_TOKEN if missing)
ADMIN_TALK_BOT_TOKEN = os.getenv("ADMIN_TALK_BOT_TOKEN", os.getenv("ADMIN_BOT_TOKEN", ""))
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))


def _is_admin(user_id: int) -> bool:
    return user_id == ADMIN_CHAT_ID


# ═══════════════════════════════════════════════════════════════════
# /start & /help
# ═══════════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    await update.message.reply_text(
        "📢 *Admin Talk & Broadcast Bot Active*\n\n"
        "Send any message or announcement here (text, photo, video, audio, or document).\n"
        "It will automatically be broadcasted to all registered users via the Main User Bot! 🚀\n\n"
        "_Example: 'Today is Monday, it is a great day! I wish you all the best of luck!'_",
        parse_mode="Markdown"
    )


# ═══════════════════════════════════════════════════════════════════
# Broadcast Handler
# ═══════════════════════════════════════════════════════════════════
async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    if not BOT_TOKEN:
        await update.message.reply_text("❌ Error: BOT_TOKEN (Main User Bot) is not configured.")
        return

    msg = update.message
    if not msg:
        return

    # Fetch registered users from database
    try:
        user_docs = list(db.collection('users').stream())
    except Exception as e:
        logger.error(f"Error fetching users for broadcast: {e}")
        await msg.reply_text(f"❌ Error reading users from database: {e}")
        return

    user_ids = []
    for doc in user_docs:
        u_data = doc.to_dict() or {}
        uid = u_data.get('user_id') or doc.id
        try:
            user_ids.append(int(uid))
        except (ValueError, TypeError):
            continue

    # Remove duplicates while preserving order
    user_ids = list(dict.fromkeys(user_ids))

    if not user_ids:
        await msg.reply_text("⚠️ No registered users found in the database.")
        return

    status_msg = await msg.reply_text(f"🚀 *Starting Broadcast...*\n👥 Target Users: {len(user_ids)}", parse_mode="Markdown")

    main_bot = Bot(token=BOT_TOKEN)
    sent_count = 0
    failed_count = 0
    blocked_count = 0

    for idx, target_id in enumerate(user_ids):
        try:
            if msg.text:
                await main_bot.send_message(
                    chat_id=target_id,
                    text=msg.text,
                    parse_mode=msg.parse_mode if hasattr(msg, 'parse_mode') else None,
                )
            elif msg.photo:
                photo_id = msg.photo[-1].file_id
                await main_bot.send_photo(
                    chat_id=target_id,
                    photo=photo_id,
                    caption=msg.caption,
                )
            elif msg.video:
                video_id = msg.video.file_id
                await main_bot.send_video(
                    chat_id=target_id,
                    video=video_id,
                    caption=msg.caption,
                )
            elif msg.audio:
                audio_id = msg.audio.file_id
                await main_bot.send_audio(
                    chat_id=target_id,
                    audio=audio_id,
                    caption=msg.caption,
                )
            elif msg.voice:
                voice_id = msg.voice.file_id
                await main_bot.send_voice(
                    chat_id=target_id,
                    voice=voice_id,
                    caption=msg.caption,
                )
            elif msg.document:
                doc_id = msg.document.file_id
                await main_bot.send_document(
                    chat_id=target_id,
                    document=doc_id,
                    caption=msg.caption,
                )
            sent_count += 1
        except Forbidden:
            blocked_count += 1
        except RetryAfter as ra:
            await asyncio.sleep(ra.retry_after + 1)
            try:
                if msg.text:
                    await main_bot.send_message(chat_id=target_id, text=msg.text)
                elif msg.photo:
                    await main_bot.send_photo(chat_id=target_id, photo=msg.photo[-1].file_id, caption=msg.caption)
                sent_count += 1
            except Exception:
                failed_count += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast to user {target_id}: {e}")
            failed_count += 1

        # Rate limiting: limit to ~25 msgs/sec
        await asyncio.sleep(0.04)

        # Update status every 50 users or at the end
        if (idx + 1) % 50 == 0 or (idx + 1) == len(user_ids):
            try:
                await status_msg.edit_text(
                    f"📢 *Broadcasting Progress...*\n\n"
                    f"⏳ Sent: {idx + 1} / {len(user_ids)}\n"
                    f"✅ Delivered: {sent_count}\n"
                    f"🚫 Blocked: {blocked_count}\n"
                    f"❌ Failed: {failed_count}",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    summary_text = (
        f"✅ *Broadcast Complete!*\n\n"
        f"👥 Total Users: {len(user_ids)}\n"
        f"✅ Delivered: {sent_count}\n"
        f"🚫 Blocked Users: {blocked_count}\n"
        f"❌ Failed: {failed_count}"
    )
    await msg.reply_text(summary_text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════
def main():
    if not ADMIN_TALK_BOT_TOKEN:
        logger.error("ADMIN_TALK_BOT_TOKEN is not configured in environment.")
        return

    async def _pre_start():
        b = Bot(token=ADMIN_TALK_BOT_TOKEN)
        await b.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(2)
        me = await b.get_me()
        logger.info(f"✅ Admin Talk bot connected: @{me.username}")

    try:
        asyncio.run(_pre_start())
    except Exception as e:
        logger.warning(f"Pre-start webhook cleanup note: {e}")

    app = Application.builder().token(ADMIN_TALK_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_broadcast_message))

    logger.info("🔧 Admin Talk Bot starting...")

    async def _handle_error(update, context):
        from telegram.error import Conflict
        if isinstance(context.error, Conflict):
            return
        logger.error(f"Unhandled exception in Admin Talk Bot: {context.error}", exc_info=context.error)

    app.add_error_handler(_handle_error)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
