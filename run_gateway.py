import os
import logging
import threading
import time
import uvicorn

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


def auto_restore_on_startup():
    """Re-seed the DB from the latest backup when it comes up empty (fresh deploy)."""
    try:
        import backup_common as bc
        result = bc.restore_if_empty()
        if result.get("restored"):
            logger.info(f"♻️ Restored data from backup: {result}")
        else:
            logger.info(f"Startup restore skipped: {result.get('reason')}")
    except Exception as e:
        logger.warning(f"Startup restore error (continuing with empty DB): {e}")


def start_backup_scheduler():
    """Background thread: periodically snapshot the gateway's live DB to the backup bot.

    The backup bot chat holds a pinned JSON snapshot, so data survives Render's
    ephemeral filesystem across deploys. This runs on the GATEWAY (the service
    that owns the live DB) — not on the bots service.
    """
    def _run():
        import backup_common as bc
        import firestore_db
        interval = max(1, int(os.getenv("BACKUP_INTERVAL_MINUTES", "1"))) * 60
        if not bc.BACKUP_BOT_TOKEN or not bc.BACKUP_CHAT_ID:
            logger.warning("Backup scheduler disabled: set BACKUP_BOT_TOKEN and BACKUP_CHAT_ID.")
            return
        time.sleep(5)
        while True:
            try:
                if firestore_db.count_documents() > 0:
                    meta = bc.create_backup()
                    logger.info(f"Auto-backup: {meta.get('documents')} records saved.")
                else:
                    logger.info("Auto-backup skipped: no documents to back up.")
            except Exception as e:
                logger.warning(f"Auto-backup failed (will retry next cycle): {e}")
            time.sleep(interval)

    t = threading.Thread(target=_run, name="BackupScheduler", daemon=True)
    t.start()
    logger.info("🔁 Backup scheduler started")
    return t


if __name__ == "__main__":
    logger.info("🚀 Starting Kelem Bingo Gateway Service (API + Socket.IO + Embedded Engine)...")

    # Re-seed from the latest backup if this deploy came up with an empty DB.
    auto_restore_on_startup()
    try:
        import firestore_db
        fixed_cnt = firestore_db.fix_playwallet()
        if fixed_cnt:
            logger.info(f"🧹 Cleaned {fixed_cnt} user wallet records containing Increment dicts.")
    except Exception as e:
        logger.warning(f"Wallet cleanup error: {e}")

    # Periodic backup of the live (gateway) DB to the backup bot.
    start_backup_scheduler()

    from api.admin_api import socket_app as app
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
