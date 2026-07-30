import logging
import os
import re
import hashlib
import asyncio
from urllib.parse import quote
from datetime import datetime, timezone

from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters,
)
from config import (
    db, BOT_TOKEN, ADMIN_CHAT_ID, ADMIN_BOT_TOKEN,
    DEFAULT_STAKE_10, DEFAULT_STAKE_20,
    SUPPORT_USERNAME, REFERRAL_BONUS, BONUS_TO_ETB_RATE, MIN_WITHDRAW, MAX_WITHDRAW,
    TELEBIRR_NUMBER,
)
from telegram import Bot
from handlers.user_manager import UserManager
from handlers.bot_content import get_bot_text, invalidate_cache, get_config_value
from firestore_db import FieldFilter, Increment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_manager = UserManager(db)
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')

# ─── Conversation states ───
REG_NAME, REG_CONTACT = 0, 1
AWAIT_PHOTO = 3
DEPOSIT_AMOUNT, DEPOSIT_TELEBIRR_NAME = 11, 12
DEPOSIT_CONFIRM, DEPOSIT_TXN_NUMBER = 14, 15
WITHDRAW_AMOUNT, WITHDRAW_TELEBIRR_NAME = 4, 13
TRANSFER_ID, TRANSFER_AMOUNT, TRANSFER_CONFIRM = 6, 7, 8
BONUS_CONFIRM = 9
PLAY_STAKE = 10

MAIN_KEYBOARD = ReplyKeyboardRemove()
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://kelembingo-frontend.onrender.com/game.html")
MAIN_INLINE_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("Play 🎮", callback_data="menu_play"), InlineKeyboardButton("Register 📝", callback_data="menu_register")],
        [InlineKeyboardButton("Check Balance 💵", callback_data="menu_balance"), InlineKeyboardButton("Deposit 💵", callback_data="menu_deposit")],
        [InlineKeyboardButton("Contact Support ☎️", callback_data="menu_support"), InlineKeyboardButton("Instruction 📖", callback_data="menu_instruction")],
        [InlineKeyboardButton("Transfer 🎁", callback_data="menu_transfer"), InlineKeyboardButton("Withdraw 🤑", callback_data="menu_withdraw")],
        [InlineKeyboardButton("Invite 🔗", callback_data="menu_invite"), InlineKeyboardButton("Convert Bonus 💸", callback_data="menu_bonus")],
        [InlineKeyboardButton("🚀 Play Now", web_app=WebAppInfo(url=WEBAPP_URL))],
    ]
)


def _admin_id():
    return int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 8462274722


# ═══════════════════════════════════════════════════════════════════
# /start
# ═══════════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    existed = await user_manager.user_exists(user.id)
    u = await user_manager.get_or_create_user(user.id, user.first_name, user.username or "")

    # Referral tracking — only attribute a referrer to brand-new users, once.
    # The referrer is rewarded later, when this user completes registration.
    if not existed and context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0][4:])
            if referrer_id != user.id and await user_manager.get_user(referrer_id):
                await user_manager.set_referred_by(user.id, referrer_id)
        except (ValueError, IndexError):
            pass

    is_reg = u.get('registered') or (u.get('phone') and len(u.get('phone')) > 0)

    if is_reg:
        # Already registered — show full menu
        pw = u.get('play_wallet', 0)
        text = get_bot_text('welcome_registered', db, name=user.first_name, balance=pw, play_wallet=pw)
        await update.effective_message.reply_text(text, reply_markup=MAIN_INLINE_KEYBOARD, parse_mode='Markdown')
    else:
        # New user — needs registration, show banner
        text = get_bot_text('welcome_new', db)
        kb = MAIN_INLINE_KEYBOARD
        banner_path = os.path.join(ASSETS_DIR, 'welcome_banner.png')
        try:
            if os.path.exists(banner_path):
                with open(banner_path, 'rb') as photo:
                    await update.effective_message.reply_photo(
                        photo=photo,
                        caption=text,
                        reply_markup=kb,
                        read_timeout=30,
                        write_timeout=60,
                        connect_timeout=30
                    )
            else:
                await update.effective_message.reply_text(text, reply_markup=kb)
        except Exception as e:
            logger.warning(f"Banner upload failed, sending text only: {e}")
            await update.effective_message.reply_text(text, reply_markup=kb)

        await update.effective_message.reply_text(
            get_bot_text('welcome_new_amharic', db)
        )


# ═══════════════════════════════════════════════════════════════════
# 🎮 Play — Opens the Mini App directly
# ═══════════════════════════════════════════════════════════════════

async def handle_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    uid = update.effective_user.id
    u = await user_manager.get_user(uid)

    if not u:
        await user_manager.get_or_create_user(uid, update.effective_user.first_name, update.effective_user.username or "")
        u = await user_manager.get_user(uid)

    is_registered = u.get('registered') or (u.get('phone') and len(u.get('phone', '')) > 0)

    if not is_registered:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Register Now", callback_data="menu_register")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu_back")],
        ])
        await update.effective_message.reply_text(
            get_bot_text('register_ask_contact', db),
            reply_markup=kb,
        )
        return

    pw = u.get('play_wallet', 0)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Play Now — 10 ETB", web_app=WebAppInfo(url=WEBAPP_URL))],
    ])
    await update.effective_message.reply_text(
        get_bot_text('play_wallet_info', db, play_wallet=pw),
        reply_markup=kb, parse_mode='Markdown',
    )


