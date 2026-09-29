"""One run at a time per results folder: ``<results-root>/.lock``.

The lock is an advisory ``flock`` held for the whole run. The kernel
releases it when the process dies, so a crash never leaves a stale
lock behind, unlike a pid file (DevSpec 4.8). Windows, used only for
unit tests on the development host, falls back to ``msvcrt.locking``.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows development host.
    fcntl = None
    import msvcrt

lock_file = ".lock"
# msvcrt locks a byte range; one byte at offset 0 is enough.
locked_bytes = 1


class RunLock:
    """Exclusive, non-blocking lock on ``<root>/.lock``."""

    def __init__(self, root: Path) -> None:
        """Prepare the lock for results folder ``root``."""
        self.path = root / lock_file
        self.fd: int | None = None

    def acquire(self) -> bool:
        """Take the lock; return False when another run holds it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, locked_bytes)
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def release(self) -> None:
        """Release the lock if this object holds it."""
        if self.fd is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            else:
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, locked_bytes)
        finally:
            os.close(self.fd)
            self.fd = None

    def __enter__(self) -> RunLock:
        """Allow ``with`` after a successful ``acquire``."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Release on leaving the block."""
        self.release()


def is_held(root: Path) -> bool:
    """Return whether a run currently holds the lock of ``root``."""
    if not (root / lock_file).exists():
        return False
    probe = RunLock(root)
    if probe.acquire():
        probe.release()
        return False
    return True
