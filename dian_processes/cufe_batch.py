"""
Descarga por lote de CUFEs — itera una lista leída desde .txt/.md/.xlsx.

Por cada CUFE: filtra en el portal, descarga si aparece, marca Done/Error en
el checkpoint. Circuit-breaker: tras N errores consecutivos reinicia la sesión.

Heredado del proyecto viejo con imports adaptados.
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional

from playwright.sync_api import sync_playwright

from dian_core.checkpoint import CufeCheckpoint
from dian_core.config import CufeBatchConfig
from dian_core.documents_page import DocumentsPage
from dian_core.session import DianSession
from dian_core.utils import parse_cufe_file

CallbackT = Callable[..., None]


class CufeBatchDownloader:
    """Descarga en lote los CUFEs listados en un archivo."""

    def __init__(self, config: CufeBatchConfig, callback: Optional[CallbackT] = None) -> None:
        self.config = config
        self.callback = callback or self._default_callback

    def _default_callback(self, event_type: str, message: str, **kwargs) -> None:
        print(message)

    def _emit(self, event_type: str, message: str, **kwargs) -> None:
        self.callback(event_type, message, **kwargs)

    def run(self) -> dict:
        """Ejecuta la descarga en lote. Retorna summary del checkpoint."""
        output_dir = self.config.output_dir
        os.makedirs(output_dir, exist_ok=True)

        cufes = parse_cufe_file(self.config.cufe_file)
        if not cufes:
            self._emit("error", f"No CUFEs found in '{self.config.cufe_file}'")
            return {"total": 0, "done": 0, "pending": 0, "error": 0}

        checkpoint = CufeCheckpoint(self.config.checkpoint_file)
        checkpoint.initialize(cufes)

        self._emit("status", f"Loaded {len(cufes)} CUFEs")
        self._emit("status", f"Output: {output_dir}")

        while True:
            pending = checkpoint.get_pending()
            if not pending:
                self._emit("status", "¡Todos los CUFEs procesados!")
                break

            self._emit("progress", f"Lote: {len(pending)} CUFEs pendientes", pending=len(pending))

            with sync_playwright() as p:
                session = DianSession(self.config.session)
                try:
                    session.start(p, on_progress=lambda m: self._emit("status", m))
                except Exception as e:
                    self._emit("error", f"Failed to init session: {e}")
                    self._emit("error", "El token DIAN podría haber expirado.")
                    break

                try:
                    docs = DocumentsPage(
                        session.page,
                        wait_s=self.config.session.page_load_wait_s,
                        download_timeout_ms=self.config.session.download_timeout_ms,
                        on_progress=lambda m: self._emit("status", m),
                    )
                    docs.navigate()
                    docs.apply_date_filter(self.config.start_date, self.config.end_date)
                    docs.set_page_size(100)

                    consecutive_errors = 0
                    need_restart = False

                    for cufe in pending:
                        checkpoint.increment_attempts(cufe)

                        try:
                            self._emit("status", f"Processing CUFE: {cufe[:20]}...")
                            docs.apply_cufe_filter(cufe)
                            rows = docs.get_rows()

                            if not rows:
                                checkpoint.mark_error(cufe, "Not found in search")
                                consecutive_errors += 1
                            else:
                                any_success = False
                                for i, row in enumerate(rows):
                                    success, fname = docs.download_row(row, i, output_dir)
                                    if success:
                                        self._emit(
                                            "downloaded",
                                            f"  Downloaded: {fname[:80]}",
                                            filename=fname,
                                        )
                                        any_success = True
                                        time.sleep(2)

                                if any_success:
                                    checkpoint.mark_done(cufe)
                                    consecutive_errors = 0
                                else:
                                    checkpoint.mark_error(cufe, "Download button not found")
                                    consecutive_errors += 1

                        except Exception as e:
                            self._emit("error", f"  Error on CUFE {cufe[:10]}: {e}")
                            checkpoint.mark_error(cufe, str(e))
                            consecutive_errors += 1

                        checkpoint.save()

                        if consecutive_errors >= self.config.max_consecutive_errors:
                            self._emit(
                                "status",
                                f"{self.config.max_consecutive_errors} consecutive errors. Restarting session...",
                            )
                            need_restart = True
                            break

                    if not need_restart:
                        break  # All pending processed without circuit-breaker

                except Exception as e:
                    self._emit("error", f"Unexpected error: {e}")
                    break
                finally:
                    session.close()

        summary = checkpoint.summary()
        self._emit(
            "success",
            f"Done! {summary['done']}/{summary['total']} downloaded",
            **summary,
        )
        return summary
