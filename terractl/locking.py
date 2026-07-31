"""Cross-platform system-test lock."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout


@contextmanager
def exclusive_run_lock(path: Path, timeout_seconds: float = 0) -> Iterator[None]:
    lock = FileLock(str(path))
    try:
        with lock.acquire(timeout=timeout_seconds):
            yield
    except Timeout as error:
        raise RuntimeError("another protected test run is active") from error
