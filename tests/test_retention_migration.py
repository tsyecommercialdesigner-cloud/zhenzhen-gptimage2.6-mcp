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
    assert db.execute('PRAGMA user_version').fetchone()[0] == 3
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
