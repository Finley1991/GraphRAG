"""Tests for base worker."""
import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from graphrag.pipeline.common.worker import BaseWorker


class SuccessWorker(BaseWorker):
    async def process(self, task: dict) -> dict:
        return {"status": "ok", "task": task}


class FailWorker(BaseWorker):
    async def process(self, task: dict) -> dict:
        raise ValueError("processing failed")


@pytest.mark.asyncio
async def test_success_worker():
    worker = SuccessWorker(queue_name="test")
    result = await worker.process({"hello": "world"})
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_fail_worker_retries():
    worker = FailWorker(queue_name="test", max_retries=2)
    assert worker.max_retries == 2
    assert worker.retry_delay == 1.0


@pytest.mark.asyncio
async def test_worker_run_loop_stop():
    worker = SuccessWorker(queue_name="test", poll_interval=0.1)
    with patch.object(worker, "setup", AsyncMock()):
        with patch.object(worker, "shutdown", AsyncMock()):
            loop_task = asyncio.create_task(worker.run())
            await asyncio.sleep(0.2)
            assert worker.is_running is True
            worker.stop()
            await asyncio.wait_for(loop_task, timeout=5)
            assert worker.is_running is False