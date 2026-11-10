import sqlite3
import hashlib
import pytest
from zhenzhen_gptimage.repository.database import connect, initialize, schema, backup

def test_initialize_and_constraints(tmp_path):
    db = connect(tmp_path / 'state.db')
    initialize(db)
    assert db.execute('pragma user_version').fetchone()[0] == 3
    assert db.execute('pragma foreign_keys').fetchone()[0] == 1
    assert db.execute('pragma journal_mode').fetchone()[0] == 'wal'
    assert db.execute('pragma synchronous').fetchone()[0] == 2
    assert db.execute('pragma busy_timeout').fetchone()[0] == 5000
    assert len(db.execute("select name from sqlite_master where type='table'").fetchall()) == 19
    assert all(row[0] == 64 for row in db.execute('select length(checksum) from schema_migrations'))
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

def test_upgrade_v1_keeps_data_and_creates_readable_backup(tmp_path):
    path = tmp_path/'legacy.db'; db = connect(path)
    sql = schema(); checksum = hashlib.sha256(sql.encode('utf-8')).hexdigest()
    db.executescript('BEGIN;\n'+sql+f"\nINSERT INTO schema_migrations VALUES (1,1,'{checksum}'); PRAGMA user_version=1; COMMIT;")
    db.execute("INSERT INTO prompt_templates VALUES ('sku',1,'A cup','[]',1,1)")
    db.execute("INSERT INTO tasks(task_id,idempotency_key,channel,family,width,height,resolved_model,input_digest,resolved_digest,snapshot_json,status,created_at,updated_at,deadline_at) VALUES ('t','key','images','flare',1024,1024,'gpt-image-2.6-flare',?,?,'{}','unknown',1,1,600001)",('a'*64,'b'*64))
    db.execute("INSERT INTO task_events(task_id,from_status,to_status,reason_code,created_at) VALUES ('t',NULL,'unknown','test',1)")
    initialize(db)
    assert db.execute('pragma user_version').fetchone()[0] == 3
    assert db.execute("select input_digest from tasks where task_id='t'").fetchone()[0] == 'a'*64
    assert db.execute("select content from prompt_templates where code='sku'").fetchone()[0] == 'A cup'
    assert db.execute("select task_id from task_events").fetchone()[0] == 't'
    assert db.execute('pragma foreign_key_check').fetchall() == []
    assert db.execute('pragma foreign_keys').fetchone()[0] == 1
    db.execute("INSERT INTO tasks(task_id,idempotency_key,channel,family,width,height,resolved_model,input_digest,resolved_digest,snapshot_json,status,created_at,updated_at,deadline_at) VALUES ('auto','auto-key','images','flare',NULL,NULL,'gpt-image-2.6-flare',?,?,'{}','queued',1,1,600001)",('c'*64,'d'*64))
    backups=list(tmp_path.glob('legacy.db.v1-backup-*.sqlite3')); assert len(backups)==1
    old=sqlite3.connect(backups[0]); assert old.execute('pragma user_version').fetchone()[0] == 1
    assert old.execute("select status from tasks where task_id='t'").fetchone()[0]=='unknown'; old.close()
    initialize(db); assert len(list(tmp_path.glob('legacy.db.v1-backup-*.sqlite3')))==1
    db.close()

def test_failed_v2_migration_retains_v1_and_backup(tmp_path,monkeypatch):
    import zhenzhen_gptimage.repository.database as module
    path=tmp_path/'legacy.db'; db=connect(path); sql=schema(); checksum=hashlib.sha256(sql.encode()).hexdigest()
    db.executescript('BEGIN;\n'+sql+f"\nINSERT INTO schema_migrations VALUES (1,1,'{checksum}'); PRAGMA user_version=1; COMMIT;")
    monkeypatch.setattr(module,'schema_v2',lambda:'CREATE TABLE new_data(id INTEGER);\nTHIS IS INVALID;\n')
    with pytest.raises(sqlite3.OperationalError): initialize(db)
    assert db.execute('pragma user_version').fetchone()[0] == 1
    assert db.execute("select name from sqlite_master where name='new_data'").fetchone() is None
    assert len(list(tmp_path.glob('legacy.db.v1-backup-*.sqlite3'))) == 1
    db.close()

