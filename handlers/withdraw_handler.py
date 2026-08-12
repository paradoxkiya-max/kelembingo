import os
import asyncio
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

from config import db
from handlers.user_manager import UserManager
from handlers.bot_content import get_bot_text, get_config_value

user_manager = UserManager(db)

async def _is_admin_online() -> bool:
    def _check():
        try:
            doc = db.collection('system').document('admin_status').get()
            if doc.exists:
                return doc.to_dict().get('online', True)
        except Exception:
            pass
        return True
    return await asyncio.to_thread(_check)

async def handle_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle withdrawal request from game wallet screen"""
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    min_withdraw = get_config_value('cfg_min_withdraw', db, as_type=int)
    val = await user_manager.validate_withdrawal(uid, min_withdraw)
    if not val['ok']:
        error_key = f"withdraw_{val['error']}"
        kwargs = {k: v for k, v in val.items() if k != 'ok' and k != 'error'}
        await query.edit_message_text(get_bot_text(error_key, db, **kwargs))
        return

    user = await user_manager.get_user(uid)
    balance = user.get('play_wallet', 0) if user else 0

    text = get_bot_text('withdraw_ask_amount', db, balance=balance, min_withdraw=min_withdraw)

    await query.edit_message_text(text, parse_mode='Markdown')
    context.user_data["awaiting_withdraw_amount"] = True

async def process_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the withdrawal amount entered by user"""
    uid = update.effective_user.id
    text = update.message.text.strip()

    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text(get_bot_text('withdraw_invalid_number', db))
        return

    val = await user_manager.validate_withdrawal(uid, amount)
    if not val['ok']:
        error_key = f"withdraw_{val['error']}"
        kwargs = {k: v for k, v in val.items() if k != 'ok' and k != 'error'}
        await update.message.reply_text(get_bot_text(error_key, db, **kwargs))
        return

    admin_online = await _is_admin_online()
    if not admin_online:
        await update.message.reply_text(get_bot_text('withdraw_admin_offline', db))
        return

    context.user_data["withdraw_amount"] = amount
    await update.message.reply_text(get_bot_text('withdraw_ask_name', db))
    context.user_data["awaiting_telebirr_number"] = True

async def process_telebirr_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the TeleBirr number and create withdrawal request"""
    user = update.effective_user
    telebirr = update.message.text.strip()
    amount = context.user_data.get("withdraw_amount", 0)

    if not telebirr.startswith("+251") or len(telebirr) < 12:
        await update.message.reply_text("❌ Invalid phone number. Must start with +251 and be at least 12 digits.")
        return

    uid = user.id
    val = await user_manager.validate_withdrawal(uid, amount)
    if not val['ok']:
        error_key = f"withdraw_{val['error']}"
        kwargs = {k: v for k, v in val.items() if k != 'ok' and k != 'error'}
        await update.message.reply_text(get_bot_text(error_key, db, **kwargs))
        return

    # Keep this legacy handler safe if it is ever registered again. The live
    # bot flow owns the per-user lock, revalidation, debit, and pending record.
    from bot import _process_withdraw
    context.user_data["telebirr_name"] = telebirr
    result = await _process_withdraw(update, context, uid, amount, telebirr)
    context.user_data.pop("withdraw_amount", None)
    context.user_data.pop("awaiting_withdraw_amount", None)
    context.user_data.pop("awaiting_telebirr_number", None)
    context.user_data.pop("telebirr_name", None)
    return result
