"""Best-effort cross-process lock to serialize the event critical section.

Daemon-free. The lock guards record -> resolve -> set light -> cache so two
concurrent hook processes cannot interleave and leave the device showing a
lower-priority state. It is bounded: if the lock cannot be taken within the
timeout it gives up and proceeds unlocked, because never blocking the agent's
hook outranks perfect serialization under rare heavy contention.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

try:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)

except ImportError:  # Windows
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = 2.0, poll: float = 0.02):
    """Acquire an exclusive lock on path for the duration of the context.

    Yields True if the lock was acquired, False if it timed out (the caller still
    runs, unlocked). Either way the hook proceeds; it never blocks indefinitely.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    locked = False
    try:
        # Ensure at least one byte exists so msvcrt.locking has a region to lock.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            with contextlib.suppress(OSError):
                handle.write("\0")
                handle.flush()
        handle.seek(0)
        deadline = time.time() + timeout
        while True:
            if _try_lock(handle.fileno()):
                locked = True
                break
            if time.time() >= deadline:
                break  # give up; proceed unlocked rather than block the hook
            time.sleep(poll)
        yield locked
    finally:
        if locked:
            with contextlib.suppress(OSError):
                handle.seek(0)
            _unlock(handle.fileno())
        handle.close()
