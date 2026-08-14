import sys
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir()) / 'kelembingo-public-stats.sqlite3'}"

from api.admin_api import _public_stats_sync

result = _public_stats_sync()
assert set(result) == {'active_cartelas', 'games_played', 'winners_today'}, result
assert all(isinstance(value, int) and value >= 0 for value in result.values()), result
print('public stats helper check: PASS', result)
