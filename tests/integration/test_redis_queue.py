"""Integration tests for Redis queue."""
import pytest
from graphrag.pipeline.common.redis_manager import RedisManager, Queue


@pytest.mark.asyncio
async def test_queue_push_pop():
    mgr = RedisManager()
    await mgr.connect()
    queue = Queue(mgr, "test_queue")
    await queue.push({"hello": "world"})
    result = await queue.pop(timeout=5)
    assert result is not None
    assert result["hello"] == "world"
    await mgr.disconnect()


@pytest.mark.asyncio
async def test_queue_empty_timeout():
    mgr = RedisManager()
    await mgr.connect()
    queue = Queue(mgr, "test_empty_queue")
    result = await queue.pop(timeout=2)
    assert result is None
    await mgr.disconnect()


@pytest.mark.asyncio
async def test_queue_ack():
    mgr = RedisManager()
    await mgr.connect()
    queue = Queue(mgr, "test_ack_queue")
    await queue.push({"task": "1"})
    msg = await queue.pop(timeout=5)
    assert msg is not None
    await queue.ack(msg)
    pending = await queue.pending_count()
    assert pending == 0
    await mgr.disconnect()