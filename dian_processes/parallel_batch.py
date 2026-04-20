"""
Descarga paralela por lotes — divide el rango total en ventanas de N días
y ejecuta M workers concurrentes (threading), cada uno con su sesión
Playwright independiente.

Upgrades vs el original (auditoria_parallel.py):
- Threads en vez de multiprocessing: el .exe PyInstaller tiene fricción con
  Pool (requiere ``multiprocessing.freeze_support()`` y re-spawn del .exe por
  worker). ThreadPoolExecutor es más simple; Playwright libera el GIL en I/O
  así que el paralelismo real igual se consigue.
- Master log con resume: lotes completados se saltan al re-ejecutar.
- Stagger: arranque escalonado para no saturar /AuthToken.
- Callback por evento (running, completed, failed) para que la UI pinte una
  tabla de lotes con estado en tiempo real.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator, Optional

from playwright.sync_api import sync_playwright

from dian_core.config import DateDownloadConfig, SessionConfig
from dian_core.documents_page import DocumentsPage
from dian_core.session import DianSession
from dian_processes.date_download import DateDownloader

CallbackT = Callable[..., None]
OnCufeDone = Callable[[str, bool, Optional[str]], None]


# ---------- helpers ----------

def _sanitize_dir(name: str) -> str:
    """Sanitiza nombre para uso como carpeta (Windows/Linux/macOS)."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(".")


def _batch_key(start: str, end: str) -> str:
    """Llave única por rango — sirve como clave en el master_log."""
    return f"{start.replace('/', '-')}_{end.replace('/', '-')}"


def generate_batches(
    start: datetime, end: datetime, days: int = 15
) -> list[tuple[str, str]]:
    """Genera una lista de (start, end) en formato YYYY/MM/DD.

    Cada ventana cubre ``days`` días (última ventana puede ser más corta).
    """
    batches: list[tuple[str, str]] = []
    current = start
    while current <= end:
        batch_end = min(current + timedelta(days=days - 1), end)
        batches.append(
            (current.strftime("%Y/%m/%d"), batch_end.strftime("%Y/%m/%d"))
        )
        current = batch_end + timedelta(days=1)
    return batches


# ---------- master log ----------

def _master_log_path(output_base: str, company: str) -> str:
    return str(
        Path(output_base)
        / "_auditoria_logs"
        / _sanitize_dir(company)
        / "master_log.json"
    )


