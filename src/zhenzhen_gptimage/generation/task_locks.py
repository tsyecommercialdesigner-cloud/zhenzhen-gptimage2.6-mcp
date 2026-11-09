"""Per-task mutual exclusion shared by execution, recovery and closure."""
import asyncio
from contextlib import asynccontextmanager

class TaskLocks:
    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._users: dict[str, int] = {}

    @asynccontextmanager
    async def hold(self, task_id: str):
        # Increment before awaiting, so an exiting owner cannot discard a lock
        # which a waiting task already references.
        lock = self._locks.setdefault(task_id, asyncio.Lock())
        self._users[task_id] = self._users.get(task_id, 0) + 1
        try:
            async with lock:
                yield
        finally:
            self._users[task_id] -= 1
            if self._users[task_id] == 0:
                del self._users[task_id]
                del self._locks[task_id]
