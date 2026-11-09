"""SQLite schema initialization and per-connection settings."""
import hashlib
from importlib.resources import files
from pathlib import Path
import sqlite3
import time

def schema() -> str:
    return files('zhenzhen_gptimage.repository').joinpath('schema_v1.sql').read_text(encoding='utf-8')

def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=5000')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        db.row_factory = sqlite3.Row
        return db
    except BaseException:
        db.close()
        raise

def initialize(db: sqlite3.Connection) -> None:
    version = db.execute('PRAGMA user_version').fetchone()[0]
    sql = schema()
    checksum = hashlib.sha256(sql.encode('utf-8')).hexdigest()
    if version == 1:
        row = db.execute('SELECT checksum FROM schema_migrations WHERE version=1').fetchone()
        if row is None or row[0] != checksum:
            raise RuntimeError('schema checksum mismatch')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('database integrity check failed')
        return
    if version != 0:
        raise RuntimeError(f'unsupported database version: {version}')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
        raise RuntimeError('unversioned database is not empty')
    # executescript commits implicitly, so transaction and migration insert are
    # inside the script; checksum is a locally calculated hexadecimal constant.
    migration = ("BEGIN IMMEDIATE;\n" + sql +
                 f"\nINSERT INTO schema_migrations VALUES (1,{time.time_ns() // 1_000_000},'{checksum}');\n"
                 "PRAGMA user_version=1;\nCOMMIT;")
    try:
        db.executescript(migration)
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise

def backup(db: sqlite3.Connection, destination: Path) -> None:
    """Create a consistent snapshot without overwriting an existing file."""
    # Reserve the name atomically; never overwrite an existing backup.
    with destination.open('xb'):
        pass
    try:
        target = sqlite3.connect(destination)
        try:
            db.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('backup integrity check failed')
        finally:
            target.close()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