def _load_master_log(path: str) -> dict:
    if not Path(path).exists():
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_master_log(path: str, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------- worker ----------

@dataclass
class _WorkerArgs:
    start_date: str
    end_date: str
    token_url: str
    company: str
    output_base: str
    page_size: int
    worker_name: str


def _run_single_batch(args: _WorkerArgs, emit: Callable[[str, str, dict], None]) -> dict:
    """Ejecuta un lote; emite eventos y retorna un resumen."""
    bk = _batch_key(args.start_date, args.end_date)
    # Stagger para no hamaquear a DIAN /AuthToken en paralelo
    time.sleep(random.uniform(1, 8))

    emit("batch_running", f"[{args.worker_name}] iniciando lote {bk}", {"batch_key": bk})

    session_cfg = SessionConfig(token_url=args.token_url, headless=True)
    config = DateDownloadConfig(
        session=session_cfg,
        company_name=args.company,
        start_date=args.start_date,
        end_date=args.end_date,
        output_base=args.output_base,
        page_size=args.page_size,
    )

    def cb(event_type, message, **kwargs):
        emit(
            "batch_log",
            f"[{args.worker_name}][{bk}] {message}",
            {"batch_key": bk, "event_type": event_type, **kwargs},
        )

    t0 = time.time()
    try:
        downloader = DateDownloader(config, callback=cb)
        summary = downloader.run()
        dt = round(time.time() - t0, 1)
        result = {
            "batch_key": bk,
            "status": "completed",
            "downloaded": summary.get("total_downloaded", 0),
            "duration_s": dt,
            "error": None,
        }
        emit(
            "batch_completed",
            f"[{args.worker_name}] OK {bk}: {result['downloaded']} archivos en {dt}s",
            result,
        )
        return result
    except Exception as e:
        dt = round(time.time() - t0, 1)
        result = {
            "batch_key": bk,
            "status": "failed",
            "downloaded": 0,
            "duration_s": dt,
            "error": str(e),
        }
        emit(
            "batch_failed",
            f"[{args.worker_name}] FAIL {bk}: {e}",
            result,
        )
        return result


# ---------- orchestrator ----------

def run_parallel_download(
    token_url: str,
    company: str,
    start: str,
    end: str,
    output_base: str,
    workers: int = 5,
    batch_days: int = 15,
    page_size: int = 100,
    callback: Optional[CallbackT] = None,
) -> dict:
    """Ejecuta la descarga paralela y retorna un resumen.

    Args:
        token_url, company, start, end: datos DIAN
        output_base: raíz donde caen las descargas
        workers: workers concurrentes (1-10, 5 es buen default)
        batch_days: días por lote (7-30, default 15)
        page_size: filas/página (100 es el máx DIAN)
        callback: función recibe ``(event_type, message, **kwargs)``.
            Eventos: ``progress``, ``batch_running``, ``batch_log``,
            ``batch_completed``, ``batch_failed``, ``success``, ``error``.

    Returns:
        dict con ``total_batches, completed, failed, total_files, duration_s``.
    """
    cb = callback or (lambda e, m, **kw: print(m))
    t0 = time.time()

    start_dt = datetime.strptime(start, "%Y/%m/%d")
    end_dt = datetime.strptime(end, "%Y/%m/%d")

    all_batches = generate_batches(start_dt, end_dt, batch_days)
    master_log_file = _master_log_path(output_base, company)
    master_log = _load_master_log(master_log_file)
    already_completed = {
        bk: info
        for bk, info in master_log.get("batches", {}).items()
        if info.get("status") == "completed"
    }

    pending = [
        (s, e) for (s, e) in all_batches if _batch_key(s, e) not in already_completed
    ]

    cb("status", f"▶ Descarga paralela")
    cb("status", f"  Empresa:     {company}")
    cb("status", f"  Rango:       {start} → {end}")
    cb("status", f"  Lotes ({batch_days}d): {len(all_batches)} total, {len(already_completed)} previamente completados")
    cb("status", f"  Pendientes:  {len(pending)}")
    cb("status", f"  Workers:     {workers}")
    cb("status", f"  Master log:  {master_log_file}")

    if not pending:
        cb("success", "Nada pendiente — todos los lotes ya estaban completados.")
        return {
            "total_batches": len(all_batches),
            "previously_completed": len(already_completed),
            "completed": 0,
            "failed": 0,
            "total_files": sum(b.get("downloaded", 0) for b in already_completed.values()),
            "duration_s": round(time.time() - t0, 1),
            "master_log": master_log_file,
        }

    lock = threading.Lock()
    shared_status: dict = dict(already_completed)

    def emit_event(event_type: str, message: str, extra: dict) -> None:
        with lock:
            bk = extra.get("batch_key")
            if bk:
                shared_status[bk] = {
                    **shared_status.get(bk, {}),
                    "status": extra.get("status", shared_status.get(bk, {}).get("status", "running")),
                    "downloaded": extra.get("downloaded", shared_status.get(bk, {}).get("downloaded", 0)),
                    "error": extra.get("error", shared_status.get(bk, {}).get("error")),
                    "duration_s": extra.get("duration_s", shared_status.get(bk, {}).get("duration_s")),
                }
                _save_master_log(
                    master_log_file,
                    {
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                        "company": company,
                        "batches": shared_status,
                    },
                )
            cb(event_type, message, **extra)

    worker_args_list = [
        _WorkerArgs(
            start_date=s,
            end_date=e,
            token_url=token_url,
            company=company,
            output_base=output_base,
            page_size=page_size,
            worker_name=f"w{i % workers + 1}",
        )
        for i, (s, e) in enumerate(pending)
    ]

    completed = 0
    failed = 0
    total_files = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_run_single_batch, wa, emit_event): wa for wa in worker_args_list
        }
        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception as e:
                cb("error", f"Worker explotó sin reportar: {e}")
                failed += 1
                continue

            if result["status"] == "completed":
                completed += 1
                total_files += result["downloaded"]
            else:
                failed += 1

            cb(
                "progress",
                f"Progreso: {completed + failed}/{len(pending)} "
                f"(OK={completed}, fallidos={failed}, archivos={total_files})",
                completed=completed, failed=failed, total_files=total_files,
                total_pending=len(pending),
            )

    duration = round(time.time() - t0, 1)
    summary = {
        "total_batches": len(all_batches),
        "previously_completed": len(already_completed),
        "completed": completed,
        "failed": failed,
        "total_files": total_files,
        "duration_s": duration,
        "master_log": master_log_file,
    }
    cb(
        "success",
        f"Descarga paralela finalizada: {completed} OK, {failed} fallidos, "
        f"{total_files} archivos en {duration}s.",
        **summary,
    )
    return summary


