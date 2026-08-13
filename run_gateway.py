import asyncio
import logging
import os

import uvicorn

from startup_state import mark_database_failed, mark_database_ready

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


def auto_restore_on_startup():
    """Re-seed the DB from the latest backup when it comes up empty."""
    import backup_common as bc

    result = bc.restore_if_empty()
    if result.get("restored"):
        logger.info(f"♻️ Restored data from backup: {result}")
    else:
        logger.info(f"Startup restore skipped: {result.get('reason')}")
    return result


def initialize_database() -> None:
    """Initialize, restore, and validate the database off the event loop."""
    try:
        auto_restore_on_startup()
        import firestore_db

        fixed_cnt = firestore_db.fix_playwallet()
        if fixed_cnt:
            logger.info(f"🧹 Cleaned {fixed_cnt} user wallet records containing Increment dicts.")
        mark_database_ready()
        logger.info("✅ Database initialization and startup restore complete; gateway is ready.")
    except Exception as exc:
        mark_database_failed(exc)
        logger.error("❌ Database initialization failed; gateway remains unready.", exc_info=True)


def main():
    logger.info("🚀 Starting Kelem Bingo Gateway Service (API + Socket.IO + Embedded Engine)...")

    # Import the FastAPI app and register a non-blocking startup task. The
    # liveness port must bind even when a fresh PostgreSQL restore is large.
    from api.admin_api import app as fastapi_app, socket_app

    @fastapi_app.on_event("startup")
    async def start_database_initialization():
        asyncio.create_task(asyncio.to_thread(initialize_database))

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(socket_app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
