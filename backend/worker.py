"""Background job runner for download jobs."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from dian_core.config import SessionConfig, UnattendedConfig
from dian_processes.unattended import run_unattended

from backend.job_manager import Job, JobStatus, job_store
from backend.zip_packager import build_result_zip

MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "4"))
_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphore


async def enqueue_job(job: Job, token_url: str) -> None:
    work_dir = Path(tempfile.mkdtemp(prefix=f"dian-{job.id[:8]}-"))
    job.work_dir = work_dir

    loop = asyncio.get_event_loop()
    asyncio.create_task(_run_job(job, token_url, loop))


async def _run_job(job: Job, token_url: str, loop: asyncio.AbstractEventLoop) -> None:
    sem = get_semaphore()
    async with sem:
        job.status = JobStatus.running
        try:
            await loop.run_in_executor(None, lambda: _run_sync(job, token_url, loop))
        except Exception as exc:
            job.status = JobStatus.failed
            job.error = str(exc)
            asyncio.run_coroutine_threadsafe(
                job.event_queue.put({"type": "error", "message": str(exc)}),
                loop,
            ).result(timeout=5)


def _run_sync(job: Job, token_url: str, loop: asyncio.AbstractEventLoop) -> None:
    start = job.start_date.replace("-", "/")
    end = job.end_date.replace("-", "/")

    config = UnattendedConfig(
        session=SessionConfig(token_url=token_url, headless=True),
        start_date=start,
        end_date=end,
        output_listados=str(job.work_dir / "output_listados"),
        output_recibidos=str(job.work_dir / "output_recibidos"),
        workers=int(os.getenv("AJAX_WORKERS", "4")),
    )

    def callback(event_type: str, message: str, **kwargs) -> None:
        payload = {"type": event_type, "message": message, **kwargs}
        asyncio.run_coroutine_threadsafe(
            job.event_queue.put(payload),
            loop,
        ).result(timeout=5)

    result = run_unattended(config, callback=callback)

    if result.get("status") in ("success", "partial"):
        zip_path = build_result_zip(job)
        job.result_zip = zip_path
        job.status = JobStatus.completed
        asyncio.run_coroutine_threadsafe(
            job.event_queue.put({"type": "job_done", **result, "zip_ready": True}),
            loop,
        ).result(timeout=5)
    else:
        job.status = JobStatus.failed
        job.error = result.get("status", "failed")
        asyncio.run_coroutine_threadsafe(
            job.event_queue.put({"type": "error", "message": "La descarga no pudo completarse", **result}),
            loop,
        ).result(timeout=5)
