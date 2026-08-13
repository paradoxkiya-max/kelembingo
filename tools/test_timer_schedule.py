from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.round_engine import _grid_next_number_at
from settlement import _next_number_at

now = datetime.now(tz=timezone.utc)

# A start time one interval ago should yield a full interval from now, not an
# already-expired anchored timestamp.
late_start = now - timedelta(seconds=5)
for helper in (_grid_next_number_at, _next_number_at):
    deadline = helper(late_start, 1)
    remaining = (deadline - datetime.now(tz=timezone.utc)).total_seconds()
    assert remaining >= 4.5, (helper.__name__, remaining)

# A future anchored schedule should be preserved rather than shifted.
future_start = now + timedelta(seconds=20)
for helper in (_grid_next_number_at, _next_number_at):
    deadline = helper(future_start, 1)
    expected = future_start + timedelta(seconds=10)
    assert abs((deadline - expected).total_seconds()) < 0.1, (helper.__name__, deadline, expected)

print("five-second timer schedule regression check: PASS")
