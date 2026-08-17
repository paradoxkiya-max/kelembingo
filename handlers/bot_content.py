"""
Bot Content CMS — Dynamic message management
Fetches messages from Firestore 'bot_content' collection with in-memory cache.
Falls back to hardcoded defaults if Firestore is empty.
"""

import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_cache = {}  # key -> (text, expiry)
_cache_ttl = 60  # seconds

# ═══════════════════════════════════════════════════════════════════
# Default messages — hardcoded fallbacks
# ═══════════════════════════════════════════════════════════════════
DEFAULTS = {
    # ── Welcome ──
    "welcome_registered": "👋 Welcome back, {name}!\n\n💰 Main Wallet: *{balance} ETB*\n🎮 Play Wallet: *{play_wallet} ETB*\n\nTap Play to start the game!",
    "welcome_new": "👋 Welcome to Kelem Bingo! Choose an Option below.",
    "welcome_new_amharic": "🎮 ጨዋታውን ለመጀመር ከታች ያለውን Play የሚለውን ይጫኑ::\n(Click Play below to start the game)",
    "welcome_banner_caption": "👋 Welcome to Kelem Bingo! Choose an Option below.",

    # ── Play ──
    "play_wallet_info": "💰 Your Play Wallet: *{play_wallet} ETB*\n\n🎯 Stake: *10 ETB* per cartela (max 2)\n🏆 Derash: *(Cartelas × Stake × 0.75) / Winners*\n\nTap below to open the game:",
    "play_need_start": "Please /start first.",

    # ── Register ──
    "register_already": "✅ You are already registered!\n\nName: {name}\nPhone: {phone}",
    "register_ask_contact": "📱 Tap the button below to share your contact:",
    "register_complete": "✅ Registration complete!\n\nName: {name}\nPhone: {phone}",

    # ── Balance ──
    "balance_info": "💰 *Account Info*\n\n👤 Name: {name}\n💳 Main wallet: {balance} ETB\n🎮 Play wallet: {play_wallet} ETB\n🪙 Bonus: {bonus} coins",

    # ── Deposit ──
    "deposit_too_many": "⚠️ You have too many pending deposits.\nWait for them to be processed.",
    "deposit_ask_name": "💰 Please enter your TeleBirr name\n(The name registered on your TeleBirr account):",
    "deposit_ask_amount": "💰 Enter deposit amount (ETB):",
    "deposit_send_to": "📱 Send {amount} ETB to this TeleBirr number:\n\n📞 *{phone}*\n\nAfter sending, enter the Transaction Number from your receipt:",
    "deposit_phone": "0911000000",
    "deposit_min_amount": "⚠️ Minimum deposit is 10 ETB. Enter again:",
    "deposit_invalid_number": "❌ Enter a valid number:",
    "deposit_send_to": "📱 Send {amount} ETB to this TeleBirr number:\n\n📞 *{phone}*\n\nAfter sending, enter the Transaction Number from your receipt:",
    "deposit_admin_offline": "⚠️ Admin is offline. Please try again later.",
    "withdraw_admin_offline": "⚠️ Admin is offline. Withdrawals are temporarily unavailable.",
    "deposit_submitted": "✅ Deposit request submitted!\n\n💵 Amount: {amount} ETB\n👤 Name: {telebirr_name}\n🔢 Transaction: {transaction_id}\n🆔 `{deposit_id}`\n\nAdmin will review and approve shortly.",
    "deposit_approved": "✅ Deposit approved!\n💰 {amount} ETB has been added to your wallet.",
    "deposit_rejected": "❌ Deposit rejected.\nPlease contact support if you need help.",
    "deposit_duplicate_txn": "❌ This transaction number was already submitted.",

    # ── Withdraw ──
    "withdraw_min_not_met": "❌ Minimum withdrawal is {min_withdraw} ETB.\nYour balance: {balance} ETB",
    "withdraw_deposit_required": "❌ You must deposit at least {min_deposit} ETB before you can make your first withdrawal.\n\nYour total deposits: {current_deposit} ETB",
    "withdraw_ask_amount": "🎰 *Withdraw*\n\nYour balance: *{balance} ETB*\nMinimum: {min_withdraw} ETB\n\nEnter amount:",
    "withdraw_invalid_range": "❌ Enter amount between {min_withdraw} and {balance} ETB.",
    "withdraw_invalid_number": "❌ Enter a valid number.",
    "withdraw_ask_name": "💰 Please enter your TeleBirr name\n(The name registered on your TeleBirr account):",
    "withdraw_submitted": "✅ Withdrawal request submitted!\n\nAmount: {amount} ETB\nPhone: {phone}\nID: `{withdrawal_id}`\n\nAdmin will process it shortly.",
    "withdraw_approved": "✅ Withdrawal approved!\n💰 {amount} ETB will be sent to your TeleBirr.",
    "withdraw_rejected": "❌ Withdrawal rejected.\n💰 {amount} ETB has been refunded to your balance.",
    "withdraw_no_phone": "❌ Please register with your phone number first.\nUse /register to complete registration.",
    "withdraw_above_max": "❌ Maximum withdrawal is {max} ETB per request.",
    "withdraw_account_new": "❌ Your account is too new.\nPlease wait 24 hours after registration before withdrawing.",
    "withdraw_pending_exists": "❌ You already have a pending withdrawal.\nWait for it to be processed before requesting another.",
    "withdraw_daily_limit": "❌ Daily withdrawal limit reached.\nYou can make up to {limit} withdrawals per day. Try again tomorrow.",
    "withdraw_cooldown": "⏳ Please wait {minutes} minutes before making another withdrawal.\n(Cooldown: {hours} hours between requests)",

    # ── Transfer ──
    "transfer_no_balance": "❌ No balance to transfer.\nYour balance: {balance} ETB",
    "transfer_ask_id": "🎁 Transfer\nYour balance: {balance} ETB\n\nEnter recipient's Telegram User ID:",
    "transfer_invalid_id": "❌ Enter a valid numeric User ID.",
    "transfer_self": "❌ You cannot transfer to yourself.",
    "transfer_not_found": "❌ User not found. Check the ID and try again.",
    "transfer_ask_amount": "👤 Recipient: {name}\n💰 Enter amount to send (ETB):",
    "transfer_invalid_amount": "❌ Enter a valid number.",
    "transfer_amount_range": "❌ Enter amount between 1 and {balance} ETB.",
    "transfer_confirm": "📤 Send {amount} ETB to {name}?",
    "transfer_cancelled": "Transfer cancelled.",
    "transfer_sent": "✅ Sent {amount} ETB to {name} successfully!",
    "transfer_failed": "❌ Transfer failed. Check your balance and try again.",

    # ── Bonus ──
    "bonus_no_coins": "❌ No bonus coins to convert.",
    "bonus_convert_info": "🔄 Convert Bonus\n\nYou have: {coins} coins\nRate: {rate} coins = 1 ETB\nYou will receive: {etb} ETB in Play Wallet",
    "bonus_cancelled": "Cancelled.",
    "bonus_converted": "✅ Converted! +{etb} ETB added to your Play Wallet.",
    "bonus_convert_failed": "❌ Conversion failed. No bonus available.",

    # ── Invite ──
    "invite_link": "🔗 *Invite Friends*\n\nShare your personal link and invite your friends to play Kelem Bingo:\n\n`{link}`\n\n👥 Friends invited: *{count}*\n\nTap *Share invite link* below, or copy the link and send it to your friends!",
    "referral_joined": "🎉 *New Friend Joined!*\n\n{name} just joined Kelem Bingo using your invite link.\n\nKeep inviting friends to grow the game!",

    # ── Support ──
    "support_info": "🆘 Need help?\n\n👇 For any questions or feedback 👇\n\n👤 @{support_username}",

    # ── Leaderboard ──
    "leaderboard_no_games": "🏆 No games played yet. Be the first!",
    "leaderboard_title": "🏆 *Top Players*\n",

    # ── History ──
    "history_no_games": "No game history yet. Play a game first!",
    "history_title": "📋 *Your Recent Games*\n",

    # ── Stats ──
    "stats_title": "📊 *Your Stats*\n\n🎮 Games Played: {total}\n🏆 Wins: {wins}\n❌ Losses: {losses}\n📈 Win Rate: {win_rate}\n\n💳 Main Wallet: {balance} ETB\n🎮 Play Wallet: {play_wallet} ETB\n🪙 Bonus Coins: {bonus}",

    # ── Admin Notifications ──
    "admin_deposit_notification": "💵 *New Deposit Request*\n\n👤 *User:* {first_name} (@{username})\n📱 *TeleBirr Name:* {telebirr_name}\n💵 *Amount:* {amount} ETB\n🔢 *Transaction:* {transaction_id}\n\n🆔 `{deposit_id}`\n🕐 {timestamp}",
    "admin_withdrawal_notification": "🎰 *New Withdrawal Request*\n\n👤 {first_name} (@{username})\n💰 TeleBirr Name: {telebirr_name}\n💵 Amount: {amount} ETB\n📱 Phone: {phone}\n🆔 {withdrawal_id}\n🕐 {timestamp}",

    # ── Cancel ──
    "cancel": "Cancelled.",

    # ── Instruction ──
    "instruction": "📖 *How to Play Kelem Bingo*\n\n1️⃣ Tap *Play 🎮* and choose your stake (10 or 20 ETB)\n2️⃣ Pick up to *2 cartelas* during the 35-second selection window\n3️⃣ When the round starts, a new number is called every *5 seconds*\n4️⃣ Mark called numbers on your card — the center is a *free space*\n5️⃣ Complete a full *row, column, or diagonal*, then tap *BINGO* to claim the win!\n\n🏆 *Derash (Prize):* the winner takes *75%* of the total stake pool\n👥 The more players in a round, the bigger the Derash\n\n💰 *Wallets*\n• *Main Wallet* — deposit & withdraw via TeleBirr\n• *Play Wallet* — move funds here to join rounds\n\n🔗 *Invite:* share your link and invite friends to play\n📤 *Transfer:* send funds to another user by ID\n🔄 *Convert Bonus:* turn bonus coins into Play Wallet balance\n\nNeed help? Type /support anytime.",

    # ── Admin Confirmations ──
    "admin_deposit_not_found": "❌ Deposit not found.",
    "admin_already_processed": "Already {status}.",
    "admin_deposit_approved": "✅ Deposit approved\nUser: {first_name} | {amount} ETB",
    "admin_deposit_rejected": "❌ Deposit rejected\nUser: {first_name}",
    "admin_withdrawal_not_found": "❌ Withdrawal not found.",
    "admin_withdrawal_approved": "✅ Withdrawal approved\nUser: {first_name} | {amount} ETB",
    "admin_withdrawal_rejected": "❌ Withdrawal rejected\nUser: {first_name} | {amount} ETB",
    "admin_error": "❌ Error: {error}",
}