# =============================================================================
# Variante CUFE-chunks (modo desatendido)
# =============================================================================

def _chunk_cufes(cufes: list[str], n_workers: int) -> list[list[str]]:
    """Divide una lista de CUFEs en ``n_workers`` chunks balanceados.

    Ej: 10 CUFEs / 3 workers → [[0,3,6,9], [1,4,7], [2,5,8]] (round-robin).
    Round-robin en vez de slice contiguo para que un chunk "lento" (muchos
    CUFEs con error consecutivos) no penalice más que los otros.
    """
    chunks: list[list[str]] = [[] for _ in range(n_workers)]
    for i, c in enumerate(cufes):
        chunks[i % n_workers].append(c)
    return [c for c in chunks if c]  # descarta chunks vacíos si cufes < workers


def _run_cufe_chunk(
    chunk: list[str],
    token_url: str,
    output_recibidos: str,
    start_date: str,
    end_date: str,
    worker_name: str,
    on_done: OnCufeDone,
    emit: Callable[[str, str, dict], None],
) -> dict:
    """Worker: abre UNA sesión Playwright y procesa todos los CUFEs del chunk.

    Reusar la sesión para N CUFEs ahorra 10-15 s por CUFE vs abrir una
    sesión por cada uno.
    """
    time.sleep(random.uniform(1, 8))  # stagger
    emit(
        "worker_started",
        f"[{worker_name}] chunk de {len(chunk)} CUFEs, primero: {chunk[0][:20]}...",
        {"worker": worker_name, "count": len(chunk)},
    )

    ok_count = 0
    err_count = 0

    session_cfg = SessionConfig(token_url=token_url, headless=True)

    with sync_playwright() as p:
        session = DianSession(session_cfg)
        try:
            session.start(
                p,
                on_progress=lambda m: emit("status", f"[{worker_name}] {m}", {}),
            )
        except Exception as e:
            for cufe in chunk:
                on_done(cufe, False, f"session init failed: {e}")
                err_count += 1
            emit(
                "worker_failed",
                f"[{worker_name}] no pudo iniciar sesión: {e}",
                {"worker": worker_name, "error": str(e)},
            )
            return {"worker": worker_name, "ok": ok_count, "err": err_count}

        try:
            docs = DocumentsPage(
                session.page,
                wait_s=session_cfg.page_load_wait_s,
                download_timeout_ms=session_cfg.download_timeout_ms,
                on_progress=lambda m: emit("status", f"[{worker_name}] {m}", {}),
            )
            # /Document/Received ya filtra por tipo Recibidos vía URL —
            # no hay dropdown adicional que tocar (verificado por inspección
            # del DOM: 4× span.filter-option, todos para tipo de documento
            # como factura/nota crédito, no Recibidos vs Emitidos).
            docs.navigate()
            docs.apply_date_filter(start_date, end_date)
            docs.set_page_size(100)

            for cufe in chunk:
                try:
                    docs.apply_cufe_filter(cufe)
                    rows = docs.get_rows()
                    if not rows:
                        on_done(cufe, False, "CUFE no encontrado en el portal")
                        err_count += 1
                        continue

                    any_ok = False
                    for i, row in enumerate(rows):
                        success, fname = docs.download_row(row, i, output_recibidos)
                        if success:
                            any_ok = True
                            emit(
                                "downloaded",
                                f"[{worker_name}] ok {fname[:80]}",
                                {"worker": worker_name, "filename": fname},
                            )
                    if any_ok:
                        on_done(cufe, True, None)
                        ok_count += 1
                    else:
                        on_done(cufe, False, "No se pudo descargar ninguna fila")
                        err_count += 1
                except Exception as e:
                    on_done(cufe, False, str(e))
                    err_count += 1
                    emit(
                        "worker_log",
                        f"[{worker_name}] falla {cufe[:20]}: {e}",
                        {"worker": worker_name, "cufe": cufe, "error": str(e)},
                    )
        finally:
            session.close()

    emit(
        "worker_completed",
        f"[{worker_name}] terminado: {ok_count} OK, {err_count} errores",
        {"worker": worker_name, "ok": ok_count, "err": err_count},
    )
    return {"worker": worker_name, "ok": ok_count, "err": err_count}


