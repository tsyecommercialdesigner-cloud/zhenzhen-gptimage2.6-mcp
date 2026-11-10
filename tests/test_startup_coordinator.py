"""Exercise startup arbitration separately from transport authentication."""
from pathlib import Path
import subprocess
import sys

import pytest

from zhenzhen_gptimage.mcp_api.lifecycle import InstanceLock
from zhenzhen_gptimage.mcp_api.startup_coordinator import (
    BackendIncompatible, Probe, ensure_backend,
)


def test_live_owner_prevents_stale_cleanup_and_start(tmp_path):
    legacy = InstanceLock(tmp_path)
    legacy.acquire()
    actions = []
    try:
        with pytest.raises(RuntimeError, match='already in use'):
            ensure_backend(tmp_path, lambda: Probe.ABSENT,
                           lambda: actions.append('launch'),
                           lambda: actions.append('cleanup'))
        assert actions == []
    finally:
        legacy.release()


def test_incompatible_backend_is_never_replaced(tmp_path):
    actions = []
    with pytest.raises(BackendIncompatible):
        ensure_backend(tmp_path, lambda: Probe.INCOMPATIBLE,
                       lambda: actions.append('launch'),
                       lambda: actions.append('cleanup'))
    assert actions == []


def test_startup_rechecks_after_competing_process_wins(tmp_path):
    # Fixture marker models an authenticated ready result; actual transport
    # readiness and permissions are verified separately by integration tests.
    code = '''
import sys, time
from pathlib import Path
from zhenzhen_gptimage.mcp_api.startup_coordinator import Probe, ensure_backend
root = Path(sys.argv[1]); marker = root / 'ready'; launches = root / 'launches'
def probe(): return Probe.READY if marker.exists() else Probe.ABSENT
def launch():
    with launches.open('a', encoding='utf-8') as f: f.write('launch\\n')
    time.sleep(.3)
    marker.write_text('ready', encoding='utf-8')
ensure_backend(root, probe, launch, lambda: None, timeout=8)
'''
    processes = [subprocess.Popen([sys.executable, '-c', code, str(tmp_path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) for _ in range(4)]
    try:
        for process in processes:
            out, err = process.communicate(timeout=15)
            assert process.returncode == 0, (out, err)
        assert (tmp_path / 'launches').read_text().splitlines() == ['launch']
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


def test_stale_cleanup_precedes_launch_and_readiness_is_bounded(tmp_path):
    actions = []
    with pytest.raises(TimeoutError, match='did not become ready'):
        ensure_backend(tmp_path, lambda: Probe.ABSENT,
                       lambda: actions.append('launch'),
                       lambda: actions.append('cleanup'), timeout=.1, poll_interval=.01)
    assert actions == ['cleanup', 'launch']
