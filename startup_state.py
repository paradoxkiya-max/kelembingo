"""Process-wide database readiness state for safe gateway startup."""

from __future__ import annotations

import threading
from typing import Optional


_database_ready = threading.Event()
_state_lock = threading.Lock()
_database_error: Optional[str] = "database initialization has not completed"


def mark_database_ready() -> None:
    """Mark the database and startup restore as ready for application traffic."""
    global _database_error
    with _state_lock:
        _database_error = None
        _database_ready.set()


def mark_database_failed(error: BaseException | str) -> None:
    """Keep the service in read-only/unready mode after startup failure."""
    global _database_error
    with _state_lock:
        _database_error = str(error)
        _database_ready.clear()


def is_database_ready() -> bool:
    return _database_ready.is_set()


def database_error() -> Optional[str]:
    with _state_lock:
        return _database_error


def wait_for_database(timeout: Optional[float] = None) -> bool:
    """Blocking wait for worker threads; never called directly on the event loop."""
    return _database_ready.wait(timeout)
