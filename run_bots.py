import logging
import multiprocessing
import os
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _configured_token(name: str) -> bool:
    """Return True only for a real configured token, not a Blueprint placeholder."""
    value = os.getenv(name, "").strip()
    return bool(value) and not value.lower().startswith(("your_", "placeholder", "replace_"))


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
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "bots"}')

        def log_message(self, format, *args):
            return

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def _worker_specs():
    return [
        ("Game Bot", run_game_bot, "BOT_TOKEN"),
        ("Admin Bot", run_admin_bot, "ADMIN_BOT_TOKEN"),
        ("Support Bot", run_support_bot, "SUPPORT_BOT_TOKEN"),
        ("Admin Support Bot", run_admin_support_bot, "ADMIN_SUPPORT_BOT_TOKEN"),
        ("Admin Talk Bot", run_admin_talk_bot, "ADMIN_TALK_BOT_TOKEN"),
    ]


def _start_configured_workers():
    processes = []
    for label, target, token_name in _worker_specs():
        if not _configured_token(token_name):
            logger.info("⏭️ %s disabled: %s is not configured", label, token_name)
            continue
        process = multiprocessing.Process(target=target, name=label.replace(" ", ""))
        process.start()
        processes.append(process)
        logger.info("✅ %s started", label)
    if not processes:
        logger.error("🛑 No bot tokens are configured; no Telegram polling workers were started.")
    return processes


def _stop_workers(processes):
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


if __name__ == "__main__":
    try:
        multiprocessing.set_start_method("spawn")
    except RuntimeError:
        pass

    USE_GATEWAY = os.getenv("USE_GATEWAY", "false").lower() == "true"
    RENDER_API_ONLY = os.getenv("RENDER_API_ONLY", "false").lower() == "true"

    # USE_GATEWAY=true explicitly identifies the Telegram bot service: it uses
    # the remote gateway DB but must still poll Telegram. Only a service with
    # RENDER_API_ONLY=true and USE_GATEWAY=false delegates to the gateway.
    if RENDER_API_ONLY and not USE_GATEWAY:
        logger.info("🔀 RENDER_API_ONLY=true and USE_GATEWAY=false — running as Gateway API service, not bots.")
        from run_gateway import main as gateway_main
        gateway_main()
        raise SystemExit(0)
    if RENDER_API_ONLY and USE_GATEWAY:
        logger.warning("⚠️ Both RENDER_API_ONLY and USE_GATEWAY are true; USE_GATEWAY takes precedence and bot polling will start.")

    logger.info("🚀 Starting Kelem Bingo Bot Service...")
    processes = _start_configured_workers()

    if USE_GATEWAY:
        logger.info(
            "🌐 Dedicated Bot Service running with Gateway bridge (port %s)...",
            os.environ.get("PORT", "8000"),
        )
        try:
            run_health_check_server()
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down...")
        finally:
            _stop_workers(processes)
    else:
        logger.info("✅ Starting API Server and Game Loop...")
        try:
            run_api()
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down...")
        finally:
            _stop_workers(processes)
