import os
import asyncio
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_deposit_locks = {}
_withdrawal_locks = {}

from config import db
import firestore_db as firestore
from handlers.bot_content import get_bot_text

ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))


def _is_admin(user_id):
    return user_id == ADMIN_CHAT_ID


# ═══════════════════════════════════════════════════════════════════
# /start
# ═══════════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_text(
        "✅ Admin Panel Active\n\n"
        "Use /deposits or /withdrawals to see pending requests.\n"
        "Approve/reject buttons are sent automatically for new requests."
    )


# ═══════════════════════════════════════════════════════════════════
# /deposits — list pending deposits
# ═══════════════════════════════════════════════════════════════════
async def deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    pending = list(db.collection('deposits').where('status', '==', 'pending').order_by('createdAt').limit(20).stream())
    if not pending:
        await update.message.reply_text("✅ No pending deposits.")
        return

    for doc in pending:
        d = doc.to_dict()
        did = doc.id

        text = get_bot_text('admin_deposit_notification', db,
            first_name=d.get('firstName', '?'),
            username=d.get('username', '?'),
            telebirr_name=d.get('telebirrName', 'N/A'),
            amount=d.get('amount', 0),
            transaction_id=d.get('transactionId', 'N/A'),
            deposit_id=did,
            timestamp=d.get('createdAt', 'N/A')
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{did}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_{did}")],
        ])
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=text,
            reply_markup=kb, parse_mode='Markdown',
        )


# ═══════════════════════════════════════════════════════════════════
# /withdrawals — list pending withdrawals
# ═══════════════════════════════════════════════════════════════════
async def withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    pending = list(db.collection('withdrawals').where('status', '==', 'pending').order_by('createdAt').limit(20).stream())
    if not pending:
        await update.message.reply_text("✅ No pending withdrawals.")
        return

    for doc in pending:
        w = doc.to_dict()
        wid = doc.id
        text = get_bot_text('admin_withdrawal_notification', db,
            first_name=w.get('firstName', '?'),
            username=w.get('username', '?'),
            telebirr_name=w.get('telebirrName', 'N/A'),
            amount=w.get('amount', 0),
            phone=w.get('phone', 'N/A'),
            withdrawal_id=wid,
            timestamp=w.get('createdAt', 'N/A')
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw_{wid}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw_{wid}")],
        ])
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=text,
            reply_markup=kb, parse_mode='Markdown',
        )


# ═══════════════════════════════════════════════════════════════════
# Callback router
# ═══════════════════════════════════════════════════════════════════
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return

    data = query.data

    if data.startswith("approve_") and not data.startswith("approve_withdraw_"):
        deposit_id = data.replace("approve_", "")
        await process_deposit(deposit_id, "approved", query)

    elif data.startswith("reject_") and not data.startswith("reject_withdraw_"):
        deposit_id = data.replace("reject_", "")
        await process_deposit(deposit_id, "rejected", query)

    elif data.startswith("approve_withdraw_"):
        wid = data.replace("approve_withdraw_", "")
        await process_withdrawal(wid, "approved", query, context)

    elif data.startswith("reject_withdraw_"):
        wid = data.replace("reject_withdraw_", "")
        await process_withdrawal(wid, "rejected", query, context)


# ═══════════════════════════════════════════════════════════════════
# Process deposit
# ═══════════════════════════════════════════════════════════════════
async def process_deposit(deposit_id, status, query):
    lock = _deposit_locks.setdefault(deposit_id, asyncio.Lock())
    async with lock:
        return await _process_deposit_impl(deposit_id, status, query)


async def _process_deposit_impl(deposit_id, status, query):
    try:
        from settlement import settle_deposit
        settled = settle_deposit(db, deposit_id, status)
        if not settled.get("ok"):
            raise Exception(settled.get("error", "Deposit settlement failed"))
        data = {"firstName": settled.get("first_name", "?")}
        user_id = settled.get("user_id")
        amount = settled.get("amount", 0)

        # Notify user via game bot
        try:
            from telegram import Bot
            from config import BOT_TOKEN
            bot = Bot(token=BOT_TOKEN)
            if status == "approved" and user_id:
                await bot.send_message(
                    chat_id=int(user_id),
                    text=get_bot_text('deposit_approved', db, amount=amount),
                )
            elif user_id:
                await bot.send_message(
                    chat_id=int(user_id),
                    text=get_bot_text('deposit_rejected', db),
                )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")

        new_text = (
            f"{'✅' if status == 'approved' else '❌'} Deposit {status}\n"
            f"User: {data.get('firstName', '?')} | {amount} ETB"
        )
        try:
            await query.edit_message_text(new_text)
        except Exception:
            try:
                await query.edit_message_caption(caption=new_text)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Error processing deposit: {e}")
        try:
            await query.edit_message_text(f"❌ Error: {str(e)[:100]}")
        except Exception:
            try:
                await query.edit_message_caption(caption=f"❌ Error: {str(e)[:100]}")
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════
# Process withdrawal
# ═══════════════════════════════════════════════════════════════════
async def process_withdrawal(wid, status, query, context):
    lock = _withdrawal_locks.setdefault(wid, asyncio.Lock())
    async with lock:
        return await _process_withdrawal_impl(wid, status, query, context)


async def _process_withdrawal_impl(wid, status, query, context):
    try:
        from settlement import settle_withdrawal
        settled = settle_withdrawal(db, wid, status)
        if not settled.get("ok"):
            raise Exception(settled.get("error", "Withdrawal settlement failed"))
        data = {"firstName": settled.get("first_name", "?")}
        user_id = settled.get("user_id")
        amount = settled.get("amount", 0)

        # Notify user
        try:
            from telegram import Bot
            from config import BOT_TOKEN
            bot = Bot(token=BOT_TOKEN)
            if status == "approved" and user_id:
                await bot.send_message(
                    chat_id=int(user_id),
                    text=get_bot_text('withdraw_approved', db, amount=amount),
                )
            elif user_id:
                await bot.send_message(
                    chat_id=int(user_id),
                    text=get_bot_text('withdraw_rejected', db),
                )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")

        await query.edit_message_text(
            f"{'✅' if status == 'approved' else '❌'} Withdrawal {status}\n"
            f"User: {data.get('firstName', '?')} | {amount} ETB"
        )

    except Exception as e:
        logger.error(f"Error processing withdrawal: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)[:100]}")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════
def main():
    import asyncio as _asyncio

    async def _pre_start():
        from telegram import Bot
        import asyncio as _aio
        b = Bot(token=ADMIN_BOT_TOKEN)
        await b.delete_webhook(drop_pending_updates=True)
        await _aio.sleep(5)
        me = await b.get_me()
        logger.info(f"✅ Admin bot connected: @{me.username}")

    _asyncio.run(_pre_start())

    app = Application.builder().token(ADMIN_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("deposits", deposits))
    app.add_handler(CommandHandler("withdrawals", withdrawals))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("🔧 Admin Bot starting...")

    async def _handle_error(update, context):
        from telegram.error import Conflict
        if isinstance(context.error, Conflict):
            return
        logger.error(f"Unhandled exception: {context.error}", exc_info=context.error)

    app.add_error_handler(_handle_error)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
