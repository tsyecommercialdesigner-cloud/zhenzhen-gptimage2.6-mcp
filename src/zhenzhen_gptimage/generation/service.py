"""Synchronous-to-caller generation use cases over durable local tasks."""
from __future__ import annotations
import asyncio
import time

class GenerationService:
    def __init__(self, admission, scheduler):
        self.admission = admission
        self.scheduler = scheduler

    async def generate_image(self, request):
        _, task_ids = await self.admission.submit([request],time.time_ns()//1_000_000)
        return await self.scheduler.wait(task_ids[0])

    async def generate_batch(self, requests):
        batch_id, task_ids = await self.admission.submit(requests,time.time_ns()//1_000_000)
        rows = await asyncio.gather(*(self.scheduler.wait(task_id) for task_id in task_ids))
        return batch_id, rows
