import os
import logging
import uvicorn
from api.admin_api import socket_app as app

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("🚀 Starting Kelem Bingo Gateway Service (API + Socket.IO + Embedded Engine)...")
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