def get_bot_text(key: str, db=None, **kwargs) -> str:
    """
    Get a bot message by key. Uses Firestore cache with TTL.
    Falls back to hardcoded defaults. Supports {variable} interpolation.
    """
    global _cache

    # Check cache
    if key in _cache:
        text, expiry = _cache[key]
        if time.time() < expiry:
            return _format(text, **kwargs)

    # Try Firestore
    if db:
        try:
            doc = db.collection('bot_content').document(key).get()
            if doc.exists:
                data = doc.to_dict()
                text = data.get('content', '')
                if text:
                    _cache[key] = (text, time.time() + _cache_ttl)
                    return _format(text, **kwargs)
        except Exception as e:
            logger.warning(f"Failed to fetch bot_content/{key}: {e}")

    # Fall back to default
    text = DEFAULTS.get(key, f"[Missing: {key}]")
    _cache[key] = (text, time.time() + _cache_ttl)
    return _format(text, **kwargs)


def _format(text: str, **kwargs) -> str:
    """Safe string formatting — only replaces known {variables}."""
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


def invalidate_cache(key: str = None):
    """Invalidate cache for a specific key or all keys."""
    global _cache
    if key:
        _cache.pop(key, None)
    else:
        _cache = {}


def get_all_defaults():
    """Return all default messages grouped by category."""
    categories = {}
    for key, value in DEFAULTS.items():
        cat = key.split('_')[0]
        if cat not in categories:
            categories[cat] = {}
        categories[cat][key] = value
    return categories


