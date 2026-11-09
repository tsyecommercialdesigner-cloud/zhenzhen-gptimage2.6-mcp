import sqlite3
import pytest
from zhenzhen_gptimage.repository.database import connect, initialize, schema, backup

def test_initialize_and_constraints(tmp_path):
    db = connect(tmp_path / 'state.db')
    initialize(db)
    assert db.execute('pragma user_version').fetchone()[0] == 1
    assert db.execute('pragma foreign_keys').fetchone()[0] == 1
    assert db.execute('pragma journal_mode').fetchone()[0] == 'wal'
    assert db.execute('pragma synchronous').fetchone()[0] == 2
    assert db.execute('pragma busy_timeout').fetchone()[0] == 5000
    assert len(db.execute("select name from sqlite_master where type='table'").fetchall()) == 10
    assert db.execute('select length(checksum) from schema_migrations').fetchone()[0] == 64
    initialize(db)
    args=('t','key','images','flare',1024,1024,'gpt-image-2.6-flare','a'*64,'b'*64,'{}','queued',0,0,600000)
    sql='insert into tasks(task_id,idempotency_key,channel,family,width,height,resolved_model,input_digest,resolved_digest,snapshot_json,status,created_at,updated_at,deadline_at) values ('+','.join(['?']*14)+')'
    db.execute(sql,args)
    for row in [args, ('t2','k2','images','flare',1024,1024,'gpt-image-2.6-flare-2k','a'*64,'b'*64,'{}','queued',0,0,600000)]:
        with pytest.raises(sqlite3.IntegrityError): db.execute(sql,row)
    for task, attempt in [('t',0),('t',4),('missing',1)]:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('insert into attempts(task_id,attempt_no,started_at,submission_certainty) values (?,?,?,?)',(task,attempt,0,'prepared'))
    db.close()

def test_unversioned_nonempty_rejected(tmp_path):
    db=connect(tmp_path/'old.db')
    db.execute('create table old_data (value text)')
    with pytest.raises(RuntimeError,match='not empty'): initialize(db)
    assert db.execute("select name from sqlite_master where name='old_data'").fetchone()
    db.close()

def test_backup_and_restore(tmp_path):
    db = connect(tmp_path/'state.db')
    initialize(db)
    db.execute('insert into batches values (?,?)', ('batch', 42))
    target = tmp_path/'backup.db'
    backup(db, target)
    with pytest.raises(FileExistsError): backup(db, target)
    restored = connect(target)
    initialize(restored)
    assert restored.execute('select created_at from batches where batch_id=?', ('batch',)).fetchone()[0] == 42
    restored.close()
    db.close()

def test_unknown_version_and_corruption_fail(tmp_path):
    db = connect(tmp_path/'future.db')
    db.execute('pragma user_version=99')
    with pytest.raises(RuntimeError, match='unsupported'): initialize(db)
    db.close()
    path = tmp_path/'corrupt.db'
    path.write_bytes(b'not a sqlite database')
    with pytest.raises(sqlite3.DatabaseError): connect(path)

def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    import zhenzhen_gptimage.repository.database as module
    db=connect(tmp_path/'failed.db')
    monkeypatch.setattr(module, 'schema', lambda: 'CREATE TABLE first (id INTEGER);\nTHIS IS INVALID;')
    with pytest.raises(sqlite3.OperationalError): initialize(db)
    assert db.execute('pragma user_version').fetchone()[0] == 0
    assert db.execute("select name from sqlite_master where name='first'").fetchone() is None
    db.close()
