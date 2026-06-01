"""Async Redis connection pool and queue abstraction for pipeline."""
import json
from typing import Any, Optional
import redis.asyncio as aioredis
from graphrag.config.settings import load_settings


class RedisManager:
    def __init__(self):
        settings = load_settings()
        self._pool = aioredis.ConnectionPool(
            host=settings.redis.host,
            port=settings.redis.port,
            db=settings.redis.db,
            password=settings.redis.password,
            decode_responses=True,
            protocol=2,
        )
        self._redis: Optional[aioredis.Redis] = None

    async def connect(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.Redis(connection_pool=self._pool)
        return self._redis

    async def client(self) -> aioredis.Redis:
        if self._redis is None:
            return await self.connect()
        return self._redis

    async def disconnect(self):
        if self._redis:
            await self._redis.aclose()
            await self._pool.disconnect()
            self._redis = None


class Queue:
    def __init__(self, mgr: RedisManager, name: str, maxsize: int = 1000):
        self._mgr = mgr
        self._name = name
        self._queue_key = f"queue:{name}"
        self._pending_key = f"queue:{name}:pending"
        self._maxsize = maxsize

    async def push(self, data: dict) -> bool:
        r = await self._mgr.client()
        if self._maxsize > 0 and await self.size() >= self._maxsize:
            return False
        msg = json.dumps(data, ensure_ascii=False)
        await r.lpush(self._queue_key, msg)
        return True

    async def pop(self, timeout: int = 30) -> Optional[dict]:
        r = await self._mgr.client()
        result = await r.brpoplpush(self._queue_key, self._pending_key, timeout=timeout)
        if result is None:
            return None
        return json.loads(result)

    async def ack(self, msg: dict) -> bool:
        r = await self._mgr.client()
        msg_str = json.dumps(msg, ensure_ascii=False)
        await r.lrem(self._pending_key, 1, msg_str)
        return True

    async def nack(self, msg: dict) -> bool:
        r = await self._mgr.client()
        msg_str = json.dumps(msg, ensure_ascii=False)
        await r.lrem(self._pending_key, 1, msg_str)
        await r.lpush(self._queue_key, msg_str)
        return True

    async def pending_count(self) -> int:
        r = await self._mgr.client()
        return await r.llen(self._pending_key)

    async def size(self) -> int:
        r = await self._mgr.client()
        return await r.llen(self._queue_key)

    async def requeue_pending(self) -> int:
        r = await self._mgr.client()
        count = 0
        while True:
            msg = await r.rpoplpush(self._pending_key, self._queue_key, timeout=1)
            if msg is None:
                break
            count += 1
        return count