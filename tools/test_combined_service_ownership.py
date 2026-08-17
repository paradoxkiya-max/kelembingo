import fcntl
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# GatewayClient workers must be able to import the compatibility adapter without
# opening a Supabase session or running create_all in every bot process.
env = os.environ.copy()
env.update(
    {
        "DATABASE_URL": "postgresql://example.invalid/db",
        "COMBINED_SERVICE": "true",
        "USE_GATEWAY": "true",
        "RENDER_API_ONLY": "false",
    }
)
probe = (
    "import firestore_db; "
    "print(firestore_db._IS_GATEWAY_CLIENT_WORKER, "
    "firestore_db.engine.pool.size(), "
    "firestore_db.engine.pool._max_overflow)"
)
result = subprocess.run(
    [sys.executable, "-c", probe],
    cwd=ROOT,
    env=env,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
assert "True 3 0" in result.stdout, result.stdout

run_all = (ROOT / "run_all.py").read_text(encoding="utf-8")
assert "pg_try_advisory_lock" in run_all
assert "_POLLING_LOCK_KEY" in run_all
assert "_release_polling_lock()" in run_all

# A duplicate worker in the same container must refuse the token lock.
os.environ["TEST_POLL_TOKEN"] = "test-token-for-lock"
import run_bots

lock_path = run_bots._worker_lock_path("TEST_POLL_TOKEN")
lock_holder = open(lock_path, "w")
fcntl.flock(lock_holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
ran = []
run_bots._run_owned_worker(lambda: ran.append(True), "TEST_POLL_TOKEN")
assert not ran
fcntl.flock(lock_holder.fileno(), fcntl.LOCK_UN)
lock_holder.close()
try:
    os.remove(lock_path)
except FileNotFoundError:
    pass

print("PASS: GatewayClient workers skip DB initialization and duplicate local polling is refused")
