"""
JSON backup / restore for Kelem Bingo.

The platform runs on Render's free plan, whose filesystem is wiped on every
deploy. To survive deploys we keep a single JSON snapshot of the whole
document store inside a Telegram bot (@kelembackupbot):

  • create_backup()  — export the DB to JSON, send it to the admin's chat with
    the backup bot, and PIN that message. Pinning makes the latest snapshot
    findable after a restart (a bot can read a chat's pinned message), so we
    never need any local persistence to locate it.
  • restore_latest() — read the pinned backup, download the JSON and seed it
    back into the DB by id.

Both an automatic loop (see run_bots.py) and the admin dashboard use these.

The backup chat is the admin's private chat with the backup bot; its chat id
equals the admin's Telegram user id (ADMIN_CHAT_ID), so no extra config is
needed — the admin only has to press Start on @kelembackupbot once.
"""

import io
import os
import json
import logging
from datetime import datetime, timezone

import httpx

import firestore_db

logger = logging.getLogger(__name__)

# ── Backup bot token (from env — never hardcode secrets) ──
# Backup bot -> t.me/kelembackupbot
BACKUP_BOT_TOKEN = os.getenv("BACKUP_BOT_TOKEN", "")
if not BACKUP_BOT_TOKEN:
    logger.warning(
        "BACKUP_BOT_TOKEN is not set — backups and startup auto-restore are disabled."
    )

# The backup is sent to the admin's chat with the backup bot.
# For reliable pinning, create a Telegram GROUP, add @kelembackupbot as admin,
# get the group's chat ID (negative number), and set BACKUP_CHAT_ID env var.
# Falls back to ADMIN_CHAT_ID (private chat — pinning may not work).
BACKUP_CHAT_ID = int(os.getenv("BACKUP_CHAT_ID") or os.getenv("ADMIN_CHAT_ID", "0") or "0")

_API = f"https://api.telegram.org/bot{BACKUP_BOT_TOKEN}"
_FILE_API = f"https://api.telegram.org/file/bot{BACKUP_BOT_TOKEN}"

_CAPTION_PREFIX = "Kelem Bingo backup"
_HTTP_TIMEOUT = 60.0


class BackupError(Exception):
    """Raised when a backup/restore operation cannot complete."""


def _require_chat():
    if not BACKUP_CHAT_ID:
        raise BackupError(
            "ADMIN_CHAT_ID is not set, so there is no chat to store backups in. "
            "Set ADMIN_CHAT_ID and press Start on @kelembackupbot."
        )


def _call(method: str, *, data=None, files=None) -> dict:
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        r = client.post(f"{_API}/{method}", data=data, files=files)
    payload = r.json()
    if not payload.get("ok"):
        raise BackupError(f"Telegram {method} failed: {payload.get('description', r.text)}")
    return payload["result"]


# ═══════════════════════════════════════════════════════════════════
# Backup
# ═══════════════════════════════════════════════════════════════════
def build_snapshot() -> dict:
    """Return the full backup payload (metadata + all documents)."""
    dump = firestore_db.export_all()
    documents = sum(len(docs) for docs in dump.values())
    return {
        "_meta": {
            "app": "kelembingo",
            "version": 1,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "documents": documents,
            "collections": {c: len(d) for c, d in dump.items()},
        },
        "data": dump,
    }


def create_backup() -> dict:
    """
    Export the DB to JSON, upload it to the backup bot and pin it.

    Returns the snapshot's `_meta` dict on success.
    """
    _require_chat()
    snapshot = build_snapshot()
    meta = snapshot["_meta"]

    raw = json.dumps(snapshot, ensure_ascii=False, indent=0).encode("utf-8")
    ts = meta["created_at"].replace(":", "").replace("-", "")[:15]
    filename = f"kelembingo_backup_{ts}.json"
    caption = f"{_CAPTION_PREFIX}\n{meta['created_at']}\n{meta['documents']} records"

    result = _call(
        "sendDocument",
        data={"chat_id": BACKUP_CHAT_ID, "caption": caption},
        files={"document": (filename, io.BytesIO(raw), "application/json")},
    )

    # Pin the newest backup so restore can always find it; clear older pins first.
    message_id = result.get("message_id")
    try:
        _call("unpinAllChatMessages", data={"chat_id": BACKUP_CHAT_ID})
    except BackupError:
        pass  # No previous pin or no permission — not critical
    try:
        _call("pinChatMessage", data={
            "chat_id": BACKUP_CHAT_ID,
            "message_id": message_id,
            "disable_notification": True,
        })
    except BackupError as e:
        logger.warning(f"Backup uploaded but could not be pinned: {e}")

    meta["pinned"] = True
    meta["message_id"] = message_id
    meta["file_size"] = len(raw)
    logger.info(f"Backup created: {meta['documents']} records, {len(raw)} bytes")
    return meta