# ═══════════════════════════════════════════════════════════════════
# 📝 Register
# ═══════════════════════════════════════════════════════════════════
async def handle_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    uid = update.effective_user.id
    if await user_manager.is_registered(uid):
        u = await user_manager.get_user(uid)
        await update.effective_message.reply_text(
            get_bot_text('register_already', db, name=u.get('first_name', ''), phone=u.get('phone', '')),
            reply_markup=MAIN_INLINE_KEYBOARD,
        )
        return ConversationHandler.END

    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Share Contact", request_contact=True)]],
        one_time_keyboard=True, resize_keyboard=True,
    )
    await update.effective_message.reply_text(
        get_bot_text('register_ask_contact', db),
        reply_markup=kb,
    )
    return REG_CONTACT


async def reg_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    if not contact:
        await update.message.reply_text(get_bot_text('register_ask_contact', db))
        return REG_CONTACT

    phone = contact.phone_number
    if not phone.startswith('+'):
        phone = '+' + phone

    name = update.effective_user.first_name or ''
    await user_manager.register_user(update.effective_user.id, name, phone, '')
    await update.message.reply_text(
        get_bot_text('register_complete', db, name=name, phone=phone),
        reply_markup=MAIN_KEYBOARD,
    )

    # Record the referral (once) now that the invited user has registered.
    # Invitation tracking only — no bonus/ETB is awarded.
    referrer_id = await user_manager.count_referral(update.effective_user.id)
    if referrer_id:
        try:
            await context.bot.send_message(
                chat_id=int(referrer_id),
                text=get_bot_text('referral_joined', db, name=name),
                parse_mode='Markdown',
            )
        except Exception as e:
            logger.warning(f"Could not notify referrer {referrer_id}: {e}")

    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════
# 💵 Check Balance
# ═══════════════════════════════════════════════════════════════════
async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    uid = update.effective_user.id
    info = await user_manager.get_balance_info(uid)
    if not info:
        await update.effective_message.reply_text("Please /start first.", reply_markup=MAIN_KEYBOARD)
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 Deposit", callback_data="bal_deposit"),
         InlineKeyboardButton("🤑 Withdraw", callback_data="bal_withdraw")],
    ])
    
    text = (
        f"💼 *Account Info*\n\n"
        f"Name:       {info['first_name']}\n"
        f"Balance:    {info['balance']:.1f} ETB\n"
        f"Coin:       {info['bonus']}"
    )

    await update.effective_message.reply_text(
        text,
        reply_markup=kb, parse_mode='Markdown',
    )


# ═══════════════════════════════════════════════════════════════════
# 💵 Deposit
# ═══════════════════════════════════════════════════════════════════
async def handle_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        return await _show_deposit_flow(update.callback_query, context)
    return await _show_deposit_flow_msg(update, context)


