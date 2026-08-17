from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
render = (ROOT / "render.yaml").read_text(encoding="utf-8")
dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
backup = (ROOT / "backup_common.py").read_text(encoding="utf-8")

assert "dockerfilePath: ./Dockerfile" in render
assert 'name: kelembingo' in render
assert 'COMBINED_SERVICE' in render
assert 'DATABASE_URL' in render
assert 'CMD ["python", "run_all.py"]' in dockerfile
assert 'if not BACKUP_BOT_TOKEN:' in backup
run_bots = (ROOT / "run_bots.py").read_text(encoding="utf-8")
assert 'if RENDER_API_ONLY and not USE_GATEWAY:' in run_bots
assert 'USE_GATEWAY takes precedence' in run_bots
run_all = (ROOT / "run_all.py").read_text(encoding="utf-8")
assert 'Gateway process started' in run_all
assert 'COMBINED_SERVICE' in run_all
assert not (ROOT / "Dockerfile.bot").exists()
assert not (ROOT / "Dockerfile.gateway").exists()
print("PASS: combined Render service, Supabase guard, bot mode, and backup contract")
