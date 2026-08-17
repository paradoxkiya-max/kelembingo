from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
render = (ROOT / "render.yaml").read_text(encoding="utf-8")
dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
backup = (ROOT / "backup_common.py").read_text(encoding="utf-8")

assert "dockerfilePath: ./Dockerfile.bot" in render
assert '- key: RENDER_API_ONLY\n        value: "false"' in render
assert 'CMD ["python", "run_gateway.py"]' in dockerfile
assert 'if not BACKUP_BOT_TOKEN:' in backup
print("PASS: Render bot mode and backup-token startup contract")
