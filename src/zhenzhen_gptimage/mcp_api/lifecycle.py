"""Single-data-directory process ownership and ordered startup."""
from contextlib import asynccontextmanager
from pathlib import Path
import os
import asyncio

class InstanceLock:
    def __init__(self, root: Path):
        root.mkdir(parents=True,exist_ok=True)
        self.path=root/'server.lock'
        self._file=None
    def acquire(self):
        file=self.path.open('a+b')
        try:
            file.seek(0,os.SEEK_END)
            if file.tell()==0: file.write(b'0');file.flush()
            file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self._file=file
        except BaseException:
            file.close()
            raise RuntimeError('data directory is already in use') from None
    def release(self):
        if self._file is None: return
        file=self._file;self._file=None
        try:
            file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_UN)
        finally: file.close()

@asynccontextmanager
async def running_service(config):
    from zhenzhen_gptimage.repository.worker import DatabaseWorker
    from zhenzhen_gptimage.bootstrap.network import create_http_client
    from zhenzhen_gptimage.providers.t8_star.client import T8StarClient
    from zhenzhen_gptimage.artifacts.output import ArtifactMaterializer
    from zhenzhen_gptimage.artifacts.recovery import RecoveryService
    from zhenzhen_gptimage.generation.task_locks import TaskLocks
    from zhenzhen_gptimage.generation.admission import Admission
    from zhenzhen_gptimage.generation.service import GenerationService
    from zhenzhen_gptimage.scheduler.engine import Scheduler
    from .backend import ServiceBackend
    lock=InstanceLock(config.data_dir); lock.acquire()
    worker=client=materializer=scheduler=admission=recovery=None
    try:
        worker=DatabaseWorker(config.data_dir/'state.sqlite3')
        await worker.fetchone('SELECT 1')
        client=create_http_client()
        provider=T8StarClient(client,config.api_key.get_secret_value(),response_limit=config.limits.response_bytes,request_limit=config.limits.request_bytes)
        materializer=ArtifactMaterializer(config.data_dir,limits=config.limits)
        locks=TaskLocks()
        recovery=RecoveryService(worker,materializer,config.data_dir,locks)
        scheduler=Scheduler(worker,provider,config.data_dir,materializer,concurrency=config.limits.max_concurrency,response_limit=config.limits.response_bytes,task_locks=locks)
        recovery.scheduler=scheduler
        admission=Admission(worker,config.data_dir,config.limits)
        # No task is scheduled until interrupted operations are classified.
        await recovery.startup()
        await scheduler.resume()
        yield ServiceBackend(worker,GenerationService(admission,scheduler),recovery)
    finally:
        # Stop scheduling immediately, even if an admission transaction needs
        # time to finish. Its durable cleanup may exceed the grace window.
        deadline = asyncio.get_running_loop().time() + min(30, config.limits.shutdown_seconds)
        if scheduler is not None: scheduler.closing = True
        if admission is not None: await admission.stop()
        remaining = lambda: max(0, deadline - asyncio.get_running_loop().time())
        if scheduler is not None: await scheduler.close(grace_seconds=remaining())
        if recovery is not None: await recovery.shutdown(grace_seconds=remaining())
        if materializer is not None: await materializer.close()
        if client is not None: await client.aclose()
        if worker is not None: await worker.close()
        lock.release()
