import json
import os
import sys
import tempfile
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
TOKEN = Path(os.environ["BACKUP_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
API = f"https://api.telegram.org/bot{TOKEN}"

chat = requests.post(API + "/getChat", data={"chat_id": "8462274722"}, timeout=30).json()
if not chat.get("ok"):
    raise RuntimeError("Telegram getChat failed")
pinned = chat["result"].get("pinned_message") or {}
document = pinned.get("document") or {}
if not document:
    raise RuntimeError("Pinned backup document not found")
file_info = requests.post(
    API + "/getFile", data={"file_id": document["file_id"]}, timeout=30
).json()
if not file_info.get("ok"):
    raise RuntimeError("Telegram getFile failed")
raw = requests.get(
    f"https://api.telegram.org/file/bot{TOKEN}/{file_info['result']['file_path']}",
    timeout=120,
).content
payload = json.loads(raw)

sqlite_path = Path(tempfile.gettempdir()) / "kelembingo-restore-performance.sqlite3"
try:
    sqlite_path.unlink()
except FileNotFoundError:
    pass
os.environ["DATABASE_URL"] = f"sqlite:///{sqlite_path}"
sys.path.insert(0, str(REPO))
import firestore_db

started = time.monotonic()
stats = firestore_db.import_all(payload["data"], overwrite=False)
elapsed = time.monotonic() - started
count = firestore_db.count_documents()
expected = sum(len(v) for v in payload["data"].values() if isinstance(v, dict))
assert stats["inserted"] == expected, stats
assert count == expected, (count, expected)
print(f"optimized restore: PASS documents={count} elapsed_seconds={elapsed:.2f} stats={stats}")
try:
    sqlite_path.unlink()
except FileNotFoundError:
    pass
