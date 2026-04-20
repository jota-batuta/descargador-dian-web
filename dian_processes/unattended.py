"""
Orquestador del flujo desatendido (v3 — listado oficial DIAN como fuente de
verdad).

Endpoints backend de DIAN explotados:
- ``POST /Document/Export``              — descarga el Excel oficial DIAN.
- ``GET  /Document/GetFilePdf?cune=<CUFE>`` — descarga el .zip individual.

Pasos:
  0/3 — Detectar Excel previo del rango. Si existe, leer CUFEs Pendiente/Error
        y saltar directo al download (resume tras token-death o cierre).
  1/3 — ListadoExporter.run() → Excel oficial DIAN (32 cols, todas las facturas).
  2/3 — ListadoUpdater.init() → agrega columna "Estado de descarga", índice
        de CUFEs, todos a "Pendiente".
  3/3 — AJAX download secuencial + reintento de Pendiente/Error.

Si la sesión DIAN muere (timeout en Playwright), se levanta
``TokenExpiredError`` para que el controller QML abra el diálogo
"Token vencido". El re-run con nuevo token retoma desde el Excel persistido
sin volver a exportar.

# BUSINESS RULE: 100 % cobertura es el criterio de aceptación del MVP.
# El Excel oficial DIAN es la fuente de verdad (lo que un auditor reconoce).
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from dian_core.config import ListadoExportConfig, UnattendedConfig
from dian_processes.ajax_download import run_ajax_download
from dian_processes.date_sweep import TokenExpiredError
from dian_processes.listado_export import ListadoExporter
from dian_processes.listado_updater import ListadoUpdater

CallbackT = Callable[..., None]

# Empirical: ~5 docs/day across typical Colombian empresa mediana.
_DOCS_PER_DAY = 5


def _listado_path(output_listados: str, start_date: str, end_date: str) -> str:
    # Matches the filename that ListadoExporter._process_zip produces from
    # date_range "YYYY-MM-DD - YYYY-MM-DD": replace spaces → "YYYY-MM-DDYYYY-MM-DD".
    start_iso = start_date.replace("/", "-")
    end_iso = end_date.replace("/", "-")
    safe_dates = f"{start_iso} - {end_iso}".replace(" ", "")
    return str(Path(output_listados) / f"listado_{safe_dates}.xlsx")


def estimate_job(start_date: str, end_date: str) -> dict:
    """Estimador empírico para la advertencia UX antes de arrancar.

    Fase 1 Export (~5 min fijo) + descarga secuencial (~0.85 s/doc).
    Empirical: ~5 docs/day. Token DIAN dura ~63 min de uso continuo.

    Returns:
        ``{days, est_docs, est_minutes, warning}``
    """
    s = datetime.strptime(start_date, "%Y/%m/%d")
    e = datetime.strptime(end_date, "%Y/%m/%d")
    days = (e - s).days + 1
    est_docs = days * _DOCS_PER_DAY
    est_minutes = round(5 + est_docs * 0.85 / 60, 1)
    warning = ""
    if est_minutes > 50:
        warning = (
            f"Rango grande ({days} dias). Estimado: {est_minutes} min. "
            "El token DIAN dura ~60 min. Es probable que necesites pegar "
            "uno nuevo a mitad del proceso. La app retomara desde donde "
            "quedo sin volver a exportar el listado."
        )
    return {
        "days": days,
        "est_docs": est_docs,
        "est_minutes": est_minutes,
        "warning": warning,
    }


def _resume_from_excel(
    listado_path: str, cb: CallbackT
) -> Optional[tuple[ListadoUpdater, list[str], int]]:
    """Si existe un Excel previo del rango lo abrimos y leemos estado.

    Returns:
        ``(updater, pending_cufes, total_rows)`` o ``None`` si no hay Excel.
    """
    if not Path(listado_path).exists():
        return None
    cb("status", "[0/3] Excel previo encontrado — intentando resume sin re-exportar.")
    try:
        updater = ListadoUpdater(listado_path)
        pending = updater.init()
    except Exception as e:
        cb("status", f"  No se pudo abrir Excel previo ({e}); re-exportando desde DIAN.")
        return None
    cb(
        "status",
        f"  Excel tiene {updater.total_rows} CUFEs, {len(pending)} pendientes.",
    )
    return updater, pending, updater.total_rows


def run_unattended(
    config: UnattendedConfig,
    callback: Optional[CallbackT] = None,
) -> dict:
    """Ejecuta el flujo desatendido con listado oficial DIAN y resume desde Excel."""
    cb = callback or (lambda e, m, **kw: print(m))
    t0 = time.time()

    os.makedirs(config.output_listados, exist_ok=True)
    os.makedirs(config.output_recibidos, exist_ok=True)

    cb("status", "Preparando descarga desatendida (v3 listado oficial DIAN)")
    cb("status", f"  Listados:  {config.output_listados}")
    cb("status", f"  Recibidos: {config.output_recibidos}")
    cb("status", f"  Rango:     {config.start_date} -> {config.end_date}")
    cb(
        "step",
        "Preparando descarga desatendida",
        step=0, total_steps=3, step_name="Preparando", percent=0,
    )

    est = estimate_job(config.start_date, config.end_date)
    cb(
        "status",
        f"  Estimado:  {est['est_docs']} docs, {est['est_minutes']} min",
    )
    if est["warning"]:
        cb("status", est["warning"])

    listado_path = _listado_path(
        config.output_listados, config.start_date, config.end_date,
    )

    # ---------- Paso 0/3 — Resume desde Excel previo ----------
    resume = _resume_from_excel(listado_path, cb)

    updater: Optional[ListadoUpdater] = None
    pending_initial: list[str] = []
    total_records = 0
    skipped_export = False

    if resume is not None:
        updater, pending_initial, total_records = resume
        skipped_export = True

    if not skipped_export:
        # ---------- Paso 1/3 — Exportar listado oficial DIAN ----------
        cb("status", "[1/3] Exportando listado oficial DIAN (~5 min)...")
        cb(
            "step",
            "Exportando listado oficial DIAN",
            step=1, total_steps=3, step_name="Exportando listado DIAN",
            percent=0,
        )
        export_cfg = ListadoExportConfig(
            session=config.session,
            date_range=config.date_range_dian,
            output_dir=config.output_listados,
            document_type_index=3,  # Recibidos
        )
        export_result = ListadoExporter(export_cfg, callback=cb).run()
        if export_result.get("status") != "success":
            cb("error", "Fallo la exportacion del listado DIAN.")
            return {
                "status": "failed",
                "step": "listado_export",
                "listado": None,
                "total": 0, "ok": 0, "err": 0,
                "duration_s": round(time.time() - t0, 1),
            }

        # ---------- Paso 2/3 — Init updater sobre el Excel oficial ----------
        cb("status", "[2/3] Inicializando log de control en el Excel...")
        cb(
            "step",
            "Inicializando log de control",
            step=2, total_steps=3, step_name="Indexando Excel",
            percent=0,
        )
        updater = ListadoUpdater(listado_path)
        try:
            pending_initial = updater.init()
        except Exception as e:
            cb("error", f"No se pudo abrir el Excel para actualizar: {e}")
            return {
                "status": "failed",
                "step": "listado_updater_init",
                "listado": listado_path,
                "total": 0, "ok": 0, "err": 0,
                "duration_s": round(time.time() - t0, 1),
            }

        total_records = updater.total_rows
        if total_records == 0:
            updater.finish()
            cb("success", "DIAN no devolvio documentos en el rango.")
            return {
                "status": "success",
                "listado": listado_path,
                "total": 0, "ok": 0, "err": 0,
                "coverage_pct": 100.0,
                "duration_s": round(time.time() - t0, 1),
            }

        cb(
            "status",
            f"  {total_records} filas en el Excel, "
            f"{len(pending_initial)} pendientes de descarga.",
        )

    assert updater is not None

    if not pending_initial:
        updater.finish()
        cb("success", "Todo el listado ya esta descargado (resume completado).")
        return {
            "status": "success",
            "listado": listado_path,
            "total": updater.total_rows,
            "ok": updater.total_rows, "err": 0,
            "coverage_pct": 100.0,
            "duration_s": round(time.time() - t0, 1),
        }

    def on_cufe_done(cufe: Optional[str], ok: bool, error: Optional[str]) -> None:
        if cufe:
            updater.mark_downloaded(cufe, ok=ok, error=error)

    try:
        # ---------- Paso 3/3 — AJAX download + reintento ----------
        # Enrich each doc with the Excel row metadata so _safe_name can
        # build filenames like "FVE123_proveedor-SAS_<cufe12>.zip" instead
        # of "<cufe12>_<idx>.zip".
        documents_step3 = [
            {"Id": cufe, **updater.get_meta(cufe)} for cufe in pending_initial
        ]
        cb(
            "status",
            f"[3/3] Descargando {len(documents_step3)} documentos...",
        )
        cb(
            "step",
            f"Descargando {len(documents_step3)} documentos",
            step=3, total_steps=3, step_name="Descargando documentos",
            percent=0, current=0, total=len(documents_step3),
        )
        try:
            run_ajax_download(
                token_url=config.session.token_url,
                documents=documents_step3,
                output_recibidos=config.output_recibidos,
                on_done=on_cufe_done,
                callback=cb,
                workers=config.workers,
            )
        except Exception as e:
            msg = str(e).lower()
            if any(s in msg for s in ("timeout", "401", "403", "net::err_")):
                raise TokenExpiredError(
                    f"Token DIAN vencio durante descarga: {e}"
                ) from e
            raise

        remaining = updater.get_pending_cufes()
        cb(
            "status",
            f"  Reintento: {len(remaining)} CUFEs aun Pendiente/Error.",
        )
        if remaining:
            run_ajax_download(
                token_url=config.session.token_url,
                documents=[
                    {"Id": c, **updater.get_meta(c)} for c in remaining
                ],
                output_recibidos=config.output_recibidos,
                on_done=on_cufe_done,
                callback=cb,
                workers=max(1, config.workers // 2),
            )
        else:
            cb("success", "Descarga cubrió todo — sin reintento necesario.")

        final_counts = updater.status_counts()
    finally:
        cb("status", "Flush final del Excel de control...")
        updater.finish()

    duration = round(time.time() - t0, 1)
    ok_total = final_counts.get("Descargado", 0)
    err_total = final_counts.get("Error", 0)
    coverage_pct = round(100.0 * ok_total / max(1, updater.total_rows), 1)

    summary = {
        "status": "success" if err_total == 0 else "partial",
        "listado": listado_path,
        "total": updater.total_rows,
        "ok": ok_total,
        "err": err_total,
        "coverage_pct": coverage_pct,
        "duration_s": duration,
        "resumed": skipped_export,
    }
    cb(
        "step",
        "Descarga completa",
        step=3, total_steps=3, step_name="Descarga completa",
        percent=100,
    )
    cb(
        "job_done",
        f"Descarga desatendida terminada: {ok_total}/{updater.total_rows} OK "
        f"({coverage_pct}% cobertura), {err_total} con error. "
        f"Duracion: {duration}s.",
        **summary,
    )
    return summary
