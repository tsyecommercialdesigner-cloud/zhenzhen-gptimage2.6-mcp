import asyncio
import pytest
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.snapshot import create_snapshot, IdempotencyConflict
from zhenzhen_gptimage.repository.worker import DatabaseWorker
from zhenzhen_gptimage.repository.tasks import accept_batch, start_attempt, transition, list_tasks, QueueFull, StateConflict

def make(key):
    r=GenerationRequest(idempotency_key=key,family='flare',width=512,height=512,prompt='mug')
    return r,create_snapshot(r,final_prompt='mug',reference_hashes=())

@pytest.mark.asyncio
async def test_atomic_batch_capacity_and_attempt(tmp_path):
    w=DatabaseWorker(tmp_path/'db.sqlite')
    pairs=[make(str(n)) for n in range(19)]
    await w.run(accept_batch,[p[0] for p in pairs],[p[1] for p in pairs],1000)
    other=[make('a'),make('b')]
    with pytest.raises(QueueFull): await w.run(accept_batch,[p[0] for p in other],[p[1] for p in other],1000)
    assert (await w.fetchone('select count(*) from tasks'))[0]==19
    r,s=make('a')
    _, ids=await w.run(accept_batch,[r,r],[s,s],1000)
    assert ids[0]==ids[1]
    assert await w.run(start_attempt,ids[0],0,1001)==1
    with pytest.raises(StateConflict): await w.run(start_attempt,ids[0],0,1002)
    assert (await w.fetchone('select count(*) from attempts where task_id=?',(ids[0],)))[0]==1
    await w.close()

@pytest.mark.asyncio
async def test_two_workers_idempotency_and_batch_history(tmp_path):
    path=tmp_path/'db.sqlite'
    a,b=DatabaseWorker(path),DatabaseWorker(path)
    await a.fetchone('select 1'); await b.fetchone('select 1')
    r,s=make('same')
    results=await asyncio.gather(*(w.run(accept_batch,[r],[s],1000) for w in (a,b)))
    assert results[0][1]==results[1][1]
    for batch,_ in results:
        rows,cursor=await a.run(lambda db: list_tasks(db,batch_id=batch))
        assert len(rows)==1 and cursor is None
    assert (await a.fetchone('select count(*) from tasks'))[0]==1
    rows,cursor=await a.run(lambda db: list_tasks(db,limit=1))
    assert len(rows)==1
    await a.close(); await b.close()

@pytest.mark.asyncio
async def test_references_reuse_and_transition(tmp_path):
    w=DatabaseWorker(tmp_path/'db.sqlite')
    r=GenerationRequest(idempotency_key='ref',family='flare',width=512,height=512,prompt='mug',references=[{'local_path':'C:/source.png'}])
    s=create_snapshot(r,final_prompt='mug',reference_hashes=('a'*64,))
    asset={'local_path':'C:/snapshot.png','sha256':'a'*64,'mime_type':'image/png','bytes':10,'width':1,'height':1}
    def add(db): return accept_batch(db,[r],[s],1000,assets=[[asset]])
    _,ids=await w.run(add)
    assert (await w.fetchone('select local_path from reference_assets where task_id=?',(ids[0],)))[0]=='C:/snapshot.png'
    # A duplicate uses the persisted snapshot and does not require the source or new assets.
    _,again=await w.run(lambda db: accept_batch(db,[r],[None],1001))
    assert again==ids
    await w.run(start_attempt,ids[0],0,1001)
    await w.run(lambda db: transition(db,ids[0],1,'materializing',1002,reason='received',response_ref='safe/response',attempt_certainty='response_received',http_status=200))
    with pytest.raises(StateConflict): await w.run(lambda db: transition(db,ids[0],1,'failed',1003,reason='stale'))
    row=await w.fetchone('select status,revision,response_ref from tasks where task_id=?',(ids[0],))
    assert tuple(row)==('materializing',2,'safe/response')
    await w.close()

@pytest.mark.asyncio
async def test_pagination_bound_to_filters_and_idempotency_conflict(tmp_path):
    w=DatabaseWorker(tmp_path/'db.sqlite')
    pairs=[make(str(n)) for n in range(3)]
    batch,_=await w.run(accept_batch,[p[0] for p in pairs],[p[1] for p in pairs],1000)
    first,cursor=await w.run(lambda db: list_tasks(db,batch_id=batch,limit=1))
    second,cursor2=await w.run(lambda db: list_tasks(db,batch_id=batch,limit=1,cursor=cursor))
    assert first[0]['task_id'] != second[0]['task_id'] and cursor2
    with pytest.raises(ValueError): await w.run(lambda db: list_tasks(db,limit=1,cursor=cursor))
    r=GenerationRequest(idempotency_key='0',family='flare',width=512,height=512,prompt='different')
    s=create_snapshot(r,final_prompt='different',reference_hashes=())
    with pytest.raises(IdempotencyConflict): await w.run(accept_batch,[r],[s],1001)
    assert (await w.fetchone('select count(*) from tasks'))[0]==3
    await w.close()

@pytest.mark.asyncio
async def test_failed_prepare_rolls_back_and_does_not_send(tmp_path):
    w=DatabaseWorker(tmp_path/'db.sqlite')
    r,s=make('not-sent')
    _,ids=await w.run(accept_batch,[r],[s],1000)
    def fail_update(db):
        db.execute("CREATE TRIGGER reject_submit BEFORE UPDATE ON tasks BEGIN SELECT RAISE(ABORT,'rejected'); END")
    await w.run(fail_update)
    sent=[]
    async def execute():
        await w.run(start_attempt,ids[0],0,1001)
        sent.append('http-called')
    with pytest.raises(Exception,match='rejected'): await execute()
    assert not sent
    assert (await w.fetchone('select count(*) from attempts'))[0] == 0
    row=await w.fetchone('select status,attempt_count,revision from tasks where task_id=?',(ids[0],))
    assert tuple(row)==('queued',0,0)
    await w.close()

@pytest.mark.asyncio
async def test_competing_capacity_and_duplicate_key(tmp_path):
    path=tmp_path/'db.sqlite'
    a,b=DatabaseWorker(path),DatabaseWorker(path)
    await a.fetchone('select 1'); await b.fetchone('select 1')
    pairs=[make(str(n)) for n in range(19)]
    await a.run(accept_batch,[x[0] for x in pairs],[x[1] for x in pairs],1000)
    left,right=make('left'),make('right')
    outcomes=await asyncio.gather(a.run(accept_batch,[left[0]],[left[1]],1001),
                                  b.run(accept_batch,[right[0]],[right[1]],1001),return_exceptions=True)
    assert sum(isinstance(x,QueueFull) for x in outcomes)==1
    assert (await a.fetchone('select count(*) from tasks'))[0]==20
    await a.close(); await b.close()
