"""
Gestión del ciclo de vida de la sesión Playwright con el portal DIAN.

Abre Chromium, navega a la URL con token (auth de ~1h de vida) y verifica que
el link a ``/Document/Received`` esté disponible — señal de que el token es
válido. Si no aparece, continúa igual: DIAN a veces tarda en renderizar el menú
pero la sesión está OK.

Heredado del proyecto viejo con import adaptado a ``dian_core.config``.
"""

from __future__ import annotations

from typing import Callable, Optional

from dian_core.config import SessionConfig

# Callback opcional: session.start(playwright, on_progress=lambda msg: ...)
ProgressCb = Callable[[str], None]


class DianSession:
    """Maneja la sesión Playwright con el portal DIAN.

    Uso típico:

        with sync_playwright() as p:
            session = DianSession(config)
            session.start(p, on_progress=print)
            # ... usar session.page ...
            session.close()
    """

    def __init__(self, config: SessionConfig) -> None:
        self.config = config
        self.browser = None
        self.context = None
        self.page = None

    def start(self, playwright, on_progress: Optional[ProgressCb] = None) -> "DianSession":
        """Lanza Chromium, autentica y retorna self.

        Args:
            playwright: Instancia de ``sync_playwright`` ya entrada como context.
            on_progress: callback opcional para feedback al usuario. Se invoca
                en cada paso (launch, context, auth) para que la UI muestre
                actividad durante los ~5-15s del arranque de Chromium.

        Returns:
            self, para permitir chaining.
        """
        emit = on_progress or (lambda _m: None)
        emit("Iniciando navegador Chromium (headless)...")
        self.browser = playwright.chromium.launch(headless=self.config.headless)
        emit("Creando contexto de navegación...")
        self.context = self.browser.new_context(accept_downloads=True)
        self.page = self.context.new_page()
        emit("Autenticando en el portal DIAN con el token...")
        self._authenticate()
        emit("Sesión DIAN establecida.")
        return self

    def close(self) -> None:
        """Cierra el browser de forma segura (swallow de excepciones)."""
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                # WORKAROUND: Playwright puede lanzar si el browser ya murió;
                # no propagamos porque close() se llama en finally.
                pass
            self.browser = None
            self.context = None
            self.page = None

    def restart(self, playwright) -> "DianSession":
        """Cierra y vuelve a abrir. Usado por el circuit-breaker cuando hay
        demasiados errores consecutivos (típicamente token expirado o DIAN
        lento)."""
        self.close()
        return self.start(playwright)

    def _authenticate(self) -> None:
        """Navega a la URL con token y espera al menú autenticado.

        # WORKAROUND: El selector a[href="/Document/Received"] aparece SOLO si
        # la autenticación fue exitosa. Si no aparece en 15s, asumimos fallo
        # pero no lanzamos — el caller (descargador) detectará la falla al
        # intentar usar la página y restartea la sesión.
        """
        self.page.goto(self.config.token_url, wait_until="domcontentloaded")
        try:
            self.page.wait_for_selector(
                'a[href="/Document/Received"]', timeout=15000
            )
        except Exception:
            pass
