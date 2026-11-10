"""The startup lock must survive races without relying on lock-file deletion."""
import subprocess
import sys

import pytest

from zhenzhen_gptimage.mcp_api.startup_lock import StartupLock


def test_startup_lock_times_out_and_releases(tmp_path):
    first, second = StartupLock(tmp_path), StartupLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(TimeoutError, match='timed out'):
            second.acquire(timeout=0.1)
    finally:
        first.release()
    second.acquire(timeout=0.1)
    second.release()
    assert (tmp_path / 'startup.lock').exists()


def test_killed_startup_owner_releases_os_lock(tmp_path):
    code = (
        'import sys; from pathlib import Path; '
        'from zhenzhen_gptimage.mcp_api.startup_lock import StartupLock; '
        'lock=StartupLock(Path(sys.argv[1])); lock.acquire(); '
        "print('locked', flush=True); sys.stdin.readline()"
    )
    proc = subprocess.Popen([sys.executable, '-u', '-c', code, str(tmp_path)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == 'locked'
        with pytest.raises(TimeoutError):
            StartupLock(tmp_path).acquire(timeout=0.1)
        proc.kill()
        proc.communicate(timeout=10)
        second = StartupLock(tmp_path)
        second.acquire(timeout=2)
        second.release()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=10)
