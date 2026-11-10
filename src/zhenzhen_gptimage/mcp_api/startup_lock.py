"""Cross-process lock for serialising backend discovery and startup."""
from __future__ import annotations

import os
from pathlib import Path
import time


class StartupLock:
    """Short-lived lock separate from the backend's data-directory lock.

    The lock file is never unlinked: the OS lock, not file existence or a
    process ID, determines ownership. Keeping it avoids inode replacement races.
    """

    def __init__(self, data_dir: Path):
        self.path = data_dir / 'startup.lock'
        self._file = None

    def acquire(self, timeout: float = 10.0) -> None:
        if self._file is not None:
            raise RuntimeError('startup lock already held')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open('a+b')
        try:
            # Lock a byte range even for an empty file. Initialising the file
            # before taking the lock races with another Windows byte-range
            # owner and can fail with a sharing violation.
            deadline = time.monotonic() + max(timeout, 0)
            while True:
                try:
                    file.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._file = file
                    return
                except (BlockingIOError, PermissionError) as exc:
                    # On Windows msvcrt reports EACCES for an occupied range.
                    if time.monotonic() >= deadline:
                        raise TimeoutError('backend startup lock timed out') from exc
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        except BaseException:
            file.close()
            raise

    def release(self) -> None:
        file, self._file = self._file, None
        if file is None:
            return
        try:
            file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        finally:
            file.close()