# ═══════════════════════════════════════════════════════════════════
# Status / restore
# ═══════════════════════════════════════════════════════════════════
def _pinned_document():
    """Return the pinned message's document dict, or None."""
    _require_chat()
    chat = _call("getChat", data={"chat_id": BACKUP_CHAT_ID})
    logger.info(f"Backup chat id={chat.get('id')} type={chat.get('type')} pinned={'yes' if chat.get('pinned_message') else 'no'}")
    pinned = chat.get("pinned_message")
    if not pinned:
        return None, None
    return pinned.get("document"), pinned.get("caption")


def get_status() -> dict:
    """
    Lightweight status for the dashboard — reads the pinned message only
    (no file download). Returns {'exists', 'created_at', 'documents', 'file_size'}.
    """
    try:
        doc, caption = _pinned_document()
    except BackupError as e:
        return {"exists": False, "error": str(e)}
    if not doc:
        return {"exists": False}
    created_at, documents = None, None
    if caption:
        lines = caption.splitlines()
        if len(lines) >= 2:
            created_at = lines[1].strip()
        if len(lines) >= 3:
            documents = lines[2].replace("records", "").strip()
    return {
        "exists": True,
        "created_at": created_at,
        "documents": documents,
        "file_size": doc.get("file_size"),
        "file_name": doc.get("file_name"),
    }


def fetch_latest_snapshot() -> dict | None:
    """Download and parse the pinned backup JSON. Returns the snapshot or None."""
    doc, _ = _pinned_document()
    if not doc:
        return None
    file_id = doc.get("file_id")
    file_info = _call("getFile", data={"file_id": file_id})
    file_path = file_info.get("file_path")
    if not file_path:
        raise BackupError("Backup file has no downloadable path.")
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        r = client.get(f"{_FILE_API}/{file_path}")
        r.raise_for_status()
        content = r.content
    try:
        return json.loads(content)
    except Exception as e:
        raise BackupError(f"Backup file is not valid JSON: {e}")


def restore_latest(overwrite: bool = False) -> dict:
    """
    Restore the DB from the pinned backup.

    overwrite=False (default): only seed missing documents (safe — never
    clobbers live data). overwrite=True: replace existing documents too.

    Returns {'restored': bool, 'inserted', 'skipped', 'overwritten', 'documents'}.
    """
    snapshot = fetch_latest_snapshot()
    if not snapshot:
        return {"restored": False, "reason": "no_backup"}
    data = snapshot.get("data", snapshot)
    stats = firestore_db.import_all(data, overwrite=overwrite)
    stats["restored"] = True
    stats["documents"] = sum(len(d) for d in data.values() if isinstance(d, dict))
    logger.info(f"Restore complete: {stats}")
    return stats


def wipe_pinned_backup() -> dict:
    """Unpin the current backup message from the backup bot chat."""
    _require_chat()
    try:
        _call("unpinChatMessage", data={"chat_id": BACKUP_CHAT_ID})
        return {"ok": True}
    except BackupError as e:
        raise BackupError(f"Failed to wipe pinned backup: {e}")


def restore_if_empty() -> dict:
    """
    Auto-restore used on startup: only restores when the DB has no documents,
    so a fresh (wiped) deploy is re-seeded but a live DB is never touched.
    """
    if firestore_db.count_documents() > 0:
        return {"restored": False, "reason": "db_not_empty"}
    if not BACKUP_CHAT_ID:
        return {"restored": False, "reason": "no_admin_chat"}
    try:
        return restore_latest(overwrite=False)
    except BackupError as e:
        logger.warning(f"Startup auto-restore skipped: {e}")
        return {"restored": False, "reason": str(e)}