def test_v2_extensions_enforce_foreign_keys_and_remote_uniqueness(tmp_path):
    db=connect(tmp_path/'state.db'); initialize(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("insert into task_format_options values ('missing',2,'t8-star','gif','strict','{}')")
    args=('t','key','images','flare',1024,1024,'gpt-image-2.6-flare','a'*64,'b'*64,'{}','queued',0,0,600000)
    sql='insert into tasks(task_id,idempotency_key,channel,family,width,height,resolved_model,input_digest,resolved_digest,snapshot_json,status,created_at,updated_at,deadline_at) values ('+','.join(['?']*14)+')'
    db.execute(sql,args); db.execute(sql,('t2','key2',*args[2:]))
    db.execute("insert into remote_tasks values ('t','seedance','remote-1','queued',1)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("insert into remote_tasks values ('t2','seedance','remote-1','queued',1)")
    db.close()

def test_remote_id_recording_requires_active_attempt_and_is_transactional(tmp_path):
    from zhenzhen_gptimage.generation.models import GenerationRequest
    from zhenzhen_gptimage.generation.snapshot import create_snapshot
    from zhenzhen_gptimage.repository.tasks import accept_batch, start_attempt, record_remote_task, StateConflict
    db=connect(tmp_path/'state.db'); initialize(db)
    request=GenerationRequest(idempotency_key='remote',family='flare',width=512,height=512,prompt='test',output_format='gif',execution_mode='async')
    snapshot=create_snapshot(request,final_prompt='test',reference_hashes=())
    _, ids=accept_batch(db,[request],[snapshot],1000)
    task_id=ids[0]
    with pytest.raises(StateConflict): record_remote_task(db,task_id,0,'remote-id',1001)
    start_attempt(db,task_id,0,1001)
    record_remote_task(db,task_id,1,'remote-id',1002)
    assert tuple(db.execute('SELECT remote_id,remote_status FROM remote_tasks').fetchone())==('remote-id','SUBMITTED')
    assert db.execute('SELECT revision FROM tasks WHERE task_id=?',(task_id,)).fetchone()[0]==2
    with pytest.raises(StateConflict): record_remote_task(db,task_id,1,'other-id',1003)
    assert db.execute('SELECT count(*) FROM remote_tasks').fetchone()[0]==1
    db.close()

def test_v1_snapshot_and_idempotency_survive_upgrade(tmp_path):
    from zhenzhen_gptimage.generation.models import GenerationRequest
    from zhenzhen_gptimage.generation.snapshot import create_snapshot, RequestSnapshot
    from zhenzhen_gptimage.repository.tasks import accept_batch
    path=tmp_path/'legacy.db';db=connect(path);sql=schema();checksum=hashlib.sha256(sql.encode()).hexdigest()
    db.executescript('BEGIN;\n'+sql+f"\nINSERT INTO schema_migrations VALUES (1,1,'{checksum}'); PRAGMA user_version=1; COMMIT;")
    req=GenerationRequest(idempotency_key='old',family='flare',width=1024,height=1024,prompt='original')
    snap=create_snapshot(req,final_prompt='frozen',reference_hashes=())
    legacy=snap.model_dump_json(exclude={'snapshot_version','provider','output_format','size','size_policy','frame_count','frame_duration_ms','svg_model','svg_reasoning_effort'})
    db.execute("INSERT INTO tasks(task_id,idempotency_key,channel,family,width,height,resolved_model,input_digest,resolved_digest,snapshot_json,status,created_at,updated_at,deadline_at) VALUES ('old-task','old','images','flare',1024,1024,'gpt-image-2.6-flare',?,?,?,'unknown',1,1,600001)",(snap.input_digest,snap.resolved_digest,legacy))
    initialize(db)
    batch,ids=accept_batch(db,[req],[None],100)
    assert ids==['old-task'] and db.execute('select reused from batch_items where batch_id=?',(batch,)).fetchone()[0]==1
    restored=RequestSnapshot.model_validate_json(db.execute("select snapshot_json from tasks where task_id='old-task'").fetchone()[0])
    assert restored.prompt=='frozen' and restored.resolved_digest==snap.resolved_digest and restored.snapshot_version==1
    db.close()
