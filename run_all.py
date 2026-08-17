"""Combined Render entrypoint for the gateway and Telegram workers.

The gateway is the single Supabase/PostgreSQL owner. Bot workers use the
local gateway HTTP endpoint, so one Render service owns the API, database
access, game engine, and Telegram polling without duplicate service owners.
"""

import json
import logging
import multiprocessing
import os
import signal
import time
import urllib.request

import psycopg2

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("combined")

_POLLING_LOCK_KEY = 827364911
_polling_lock_connection = None


def _acquire_polling_lock(timeout: float = 120.0):
    """Hold a PostgreSQL advisory lock for this service's full lifetime.

    Render deployments can overlap briefly, and an old backend service may
    remain online after a new combined service is created. Telegram permits
    only one getUpdates owner per token, so the losing service must never start
    the gateway or any polling worker.
    """
    global _polling_lock_connection
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required before acquiring the combined-service lock")

    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        connection = None
        try:
            connection = psycopg2.connect(database_url, connect_timeout=5)
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (_POLLING_LOCK_KEY,))
                acquired = bool(cursor.fetchone()[0])
            if acquired:
                _polling_lock_connection = connection
                logger.info("🔐 Combined-service ownership lock acquired")
                return
            connection.close()
            logger.warning("⏳ Another combined service owns the polling lock; waiting...")
        except Exception as exc:
            last_error = exc
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            logger.warning("⏳ Could not acquire combined-service ownership lock yet: %s", exc)
        time.sleep(5)

    raise RuntimeError(f"Could not acquire combined-service ownership lock within {timeout:.0f}s: {last_error}")


def _release_polling_lock():
    global _polling_lock_connection
    if _polling_lock_connection is None:
        return
    try:
        with _polling_lock_connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", (_POLLING_LOCK_KEY,))
        _polling_lock_connection.close()
        logger.info("🔓 Combined-service ownership lock released")
    except Exception:
        logger.warning("Could not release combined-service ownership lock cleanly", exc_info=True)
    finally:
        _polling_lock_connection = None


def _gateway_process():
    from run_gateway import main as gateway_main
    gateway_main()


def _health_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and bool(payload.get("ready"))
    except Exception:
        return False


def main():
    try:
        multiprocessing.set_start_method("spawn")
    except RuntimeError:
        pass

    port = int(os.getenv("PORT", "8000"))
    local_gateway_url = f"http://127.0.0.1:{port}"
    os.environ["GATEWAY_URL"] = local_gateway_url
    os.environ["COMBINED_SERVICE"] = "true"

    # The gateway process uses the local PostgreSQL/Supabase adapter. It must
    # not use GatewayClient pointed back at itself.
    os.environ["USE_GATEWAY"] = "false"
    os.environ["RENDER_API_ONLY"] = "true"
    gateway = multiprocessing.Process(target=_gateway_process, name="Gateway")
    gateway.start()
    logger.info("🚀 Gateway process started; waiting for Supabase/PostgreSQL readiness...")

    deadline = time.monotonic() + float(os.getenv("GATEWAY_READY_TIMEOUT", "120"))
    while gateway.is_alive() and time.monotonic() < deadline:
        if _health_ready(local_gateway_url):
            break
        time.sleep(1)
    else:
        logger.error("🛑 Gateway did not become ready before timeout; stopping combined service.")
        if gateway.is_alive():
            gateway.terminate()
            gateway.join(timeout=10)
        raise SystemExit(1)

    # Keep the web port live while an overlapping deployment waits for the
    # previous polling owner to release the Telegram ownership lock.
    _acquire_polling_lock(float(os.getenv("POLLING_LOCK_TIMEOUT", "120")))

    # Bot children use the local gateway HTTP bridge while the gateway owns the
    # actual Supabase/PostgreSQL connection and game engine.
    os.environ["USE_GATEWAY"] = "true"
    os.environ["RENDER_API_ONLY"] = "false"
    from run_bots import _start_configured_workers, _stop_workers

    workers = _start_configured_workers()
    logger.info("✅ Combined service ready: gateway + %d configured bot worker(s)", len(workers))

    def shutdown(signum=None, frame=None):
        logger.info("🛑 Shutting down combined gateway and bot workers...")
        _stop_workers(workers)
        if gateway.is_alive():
            gateway.terminate()
            gateway.join(timeout=10)
        _release_polling_lock()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        while gateway.is_alive():
            if any(not worker.is_alive() for worker in workers):
                logger.warning("A bot worker exited; polling ownership is no longer complete.")
            time.sleep(5)
    finally:
        shutdown()


if __name__ == "__main__":
    main()
