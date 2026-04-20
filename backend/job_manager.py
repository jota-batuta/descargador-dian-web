"""In-memory job store for download jobs."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


@dataclass
class Job:
    id: str
    user_email: str
    status: JobStatus
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    result_zip: Optional[Path] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    work_dir: Optional[Path] = None
    empresa: str = ""
    start_date: str = ""
    end_date: str = ""


class JobStore:
    def __init__(self, ttl_seconds: int = 7200):
        self._jobs: dict[str, Job] = {}
        self._ttl = ttl_seconds

    def create(self, user_email: str, empresa: str, start_date: str, end_date: str) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            user_email=user_email,
            status=JobStatus.queued,
            empresa=empresa,
            start_date=start_date,
            end_date=end_date,
        )
        self._jobs[job_id] = job
        self._evict_expired()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [
            jid for jid, job in self._jobs.items()
            if now - job.created_at > self._ttl
            and job.status in (JobStatus.completed, JobStatus.failed)
        ]
        for jid in expired:
            job = self._jobs.pop(jid)
            if job.work_dir and job.work_dir.exists():
                import shutil
                shutil.rmtree(job.work_dir, ignore_errors=True)


job_store = JobStore()