def run_parallel_cufe_chunks(
    cufes: list[str],
    token_url: str,
    output_recibidos: str,
    start_date: str,
    end_date: str,
    workers: int = 8,
    on_done: Optional[OnCufeDone] = None,
    callback: Optional[CallbackT] = None,
) -> dict:
    """Descarga una lista de CUFEs en paralelo (N workers, una sesión c/u).

    Args:
        cufes: lista de CUFEs a descargar (ya filtrada, sin los Descargado).
        token_url, start_date, end_date: auth + rango para el filtro DIAN.
        output_recibidos: carpeta donde caen los .zip.
        workers: 1-10, se clampa.
        on_done: callback ``(cufe, ok, error)`` por cada CUFE al terminar.
            Típicamente lo pasa el orquestador para que ListadoUpdater
            marque el Excel.
        callback: callback de logs ``(event_type, message, **kwargs)``.

    Returns:
        ``{total_cufes, ok, err, duration_s, workers}``.
    """
    cb = callback or (lambda e, m, **kw: print(m))
    on_cufe_done = on_done or (lambda cufe, ok, err: None)

    t0 = time.time()
    workers = max(1, min(10, workers))

    if not cufes:
        cb("success", "No hay CUFEs pendientes — nada que hacer.")
        return {
            "total_cufes": 0, "ok": 0, "err": 0,
            "duration_s": 0.0, "workers": workers,
        }

    os.makedirs(output_recibidos, exist_ok=True)

    chunks = _chunk_cufes(cufes, workers)
    effective_workers = len(chunks)
    cb(
        "status",
        f"▶ Descarga paralela: {len(cufes)} CUFEs en {effective_workers} workers "
        f"(~{len(cufes) // effective_workers} c/u)",
    )

    def emit(event_type: str, message: str, extra: dict) -> None:
        cb(event_type, message, **extra)

    done_counter = [0, 0]  # [ok, err]
    counter_lock = threading.Lock()

    def wrapped_done(cufe: str, ok: bool, error: Optional[str]) -> None:
        on_cufe_done(cufe, ok, error)
        with counter_lock:
            if ok:
                done_counter[0] += 1
            else:
                done_counter[1] += 1
            total = done_counter[0] + done_counter[1]
        if total % 25 == 0 or total == len(cufes):
            cb(
                "progress",
                f"Progreso: {total}/{len(cufes)} "
                f"(OK={done_counter[0]}, errores={done_counter[1]})",
                current=total, total=len(cufes),
                ok=done_counter[0], err=done_counter[1],
            )

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        futures = [
            pool.submit(
                _run_cufe_chunk,
                chunk,
                token_url,
                output_recibidos,
                start_date,
                end_date,
                f"w{i+1}",
                wrapped_done,
                emit,
            )
            for i, chunk in enumerate(chunks)
        ]
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                cb("error", f"Worker explotó: {e}")

    duration = round(time.time() - t0, 1)
    summary = {
        "total_cufes": len(cufes),
        "ok": done_counter[0],
        "err": done_counter[1],
        "duration_s": duration,
        "workers": effective_workers,
    }
    cb(
        "success",
        f"Paralelo CUFE terminado: {done_counter[0]} OK, {done_counter[1]} errores en {duration}s.",
        **summary,
    )
    return summary
