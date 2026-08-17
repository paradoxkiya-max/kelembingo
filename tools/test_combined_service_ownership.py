import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

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

print("PASS: GatewayClient workers skip DB initialization and combined service has one polling owner")
