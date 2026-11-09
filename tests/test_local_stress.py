"""Local concurrency and responsiveness evidence; no provider network."""
import asyncio
import ctypes
import json
import os
import time
from types import SimpleNamespace
import pytest
from zhenzhen_gptimage.bootstrap.config import Limits
from zhenzhen_gptimage.bootstrap.observability import configure_logging
from zhenzhen_gptimage.generation.admission import Admission
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.repository.tasks import QueueFull, list_tasks
from zhenzhen_gptimage.repository.worker import DatabaseWorker
from zhenzhen_gptimage.scheduler.engine import Scheduler

def peak_rss():
    if os.name != 'nt':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),('PeakWorkingSetSize',ctypes.c_size_t),('WorkingSetSize',ctypes.c_size_t),('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
    c=Counters(); c.cb=ctypes.sizeof(c)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True); psapi=ctypes.WinDLL('psapi',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(c),c.cb): raise OSError('GetProcessMemoryInfo failed')
    return c.PeakWorkingSetSize

@pytest.mark.asyncio
async def test_local_queue_concurrency_and_query_latency(tmp_path):
    db=DatabaseWorker(tmp_path/'state.db'); admission=Admission(db,tmp_path,Limits(free_disk_bytes=1))
    now=time.time_ns()//1_000_000
    requests=[GenerationRequest(idempotency_key=str(n),family='flare',channel='chat',prompt='cup') for n in range(20)]
    _,ids=await admission.submit(requests,now)
    with pytest.raises(QueueFull):
        await admission.submit([GenerationRequest(idempotency_key='overflow',family='flare',channel='chat',prompt='cup')],now)
    duplicates=await asyncio.gather(*(admission.submit([requests[0]],now) for _ in range(8)))
    assert all(result[1][0]==ids[0] for result in duplicates)
    assert (await db.fetchone('SELECT count(*) FROM tasks'))[0]==20
    release=asyncio.Event(); six=asyncio.Event()
    class Provider:
        def __init__(self):self.active=0;self.peak=0;self.calls=0
        async def generate(self,*args,**kwargs):
            self.active+=1;self.calls+=1;self.peak=max(self.peak,self.active)
            if self.active==6:six.set()
            try:await release.wait();return b'{}'
            finally:self.active-=1
    class Materializer:
        async def materialize(self,task_id,*args,**kwargs):
            return [SimpleNamespace(image_index=0,local_path=str(tmp_path/(task_id+'.png')),sha256='a'*64,mime_type='image/png',bytes=1,width=1,height=1,revised_prompt=None)]
    provider=Provider();scheduler=Scheduler(db,provider,tmp_path,Materializer())
    tasks=[asyncio.create_task(scheduler.wait(task_id)) for task_id in ids]
    try:
        await asyncio.wait_for(six.wait(),5)
        timings=[]
        for _ in range(20):
            started=time.perf_counter();rows,_=await db.run(list_tasks);timings.append((time.perf_counter()-started)*1000)
            assert len(rows)==20
        assert provider.peak==6 and provider.active==6
        release.set();results=await asyncio.gather(*tasks)
        assert all(row['status']=='succeeded' for row in results) and provider.calls==20
        logfile=tmp_path/'test.log'; logger=configure_logging(logfile,max_bytes=100,backup_count=2)
        for _ in range(20): logger.info('ignored',extra={'status':'queued'})
        assert (tmp_path/'test.log.1').exists() and len(list(tmp_path.glob('test.log.*')))<=2
        configure_logging()
        evidence={'query_max_ms':round(max(timings),3),'query_mean_ms':round(sum(timings)/len(timings),3),'peak_working_set_bytes':peak_rss(),'provider_peak':provider.peak,'tasks':len(results),'note':'in-process fake provider and synthetic image metadata; peak includes entire pytest process'}
        (tmp_path/'stress-result.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps(evidence))
    finally:
        release.set(); await asyncio.gather(*tasks,return_exceptions=True)
        await scheduler.close(); await db.close()
