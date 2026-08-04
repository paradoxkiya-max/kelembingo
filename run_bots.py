import os
import logging
import multiprocessing
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_game_bot():
    try:
        from bot import main
        main()
    except Exception as e:
        logger.error(f"Game bot error: {e}", exc_info=True)


def run_admin_bot():
    try:
        from admin_bot import main
        main()
    except Exception as e:
        logger.error(f"Admin bot error: {e}", exc_info=True)


def run_support_bot():
    try:
        from support_bot import main
        main()
    except Exception as e:
        logger.error(f"Support bot error: {e}", exc_info=True)


def run_admin_support_bot():
    try:
        from admin_support_bot import main
        main()
    except Exception as e:
        logger.error(f"Admin support bot error: {e}", exc_info=True)


def run_admin_talk_bot():
    try:
        from admin_talk_bot import main
        main()
    except Exception as e:
        logger.error(f"Admin talk bot error: {e}", exc_info=True)


def run_api():
    try:
        import uvicorn
        from api.admin_api import socket_app as app
        port = int(os.environ.get("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port)
    except Exception as e:
        logger.error(f"API error: {e}", exc_info=True)


def run_backup_scheduler():
    """Periodically snapshot the DB to the backup bot so data survives deploys."""
    import time
    try:
        import backup_common as bc
        import firestore_db
    except Exception as e:
        logger.error(f"Backup scheduler import error: {e}", exc_info=True)
        return

    interval = max(1, int(os.getenv("BACKUP_INTERVAL_MINUTES", "1"))) * 60
    if not bc.BACKUP_CHAT_ID:
        logger.warning("ADMIN_CHAT_ID not set — automatic backups are disabled.")
        return

    # Small delay to let DB initialize, then create an immediate backup
    time.sleep(5)
    while True:
        try:
            # Keep-Alive ping to keep Gateway awake 24/7 on Render Free Tier
            gw_url = os.getenv("GATEWAY_URL")
            if gw_url:
                try:
                    import requests
                    requests.get(f"{gw_url.rstrip('/')}/api/health", timeout=5)
                except Exception:
                    pass

            if firestore_db.count_documents() > 0:
                meta = bc.create_backup()
                logger.info(f"Auto-backup: {meta.get('documents')} records saved.")
            else:
                logger.info("Auto-backup skipped: no documents to back up.")
        except Exception as e:
            logger.warning(f"Auto-backup failed (will retry next cycle): {e}")
        time.sleep(interval)


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


def run_health_check_server():
    from http.server import HTTPServer, BaseHTTPRequestHandler
    port = int(os.environ.get("PORT", 8000))
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "bots"}')
        def log_message(self, format, *args):
            return
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()


if __name__ == "__main__":
    try:
        multiprocessing.set_start_method("spawn")
    except RuntimeError:
        pass

    USE_GATEWAY = os.getenv("USE_GATEWAY", "false").lower() == "true"

    logger.info("🚀 Starting Kelem Bingo Bot Service...")

    # In gateway mode the GATEWAY service owns the live DB and runs the backup
    # scheduler + startup restore. Here the local DB is vestigial, so skip both.
    if not USE_GATEWAY:
        auto_restore_on_startup()

    game_proc = multiprocessing.Process(target=run_game_bot, name="GameBot")
    admin_proc = multiprocessing.Process(target=run_admin_bot, name="AdminBot")
    support_proc = multiprocessing.Process(target=run_support_bot, name="SupportBot")
    admin_support_proc = multiprocessing.Process(target=run_admin_support_bot, name="AdminSupportBot")
    admin_talk_proc = multiprocessing.Process(target=run_admin_talk_bot, name="AdminTalkBot")
    backup_proc = None
    if not USE_GATEWAY:
        backup_proc = multiprocessing.Process(target=run_backup_scheduler, name="BackupScheduler")

    game_proc.start()
    logger.info("✅ Game Bot started")
    admin_proc.start()
    logger.info("✅ Admin Bot started")
    support_proc.start()
    logger.info("✅ Support Bot started")
    admin_support_proc.start()
    logger.info("✅ Admin Support Bot started")
    admin_talk_proc.start()
    logger.info("✅ Admin Talk Bot started")
    if backup_proc:
        backup_proc.start()
    if USE_GATEWAY:
        logger.info("🌐 Dedicated Bot Service running with Gateway bridge (port %s)...", os.environ.get("PORT", "8000"))
        try:
            run_health_check_server()
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down...")
        finally:
            for proc in (game_proc, admin_proc, support_proc, admin_support_proc, admin_talk_proc):
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=5)
    else:
        logger.info("✅ Starting API Server and Game Loop...")
        try:
            run_api()
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down...")
        finally:
            procs = [game_proc, admin_proc, support_proc, admin_support_proc, admin_talk_proc]
            if backup_proc:
                procs.append(backup_proc)
            for proc in procs:
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=5)
