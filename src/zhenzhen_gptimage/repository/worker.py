"""Serialized SQLite execution on a dedicated thread, outside the event loop."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections.abc import Callable
from typing import TypeVar
from .database import connect, initialize

T = TypeVar('T')

class DatabaseWorker:
    def __init__(self, path: Path):
        self._path = path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sqlite')
        self._db = None
        self._closed = False

    def _invoke(self, operation: Callable[..., T], args: tuple) -> T:
        if self._db is None:
            db = connect(self._path)
            try:
                initialize(db)
            except BaseException:
                db.close()
                raise
            self._db = db
        try:
            return operation(self._db, *args)
        finally:
            # Never carry a transaction into the next queued operation.
            if self._db.in_transaction:
                self._db.rollback()

    async def run(self, operation: Callable[..., T], *args) -> T:
        if self._closed:
            raise RuntimeError('database worker closed')
        return await asyncio.get_running_loop().run_in_executor(self._executor, self._invoke, operation, args)

    async def fetchone(self, sql: str, params: tuple = ()):
        return await self.run(lambda db: db.execute(sql, params).fetchone())

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        def close_db():
            if self._db is not None:
                self._db.close()
                self._db = None
        await asyncio.get_running_loop().run_in_executor(self._executor, close_db)
        self._executor.shutdown(wait=True)
