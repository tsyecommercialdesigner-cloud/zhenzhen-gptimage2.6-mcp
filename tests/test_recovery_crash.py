"""Abrupt child termination at durable task/response/image boundaries."""
import asyncio
import base64
import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path
import pytest
from PIL import Image
from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
from zhenzhen_gptimage.artifacts.recovery import RecoveryService
from zhenzhen_gptimage.bootstrap.config import Limits
from zhenzhen_gptimage.generation.admission import Admission
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.task_locks import TaskLocks
from zhenzhen_gptimage.repository.worker import DatabaseWorker

CHILD = r'''
import os,sys
from pathlib import Path
from zhenzhen_gptimage.repository.database import connect, initialize
from zhenzhen_gptimage.repository.tasks import start_attempt, transition
from zhenzhen_gptimage.artifacts.storage import write_response
from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
root=Path(sys.argv[1]); task=sys.argv[2]; stage=sys.argv[3]
db=connect(root/'state.db'); initialize(db)
if stage=='before_send': os._exit(70)
start_attempt(db,task,0,1001)
if stage=='after_send':
    import http.server, threading, urllib.request
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            self.send_response(200); self.end_headers(); self.wfile.write(b'accepted')
        def log_message(self,*args): pass
    server=http.server.HTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%d/'%server.server_port,data=b'test'),timeout=5) as response:
        assert response.read()==b'accepted'
    os._exit(71)
raw=(root/'response.json').read_bytes()
artifact=write_response(root,task,1,[raw],max_bytes=1048576)
if stage=='after_response': os._exit(72)
transition(db,task,1,'materializing',1002,reason='received',response_ref=artifact.local_path,attempt_certainty='response_received',http_status=200)
if stage=='after_register': os._exit(73)
image=(root/'sample.png').read_bytes()
m=ArtifactMaterializer(root)
m._publish(task, [(image,'image/png',32,32,None)])
os._exit(74)
'''

@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['before_send','after_send','after_response','after_register','after_publish'])
async def test_crash_windows_never_resubmit(tmp_path, stage):
    db=DatabaseWorker(tmp_path/'state.db')
    admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    request=GenerationRequest(idempotency_key=stage,family='flare',width=32,height=32,prompt='cup')
    _,ids=await admission.submit([request],1000)
    task=ids[0]
    await db.close()
    out=BytesIO();Image.new('RGB',(32,32),'blue').save(out,'PNG'); data=out.getvalue()
    (tmp_path/'sample.png').write_bytes(data)
    (tmp_path/'response.json').write_text(json.dumps({'data':[{'b64_json':base64.b64encode(data).decode()}]}))
    result=await asyncio.to_thread(subprocess.run,[sys.executable,'-c',CHILD,str(tmp_path),task,stage],capture_output=True)
    assert result.returncode in (70,71,72,73,74), result.stderr.decode(errors='replace')
    db=DatabaseWorker(tmp_path/'state.db'); materializer=ArtifactMaterializer(tmp_path)
    recovery=RecoveryService(db,materializer,tmp_path,TaskLocks())
    await recovery.startup()
    row=await recovery._row(task)
    assert row['attempt_count']==(0 if stage=='before_send' else 1)
    if stage=='before_send':
        assert row['status']=='queued'
    elif stage=='after_send':
        assert row['status']=='unknown'
    else:
        assert row['status']=='recovery_pending'
        row=await recovery.recover(task)
        assert row['status']=='succeeded' and row['attempt_count']==1
        assert (await db.fetchone('select count(*) from image_artifacts where task_id=?',(task,)))[0]==1
    assert (await db.fetchone('select count(*) from attempts where task_id=?',(task,)))[0] == (0 if stage=='before_send' else 1)
    await materializer.close();await db.close()
