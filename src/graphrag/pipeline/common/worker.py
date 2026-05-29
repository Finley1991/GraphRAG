"""Abstract base worker with retry, error handling, and lifecycle management."""
import asyncio
import traceback
from typing import Any, Optional
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
from graphrag.pipeline.common.redis_manager import RedisManager, Queue


class BaseWorker:
    def __init__(
        self,
        queue_name: str,
        redis_mgr: Optional[RedisManager] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        poll_interval: float = 1.0,
    ):
        self.queue_name = queue_name
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.poll_interval = poll_interval
        self._running = False
        self._redis = redis_mgr or RedisManager()
        self._queue: Optional[Queue] = None

    async def setup(self):
        await self._redis.connect()
        self._queue = Queue(self._redis, self.queue_name)
        logger.info(f"Worker initialized for queue: {self.queue_name}")

    async def shutdown(self):
        self._running = False
        await self._redis.disconnect()
        logger.info(f"Worker shut down for queue: {self.queue_name}")

    async def process(self, task: dict) -> dict:
        raise NotImplementedError

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def process_with_retry(self, task: dict) -> dict:
        return await self.process(task)

    async def handle_task(self, task: dict) -> bool:
        try:
            result = await self.process_with_retry(task)
            if self._queue:
                await self._queue.ack(task)
            logger.info(f"Task completed: {task.get('document', {}).get('doc_id', 'unknown')}")
            return True
        except Exception as e:
            logger.error(f"Task failed after retries: {e}\n{traceback.format_exc()}")
            if self._queue:
                await self._queue.nack(task)
            return False

    async def run(self):
        self._running = True
        await self.setup()
        logger.info(f"Worker started, polling queue: {self.queue_name}")

        while self._running:
            try:
                if self._queue is None:
                    await asyncio.sleep(self.poll_interval)
                    continue
                task = await self._queue.pop(timeout=5)
                if task is None:
                    continue
                await self.handle_task(task)
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(self.poll_interval)

        await self.shutdown()

    def stop(self):
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running