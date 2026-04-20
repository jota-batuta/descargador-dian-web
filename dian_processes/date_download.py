"""
Descarga por rango de fechas — baja TODAS las facturas recibidas en el rango.

Usa paginación (DIAN limita a 100 filas/página), checkpoint para reanudar, y
un circuit-breaker: si una página arroja 4+ errores consecutivos, cierra la
sesión y la reabre. Máximo N reinicios antes de rendirse.

Upgrades vs original:
- Progress callback granular: emite en cada paso del arranque (~5-15 s) para
  que la UI no parezca colgada.
- ``go_to_next_page`` detecta cambio REAL de página (no blind sleep).
- Detecta 2 páginas consecutivas sin descargas-y-sin-errores y rompe el loop
  (evita bucle infinito si DIAN no avanza).
"""

from __future__ import annotations

import os
import re
import time
from typing import Callable, Optional

from playwright.sync_api import sync_playwright

from dian_core.checkpoint import DateCheckpoint
from dian_core.config import DateDownloadConfig
from dian_core.documents_page import DocumentsPage
from dian_core.session import DianSession
from dian_core.utils import sanitize_filename

# BUSINESS RULE: 4 fue el valor que balanceó tolerancia con progreso en el
# proyecto viejo; menor → demasiados reinicios; mayor → desperdicia tiempo.
_ERROR_THRESHOLD = 4

CallbackT = Callable[..., None]


class DateDownloader:
    """Descarga todas las facturas de un rango de fechas."""

    def __init__(self, config: DateDownloadConfig, callback: Optional[CallbackT] = None) -> None:
        self.config = config
        self.callback = callback or self._default_callback

    def _default_callback(self, event_type: str, message: str, **kwargs) -> None:
        print(message)

    def _emit(self, event_type: str, message: str, **kwargs) -> None:
        self.callback(event_type, message, **kwargs)

    def _status(self, message: str, **kwargs) -> None:
        """Shortcut para emitir status."""
        self._emit("status", message, **kwargs)

    def run(self) -> dict:
        """Ejecuta la descarga completa. Retorna ``{total_downloaded, output_dir}``."""
        output_dir = self.config.output_dir
        os.makedirs(output_dir, exist_ok=True)

        # Emitir DE INMEDIATO para que el usuario vea actividad — el arranque
        # del browser toma 5-15 s y antes no había ningún log.
        self._status("▶ Preparando descarga...")
        self._status(f"  Rango: {self.config.start_date} → {self.config.end_date}")
        self._status(f"  Destino: {output_dir}")

        checkpoint = DateCheckpoint(self.config.checkpoint_file)
        if checkpoint.total > 0:
            self._status(f"  Checkpoint: {checkpoint.total} archivos previamente descargados (se saltan)")

        session_attempts = 0
        all_done = False

        while session_attempts < self.config.max_session_restarts:
            session_attempts += 1
            if session_attempts > 1:
                self._status(f"Reintentando sesión ({session_attempts}/{self.config.max_session_restarts})...")

            with sync_playwright() as p:
                session = DianSession(self.config.session)
                try:
                    session.start(p, on_progress=self._status)
                except Exception as e:
                    self._emit("error", f"No se pudo iniciar sesión: {e}")
                    break

                try:
                    docs = DocumentsPage(
                        session.page,
                        wait_s=self.config.session.page_load_wait_s,
                        download_timeout_ms=self.config.session.download_timeout_ms,
                        on_progress=self._status,
                    )
                    docs.navigate()
                    docs.apply_date_filter(self.config.start_date, self.config.end_date)
                    docs.set_page_size(self.config.page_size)

                    info_text, total = docs.get_page_info()
                    if total is not None:
                        self._emit(
                            "progress",
                            f"Total de facturas en el rango: {total}",
                            total=total,
                        )
                    elif info_text:
                        self._status(f"DIAN: {info_text}")

                    page_num = 1
                    empty_pages = 0  # páginas seguidas sin descargas ni errores

                    while True:
                        self._status(f"── Página {page_num} ──")
                        rows = docs.get_rows()
                        if not rows:
                            self._status("No hay documentos en esta página.")
                            break

                        downloaded, errors = self._process_rows(
                            rows, docs, checkpoint, output_dir
                        )

                        self._status(
                            f"Página {page_num}: {downloaded} descargados, {errors} errores "
                            f"(total acumulado: {checkpoint.total})"
                        )

                        if errors >= _ERROR_THRESHOLD:
                            self._status("Demasiados errores en esta página, reiniciando sesión...")
                            break

                        # Detecta estancamiento: 2 páginas sin trabajo nuevo
                        if downloaded == 0 and errors == 0:
                            empty_pages += 1
                        else:
                            empty_pages = 0

                        if empty_pages >= 2:
                            self._status("2 páginas sin trabajo nuevo — fin del rango.")
                            all_done = True
                            break

                        if not docs.go_to_next_page():
                            self._status("✓ Última página alcanzada.")
                            all_done = True
                            break

                        page_num += 1

                    if all_done:
                        session_attempts = self.config.max_session_restarts

                except Exception as e:
                    self._emit("error", f"Error inesperado: {e}")
                finally:
                    session.close()

        summary = {"total_downloaded": checkpoint.total, "output_dir": output_dir}
        self._emit(
            "success",
            f"Descarga completa: {checkpoint.total} archivos en {output_dir}",
            **summary,
        )
        return summary

    # ---------- helpers ----------

    def _process_rows(self, rows, docs, checkpoint, output_dir) -> tuple[int, int]:
        """Descarga las filas pendientes de la página actual. Retorna (ok, err)."""
        downloaded = 0
        errors = 0
        for i, row in enumerate(rows):
            try:
                row_text = row.inner_text()
                clean = re.sub(r"\s+", "_", row_text).strip()
                filename = f"{sanitize_filename(clean)}_{i}.zip"
            except Exception:
                filename = f"unknown_{i}.zip"

            if checkpoint.is_downloaded(filename):
                continue

            success, fname = docs.download_row(row, i, output_dir)
            if success:
                checkpoint.mark_downloaded(fname)
                checkpoint.save()
                downloaded += 1
                self._emit(
                    "downloaded",
                    f"  ✓ [{checkpoint.total}] {fname[:90]}",
                    filename=fname,
                    total=checkpoint.total,
                )
                time.sleep(1)
            else:
                errors += 1
                self._status(f"  ✗ fallo: {fname[:90]}")
        return downloaded, errors