async def _show_deposit_flow_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = await user_manager.get_user(uid)
    if not u:
        await update.effective_message.reply_text(get_bot_text('play_need_start', db), reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    # Check pending deposits limit
    pending = db.collection('deposits').where('userId', '==', str(uid)).where('status', '==', 'pending').get()
    if len(list(pending)) >= 3:
        await update.effective_message.reply_text(
            get_bot_text('deposit_too_many', db),
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    await update.effective_message.reply_text(
        get_bot_text('deposit_ask_name', db)
    )
    return DEPOSIT_TELEBIRR_NAME


async def _show_deposit_flow(query, context):
    uid = query.from_user.id
    u = await user_manager.get_user(uid)
    if not u:
        try:
            await query.edit_message_text(get_bot_text('play_need_start', db))
        except Exception:
            await context.bot.send_message(chat_id=query.message.chat_id, text=get_bot_text('play_need_start', db))
        return ConversationHandler.END
    pending = db.collection('deposits').where('userId', '==', str(uid)).where('status', '==', 'pending').get()
    if len(list(pending)) >= 3:
        try:
            await query.edit_message_text(get_bot_text('deposit_too_many', db))
        except Exception:
            await context.bot.send_message(chat_id=query.message.chat_id, text=get_bot_text('deposit_too_many', db))
        return ConversationHandler.END

    try:
        await query.edit_message_text(get_bot_text('deposit_ask_name', db))
    except Exception:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=get_bot_text('deposit_ask_name', db)
        )
    return DEPOSIT_TELEBIRR_NAME


async def deposit_telebirr_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['telebirr_name'] = update.message.text.strip()
    await update.effective_message.reply_text(get_bot_text('deposit_ask_amount', db))
    return DEPOSIT_AMOUNT


async def deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        if amount < 10:
            await update.effective_message.reply_text(get_bot_text('deposit_min_amount', db))
            return DEPOSIT_AMOUNT
    except ValueError:
        await update.effective_message.reply_text(get_bot_text('deposit_invalid_number', db))
        return DEPOSIT_AMOUNT

    context.user_data['deposit_amount'] = amount
    await update.effective_message.reply_text(
        get_bot_text('deposit_send_to', db, amount=int(amount), phone=get_bot_text('deposit_phone', db)),
    )
    return DEPOSIT_TXN_NUMBER


async def deposit_txn_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = await user_manager.get_user(uid)

    if not u:
        await update.effective_message.reply_text(get_bot_text('play_need_start', db), reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    txn_number = update.message.text.strip()
    if not txn_number or len(txn_number) < 3:
        await update.effective_message.reply_text(get_bot_text('deposit_invalid_number', db))
        return DEPOSIT_TXN_NUMBER

    # Check admin online
    admin_online = await _is_admin_online()
    if not admin_online:
        await update.effective_message.reply_text(
            get_bot_text('deposit_admin_offline', db),
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    amount = context.user_data.get('deposit_amount', 0)
    telebirr_name = context.user_data.get('telebirr_name', '')

    # Check duplicate transaction number
    dup = db.collection('deposits').where('transactionId', '==', txn_number).limit(1).get()
    if dup:
        await update.effective_message.reply_text(get_bot_text('deposit_duplicate_txn', db), reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    deposit_data = {
        'userId': str(uid),
        'username': update.message.from_user.username or '',
        'firstName': update.message.from_user.first_name or '',
        'telebirrName': telebirr_name,
        'amount': amount,
        'transactionId': txn_number,
        'senderName': u.get('first_name', 'Unknown') if u else 'Unknown',
        'status': 'pending',
        'createdAt': datetime.now(tz=timezone.utc),
        'processedAt': None,
        'adminNote': '',
    }
    deposit_ref = db.collection('deposits').document()
    deposit_ref.set(deposit_data)
    deposit_id = deposit_ref.id

    context.user_data.pop('deposit_amount', None)
    context.user_data.pop('telebirr_name', None)

    await update.effective_message.reply_text(
        get_bot_text('deposit_submitted', db, amount=amount, telebirr_name=telebirr_name, transaction_id=txn_number, deposit_id=deposit_id),
        parse_mode='Markdown', reply_markup=MAIN_KEYBOARD,
    )

    await _notify_admin_deposit(deposit_data, deposit_id, context)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════
# 🎰 Withdraw
# ═══════════════════════════════════════════════════════════════════
async def handle_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        return await _show_withdraw_flow(update.callback_query, context)
    return await _show_withdraw_flow_msg(update, context)


async def _show_withdraw_flow_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = await user_manager.get_user(uid)
    if not u:
        await update.effective_message.reply_text(get_bot_text('play_need_start', db), reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    min_withdraw = get_config_value('cfg_min_withdraw', db, as_type=int)
    val = await user_manager.validate_withdrawal(uid, min_withdraw)
    if not val['ok']:
        error_key = f"withdraw_{val['error']}"
        kwargs = {k: v for k, v in val.items() if k != 'ok' and k != 'error'}
        await update.effective_message.reply_text(
            get_bot_text(error_key, db, **kwargs),
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    bal = u.get('play_wallet', 0)
    await update.effective_message.reply_text(
        get_bot_text('withdraw_ask_amount', db, balance=bal, min_withdraw=min_withdraw),
        reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown',
    )
    return WITHDRAW_AMOUNT


async def _show_withdraw_flow(query, context):
    uid = query.from_user.id
    u = await user_manager.get_user(uid)
    if not u:
        try:
            await query.edit_message_text(get_bot_text('play_need_start', db))
        except Exception:
            await context.bot.send_message(chat_id=query.message.chat_id, text=get_bot_text('play_need_start', db))
        return ConversationHandler.END

    min_withdraw = get_config_value('cfg_min_withdraw', db, as_type=int)
    val = await user_manager.validate_withdrawal(uid, min_withdraw)
    if not val['ok']:
        error_key = f"withdraw_{val['error']}"
        kwargs = {k: v for k, v in val.items() if k != 'ok' and k != 'error'}
        text = get_bot_text(error_key, db, **kwargs)
        try:
            await query.edit_message_text(text)
        except Exception:
            await context.bot.send_message(chat_id=query.message.chat_id, text=text)
        return ConversationHandler.END

    bal = u.get('play_wallet', 0)
    try:
        await query.edit_message_text(get_bot_text('withdraw_ask_amount', db, balance=bal, min_withdraw=min_withdraw))
    except Exception:
        await context.bot.send_message(chat_id=query.message.chat_id, text=get_bot_text('withdraw_ask_amount', db, balance=bal, min_withdraw=min_withdraw))
    return WITHDRAW_AMOUNT


async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.effective_message.reply_text(get_bot_text('withdraw_invalid_number', db))
        return WITHDRAW_AMOUNT

    uid = update.effective_user.id
    val = await user_manager.validate_withdrawal(uid, amount)
    if not val['ok']:
        error_key = f"withdraw_{val['error']}"
        kwargs = {k: v for k, v in val.items() if k != 'ok' and k != 'error'}
        await update.effective_message.reply_text(get_bot_text(error_key, db, **kwargs))
        return WITHDRAW_AMOUNT

    context.user_data['withdraw_amount'] = amount
    await update.effective_message.reply_text(
        get_bot_text('withdraw_ask_name', db)
    )
    return WITHDRAW_TELEBIRR_NAME


async def withdraw_telebirr_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['telebirr_name'] = update.message.text.strip()
    uid = update.effective_user.id
    u = await user_manager.get_user(uid)
    amount = context.user_data.get('withdraw_amount', 0)
    phone = u.get('phone', '') if u else ''
    return await _process_withdraw(update, context, uid, amount, phone)


async def _process_withdraw(update, context, uid, amount, phone):
    u = await user_manager.get_user(uid)
    if not u:
        await update.effective_message.reply_text(get_bot_text('play_need_start', db), reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    user_ref = db.collection('users').document(str(uid))
    user_ref.update({'play_wallet': Increment(-amount), 'updated_at': datetime.now(tz=timezone.utc)})

    withdrawal_data = {
        'userId': str(uid),
        'username': update.effective_user.username or '',
        'firstName': update.effective_user.first_name or '',
        'telebirrName': context.user_data.get('telebirr_name', '') if u else '',
        'amount': amount,
        'phone': phone,
        'status': 'pending',
        'createdAt': datetime.now(tz=timezone.utc),
        'processedAt': None,
        'adminNote': '',
    }
    ref = db.collection('withdrawals').document()
    ref.set(withdrawal_data)

    await update.effective_message.reply_text(
        get_bot_text('withdraw_submitted', db, amount=amount, phone=phone, withdrawal_id=ref.id),
        reply_markup=MAIN_KEYBOARD, parse_mode='Markdown',
    )

    await _notify_admin_withdrawal(withdrawal_data, ref.id, context)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════
# 🎁 Transfer
# ═══════════════════════════════════════════════════════════════════
async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    uid = update.effective_user.id
    u = await user_manager.get_user(uid)
    if not u:
        await update.effective_message.reply_text(get_bot_text('play_need_start', db), reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    bal = u.get('play_wallet', 0)
    if bal < 1:
        await update.effective_message.reply_text(
            get_bot_text('transfer_no_balance', db, balance=bal),
            reply_markup=MAIN_KEYBOARD,
        )
        return ConversationHandler.END

    await update.effective_message.reply_text(
        get_bot_text('transfer_ask_id', db, balance=bal),
        reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown',
    )
    return TRANSFER_ID


async def transfer_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        recipient_id = int(update.message.text.strip())
    except ValueError:
        await update.effective_message.reply_text(get_bot_text('transfer_invalid_id', db))
        return TRANSFER_ID

    if recipient_id == update.effective_user.id:
        await update.effective_message.reply_text(get_bot_text('transfer_self', db))
        return TRANSFER_ID

    recipient = await user_manager.get_user(recipient_id)
    if not recipient:
        await update.effective_message.reply_text(get_bot_text('transfer_not_found', db))
        return TRANSFER_ID

    context.user_data['transfer_to'] = recipient_id
    context.user_data['transfer_to_name'] = recipient.get('first_name', 'Unknown')

    await update.effective_message.reply_text(
        get_bot_text('transfer_ask_amount', db, name=recipient.get('first_name', 'Unknown'))
    )
    return TRANSFER_AMOUNT


async def transfer_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.effective_message.reply_text(get_bot_text('transfer_invalid_amount', db))
        return TRANSFER_AMOUNT

    uid = update.effective_user.id
    u = await user_manager.get_user(uid)
    bal = u.get('play_wallet', 0) if u else 0

    if amount < 1 or amount > bal:
        await update.effective_message.reply_text(get_bot_text('transfer_amount_range', db, balance=bal))
        return TRANSFER_AMOUNT

    context.user_data['transfer_amount'] = amount
    to_name = context.user_data.get('transfer_to_name', 'Unknown')

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="tf_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="tf_no")],
    ])
    await update.effective_message.reply_text(
        get_bot_text('transfer_confirm', db, amount=amount, name=to_name),
        reply_markup=kb, parse_mode='Markdown',
    )
    return TRANSFER_CONFIRM


async def transfer_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "tf_no":
        await query.edit_message_text(get_bot_text('transfer_cancelled', db))
        return ConversationHandler.END

    uid = query.from_user.id
    recipient_id = context.user_data.get('transfer_to')
    amount = context.user_data.get('transfer_amount', 0)

    success = await user_manager.transfer_funds(uid, recipient_id, amount)
    if success:
        to_name = context.user_data.get('transfer_to_name', 'Unknown')
        await query.edit_message_text(
            get_bot_text('transfer_sent', db, amount=amount, name=to_name),
            parse_mode='Markdown',
        )
    else:
        await query.edit_message_text(get_bot_text('transfer_failed', db))
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════
# 🔄 Convert Bonus
# ═══════════════════════════════════════════════════════════════════
async def handle_convert_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    uid = update.effective_user.id
    u = await user_manager.get_user(uid)
    if not u:
        await update.effective_message.reply_text(get_bot_text('play_need_start', db), reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    coins = u.get('bonus', 0)
    if coins <= 0:
        await update.effective_message.reply_text(get_bot_text('bonus_no_coins', db), reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    rate = get_config_value("cfg_bonus_to_etb_rate", db, as_type=int)
    etb = coins / rate
    context.user_data['convert_etb'] = etb
    context.user_data['convert_coins'] = coins

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Convert {coins} coins → {etb} ETB", callback_data="bonus_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="bonus_no")],
    ])
    await update.effective_message.reply_text(
        get_bot_text('bonus_convert_info', db, coins=coins, rate=rate, etb=etb),
        reply_markup=kb, parse_mode='Markdown',
    )
    return BONUS_CONFIRM


async def bonus_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "bonus_no":
        await query.edit_message_text(get_bot_text('bonus_cancelled', db))
        return ConversationHandler.END

    uid = query.from_user.id
    rate = get_config_value("cfg_bonus_to_etb_rate", db, as_type=int)
    etb = await user_manager.convert_bonus(uid, rate)
    if etb is not None:
        await query.edit_message_text(get_bot_text('bonus_converted', db, etb=etb))
    else:
        await query.edit_message_text(get_bot_text('bonus_convert_failed', db))
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════
# 🔗 Invite
# ═══════════════════════════════════════════════════════════════════
async def handle_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    uid = update.effective_user.id
    bot_username = context.bot.username if context.bot else "YourBotUsername"
    link = f"https://t.me/{bot_username}?start=ref_{uid}"
    count = await user_manager.get_referral_count(uid)

    share_text = quote(
        f"🎮 Join me on Kelem Bingo and let's win together! Play now:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📨 Share invite link",
            url=f"https://t.me/share/url?url={quote(link, safe='')}&text={share_text}",
        )],
    ])
    text = get_bot_text('invite_link', db, link=link, count=count)
    try:
        await update.effective_message.reply_text(
            text, reply_markup=kb, parse_mode='Markdown',
        )
    except Exception as e:
        # Never leave the button unresponsive if Markdown parsing fails.
        logger.warning(f"Invite Markdown send failed, sending plain text: {e}")
        await update.effective_message.reply_text(text, reply_markup=kb)


# ═══════════════════════════════════════════════════════════════════
# 📖 Instruction
# ═══════════════════════════════════════════════════════════════════
async def handle_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Menu", callback_data="menu_back")],
    ])
    await update.effective_message.reply_text(
        get_bot_text('instruction', db),
        reply_markup=kb, parse_mode='Markdown',
    )


