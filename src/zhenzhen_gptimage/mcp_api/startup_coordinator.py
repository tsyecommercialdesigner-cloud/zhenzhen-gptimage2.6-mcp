"""Serialise shared backend discovery without replaying business operations.

Transport-specific probing and protected publication are injected: merely
finding a discovery file is never sufficient to establish compatibility.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
import time
from typing import Callable

from .lifecycle import InstanceLock
from .startup_lock import StartupLock


class Probe(Enum):
    ABSENT = 'absent'
    READY = 'ready'
    INCOMPATIBLE = 'incompatible'


class BackendIncompatible(RuntimeError):
    """An existing backend must not be replaced or silently reused."""


def ensure_backend(
    data_dir: Path,
    probe: Callable[[], Probe],
    launch: Callable[[], None],
    clear_stale: Callable[[], None],
    *,
    timeout: float = 15.0,
    poll_interval: float = 0.05,
) -> None:
    """Connect or start exactly one backend while serialising startup attempts.

    Probe must perform authenticated compatibility checks and return ABSENT
    for missing or unreachable endpoints. clear_stale only runs while both
    startup and directory ownership locks are held. The child must acquire
    the directory lock itself before publishing readiness. No PID is trusted.
    """
    if timeout <= 0 or poll_interval <= 0:
        raise ValueError('startup timing must be positive')
    deadline = time.monotonic() + timeout

    def check() -> bool:
        result = probe()
        if result is Probe.INCOMPATIBLE:
            raise BackendIncompatible('existing backend configuration or version is incompatible')
        if not isinstance(result, Probe):
            raise ValueError('invalid backend probe result')
        return result is Probe.READY

    if check():
        return
    lock = StartupLock(data_dir)
    lock.acquire(timeout=max(0, deadline - time.monotonic()))
    try:
        if check():
            return
        # A live old process or unresponsive new backend must not be displaced.
        ownership = InstanceLock(data_dir)
        ownership.acquire()
        try:
            clear_stale()
        finally:
            ownership.release()
        launch()
        while True:
            if check():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('backend did not become ready')
            time.sleep(min(poll_interval, remaining))
    finally:
        lock.release()
