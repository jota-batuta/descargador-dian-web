"""Background job runner for download jobs."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

from backend.job_manager import Job, JobStatus
from backend.zip_packager import build_result_zip

MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "4"))
_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphore


_JOBS_ROOT = Path(os.getenv("JOBS_DIR", "/data/dian-jobs"))


async def enqueue_job(job: Job, token_url: str) -> None:
    _JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f"dian-{job.id[:8]}-", dir=_JOBS_ROOT))
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
            _update_log(job, status="failed")
            asyncio.run_coroutine_threadsafe(
                job.event_queue.put({"type": "error", "message": str(exc)}),
                loop,
            ).result(timeout=30)


def _run_sync(job: Job, token_url: str, loop: asyncio.AbstractEventLoop) -> None:
    from backend.db.pool import pool
    from dian_core.config import SessionConfig, UnattendedConfig
    from dian_processes.unattended import run_unattended

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

    _insert_log(job, pool)

    def callback(event_type: str, message: str, **kwargs) -> None:
        payload = {"type": event_type, "message": message, **kwargs}
        asyncio.run_coroutine_threadsafe(
            job.event_queue.put(payload),
            loop,
        ).result(timeout=30)

    result = run_unattended(config, callback=callback)

    if result.get("status") in ("success", "partial"):
        zip_path = build_result_zip(job)
        job.result_zip = zip_path
        job.status = JobStatus.completed
        _update_log(job, status="completed", result=result, pool=pool)
        asyncio.run_coroutine_threadsafe(
            job.event_queue.put({"type": "job_done", **result, "zip_ready": True}),
            loop,
        ).result(timeout=30)
    else:
        job.status = JobStatus.failed
        job.error = result.get("status", "failed")
        _update_log(job, status="failed", result=result, pool=pool)
        asyncio.run_coroutine_threadsafe(
            job.event_queue.put({"type": "error", "message": "La descarga no pudo completarse", **result}),
            loop,
        ).result(timeout=30)


def _insert_log(job: Job, pool) -> None:
    try:
        with pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO download_log
                  (user_email, job_id, start_date, end_date, empresa, status)
                VALUES (%s, %s, %s, %s, %s, 'running')
                ON CONFLICT DO NOTHING
                """,
                (job.user_email, job.id, job.start_date, job.end_date, job.empresa),
            )
    except Exception as exc:
        log.warning("_insert_log failed (non-fatal): %s", exc)


def _update_log(job: Job, status: str, result: dict | None = None, pool=None) -> None:
    try:
        if pool is None:
            from backend.db.pool import pool as _pool
            pool = _pool
        r = result or {}
        with pool.connection() as conn:
            conn.execute(
                """
                UPDATE download_log SET
                  status       = %s,
                  total_docs   = %s,
                  ok_docs      = %s,
                  err_docs     = %s,
                  coverage_pct = %s,
                  duration_s   = %s,
                  finished_at  = NOW()
                WHERE job_id = %s
                """,
                (
                    status,
                    r.get("total", 0),
                    r.get("ok", 0),
                    r.get("err", 0),
                    r.get("coverage_pct", 0),
                    r.get("duration_s", 0),
                    job.id,
                ),
            )
        log.info(
            "_update_log job=%s status=%s total=%s ok=%s err=%s",
            job.id[:8], status, r.get("total"), r.get("ok"), r.get("err"),
        )
    except Exception as exc:
        log.warning("_update_log failed (non-fatal): %s", exc)
