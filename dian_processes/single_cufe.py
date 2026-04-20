"""
Descarga de un solo CUFE — operación atómica, sin checkpoint.

Es el caso más simple: el usuario pega UN CUFE, la app abre una sesión,
filtra, baja el archivo y cierra. No hay reintentos automáticos porque el
usuario está mirando la UI y puede reintentar manualmente.

Módulo NUEVO (no existe en el proyecto viejo). Reusa DianSession + DocumentsPage.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from playwright.sync_api import sync_playwright

from dian_core.config import SingleCufeConfig
from dian_core.documents_page import DocumentsPage
from dian_core.session import DianSession

CallbackT = Callable[..., None]


class SingleCufeDownloader:
    """Descarga un único CUFE del portal DIAN.

    Retorna ``{success: bool, filename: str|None, error: str|None}``.
    La UI muestra éxito/error inmediatamente al usuario.
    """

    def __init__(self, config: SingleCufeConfig, callback: Optional[CallbackT] = None) -> None:
        self.config = config
        self.callback = callback or self._default_callback

    def _default_callback(self, event_type: str, message: str, **kwargs) -> None:
        print(message)

    def _emit(self, event_type: str, message: str, **kwargs) -> None:
        self.callback(event_type, message, **kwargs)

    def run(self) -> dict:
        """Ejecuta la descarga. Bloquea hasta completar o fallar."""
        cufe = self.config.cufe.strip()
        if not cufe:
            self._emit("error", "CUFE vacío")
            return {"success": False, "filename": None, "error": "CUFE vacío"}

        output_dir = self.config.output_dir
        os.makedirs(output_dir, exist_ok=True)

        self._emit("status", f"▶ Descargando CUFE: {cufe[:20]}...")
        self._emit("status", f"  Destino: {output_dir}")

        with sync_playwright() as p:
            session = DianSession(self.config.session)
            try:
                session.start(p, on_progress=lambda m: self._emit("status", m))
            except Exception as e:
                msg = f"No se pudo iniciar sesión: {e}"
                self._emit("error", msg)
                return {"success": False, "filename": None, "error": msg}

            try:
                docs = DocumentsPage(
                    session.page,
                    wait_s=self.config.session.page_load_wait_s,
                    download_timeout_ms=self.config.session.download_timeout_ms,
                    on_progress=lambda m: self._emit("status", m),
                )
                docs.navigate()
                # DIAN exige filtro de fecha junto al de CUFE. Rango amplio
                # por defecto (configurable en SingleCufeConfig).
                docs.apply_date_filter(self.config.start_date, self.config.end_date)
                docs.apply_cufe_filter(cufe)

                rows = docs.get_rows()
                if not rows:
                    msg = "CUFE no encontrado en el portal"
                    self._emit("error", msg)
                    return {"success": False, "filename": None, "error": msg}

                # El portal puede listar varias filas (ej. notas asociadas).
                # Descargamos todas; la primera exitosa define 'filename'.
                first_file: Optional[str] = None
                any_success = False
                for i, row in enumerate(rows):
                    success, fname = docs.download_row(row, i, output_dir)
                    if success:
                        any_success = True
                        first_file = first_file or fname
                        self._emit(
                            "downloaded",
                            f"Descargado: {fname[:80]}",
                            filename=fname,
                        )

                if any_success:
                    self._emit(
                        "success",
                        f"CUFE descargado a {output_dir}",
                        filename=first_file,
                        output_dir=output_dir,
                    )
                    return {"success": True, "filename": first_file, "error": None}

                msg = "Se encontró el CUFE pero no se pudo descargar"
                self._emit("error", msg)
                return {"success": False, "filename": None, "error": msg}

            except Exception as e:
                msg = f"Error inesperado: {e}"
                self._emit("error", msg)
                return {"success": False, "filename": None, "error": msg}
            finally:
                session.close()
