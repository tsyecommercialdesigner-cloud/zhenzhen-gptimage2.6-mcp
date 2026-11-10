"""Use a real subprocess and private IPC, without contacting the provider."""
import asyncio
import json
import subprocess
import sys
import time

from zhenzhen_gptimage.bootstrap.config import load_config
from zhenzhen_gptimage.mcp_api.lifecycle import InstanceLock
from zhenzhen_gptimage.mcp_api.local_ipc import connect, read_frame, write_frame
from zhenzhen_gptimage.mcp_api.discovery import read_endpoint
from zhenzhen_gptimage.mcp_api.shared_launch import ensure_shared_backend


def test_competing_clients_reuse_real_owned_backend(tmp_path, monkeypatch):
    monkeypatch.setenv('ZHENZHEN_GPTIMAGEGEN_API_KEY', 'test-only-secret')
    config = load_config(tmp_path, tmp_path / 'data')
    code = '''
import json, sys
from pathlib import Path
from zhenzhen_gptimage.bootstrap.config import load_config
from zhenzhen_gptimage.mcp_api.shared_launch import ensure_shared_backend
root = Path(sys.argv[1]); cfg = load_config(root, root / 'data')
endpoint = ensure_shared_backend(cfg, root)
print(json.dumps({'instance': endpoint.instance, 'port': endpoint.port}))
'''
    processes = [subprocess.Popen([sys.executable, '-c', code, str(tmp_path)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(3)]
    results = []
    for process in processes:
        out, err = process.communicate(timeout=30)
        assert process.returncode == 0, err
        results.append(json.loads(out))
    assert len({result['instance'] for result in results}) == 1
    assert len({result['port'] for result in results}) == 1
    endpoint = read_endpoint(config.data_dir)

    control = [sys.executable, '-m', 'zhenzhen_gptimage.mcp_api.backend_control']
    options = ['--config-dir', str(tmp_path), '--data-dir', str(config.data_dir)]
    for action, expected in (('status', 'ready'), ('stop', 'stopping')):
        result = subprocess.run(control + [action] + options, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['status'] == expected
        assert 'test-only-secret' not in result.stdout + result.stderr
    deadline = time.monotonic() + 10
    while True:
        lock = InstanceLock(config.data_dir)
        try:
            lock.acquire()
            lock.release()
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise AssertionError('backend did not stop')
            time.sleep(.05)


def test_starter_crash_does_not_create_a_second_backend(tmp_path, monkeypatch):
    monkeypatch.setenv('ZHENZHEN_GPTIMAGEGEN_API_KEY', 'test-only-secret')
    code = '''
import sys, time
from pathlib import Path
from zhenzhen_gptimage.bootstrap.config import load_config
from zhenzhen_gptimage.mcp_api.shared_launch import probe_backend, start_shared_process, clear_stale_endpoint
from zhenzhen_gptimage.mcp_api.startup_coordinator import ensure_backend
root=Path(sys.argv[1]); cfg=load_config(root,root/'data')
def launch():
    start_shared_process(cfg,root)
    print('launched',flush=True)
    time.sleep(30)
ensure_backend(cfg.data_dir,lambda: probe_backend(cfg,root),launch,
               lambda: clear_stale_endpoint(cfg.data_dir),timeout=40)
'''
    starter = subprocess.Popen([sys.executable, '-u', '-c', code, str(tmp_path)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    config = load_config(tmp_path, tmp_path / 'data')
    endpoint = None
    try:
        assert starter.stdout.readline().strip() == 'launched'
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            endpoint = read_endpoint(config.data_dir)
            if endpoint is not None:
                break
            time.sleep(.05)
        assert endpoint is not None
        starter.kill()
        starter.communicate(timeout=10)
        assert ensure_shared_backend(config, tmp_path).instance == endpoint.instance
    finally:
        if starter.poll() is None:
            starter.kill()
            starter.communicate(timeout=10)
        if endpoint is not None:
            async def stop():
                reader, writer = await connect(endpoint, endpoint.identity)
                await write_frame(writer, {'op': 'stop'}, timeout=5)
                await read_frame(reader, timeout=5)
                writer.close()
                await writer.wait_closed()
            asyncio.run(stop())
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                lock = InstanceLock(config.data_dir)
                try:
                    lock.acquire()
                    lock.release()
                    break
                except RuntimeError:
                    time.sleep(.05)