# ═══════════════════════════════════════════════════════════════════
# Config value defaults (matching dashboard Config tab)
# ═══════════════════════════════════════════════════════════════════
_CONFIG_DEFAULTS = {
    'cfg_min_withdraw': 50,
    'cfg_max_withdraw': 50000,
    'cfg_min_initial_deposit': 50,
    'cfg_max_withdraw_per_day': 3,
    'cfg_withdraw_cooldown_hours': 4,
    'cfg_referral_bonus': 10,
    'cfg_bonus_to_etb_rate': 10,
    'cfg_support_username': 'kelemsupportbot',
}


def get_config_value(key: str, db=None, as_type=int):
    """
    Get a system config value from Firestore (cfg_* keys).

    Always reads live from the database (no caching). Config values such as the
    minimum withdrawal are edited by admins from the dashboard and must take
    effect immediately — the bot and API run in separate processes, so a cached
    value in one process would not be invalidated when the admin saves a change.
    These values are only read on user actions (withdraw/deposit/invite), never
    in a hot loop, so reading live has negligible cost.

    as_type: int, float, or str — used to cast the stored string value.
    """
    # Try Firestore (live, uncached)
    if db:
        try:
            doc = db.collection('bot_content').document(key).get()
            if doc.exists:
                text = doc.to_dict().get('content', '')
                if text != '' and text is not None:
                    try:
                        return as_type(text)
                    except (ValueError, TypeError):
                        return _CONFIG_DEFAULTS.get(key, text)
        except Exception as e:
            logger.warning(f"Failed to fetch config/{key}: {e}")

    # Fall back to default
    return _CONFIG_DEFAULTS.get(key)
