import sqlite3

import pytest

from zhenzhen_gptimage.repository import database


def test_v2_upgrade_backup_and_restore_preserves_identity(tmp_path, monkeypatch):
    path = tmp_path / 'state.sqlite3'
    db = database.connect(path)
    original = database.schema_v3
    monkeypatch.setattr(database, 'schema_v3', lambda: 'THIS IS INVALID;\n')
    with pytest.raises(sqlite3.OperationalError):
        database.initialize(db)
    assert db.execute('PRAGMA user_version').fetchone()[0] == 2
    db.execute("INSERT INTO tasks(task_id,idempotency_key,channel,family,width,height,resolved_model,input_digest,resolved_digest,snapshot_json,status,created_at,updated_at,deadline_at) VALUES ('t','key','images','flare',1024,1024,'gpt-image-2.6-flare',?,?,'{}','unknown',1,1,600001)", ('a'*64, 'b'*64))
    monkeypatch.setattr(database, 'schema_v3', original)
    database.initialize(db)
    assert db.execute('PRAGMA user_version').fetchone()[0] == 4
    assert tuple(db.execute('SELECT task_id,idempotency_key,status FROM tasks').fetchone()) == ('t', 'key', 'unknown')
    assert db.execute('SELECT enabled FROM artifact_retention_policy').fetchone()[0] == 0
    old_path, = tmp_path.glob('state.sqlite3.v2-backup-*.sqlite3')
    old = sqlite3.connect(old_path)
    assert old.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert old.execute('PRAGMA user_version').fetchone()[0] == 2
    assert old.execute('SELECT idempotency_key FROM tasks').fetchone()[0] == 'key'
    old.close()
    restored = sqlite3.connect(tmp_path / 'restored.sqlite3')
    source = sqlite3.connect(old_path)
    source.backup(restored)
    assert restored.execute('PRAGMA user_version').fetchone()[0] == 2
    assert restored.execute('SELECT status FROM tasks').fetchone()[0] == 'unknown'
    source.close()
    restored.close()
    database.initialize(db)
    assert len(list(tmp_path.glob('state.sqlite3.v2-backup-*.sqlite3'))) == 1
    db.close()


def test_failed_v3_migration_keeps_v2_and_backup(tmp_path, monkeypatch):
    path = tmp_path / 'state.sqlite3'
    db = database.connect(path)
    monkeypatch.setattr(database, 'schema_v3', lambda: 'CREATE TABLE partial (id INTEGER);\nINVALID;\n')
    with pytest.raises(sqlite3.OperationalError):
        database.initialize(db)
    assert db.execute('PRAGMA user_version').fetchone()[0] == 2
    assert db.execute("SELECT 1 FROM sqlite_master WHERE name='partial'").fetchone() is None
    with pytest.raises(sqlite3.OperationalError):
        database.initialize(db)
    assert len(list(tmp_path.glob('state.sqlite3.v2-backup-*.sqlite3'))) == 1
    db.close()


def test_v3_to_v4_keeps_gif_acceptance_and_cleanup_history(tmp_path, monkeypatch):
    path = tmp_path / 'state.sqlite3'
    db = database.connect(path)
    original = database.schema_v4
    monkeypatch.setattr(database, 'schema_v4', lambda: 'INVALID SQL;')
    with pytest.raises(sqlite3.OperationalError):
        database.initialize(db)
    assert db.execute('PRAGMA user_version').fetchone()[0] == 3
    db.execute("INSERT INTO tasks(task_id,idempotency_key,channel,family,width,height,resolved_model,input_digest,resolved_digest,snapshot_json,status,created_at,updated_at,deadline_at) VALUES ('gif','original-key','images','flare',512,512,'gpt-image-2.6-flare',?,?,'{}','succeeded',1,1,600001)", ('a'*64, 'b'*64))
    db.execute("INSERT INTO image_artifacts VALUES ('gif',0,'fixture.gif',?,'image/gif',1,512,512,NULL,1)", ('c'*64,))
    db.execute("INSERT INTO image_acceptance_records VALUES ('gif',?,512,512,1,'user_accepted_actual_size')", ('c'*64,))
    db.execute("INSERT INTO artifact_cleanup_events VALUES ('event','gif',0,'fixture.gif',?,1,'manual',NULL,'deleted',NULL,2,2)", ('c'*64,))
    db.execute("INSERT INTO artifact_cleanup_status VALUES ('gif',0,2,'event')")
    monkeypatch.setattr(database, 'schema_v4', original)
    database.initialize(db)
    with sqlite3.connect(next(tmp_path.glob('*.v3-backup-*.sqlite3'))) as old:
        assert old.execute('PRAGMA user_version').fetchone()[0] == 3
        for table in ('tasks','image_artifacts','image_acceptance_records','artifact_cleanup_status','artifact_cleanup_events'):
            assert [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] == old.execute(f'SELECT * FROM {table}').fetchall()
    assert db.execute('PRAGMA user_version').fetchone()[0] == 4
    db.close()
