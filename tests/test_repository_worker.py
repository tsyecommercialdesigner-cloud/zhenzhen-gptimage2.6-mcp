import asyncio
import sqlite3
import pytest
from zhenzhen_gptimage.repository.worker import DatabaseWorker

@pytest.mark.asyncio
async def test_worker_serializes_and_does_not_block_event_loop(tmp_path):
    path = tmp_path / 'state.db'
    worker = DatabaseWorker(path)
    await worker.fetchone('select 1')
    lock = sqlite3.connect(path, isolation_level=None)
    lock.execute('BEGIN IMMEDIATE')
    pending = asyncio.create_task(worker.run(lambda db: db.execute("insert into batches values (?,?)", ('b', 1))))
    await asyncio.sleep(.1)
    assert not pending.done()
    lock.rollback()
    await pending
    rows = await asyncio.gather(*(worker.fetchone('select batch_id from batches where batch_id=?', ('b',)) for _ in range(10)))
    assert all(row[0] == 'b' for row in rows)
    lock.close()
    await worker.close()

@pytest.mark.asyncio
async def test_worker_rolls_back_unfinished_transaction(tmp_path):
    worker = DatabaseWorker(tmp_path/'state.db')
    def incomplete(db):
        db.execute('BEGIN IMMEDIATE')
        db.execute('insert into batches values (?,?)', ('b', 1))
    await worker.run(incomplete)
    assert await worker.fetchone('select batch_id from batches where batch_id=?', ('b',)) is None
    await worker.close()
