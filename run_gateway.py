import os
import logging
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

    # Backups are manual-only: the admin dashboard triggers them via
    # POST /api/admin/backup/create when the operator asks to save.

    from api.admin_api import socket_app as app
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