# ═══════════════════════════════════════════════════════════════════
# 🆘 Contact Support
# ═══════════════════════════════════════════════════════════════════
async def handle_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Menu", callback_data="menu_back")],
    ])
    support_username = get_config_value('cfg_support_username', db, as_type=str)
    await update.effective_message.reply_text(
        f"🆘 ድጋፍ ይፈልጋሉ?\n\n"
        f"👇 ለማንኛውም ጥያቄ ወይም አስተያየት 👇\n\n"
        f"👤 @{support_username}",
        reply_markup=kb,
    )


# ═══════════════════════════════════════════════════════════════════
# 🏠 Back to Menu
# ═══════════════════════════════════════════════════════════════════
async def handle_menu_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    uid = update.effective_user.id
    u = await user_manager.get_user(uid)
    if not u:
        await user_manager.get_or_create_user(uid, update.effective_user.first_name, update.effective_user.username or "")
        u = await user_manager.get_user(uid)
    pw = u.get('play_wallet', 0)
    text = get_bot_text('welcome_registered', db, name=update.effective_user.first_name, balance=pw, play_wallet=pw)
    await update.effective_message.reply_text(text, reply_markup=MAIN_INLINE_KEYBOARD, parse_mode='Markdown')


# ═══════════════════════════════════════════════════════════════════
# Admin notifications
# ═══════════════════════════════════════════════════════════════════
async def _notify_admin_deposit(deposit_data, deposit_id, context):
    try:
        text = get_bot_text('admin_deposit_notification', db,
            first_name=deposit_data.get('firstName', 'Unknown'),
            username=deposit_data.get('username', ''),
            telebirr_name=deposit_data.get('telebirrName', 'N/A'),
            amount=deposit_data.get('amount', 0),
            transaction_id=deposit_data.get('transactionId', 'N/A'),
            deposit_id=deposit_id,
            timestamp=datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{deposit_id}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_{deposit_id}")],
        ])
        bot = Bot(token=ADMIN_BOT_TOKEN) if ADMIN_BOT_TOKEN else context.bot
        await bot.send_message(
            chat_id=_admin_id(), text=text,
            reply_markup=kb, parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Failed to notify admin (deposit): {e}")


async def _notify_admin_withdrawal(withdrawal_data, withdrawal_id, context):
    try:
        text = get_bot_text('admin_withdrawal_notification', db,
            first_name=withdrawal_data.get('firstName', 'Unknown'),
            username=withdrawal_data.get('username', ''),
            telebirr_name=withdrawal_data.get('telebirrName', 'N/A'),
            amount=withdrawal_data.get('amount', 0),
            phone=withdrawal_data.get('phone', 'N/A'),
            withdrawal_id=withdrawal_id,
            timestamp=datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdraw_{withdrawal_id}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdraw_{withdrawal_id}")],
        ])
        bot = Bot(token=ADMIN_BOT_TOKEN) if ADMIN_BOT_TOKEN else context.bot
        await bot.send_message(
            chat_id=_admin_id(), text=text,
            reply_markup=kb, parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Failed to notify admin (withdrawal): {e}")


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════
# Admin approve/reject (fallback when ADMIN_BOT_TOKEN not set)
# ═══════════════════════════════════════════════════════════════════
async def admin_approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != _admin_id():
        return
    deposit_id = query.data.replace("approve_", "")
    try:
        ref = db.collection('deposits').document(deposit_id)
        doc = ref.get()
        if not doc.exists:
            await query.edit_message_text(get_bot_text('admin_deposit_not_found', db))
            return
        data = doc.to_dict()
        if data.get('status') != 'pending':
            await query.edit_message_text(get_bot_text('admin_already_processed', db, status=data.get('status')))
            return
        ref.update({'status': 'approved', 'processedAt': datetime.now(tz=timezone.utc)})
        user_id = data.get('userId')
        amount = data.get('amount', 0)
        if user_id and amount > 0:
            user_ref = db.collection('users').document(str(user_id))
            user_ref.update({'play_wallet': Increment(amount), 'updated_at': datetime.now(tz=timezone.utc)})
            try:
                await context.bot.send_message(chat_id=int(user_id), text=get_bot_text('deposit_approved', db, amount=amount))
            except Exception:
                pass
        await query.edit_message_text(get_bot_text('admin_deposit_approved', db, first_name=data.get('firstName', '?'), amount=amount))
    except Exception as e:
        logger.error(f"Error approving deposit: {e}")
        await query.edit_message_text(get_bot_text('admin_error', db, error=str(e)[:100]))


async def admin_reject_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != _admin_id():
        return
    deposit_id = query.data.replace("reject_", "")
    try:
        ref = db.collection('deposits').document(deposit_id)
        doc = ref.get()
        if not doc.exists:
            await query.edit_message_text(get_bot_text('admin_deposit_not_found', db))
            return
        data = doc.to_dict()
        if data.get('status') != 'pending':
            await query.edit_message_text(get_bot_text('admin_already_processed', db, status=data.get('status')))
            return
        ref.update({'status': 'rejected', 'processedAt': datetime.now(tz=timezone.utc)})
        user_id = data.get('userId')
        if user_id:
            try:
                await context.bot.send_message(chat_id=int(user_id), text=get_bot_text('deposit_rejected', db))
            except Exception:
                pass
        await query.edit_message_text(get_bot_text('admin_deposit_rejected', db, first_name=data.get('firstName', '?')))
    except Exception as e:
        logger.error(f"Error rejecting deposit: {e}")
        await query.edit_message_text(get_bot_text('admin_error', db, error=str(e)[:100]))


async def admin_approve_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != _admin_id():
        return
    wid = query.data.replace("approve_withdraw_", "")
    try:
        ref = db.collection('withdrawals').document(wid)
        doc = ref.get()
        if not doc.exists:
            await query.edit_message_text(get_bot_text('admin_withdrawal_not_found', db))
            return
        data = doc.to_dict()
        if data.get('status') != 'pending':
            await query.edit_message_text(get_bot_text('admin_already_processed', db, status=data.get('status')))
            return
        ref.update({'status': 'approved', 'processedAt': datetime.now(tz=timezone.utc)})
        user_id = data.get('userId')
        amount = data.get('amount', 0)
        if user_id:
            try:
                await context.bot.send_message(chat_id=int(user_id), text=get_bot_text('withdraw_approved', db, amount=amount))
            except Exception:
                pass
        await query.edit_message_text(get_bot_text('admin_withdrawal_approved', db, first_name=data.get('firstName', '?'), amount=amount))
    except Exception as e:
        logger.error(f"Error approving withdrawal: {e}")
        await query.edit_message_text(get_bot_text('admin_error', db, error=str(e)[:100]))


async def admin_reject_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != _admin_id():
        return
    wid = query.data.replace("reject_withdraw_", "")
    try:
        ref = db.collection('withdrawals').document(wid)
        doc = ref.get()
        if not doc.exists:
            await query.edit_message_text(get_bot_text('admin_withdrawal_not_found', db))
            return
        data = doc.to_dict()
        if data.get('status') != 'pending':
            await query.edit_message_text(get_bot_text('admin_already_processed', db, status=data.get('status')))
            return
        ref.update({'status': 'rejected', 'processedAt': datetime.now(tz=timezone.utc)})
        user_id = data.get('userId')
        amount = data.get('amount', 0)
        if user_id and amount > 0:
            user_ref = db.collection('users').document(str(user_id))
            user_ref.update({'play_wallet': Increment(amount), 'updated_at': datetime.now(tz=timezone.utc)})
        if user_id:
            try:
                await context.bot.send_message(chat_id=int(user_id), text=get_bot_text('withdraw_rejected', db, amount=amount))
            except Exception:
                pass
        await query.edit_message_text(get_bot_text('admin_withdrawal_rejected', db, first_name=data.get('firstName', '?'), amount=amount))
    except Exception as e:
        logger.error(f"Error rejecting withdrawal: {e}")
        await query.edit_message_text(get_bot_text('admin_error', db, error=str(e)[:100]))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(get_bot_text('cancel', db), reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════
# 🆘 Support (slash command)
# ═══════════════════════════════════════════════════════════════════
async def handle_support_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_username = get_config_value('cfg_support_username', db, as_type=str)
    await update.effective_message.reply_text(
        get_bot_text('support_info', db, support_username=support_username)
    )


# ═══════════════════════════════════════════════════════════════════
# 🏆 Leaderboard
# ═══════════════════════════════════════════════════════════════════
async def handle_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leaders = await user_manager.get_leaderboard(10)
    if not leaders:
        await update.effective_message.reply_text(get_bot_text('leaderboard_no_games', db), reply_markup=MAIN_KEYBOARD)
        return

    lines = [get_bot_text('leaderboard_title', db)]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(leaders):
        prefix = medals[i] if i < 3 else f" {i+1}."
        name = u.get('first_name', 'Unknown')
        wins = u.get('wins', 0)
        lines.append(f"{prefix} *{name}* — {wins} wins")

    await update.effective_message.reply_text("\n".join(lines), reply_markup=MAIN_KEYBOARD, parse_mode='Markdown')


# ═══════════════════════════════════════════════════════════════════
# 📜 History
# ═══════════════════════════════════════════════════════════════════
async def handle_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    history = await user_manager.get_user_history(uid, 10)
    if not history:
        await update.effective_message.reply_text(get_bot_text('history_no_games', db), reply_markup=MAIN_KEYBOARD)
        return

    lines = [get_bot_text('history_title', db)]
    for g in history:
        result = "✅ Won" if g.get('won') else "❌ Lost"
        stake = g.get('stake', 0)
        prize = g.get('prize', 0)
        date = g.get('created_at', '')
        if hasattr(date, 'strftime'):
            date = date.strftime('%m/%d %H:%M')
        lines.append(f"• {result} — Stake: {stake} ETB, Derash: {prize} ETB  {date}")

    await update.effective_message.reply_text("\n".join(lines), reply_markup=MAIN_KEYBOARD, parse_mode='Markdown')


# ═══════════════════════════════════════════════════════════════════
# 📊 Stats
# ═══════════════════════════════════════════════════════════════════
async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = await user_manager.get_user(uid)
    if not u:
        await update.effective_message.reply_text(get_bot_text('play_need_start', db), reply_markup=MAIN_KEYBOARD)
        return

    total = u.get('total_games', 0)
    wins = u.get('wins', 0)
    losses = u.get('losses', 0)
    win_rate = f"{(wins / total * 100):.1f}%" if total > 0 else "N/A"

    text = get_bot_text('stats_title', db, total=total, wins=wins, losses=losses,
        win_rate=win_rate, balance=u.get('play_wallet', 0), play_wallet=u.get('play_wallet', 0), bonus=u.get('bonus', 0))
    await update.effective_message.reply_text(text, reply_markup=MAIN_KEYBOARD, parse_mode='Markdown')


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════
def main():
    import asyncio as _asyncio

    async def _pre_start():
        from telegram import Bot
        from telegram import BotCommand
        import asyncio as _aio
        b = Bot(token=BOT_TOKEN)
        await b.delete_webhook(drop_pending_updates=True)

        commands = [
            BotCommand("start", "Start the bot / Welcome"),
            BotCommand("play", "Open the Bingo game"),
            BotCommand("register", "Register with your phone number"),
            BotCommand("balance", "Check your wallets"),
            BotCommand("deposit", "Deposit ETB via TeleBirr"),
            BotCommand("withdraw", "Withdraw ETB to TeleBirr"),
            BotCommand("transfer", "Send ETB to another user"),
            BotCommand("invite", "Get your referral link"),
            BotCommand("leaderboard", "Top players by wins"),
            BotCommand("history", "Your recent game history"),
            BotCommand("stats", "Your personal game stats"),
            BotCommand("support", "Contact support"),
            BotCommand("help", "How to play"),
            BotCommand("cancel", "Cancel current action"),
        ]
        await b.set_my_commands(commands)
        logger.info("✅ Bot commands registered in Telegram menu")

        await _aio.sleep(5)
        me = await b.get_me()
        logger.info(f"✅ Game bot connected: @{me.username}")

    _asyncio.run(_pre_start())

    app = Application.builder().token(BOT_TOKEN).read_timeout(30).write_timeout(30).connect_timeout(30).pool_timeout(30).build()

    # ─── /start ───
    app.add_handler(CommandHandler("start", start))

    # ─── Slash commands for Telegram menu ───
    app.add_handler(CommandHandler("play", handle_play))
    app.add_handler(CommandHandler("balance", handle_balance))
    app.add_handler(CommandHandler("invite", handle_invite))
    app.add_handler(CommandHandler("help", handle_instruction))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("support", handle_support_cmd))
    app.add_handler(CommandHandler("leaderboard", handle_leaderboard))
    app.add_handler(CommandHandler("history", handle_history))
    app.add_handler(CommandHandler("stats", handle_stats))

    # ─── Simple menu handlers (no conversation needed) ───
    app.add_handler(MessageHandler(filters.Regex("(?i).*(balance).*"), handle_balance))
    app.add_handler(MessageHandler(filters.Regex("(?i).*(invite).*"), handle_invite))
    app.add_handler(MessageHandler(filters.Regex("(?i).*(instruction|help).*"), handle_instruction))
    app.add_handler(MessageHandler(filters.Regex("(?i).*(support|contact).*"), handle_support))

    # ─── Play handler (no conversation — just opens webapp) ───
    app.add_handler(MessageHandler(filters.Regex("(?i).*(play).*"), handle_play))
    app.add_handler(CallbackQueryHandler(handle_play, pattern="^menu_play$"))

    # ─── ConversationHandler: Register ───
    reg_conv = ConversationHandler(
        entry_points=[
            CommandHandler("register", handle_register),
            MessageHandler(filters.Regex("(?i).*(register).*"), handle_register),
            CallbackQueryHandler(handle_register, pattern="^menu_register$"),
        ],
        per_message=False,
        states={
            REG_CONTACT: [MessageHandler(filters.CONTACT, reg_contact),
                          MessageHandler(filters.TEXT & ~filters.COMMAND, reg_contact)],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^Cancel$"), cancel)],
    )
    app.add_handler(reg_conv, group=2)

    # ─── ConversationHandler: Deposit ───
    deposit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("deposit", handle_deposit),
            MessageHandler(filters.Regex("(?i).*(deposit).*"), handle_deposit),
            CallbackQueryHandler(handle_deposit, pattern="^(menu_deposit|bal_deposit)$"),
        ],
        per_message=False,
        states={
            DEPOSIT_TELEBIRR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_telebirr_name)],
            DEPOSIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount)],
            DEPOSIT_TXN_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_txn_number)],
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^Cancel$"), cancel),
            CallbackQueryHandler(handle_deposit, pattern="^(menu_deposit|bal_deposit)$"),
        ],
    )
    app.add_handler(deposit_conv, group=3)

    # ─── ConversationHandler: Withdraw ───
    withdraw_conv = ConversationHandler(
        entry_points=[
            CommandHandler("withdraw", handle_withdraw),
            MessageHandler(filters.Regex("(?i).*(withdraw).*"), handle_withdraw),
            CallbackQueryHandler(handle_withdraw, pattern="^(menu_withdraw|bal_withdraw)$"),
        ],
        per_message=False,
        states={
            WITHDRAW_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
            WITHDRAW_TELEBIRR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_telebirr_name)],
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^Cancel$"), cancel),
            CallbackQueryHandler(handle_withdraw, pattern="^(menu_withdraw|bal_withdraw)$"),
        ],
    )
    app.add_handler(withdraw_conv, group=4)

    # ─── ConversationHandler: Transfer ───
    transfer_conv = ConversationHandler(
        entry_points=[
            CommandHandler("transfer", handle_transfer),
            MessageHandler(filters.Regex("(?i).*(transfer).*"), handle_transfer),
            CallbackQueryHandler(handle_transfer, pattern="^menu_transfer$")
        ],
        per_message=False,
        states={
            TRANSFER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_id)],
            TRANSFER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_amount)],
            TRANSFER_CONFIRM: [CallbackQueryHandler(transfer_confirm, pattern="^tf_")],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^Cancel$"), cancel)],
    )
    app.add_handler(transfer_conv, group=5)

    # ─── ConversationHandler: Convert Bonus ───
    bonus_conv = ConversationHandler(
        entry_points=[
            CommandHandler("bonus", handle_convert_bonus),
            MessageHandler(filters.Regex("(?i).*(bonus).*"), handle_convert_bonus),
            CallbackQueryHandler(handle_convert_bonus, pattern="^menu_bonus$")
        ],
        per_message=False,
        states={
            BONUS_CONFIRM: [CallbackQueryHandler(bonus_confirm, pattern="^bonus_")],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^Cancel$"), cancel)],
    )
    app.add_handler(bonus_conv, group=6)

    # ─── New Inline Menu Callbacks ───
    app.add_handler(CallbackQueryHandler(handle_balance, pattern="^menu_balance$"))
    app.add_handler(CallbackQueryHandler(handle_invite, pattern="^menu_invite$"))
    app.add_handler(CallbackQueryHandler(handle_instruction, pattern="^menu_instruction$"))
    app.add_handler(CallbackQueryHandler(handle_support, pattern="^menu_support$"))
    app.add_handler(CallbackQueryHandler(handle_menu_back, pattern="^menu_back$"))

    # ─── Admin approve/reject callbacks (fallback when ADMIN_BOT_TOKEN not set) ───
    app.add_handler(CallbackQueryHandler(admin_approve_deposit, pattern="^approve_(?!withdraw_)"))
    app.add_handler(CallbackQueryHandler(admin_reject_deposit, pattern="^reject_(?!withdraw_)"))
    app.add_handler(CallbackQueryHandler(admin_approve_withdraw, pattern="^approve_withdraw_"))
    app.add_handler(CallbackQueryHandler(admin_reject_withdraw, pattern="^reject_withdraw_"))

    logger.info("🎯 Kelem Bingo Bot starting...")

    async def _handle_error(update, context):
        from telegram.error import Conflict
        if isinstance(context.error, Conflict):
            return
        logger.error(f"Unhandled exception: {context.error}", exc_info=context.error)

    app.add_error_handler(_handle_error)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
