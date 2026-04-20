"""
Exportador del Listado Excel desde DIAN.

Usa la página ``/Document/Export`` para generar un ZIP con el Excel de TODAS
las facturas del rango. El Excel se usa después para:
  - Cruzar contra los ZIP descargados y generar el reporte de faltantes.
  - Auditorías contables donde el cliente necesita la lista oficial DIAN.

Heredado del proyecto viejo con import adaptados y callback de progreso.
"""

from __future__ import annotations

import os
import time
import zipfile
from typing import Callable, Optional

import openpyxl
from playwright.sync_api import sync_playwright

from dian_core.config import ListadoExportConfig
from dian_core.session import DianSession
from dian_core.utils import DIAN_EXPORT_URL

CallbackT = Callable[..., None]


class ListadoExporter:
    """Exporta el listado Excel del portal DIAN (página Export)."""

    def __init__(self, config: ListadoExportConfig, callback: Optional[CallbackT] = None) -> None:
        self.config = config
        self.callback = callback or self._default_callback

    def _default_callback(self, event_type: str, message: str, **kwargs) -> None:
        print(message)

    def _emit(self, event_type: str, message: str, **kwargs) -> None:
        self.callback(event_type, message, **kwargs)

    def _status(self, message: str) -> None:
        self._emit("status", message)

    def run(self) -> dict:
        """Ejecuta el flujo completo. Retorna ``{status, file}``."""
        os.makedirs(self.config.output_dir, exist_ok=True)

        self._status(f"▶ Generando listado Excel DIAN")
        self._status(f"  Tipo doc: {self.config.document_type_index} (3=Recibidos)")
        self._status(f"  Rango: {self.config.date_range}")
        self._status(f"  Destino: {self.config.output_dir}")

        with sync_playwright() as p:
            session = DianSession(self.config.session)
            try:
                session.start(p, on_progress=self._status)
                self._navigate_to_export(session.page)
                self._configure_export(session.page)
                self._trigger_export(session.page)
                result_path = self._poll_and_download(session.page)

                if result_path:
                    self._emit(
                        "success",
                        f"Listado descargado: {result_path}",
                        file=result_path,
                    )
                    return {"status": "success", "file": result_path}

                self._emit("error", "El listado no estuvo listo antes del timeout.")
                return {"status": "error", "file": None}

            except Exception as e:
                self._emit("error", f"Error fatal: {e}")
                return {"status": "error", "file": None}
            finally:
                session.close()

    # ---------- steps ----------

    def _navigate_to_export(self, page) -> None:
        self._status("Navegando a la página Export...")
        page.goto(DIAN_EXPORT_URL, wait_until="domcontentloaded", timeout=30000)

        try:
            page.wait_for_selector("#export-range", timeout=15000)
            self._status("Página Export cargada.")
            return
        except Exception:
            pass

        # Fallback: navegar desde el menú
        self._status("Navegación directa falló, intentando desde el menú...")
        page.goto("https://catalogo-vpfe.dian.gov.co/", wait_until="domcontentloaded")
        time.sleep(2)

        for sel_click in ("#mainnav-toggle", "#DocumentIndex", "#DocumentExport > a"):
            el = page.query_selector(sel_click)
            if el:
                el.click()
                time.sleep(1)

        page.wait_for_selector("#export-range", timeout=15000)

    def _configure_export(self, page) -> None:
        # El form real submitea HIDDEN inputs (#StartDate, #EndDate, #Type,
        # GroupCode via #filter-groups). El daterangepicker sobre #export-range
        # es SOLO decorativo — #export-range no tiene atributo name, así que
        # su value jamás viaja al server. El <select id="filter-groups">
        # también está oculto por bootstrap-select y sus options son:
        #     value="0" → Todos
        #     value="1" → Emitidos
        #     value="2" → Recibidos
        # El fix confiable es bypassear ambos widgets y escribir directamente
        # los inputs hidden que el form submitea. Verificado empíricamente
        # 2026-04-20 interceptando el POST /Document/Export: los métodos
        # "correctos vía UI" (keyboard.type sobre daterangepicker,
        # select_option con el label "Recibidos") dejaban StartDate/EndDate
        # con el default del mes corriente y GroupCode=0 (Todos).
        history_to_groupcode = {2: "1", 3: "2"}  # 2=Emitidos, 3=Recibidos
        group_code = history_to_groupcode.get(
            self.config.document_type_index, "2"
        )
        start_str, _, end_str = self.config.date_range.partition(" - ")
        self._status(
            f"Configurando: GroupCode={group_code} "
            f"(index={self.config.document_type_index}), "
            f"StartDate={start_str}, EndDate={end_str}"
        )

        applied = page.evaluate(
            """(args) => {
                // Formato que DIAN espera en los hidden: "M/d/YYYY h:mm:ss AM/PM"
                // (US invariant). Start a 12:00:00 AM, End a 11:59:59 PM para
                // que el rango incluya el día entero.
                function toUS(iso, isEnd) {
                    const [y, m, d] = iso.split('-').map(Number);
                    if (isEnd) return `${m}/${d}/${y} 11:59:59 PM`;
                    return `${m}/${d}/${y} 12:00:00 AM`;
                }
                const sd = document.querySelector('#StartDate');
                const ed = document.querySelector('#EndDate');
                const fg = document.querySelector('#filter-groups');
                const disp = document.querySelector('#export-range');
                if (!sd || !ed || !fg) {
                    return {error: 'hidden inputs no encontrados: ' +
                        JSON.stringify({sd: !!sd, ed: !!ed, fg: !!fg})};
                }
                sd.value = toUS(args.start, false);
                ed.value = toUS(args.end, true);
                fg.value = args.group;
                // change para que cualquier handler escuchando re-pinte.
                fg.dispatchEvent(new Event('change', {bubbles: true}));
                // Sincronizar el input visible (mejor UX en headed; no afecta POST).
                if (disp) disp.value = args.start + ' - ' + args.end;
                return {
                    StartDate: sd.value,
                    EndDate: ed.value,
                    GroupCode: fg.value,
                    display: disp ? disp.value : null,
                };
            }""",
            {"start": start_str, "end": end_str, "group": group_code},
        )
        if isinstance(applied, dict) and applied.get("error"):
            raise RuntimeError(
                f"No se pudieron setear los inputs del form Export: "
                f"{applied['error']}"
            )
        self._status(f"Form configurado: {applied}")
        time.sleep(1)

    def _trigger_export(self, page) -> None:
        self._status("Disparando export...")

        export_btn = page.query_selector("div.panel-footer-grey > button")
        if not export_btn:
            export_btn = page.query_selector("button:has-text('Exportar Excel')")
        if not export_btn:
            raise RuntimeError("Botón 'Exportar Excel' no encontrado")

        export_btn.scroll_into_view_if_needed()
        export_btn.click()
        time.sleep(2)

        # Modal de confirmación (a veces no aparece)
        try:
            confirm = page.wait_for_selector("#confirmModal-confirm-button", timeout=10000)
            confirm.click()
            self._status("Export confirmado.")
        except Exception:
            self._status("(No apareció modal de confirmación)")

        self._status(
            f"DIAN procesando en su servidor. Esperando {self.config.export_wait_s}s "
            f"antes de empezar a pollear..."
        )
        time.sleep(self.config.export_wait_s)

    def _poll_and_download(self, page):
        self._status(f"Polling (max {self.config.max_poll_retries} intentos)...")

        for attempt in range(1, self.config.max_poll_retries + 1):
            try:
                page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception:
                continue
            time.sleep(3)

            icon = page.query_selector("#tableExport tbody tr td:nth-of-type(8) a i")
            if not icon:
                icon = page.query_selector("#tableExport tbody tr td a i")

            if icon:
                self._status("¡Listado listo! Descargando ZIP...")
                link = icon.evaluate_handle("el => el.closest('a')").as_element()
                if not link:
                    link = page.query_selector("#tableExport tbody tr td:nth-of-type(8) a")
                if not link:
                    continue

                with page.expect_download(timeout=60000) as dl:
                    link.scroll_into_view_if_needed()
                    link.click()

                zip_name = f"temp_listado_{int(time.time())}.zip"
                zip_path = os.path.join(self.config.output_dir, zip_name)
                dl.value.save_as(zip_path)
                return self._process_zip(zip_path)

            self._status(f"  (esperando — intento {attempt}/{self.config.max_poll_retries})")
            time.sleep(self.config.poll_interval_s)

        return None

    def _process_zip(self, zip_path: str):
        """Descomprime el ZIP, renombra el Excel y la hoja."""
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(self.config.output_dir)
                files = z.namelist()

            excel_file = next(
                (f for f in files if f.lower().endswith((".xlsx", ".xls"))), None
            )
            if not excel_file:
                self._emit("error", "El ZIP no contenía Excel.")
                return None

            src = os.path.join(self.config.output_dir, excel_file)
            safe_dates = self.config.date_range.replace(" ", "").replace("/", "-")
            dst = os.path.join(self.config.output_dir, f"listado_{safe_dates}.xlsx")

            if os.path.exists(dst):
                os.remove(dst)
            os.rename(src, dst)

            # Renombrar la primera hoja a "REPORTE" (convención del proyecto viejo)
            wb = openpyxl.load_workbook(dst)
            if wb.sheetnames:
                wb.active.title = "REPORTE"
                wb.save(dst)

            try:
                os.remove(zip_path)
            except Exception:
                pass

            return dst
        except Exception as e:
            self._emit("error", f"Error procesando ZIP: {e}")
            return None
