import os
import subprocess
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
probe = "import firestore_db; print(firestore_db.DATABASE_URL)"

def run(env):
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
    )
    return result

base = os.environ.copy()
no_db_gateway = dict(base)
no_db_gateway.pop("DATABASE_URL", None)
no_db_gateway["RENDER_API_ONLY"] = "true"
failed = run(no_db_gateway)
assert failed.returncode != 0
assert "DATABASE_URL must be a PostgreSQL" in failed.stderr

no_db_combined = dict(base)
no_db_combined.pop("DATABASE_URL", None)
no_db_combined["COMBINED_SERVICE"] = "true"
combined_failed = run(no_db_combined)
assert combined_failed.returncode != 0
assert "DATABASE_URL must be a PostgreSQL/Supabase" in combined_failed.stderr

local = dict(base)
local.pop("DATABASE_URL", None)
local.pop("RENDER_API_ONLY", None)
local_ok = run(local)
assert local_ok.returncode == 0, local_ok.stderr
assert local_ok.stdout.strip().startswith("sqlite:///")

postgres = dict(base)
postgres["RENDER_API_ONLY"] = "true"
postgres["DATABASE_URL"] = "postgresql://example.invalid/db"
postgres_ok = run(postgres)
# Connection is not attempted during import; this validates URL acceptance only.
assert postgres_ok.returncode == 0, postgres_ok.stderr
assert postgres_ok.stdout.strip() == "postgresql://example.invalid/db"

print("database configuration fail-closed regression check: PASS")
