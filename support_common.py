"""
Shared helpers for the Kelem support bots.

Two bots use this module:
  • support_bot.py        — user-facing support bot (@kelemsupportbot)
  • admin_support_bot.py  — admin-facing support bot (@kelemadminsupportbot)

State is persisted through the existing Firestore SQL emulator (config.db) so the
two bot processes (and the rest of the platform) share the same store.

Collections
-----------
support_users   doc_id = str(user_id)
    userId, chatId, firstName, username, lastText,
    lastMessageAt (iso), quotaDate (YYYY-MM-DD), quotaCount
support_tickets  doc_id = uuid
    userId, chatId, firstName, username, text,
    direction ('user' | 'admin'), createdAt (iso)
"""

import logging
from datetime import datetime, timezone

from config import db

logger = logging.getLogger(__name__)

import os

SUPPORT_BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN", "")
ADMIN_SUPPORT_BOT_TOKEN = os.getenv("ADMIN_SUPPORT_BOT_TOKEN", "")

ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

# Each user may send at most this many support messages per calendar day (UTC).
DAILY_QUESTION_LIMIT = 3


def _today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def register_support_user(user, chat_id):
    """Upsert the user's profile so the admin can later reply to them."""
    db.collection('support_users').document(str(user.id)).set({
        'userId': user.id,
        'chatId': chat_id,
        'firstName': user.first_name or '',
        'username': user.username or '',
        'lastSeenAt': _now_iso(),
    }, merge=True)


def try_consume_quota(user_id):
    """
    Attempt to consume one daily support slot.

    Returns (allowed: bool, remaining: int). When the daily limit is already
    reached, returns (False, 0) and does not consume anything.
    """
    ref = db.collection('support_users').document(str(user_id))
    doc = ref.get()
    data = doc.to_dict() if doc.exists else {}
    today = _today()
    count = data.get('quotaCount', 0) if data.get('quotaDate') == today else 0

    if count >= DAILY_QUESTION_LIMIT:
        return False, 0

    ref.set({'quotaDate': today, 'quotaCount': count + 1}, merge=True)
    return True, DAILY_QUESTION_LIMIT - (count + 1)


def record_message(user, chat_id, text, direction):
    """Persist a support message. direction is 'user' or 'admin'."""
    ref = db.collection('support_tickets').document()
    ref.set({
        'userId': getattr(user, 'id', user),
        'chatId': chat_id,
        'firstName': getattr(user, 'first_name', '') or '',
        'username': getattr(user, 'username', '') or '',
        'text': text,
        'direction': direction,
        'createdAt': _now_iso(),
    })
    if direction == 'user':
        db.collection('support_users').document(str(user.id)).set({
            'lastText': text,
            'lastMessageAt': _now_iso(),
        }, merge=True)
    return ref.id


def get_user_chat_id(user_id):
    """Return the stored chat id for a user (falls back to user_id itself)."""
    doc = db.collection('support_users').document(str(user_id)).get()
    if doc.exists:
        data = doc.to_dict()
        return data.get('chatId') or data.get('userId') or int(user_id)
    return int(user_id)


def get_support_user(user_id):
    doc = db.collection('support_users').document(str(user_id)).get()
    return doc.to_dict() if doc.exists else None


def list_recent_users(limit=20):
    """Most-recently-active support users first."""
    users = [d.to_dict() for d in db.collection('support_users').stream()]
    users = [u for u in users if u.get('lastMessageAt')]
    users.sort(key=lambda u: u.get('lastMessageAt', ''), reverse=True)
    return users[:limit]
