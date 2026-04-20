"""AJAX download — descarga el ZIP de un documento llamando directo al
endpoint backend ``GET /Document/GetFilePdf?cune=<CUFE>``.

Aunque el endpoint se llama "GetFilePdf", devuelve un .zip con XML+PDF
(verificado por sniff: el primer documento de prueba bajó como zip de 51 KB).
Usar este endpoint en vez del click visual permite paralelismo masivo
(simple HTTP GET, sin re-aplicar filtros ni clickear botones).
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import sync_playwright

from dian_core.config import SessionConfig
from dian_core.session import DianSession
from dian_core.utils import sanitize_filename

CallbackT = Callable[..., None]
OnDone = Callable[[str, bool, Optional[str]], None]

DOWNLOAD_ENDPOINT = "https://catalogo-vpfe.dian.gov.co/Document/GetFilePdf?cune={cufe}"


def _pick_by_fragments(meta: dict, *fragment_groups: tuple[str, ...]) -> str:
    """Find the first non-empty meta value whose header matches any fragment.

    Each positional arg is a tuple of lowercase fragments — ALL must appear in
    the lowercase header for it to match. Multiple groups are tried in order.

    Example: ``_pick_by_fragments(meta, ("nombre", "emisor"), ("emisor",))``
    tries "Nombre Emisor" first, then falls back to a bare "Emisor" column.
    """
    lowered = {str(k).lower(): v for k, v in meta.items() if v is not None}
    for group in fragment_groups:
        for header, value in lowered.items():
            if all(frag in header for frag in group):
                s = str(value).strip()
                if s:
                    return s
    return ""


def _safe_name(meta: dict, cufe: str, idx: int) -> str:
    """Build a descriptive .zip filename from DIAN Excel row metadata.

    The official DIAN Recibidos Excel uses Spanish headers like
    ``"Prefijo"``, ``"Número"`` or ``"Folio"``, ``"Nombre Emisor"``,
    ``"NIT Emisor"``, ``"Fecha Emisión"``. Both Spanish and English keys
    are supported via fuzzy match.

    Output shape: ``<fecha>_<prefijo><folio>_<emisor>_<cufe12>.zip``
    Convention: Fecha-Factura-Proveedor
    """
    # Fecha de emisión del documento (YYYY-MM-DD).
    fecha_raw = _pick_by_fragments(
        meta,
        ("fecha", "emisi"),
        ("fecha", "documento"),
        ("fecha",),
        ("issuedate",),
        ("date",),
    )
    # Normalise to YYYY-MM-DD (DIAN often returns DD/MM/YYYY or YYYY-MM-DD).
    fecha = ""
    if fecha_raw:
        import re as _re
        m = _re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})", fecha_raw)
        if m:
            fecha = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            m2 = _re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", fecha_raw)
            if m2:
                fecha = f"{m2.group(3)}-{m2.group(2)}-{m2.group(1)}"

    # Prefijo / serie (e.g. "FVE", "FC").
    prefix = _pick_by_fragments(
        meta,
        ("prefijo",),
        ("documentnumber",),
        ("serieandnumber",),
    )

    # Folio / número de documento.
    folio = _pick_by_fragments(
        meta,
        ("folio",),
        ("número", "documento"),
        ("numero", "documento"),
        ("número",),
        ("numero",),
        ("documentnumber",),
    )

    # Nombre del emisor (preferido) o NIT del emisor (fallback).
    emisor = _pick_by_fragments(
        meta,
        ("nombre", "emisor"),
        ("razón", "social", "emisor"),
        ("razon", "social", "emisor"),
        ("sendername",),
        ("sender",),
        ("nit", "emisor"),
        ("emisor",),
    )[:40]

    parts = []
    if fecha:
        parts.append(fecha)
    if prefix and folio:
        parts.append(f"{prefix}{folio}")
    elif folio:
        parts.append(folio)
    elif prefix:
        parts.append(prefix)
    if emisor:
        parts.append(emisor)
    # CUFE prefix keeps names unique on same-day reissues.
    parts.append(cufe[:12])

    raw = "_".join(parts) if parts else cufe[:12]
    safe = sanitize_filename(re.sub(r"\s+", "_", raw))
    return f"{safe}.zip"


def _download_one(
    request,
    cufe: str,
    output_dir: str,
    meta: dict,
    idx: int,
) -> tuple[bool, Optional[str], str]:
    """Descarga 1 ZIP. Devuelve (ok, error, filename)."""
    url = DOWNLOAD_ENDPOINT.format(cufe=cufe)
    try:
        resp = request.get(url, timeout=60_000)
        if not resp.ok:
            return False, f"HTTP {resp.status}", ""
        body = resp.body()
        if not body or len(body) < 200:
            return False, f"respuesta vacía ({len(body)} bytes)", ""
        fname = _safe_name(meta, cufe, idx)
        out_path = Path(output_dir) / fname
        out_path.write_bytes(body)
        return True, None, fname
    except Exception as e:
        return False, str(e), ""


def run_ajax_download(
    token_url: str,
    documents: list[dict],
    output_recibidos: str,
    on_done: Optional[OnDone] = None,
    callback: Optional[CallbackT] = None,
    workers: int = 4,
) -> dict:
    """Descarga en paralelo todos los documentos vía endpoint AJAX.

    Args:
        token_url: URL DIAN con token.
        documents: lista de dicts retornada por ``ajax_index.fetch_index``.
            Cada dict debe tener al menos ``Id`` (CUFE 96 hex).
        output_recibidos: carpeta destino.
        on_done: callback ``(cufe, ok, error)`` por cada descarga.
        callback: callback de logs.
        workers: hilos paralelos (cada uno reusa la sesión Playwright;
            ``page.request`` libera el GIL durante I/O).

    Returns:
        ``{ok, err, total, duration_s}``.
    """
    cb = callback or (lambda e, m, **kw: print(m))
    notify = on_done or (lambda cufe, ok, err: None)

    t0 = time.time()
    os.makedirs(output_recibidos, exist_ok=True)

    cufes_meta = [
        (d.get("Id", "").strip().lower(), d)
        for d in documents
        if (d.get("Id") or "").strip()
    ]
    total = len(cufes_meta)
    if total == 0:
        cb("success", "AJAX download: nada que bajar.")
        return {"ok": 0, "err": 0, "total": 0, "duration_s": 0.0}

    cb(
        "status",
        f"▶ AJAX download: {total} documentos secuencial (page.request no es "
        "thread-safe; cada request tarda ~0.5 s).",
    )

    counters = {"ok": 0, "err": 0}
    cfg = SessionConfig(token_url=token_url, headless=True)

    with sync_playwright() as p:
        session = DianSession(cfg)
        try:
            session.start(p, on_progress=lambda m: cb("status", m))
        except Exception as e:
            raise RuntimeError(f"AJAX download no pudo iniciar sesión: {e}") from e

        try:
            request = session.page.request
            for idx, (cufe, meta) in enumerate(cufes_meta):
                ok, err, fname = _download_one(request, cufe, output_recibidos, meta, idx)
                notify(cufe, ok, err)
                if ok:
                    counters["ok"] += 1
                    cb("downloaded", f"  ok {fname[:80]}", filename=fname, cufe=cufe)
                else:
                    counters["err"] += 1
                    cb(
                        "worker_log",
                        f"  ✗ fallo {cufe[:20]}: {err}",
                        cufe=cufe, error=err or "",
                    )
                done = counters["ok"] + counters["err"]
                # Fine-grained step progress on every doc (used by the UI
                # progress bar). Summary log line only every 25 docs.
                cb(
                    "step",
                    "",  # no log line — only the bar updates
                    step=3, total_steps=3,
                    step_name="Descargando documentos",
                    current=done, total=total,
                    percent=int(round(100 * done / max(1, total))),
                    ok=counters["ok"], err=counters["err"],
                )
                if done % 25 == 0 or done == total:
                    cb(
                        "progress",
                        f"AJAX dl: {done}/{total} (OK={counters['ok']}, err={counters['err']})",
                        current=done, total=total,
                        ok=counters["ok"], err=counters["err"],
                    )
        finally:
            session.close()

    duration = round(time.time() - t0, 1)
    summary = {
        "ok": counters["ok"],
        "err": counters["err"],
        "total": total,
        "duration_s": duration,
    }
    cb(
        "success",
        f"AJAX download terminado: {counters['ok']}/{total} OK, "
        f"{counters['err']} err en {duration}s.",
        **summary,
    )
    return summary
