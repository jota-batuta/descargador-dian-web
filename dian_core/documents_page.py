"""
Page Object para la página Documentos Recibidos del portal DIAN.

Encapsula los selectores CSS y las interacciones con el DOM. Separarlo de la
lógica de descarga permite que cuando DIAN cambie su HTML (ocurre cada 6-12
meses) se toque SOLO este archivo.

Heredado del proyecto viejo con estos upgrades:
- ``set_page_size`` default 100 (máx de DIAN, mitad de clicks Siguiente)
- ``go_to_next_page`` detecta CAMBIO real de página (no blind sleep)
- Hooks de progreso opcionales para que la UI muestre actividad durante los
  waits largos (autenticación, filtrado, re-paginación).
"""

from __future__ import annotations

import os
import re
import time
from typing import Callable, Optional

from dian_core.utils import DIAN_RECEIVED_URL, sanitize_filename

ProgressCb = Callable[[str], None]


class DocumentsPage:
    """Interacciones con la página Documentos Recibidos del portal DIAN.

    Todos los selectores CSS viven aquí. Si DIAN rompe la UI, cambiar sólo esta
    clase.
    """

    # --- Selectores (cambiar aquí si DIAN actualiza su UI) ---
    SEL_DATE_RANGE = "#dashboard-report-range"
    SEL_CUFE_INPUT = "#DocumentKey"
    SEL_SEARCH_BUTTON = "button:has-text('Buscar')"
    SEL_TABLE_ROWS = "table#tableDocuments tbody tr"
    SEL_TABLE_INFO = "#tableDocuments_info"
    SEL_NEXT_PAGE = "#tableDocuments_next"
    SEL_PAGE_SIZE = 'select[name="tableDocuments_length"]'
    SEL_DOWNLOAD_BUTTON = (
        'a[title="Descargar elementos"], '
        'i[title="Descargar elementos"], '
        'button[title="Descargar elementos"]'
    )

    def __init__(
        self,
        page,
        wait_s: int = 5,
        download_timeout_ms: int = 30000,
        on_progress: Optional[ProgressCb] = None,
    ) -> None:
        self.page = page
        self.wait_s = wait_s
        self.download_timeout_ms = download_timeout_ms
        self._emit = on_progress or (lambda _m: None)

    def navigate(self) -> None:
        """Navega a /Document/Received."""
        self._emit("Cargando tabla de documentos recibidos...")
        self.page.goto(DIAN_RECEIVED_URL, wait_until="domcontentloaded")

    def extract_cufe(self, row) -> Optional[str]:
        """Extrae el CUFE (96 hex chars) de la fila.

        El CUFE no está en el texto visible de la fila — está en el atributo
        ``data-id`` del botón de descarga interno (verificado por DOM
        inspection: ``<button class="download-document" data-id="...">`` para
        facturas, y ``download-support-document`` para documentos soporte).

        Fallback: si no hay button[data-id], busca el primer hex de 96 chars
        en cualquier atributo de la fila vía regex sobre el HTML.
        """
        try:
            btn = row.query_selector("button[data-id]")
            if btn:
                cufe = btn.get_attribute("data-id") or ""
                if re.fullmatch(r"[0-9a-f]{96}", cufe, re.IGNORECASE):
                    return cufe.lower()
            # Fallback HTML scan
            html = row.inner_html()
            m = re.search(r"[0-9a-f]{96}", html, re.IGNORECASE)
            return m.group(0).lower() if m else None
        except Exception:
            return None

    def apply_date_filter(self, start_date: str, end_date: str) -> None:
        """Establece rango de fechas y dispara la búsqueda.

        Args:
            start_date: YYYY/MM/DD
            end_date: YYYY/MM/DD
        """
        self._emit(f"Aplicando filtro de fechas {start_date} → {end_date}...")
        self.page.wait_for_selector(self.SEL_DATE_RANGE)
        self.page.click(self.SEL_DATE_RANGE)
        self.page.keyboard.press("Control+a")
        self.page.keyboard.press("Delete")
        self.page.keyboard.type(f"{start_date} - {end_date}")
        self.page.keyboard.press("Enter")
        time.sleep(self.wait_s)

        try:
            cufe_input = self.page.query_selector(self.SEL_CUFE_INPUT)
            if cufe_input:
                cufe_input.fill("")
        except Exception:
            pass

        search_btn = self.page.query_selector(self.SEL_SEARCH_BUTTON)
        if search_btn:
            self._emit("Ejecutando búsqueda en el portal...")
            search_btn.click()
            time.sleep(self.wait_s + 2)

    def apply_cufe_filter(self, cufe: str) -> None:
        """Filtra por CUFE específico."""
        self._emit(f"Buscando CUFE {cufe[:20]}...")
        self.page.wait_for_selector(self.SEL_CUFE_INPUT)
        self.page.fill(self.SEL_CUFE_INPUT, "")
        self.page.fill(self.SEL_CUFE_INPUT, cufe)

        search_btn = self.page.query_selector(self.SEL_SEARCH_BUTTON)
        if search_btn:
            search_btn.click()
        time.sleep(self.wait_s + 2)

    def clear_cufe_filter(self) -> None:
        """Vacía el input de CUFE."""
        try:
            cufe_input = self.page.query_selector(self.SEL_CUFE_INPUT)
            if cufe_input:
                cufe_input.fill("")
        except Exception:
            pass

    def set_page_size(self, size: int = 100) -> bool:
        """Elige cuántas filas mostrar por página (max 100 en DIAN).

        El ``<select>`` real de DIAN no tiene id, name ni class útiles
        (verificado por DOM inspection: ``<label for="dt-length-0">Mostrar
        <select>``). Lo identificamos por su patrón único de options
        ``['10', '25', '50', '100']`` y disparamos ``change`` por JS para
        que DataTables re-pinte la tabla.

        Returns:
            True si el select se encontró y el cambio se aplicó.
        """
        self._emit(f"Configurando {size} filas por página...")
        try:
            applied = self.page.evaluate(
                """
                (target) => {
                    const selects = document.querySelectorAll('select');
                    for (const sel of selects) {
                        const vals = Array.from(sel.options).map(o => o.value);
                        if (vals.includes('100') && vals.includes('10')
                                && vals.length <= 5) {
                            sel.value = target;
                            sel.dispatchEvent(new Event('change', {bubbles: true}));
                            return true;
                        }
                    }
                    return false;
                }
                """,
                str(size),
            )
        except Exception:
            applied = False
        time.sleep(self.wait_s)
        return bool(applied)

    def get_page_info(self) -> tuple[Optional[str], Optional[int]]:
        """Lee el texto de paginación. Retorna (texto, total_registros)."""
        try:
            info_el = self.page.query_selector(self.SEL_TABLE_INFO)
            if info_el:
                text = info_el.inner_text()
                match = re.search(r"de\s+([\d,.]+)", text)
                if match:
                    total = int(match.group(1).replace(",", "").replace(".", ""))
                    return text, total
                return text, None
        except Exception:
            pass
        return None, None

    def get_rows(self) -> list:
        """Retorna las filas de la página actual."""
        try:
            self.page.wait_for_selector(self.SEL_TABLE_ROWS, timeout=15000)
        except Exception:
            return []

        rows = self.page.query_selector_all(self.SEL_TABLE_ROWS)
        if rows and "No se encontraron" in rows[0].inner_text():
            return []
        return rows

    # ---------- pagination ----------

    def _info_text(self) -> str:
        try:
            el = self.page.query_selector(self.SEL_TABLE_INFO)
            if el:
                return el.inner_text().strip()
        except Exception:
            pass
        return ""

    def _first_row_text(self) -> str:
        try:
            rows = self.page.query_selector_all(self.SEL_TABLE_ROWS)
            if rows:
                return rows[0].inner_text()[:200].strip()
        except Exception:
            pass
        return ""

    # JS que clickea el botón "Siguiente" sin depender de selectores de DT
    # 1.x ni 2.x. DIAN usa DataTables 2.x (clases ``dt-*``) y el HTML cambió
    # — buscamos por el TEXTO visible "Siguiente"/"Next"/"›" en cualquier
    # button/a/span. Retorna {"clicked": bool, "disabled": bool, "found": bool}.
    _NEXT_CLICK_JS = """
        () => {
            const candidates = document.querySelectorAll('button, a, span');
            for (const e of candidates) {
                const t = (e.innerText || '').trim();
                if (t === 'Siguiente' || t === 'Next' || t === '›' || t === '>') {
                    const cls = (e.className || '').toLowerCase();
                    const aria = (e.getAttribute('aria-disabled') || '').toLowerCase();
                    const disabled = e.disabled === true
                        || cls.includes('disabled') || aria === 'true';
                    if (disabled) return {found: true, disabled: true, clicked: false};
                    e.scrollIntoView({block: 'nearest'});
                    e.click();
                    return {found: true, disabled: false, clicked: true};
                }
            }
            return {found: false, disabled: false, clicked: false};
        }
    """

    def _is_next_disabled(self) -> bool:
        """True si el botón 'Siguiente' está deshabilitado (o no existe)."""
        try:
            res = self.page.evaluate(self._NEXT_CLICK_JS.replace("e.click();", ""))
            if not res.get("found"):
                return True
            return bool(res.get("disabled"))
        except Exception:
            return True

    def go_to_next_page(self, timeout_s: int = 20) -> bool:
        """Avanza a la siguiente página de la tabla DIAN (DataTables 2.x).

        Estrategia: click vía JS sobre el elemento cuyo texto es "Siguiente",
        sin depender de selectores de DataTables (que cambiaron entre 1.x y
        2.x).

        Espera dos cosas para confirmar el cambio:
        1. ``info_text`` o la primera fila cambiaron (señal de que DT empezó
           a renderizar la nueva página).
        2. ``len(get_rows())`` se mantiene estable entre dos mediciones
           consecutivas (señal de que terminó de renderizar todas las filas).

        Sin (2) podemos llamar ``get_rows()`` mientras DT está pintando filas
        a medias y perder hasta el 50% de las filas en páginas grandes.
        """
        info_before = self._info_text()
        first_before = self._first_row_text()

        try:
            res = self.page.evaluate(self._NEXT_CLICK_JS)
        except Exception:
            return False

        if not res.get("found") or res.get("disabled") or not res.get("clicked"):
            return False

        # Paso 1: esperar a que info text o primera fila cambien (señal de
        # que el click se procesó).
        deadline = time.monotonic() + timeout_s
        changed = False
        while time.monotonic() < deadline:
            time.sleep(0.5)
            info_now = self._info_text()
            first_now = self._first_row_text()
            if info_now and info_now != info_before:
                changed = True
                break
            if first_now and first_before and first_now != first_before:
                changed = True
                break

        if not changed:
            return False

        # Paso 2: esperar a que el conteo de filas sea estable entre 2
        # mediciones consecutivas separadas por 1s. DataTables 2.x renderiza
        # de forma incremental — sin esto, perdemos filas a medio renderizar.
        last_count = -1
        stable_deadline = time.monotonic() + timeout_s
        while time.monotonic() < stable_deadline:
            time.sleep(1.0)
            current_count = len(self._safe_rows())
            if current_count > 0 and current_count == last_count:
                return True
            last_count = current_count
        return True  # devolvemos True igual si paso 1 cambió, aunque el render no se estabilizó

    def _safe_rows(self) -> list:
        """get_rows sin esperas largas, para el polling de paginación."""
        try:
            return self.page.query_selector_all(self.SEL_TABLE_ROWS)
        except Exception:
            return []

    # ---------- downloads ----------

    def download_row(self, row, index: int, output_dir: str) -> tuple[bool, str]:
        """Descarga el archivo de una fila.

        Args:
            row: Elemento tr (retornado por get_rows()).
            index: Índice en la página (para desambiguar nombres).
            output_dir: Carpeta destino.

        Returns:
            (éxito, filename) — ``filename`` se usa aun en fallo para logs.
        """
        row_text = row.inner_text()
        clean_text = re.sub(r"\s+", "_", row_text).strip()
        safe_text = sanitize_filename(clean_text)
        filename = f"{safe_text}_{index}.zip"

        btn = row.query_selector(self.SEL_DOWNLOAD_BUTTON)
        if not btn:
            return False, filename

        try:
            with self.page.expect_download(timeout=self.download_timeout_ms) as dl:
                btn.scroll_into_view_if_needed()
                btn.click()

            save_path = os.path.join(output_dir, filename)
            dl.value.save_as(save_path)
            return True, filename
        except Exception:
            return False, filename
