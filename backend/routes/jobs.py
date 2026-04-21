"""Download job routes: create, stream progress, download result."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from backend.job_manager import JobStatus, job_store
from backend.routes.auth import require_active_user
from backend.worker import enqueue_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("")
async def create_job(
    token_url: Annotated[str, Form()],
    start_date: Annotated[str, Form()],
    end_date: Annotated[str, Form()],
    empresa: Annotated[str, Form()] = "",
    user: dict = Depends(require_active_user),
):
    if not token_url.startswith("https://catalogo-vpfe.dian.gov.co"):
        raise HTTPException(status_code=422, detail="Token URL inválido")

    from datetime import date as _date
    try:
        d_start = _date.fromisoformat(start_date)
        d_end = _date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Fechas inválidas (usa YYYY-MM-DD)")
    if d_start.year != d_end.year:
        raise HTTPException(
            status_code=422,
            detail="El rango debe estar dentro del mismo año calendario (limitación DIAN)",
        )
    if d_end < d_start:
        raise HTTPException(status_code=422, detail="La fecha fin no puede ser anterior a la fecha inicio")

    job = job_store.create(
        user_email=user["email"],
        empresa=empresa or user.get("full_name", ""),
        start_date=start_date,
        end_date=end_date,
    )
    await enqueue_job(job, token_url)
    return {"job_id": job.id, "status": job.status}


@router.get("/{job_id}/stream")
async def stream_job(job_id: str, user: dict = Depends(require_active_user)):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    if job.user_email != user["email"]:
        raise HTTPException(status_code=403)

    async def generator():
        # Replay any events already queued (job may have started while browser was loading)
        while not job.event_queue.empty():
            event = job.event_queue.get_nowait()
            yield {"event": event["type"], "data": json.dumps(event)}

        # Stream new events
        while True:
            if job.status in (JobStatus.completed, JobStatus.failed):
                # Send one final status event if queue is empty
                if job.event_queue.empty():
                    final_type = "job_done" if job.status == JobStatus.completed else "error"
                    payload = {"type": final_type, "status": job.status}
                    if job.error:
                        payload["message"] = job.error
                    yield {"event": final_type, "data": json.dumps(payload)}
                    break

            try:
                event = await asyncio.wait_for(job.event_queue.get(), timeout=30)
                yield {"event": event["type"], "data": json.dumps(event)}
                if event["type"] in ("job_done", "error"):
                    break
            except TimeoutError:
                # Keep-alive ping
                yield {"event": "ping", "data": "{}"}

    import asyncio
    return EventSourceResponse(generator())


@router.get("/{job_id}/status")
async def job_status(job_id: str, user: dict = Depends(require_active_user)):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404)
    if job.user_email != user["email"]:
        raise HTTPException(status_code=403)
    return {"job_id": job.id, "status": job.status, "error": job.error}


@router.get("/{job_id}/download")
async def download_job(job_id: str, user: dict = Depends(require_active_user)):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404)
    if job.user_email != user["email"]:
        raise HTTPException(status_code=403)
    if job.status != JobStatus.completed or job.result_zip is None:
        raise HTTPException(status_code=409, detail="El trabajo aún no está listo")

    zip_path = job.result_zip
    filename = zip_path.name

    def iterfile():
        with open(zip_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        iterfile(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
