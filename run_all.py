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

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("combined")


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
