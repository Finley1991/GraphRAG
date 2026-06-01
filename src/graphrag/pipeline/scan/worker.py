"""Scan worker that consumes scan queue tasks and produces parse queue tasks."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from loguru import logger
from graphrag.pipeline.common.worker import BaseWorker
from graphrag.pipeline.scan.scanner import PDFScanner
from graphrag.models.tasks import ScanTask
from graphrag.config.settings import load_settings
from graphrag.pipeline.common.redis_manager import Queue


class ScanWorker(BaseWorker):
    def __init__(self, redis_mgr=None):
        settings = load_settings()
        super().__init__(
            queue_name=settings.redis.scan_queue_name,
            redis_mgr=redis_mgr,
            max_retries=2,
        )
        self._output_queue_name = settings.redis.parse_queue_name
        self._scanner = PDFScanner()
        self._executor = ThreadPoolExecutor(max_workers=settings.pipeline.scan_workers)

    @property
    def output_queue_name(self) -> str:
        return self._output_queue_name

    async def shutdown(self):
        self._executor.shutdown(wait=False)
        await super().shutdown()

    async def process(self, task: dict) -> dict:
        scan_task = ScanTask(**task)
        doc = scan_task.document
        logger.info(f"Scanning document: {doc.doc_id} ({doc.filename})")

        scan_result = await self._do_scan(doc.source_path)

        parse_task = {
            "document": {
                "doc_id": doc.doc_id,
                "filename": doc.filename,
                "source_path": doc.source_path,
                "total_pages": scan_result["total_pages"],
                "metadata": doc.metadata.model_dump() if doc.metadata else None,
            },
            "table_page_ranges": [
                {"start": pr.start, "end": pr.end}
                for pr in scan_result["table_page_ranges"]
            ],
            "context_page_ranges": [
                {"start": cr.start, "end": cr.end}
                for cr in scan_result["context_page_ranges"]
            ],
            "tableless_html_pages": {
                str(k): v for k, v in scan_result["tableless_html_pages"].items()
            },
        }

        if self._queue:
            output_queue = Queue(self._redis, self._output_queue_name, maxsize=settings.redis.parse_queue_maxsize)
            if await output_queue.size() >= output_queue._maxsize:
                logger.warning(f"Output queue {self._output_queue_name} is full, retrying later")
                return {"stage": "queue_full", "doc_id": doc.doc_id}
            await output_queue.push(parse_task)

        return {
            "stage": "scan_complete",
            "doc_id": doc.doc_id,
            "parse_task": parse_task,
            "table_count": len(scan_result["table_page_ranges"]),
        }

    async def _do_scan(self, filepath: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._scanner.scan, filepath)