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
        if request.execution_mode == 'async':
            self.scheduler.kick(task_ids[0])
            return await self.scheduler._row(task_ids[0])
        return await self.scheduler.wait(task_ids[0])

    async def generate_batch(self, requests):
        batch_id, task_ids = await self.admission.submit(requests,time.time_ns()//1_000_000)
        async def result(request, task_id):
            if request.execution_mode == 'async':
                self.scheduler.kick(task_id)
                return await self.scheduler._row(task_id)
            return await self.scheduler.wait(task_id)
        rows = await asyncio.gather(*(result(request, task_id) for request, task_id in zip(requests,task_ids)))
        return batch_id, rows
