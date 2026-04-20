"""Sweep secuencial por sub-rangos (Etapa 1 del flujo desatendido).

Diseño: 1 sesión Playwright. El rango total se divide en sub-rangos chicos
(default 7 días) y cada uno se procesa secuencialmente: aplicar filtro, set
page_size=100, iterar todas las páginas, descargar.

Por qué sub-rangos pequeños:
- DataTables 2.x de DIAN tiene un bug en la paginación cuando hay >100 filas:
  páginas 2 y siguientes pueden traer ~50 filas en vez de 100, perdiendo
  hasta el 20% de las facturas (verificado: 439/539 en Q1 2026).
- Si el sub-rango se elige chico (semanal), casi siempre cae en 1-2 páginas
  donde el bug no aparece o es marginal.

Por qué NO N sesiones paralelas:
- DIAN limita 1 sesión activa por token URL — múltiples sesiones se invalidan
  entre sí. La paralelización útil se hace en la Etapa 2 (reintento por CUFE).

Por cada fila descargada:
1. Extrae el CUFE del atributo ``data-id`` del botón download.
2. Llama ``download_row()`` para bajar el .zip.
3. Invoca ``on_row_done(cufe, ok, error)`` — el orquestador wireea esto a
   ``ListadoUpdater.mark_downloaded`` (thread-safe).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from playwright.sync_api import sync_playwright

from dian_core.config import SessionConfig
from dian_core.documents_page import DocumentsPage
from dian_core.session import DianSession

CallbackT = Callable[..., None]
OnRowDone = Callable[[Optional[str], bool, Optional[str]], None]


class TokenExpiredError(RuntimeError):
    """El token URL DIAN venció o el portal no responde — el usuario debe
    pegar uno nuevo."""


def _generate_subranges(
    start_date: str, end_date: str, days_per_subrange: int
) -> list[tuple[str, str]]:
    """Divide [start, end] en ventanas contiguas de N días en formato YYYY/MM/DD."""
    start_dt = datetime.strptime(start_date, "%Y/%m/%d")
    end_dt = datetime.strptime(end_date, "%Y/%m/%d")
    subs: list[tuple[str, str]] = []
    current = start_dt
    while current <= end_dt:
        sub_end = min(current + timedelta(days=days_per_subrange - 1), end_dt)
        subs.append(
            (current.strftime("%Y/%m/%d"), sub_end.strftime("%Y/%m/%d"))
        )
        current = sub_end + timedelta(days=1)
    return subs


def _process_subrange(
    docs: DocumentsPage,
    sub_start: str,
    sub_end: str,
    output_recibidos: str,
    on_row_done: OnRowDone,
    cb: CallbackT,
    page_size: int,
    counters: dict,
) -> None:
    """Procesa un sub-rango: filtro de fechas + iterar páginas + descargar."""
    cb("status", f"  sub-rango {sub_start} → {sub_end}: aplicando filtro...")
    docs.apply_date_filter(sub_start, sub_end)
    docs.set_page_size(page_size)

    sub_pages = 0
    while True:
        sub_pages += 1
        rows = docs.get_rows()
        if not rows:
            break
        cb("status", f"    página {sub_pages}: {len(rows)} filas")

        for i, row in enumerate(rows):
            cufe = docs.extract_cufe(row)
            if cufe is None:
                counters["no_cufe"] += 1
            try:
                success, fname = docs.download_row(row, i, output_recibidos)
            except Exception as e:
                on_row_done(cufe, False, f"download_row exception: {e}")
                counters["err"] += 1
                continue

            if success:
                counters["ok"] += 1
                on_row_done(cufe, True, None)
                cb(
                    "downloaded",
                    f"    ok {fname[:80]}",
                    filename=fname, cufe=cufe or "",
                )
            else:
                counters["err"] += 1
                on_row_done(cufe, False, "download_row returned False")

            done = counters["ok"] + counters["err"]
            if done % 25 == 0:
                cb(
                    "progress",
                    f"Sweep: {done} filas procesadas (OK={counters['ok']}, err={counters['err']})",
                    current=done, ok=counters["ok"], err=counters["err"],
                )

        if not docs.go_to_next_page():
            break

    counters["pages"] += sub_pages


def run_date_sweep(
    token_url: str,
    start_date: str,
    end_date: str,
    output_recibidos: str,
    on_row_done: Optional[OnRowDone] = None,
    callback: Optional[CallbackT] = None,
    page_size: int = 100,
    days_per_subrange: int = 7,
) -> dict:
    """Ejecuta el sweep secuencial por sub-rangos sobre el rango de fechas.

    Args:
        token_url: URL DIAN con token.
        start_date, end_date: ``YYYY/MM/DD``.
        output_recibidos: carpeta destino para los .zip.
        on_row_done: callback ``(cufe, ok, error)`` por cada fila.
        callback: callback de logs ``(event_type, message, **kwargs)``.
        page_size: filas por página (max 100 en DIAN, default 100).
        days_per_subrange: tamaño de los sub-rangos en días (default 7 =
            semanal). Sub-rangos chicos evitan el bug de paginación de DT
            2.x cuando hay >100 filas.

    Returns:
        ``{ok, err, no_cufe, total, pages, subranges, duration_s, fatal}``.

    Raises:
        TokenExpiredError: si el token DIAN no responde al cargar la página
        de Recibidos (sesión inválida o vencida).
    """
    cb = callback or (lambda e, m, **kw: print(m))
    on_done = on_row_done or (lambda cufe, ok, err: None)

    t0 = time.time()
    os.makedirs(output_recibidos, exist_ok=True)

    subranges = _generate_subranges(start_date, end_date, days_per_subrange)
    cb(
        "status",
        f"▶ Sweep secuencial {start_date} → {end_date} en {len(subranges)} "
        f"sub-rangos de {days_per_subrange} días.",
    )

    counters = {"ok": 0, "err": 0, "no_cufe": 0, "pages": 0}
    session_cfg = SessionConfig(token_url=token_url, headless=True)

    with sync_playwright() as p:
        session = DianSession(session_cfg)
        try:
            session.start(p, on_progress=lambda m: cb("status", m))
        except Exception as e:
            cb("error", f"Sweep no pudo iniciar sesión: {e}")
            raise TokenExpiredError(
                f"No se pudo iniciar sesión con el token DIAN: {e}"
            ) from e

        try:
            docs = DocumentsPage(
                session.page,
                wait_s=session_cfg.page_load_wait_s,
                download_timeout_ms=session_cfg.download_timeout_ms,
                on_progress=lambda m: cb("status", m),
            )
            try:
                docs.navigate()
                # Verificación temprana: si #dashboard-report-range no carga
                # en 30s, el token está muerto o DIAN no responde — abortar
                # con error específico que el caller traduce a UX clara.
                session.page.wait_for_selector(docs.SEL_DATE_RANGE, timeout=30000)
            except Exception as e:
                raise TokenExpiredError(
                    "El portal DIAN no respondió. Probablemente el token "
                    "venció (los tokens DIAN viven ~1 hora). Pegá uno nuevo."
                ) from e

            for s, e in subranges:
                _process_subrange(
                    docs, s, e, output_recibidos,
                    on_done, cb, page_size, counters,
                )
        finally:
            session.close()

    duration = round(time.time() - t0, 1)
    summary = {
        "ok": counters["ok"],
        "err": counters["err"],
        "no_cufe": counters["no_cufe"],
        "total": counters["ok"] + counters["err"],
        "pages": counters["pages"],
        "subranges": len(subranges),
        "duration_s": duration,
        "fatal": None,
    }
    cb(
        "success",
        f"Sweep terminado: {counters['ok']} OK, {counters['err']} err, "
        f"{counters['no_cufe']} sin CUFE en {counters['pages']} páginas "
        f"de {len(subranges)} sub-rangos, {duration}s.",
        **summary,
    )
    return summary
