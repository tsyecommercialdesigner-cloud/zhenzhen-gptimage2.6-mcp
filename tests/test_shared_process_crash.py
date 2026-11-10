"""Kill the owned backend at a real provider boundary, without network access."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys

import pytest

from zhenzhen_gptimage.mcp_api.backend_control import request_stop
from zhenzhen_gptimage.mcp_api.discovery import read_endpoint
from zhenzhen_gptimage.mcp_api.local_ipc import IPCError, RemoteBackend, connect


CHILD = r'''
import asyncio, base64, json, os, sys, threading
from io import BytesIO
from pathlib import Path
from PIL import Image
from zhenzhen_gptimage.providers.t8_star import client as provider_module
root=Path(sys.argv[1]); mode=sys.argv[2]; phase=sys.argv[3]
def record(text):
    with (root/'ledger').open('a',encoding='utf-8') as stream:
        stream.write(text+'\n'); stream.flush(); os.fsync(stream.fileno())
class Provider:
    def __init__(self,*args,**kwargs): pass
    async def generate(self,snapshot,refs,*,remaining_seconds):
        if mode=='prepared' and phase=='before-crash':
            record('prepared'); await asyncio.Event().wait()
        record('submit-sync')
        if mode=='sync' and phase=='before-crash': await asyncio.Event().wait()
        out=BytesIO(); Image.new('RGB',(512,512),'blue').save(out,format='PNG')
        return json.dumps({'data':[{'b64_json':base64.b64encode(out.getvalue()).decode()}]}).encode()
    async def submit_async(self,snapshot,*,remaining_seconds):
        record('submit-async'); return 'remote-crash-test'
    async def query_async(self,remote_id,*,remaining_seconds):
        record('poll:'+remote_id)
        if phase == 'before-crash': await asyncio.Event().wait()
        out=BytesIO(); frames=[Image.new('RGB',(512,512),c) for c in ('red','blue')]
        frames[0].save(out,format='GIF',save_all=True,append_images=frames[1:],duration=200,loop=0)
        return 'SUCCESS',json.dumps({'data':[{'b64_json':base64.b64encode(out.getvalue()).decode()}]}).encode()
provider_module.T8StarClient=Provider
if mode=='queued' and phase=='before-crash':
    from zhenzhen_gptimage.generation.admission import Admission
    old_submit=Admission.submit
    async def stall_after_admission(self,*args,**kwargs):
        result=await old_submit(self,*args,**kwargs)
        record('admitted'); await asyncio.Event().wait()
        return result
    Admission.submit=stall_after_admission
if mode=='save' and phase=='before-crash':
    from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
    old_publish=ArtifactMaterializer._publish
    def stall_after_publish(self,*args,**kwargs):
        result=old_publish(self,*args,**kwargs)
        record('published'); threading.Event().wait()
        return result
    ArtifactMaterializer._publish=stall_after_publish
from zhenzhen_gptimage.mcp_api.shared_process import main
sys.argv=['shared_process','--config-dir',str(root),'--data-dir',str(root/'data')]
main()
'''


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['queued', 'prepared', 'sync', 'async', 'save'])
async def test_process_crash_never_duplicates_remote_submission(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('ZHENZHEN_GPTIMAGEGEN_API_KEY', 'test-only')
    script = tmp_path / 'backend.py'
    script.write_text(CHILD, encoding='utf-8')
    root = tmp_path / 'data'

    def spawn(phase):
        return subprocess.Popen([sys.executable, str(script), str(tmp_path), mode, phase],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    async def await_endpoint(previous=None):
        for _ in range(400):
            endpoint = read_endpoint(root)
            if endpoint and endpoint.instance != previous:
                try:
                    reader, writer = await connect(endpoint, endpoint.identity)
                    writer.close(); await writer.wait_closed()
                    return endpoint
                except (OSError, IPCError):
                    pass
            await asyncio.sleep(.025)
        raise AssertionError('backend not ready')

    async def await_ledger(marker):
        for _ in range(400):
            if (tmp_path / 'ledger').exists() and marker in (tmp_path / 'ledger').read_text():
                return
            await asyncio.sleep(.025)
        raise AssertionError('provider boundary not reached')

    first = spawn('before-crash')
    second = None
    call = None
    endpoint = None
    try:
        old = await await_endpoint()
        request = {'idempotency_key': 'crash-test', 'family': 'flare', 'prompt': 'test',
                   'width': 512, 'height': 512}
        if mode == 'async':
            request.update(output_format='gif', execution_mode='async')
        call = asyncio.create_task(RemoteBackend(old, old.identity).call('generate_image', {'request': request}))
        marker = {'queued': 'admitted', 'prepared': 'prepared', 'sync': 'submit-sync',
                  'async': 'poll:remote-crash-test', 'save': 'published'}[mode]
        await await_ledger(marker)
        initial = await RemoteBackend(old, old.identity).call('get_task', {'idempotency_key': 'crash-test'})
        assert initial['data']['attempt_count'] == (0 if mode == 'queued' else 1)
        first.kill()
        first.wait(timeout=10)
        await asyncio.gather(call, return_exceptions=True)
        second = spawn('after-crash')
        endpoint = await await_endpoint(old.instance)
        backend = RemoteBackend(endpoint, endpoint.identity)
        for _ in range(400):
            view = await backend.call('get_task', {'idempotency_key': 'crash-test'})
            if view['data']['status'] in ('unknown', 'succeeded', 'recovery_pending'):
                break
            await asyncio.sleep(.025)
        expected = {'sync': 'unknown', 'prepared': 'unknown', 'async': 'succeeded', 'queued': 'succeeded', 'save': 'recovery_pending'}
        assert view['data']['status'] == expected[mode]
        if mode == 'save':
            view = await backend.call('recover_task', {'task_id': view['data']['task_id']})
            assert view['data']['status'] == 'succeeded'
        assert view['data']['attempt_count'] == 1
        assert view['data']['deadline_at'] == initial['data']['deadline_at']
        ledger = (tmp_path / 'ledger').read_text().splitlines()
        assert ledger.count('submit-async' if mode == 'async' else 'submit-sync') == (0 if mode == 'prepared' else 1)
        if mode == 'async':
            assert ledger.count('poll:remote-crash-test') >= 2
    finally:
        if call and not call.done():
            call.cancel()
            await asyncio.gather(call, return_exceptions=True)
        if first.poll() is None:
            first.kill(); first.wait(timeout=10)
        if second is not None and second.poll() is None:
            if endpoint:
                try:
                    await request_stop(endpoint, endpoint.identity)
                    await asyncio.to_thread(second.wait, timeout=10)
                except Exception:
                    second.kill(); second.wait(timeout=10)
            else:
                second.kill(); second.wait(timeout=10)
