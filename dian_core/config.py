"""
Dataclasses de configuración para las tres estrategias de descarga DIAN.

Heredado del proyecto viejo. Cambios frente a la versión original:
- ``output_base`` por defecto apunta a ``~/Documents/DIAN`` (era ``e:\\facturas\\dian``).
- ``checkpoint_file`` cae en ``%APPDATA%/BatutaAI/DianDownloader/checkpoints/``.
- Imports absolutos ``dian_core.*`` (antes ``core.*``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dian_core.utils import appdata_dir, build_output_dir, default_output_base


def _default_checkpoint_path(name: str, output_dir: str = "") -> str:
    """Ruta al checkpoint — junto a los archivos descargados si se conoce el
    output_dir, si no, cae a %APPDATA%/BatutaAI/DianDownloader/checkpoints/.

    # BUSINESS RULE: tener el checkpoint visible al lado de los ZIPs facilita
    # que el usuario vea el progreso/estado sin excavar en AppData.
    """
    if output_dir:
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder / name)
    folder = appdata_dir() / "checkpoints"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / name)


@dataclass
class SessionConfig:
    """Parámetros compartidos de la sesión Playwright con el portal DIAN.

    Attributes:
        token_url: URL con token generada desde el portal DIAN (vida ~1h).
        headless: ``False`` para debug con ventana visible; ``True`` en .exe.
        download_timeout_ms: Timeout por descarga individual.
        page_load_wait_s: Espera tras navegaciones para que JS cargue.
    """

    token_url: str
    headless: bool = True
    download_timeout_ms: int = int(os.getenv("DIAN_DOWNLOAD_TIMEOUT_MS", "30000"))
    page_load_wait_s: int = int(os.getenv("DIAN_PAGE_LOAD_WAIT_S", "5"))


@dataclass
class DateDownloadConfig:
    """Configuración para descarga por rango de fechas."""

    session: SessionConfig
    company_name: str
    start_date: str  # YYYY/MM/DD
    end_date: str    # YYYY/MM/DD
    output_base: str = ""
    # BUSINESS RULE: DIAN permite hasta 100 filas/página. Usar el máximo
    # reduce 50% el número de clicks "Siguiente" y 50% el riesgo de que el
    # token expire a mitad de descarga.
    page_size: int = int(os.getenv("DIAN_PAGE_SIZE", "100"))
    checkpoint_file: str = ""
    max_session_restarts: int = int(os.getenv("DIAN_MAX_SESSION_RESTARTS", "3"))

    def __post_init__(self) -> None:
        if not self.output_base:
            self.output_base = default_output_base()
        if not self.checkpoint_file:
            self.checkpoint_file = _default_checkpoint_path(
                f"_checkpoint_fechas_{self.start_date.replace('/', '-')}_{self.end_date.replace('/', '-')}.json",
                output_dir=self.output_dir,
            )

    @property
    def output_dir(self) -> str:
        return build_output_dir(self.output_base, self.start_date, self.company_name)


@dataclass
class CufeBatchConfig:
    """Configuración para descarga por lote de CUFEs."""

    session: SessionConfig
    company_name: str
    start_date: str
    end_date: str
    cufe_file: str
    output_base: str = ""
    checkpoint_file: str = ""
    max_consecutive_errors: int = int(os.getenv("DIAN_MAX_CONSECUTIVE_ERRORS", "4"))
    max_session_restarts: int = int(os.getenv("DIAN_MAX_SESSION_RESTARTS", "3"))

    def __post_init__(self) -> None:
        if not self.output_base:
            self.output_base = default_output_base()
        if not self.checkpoint_file:
            stem = Path(self.cufe_file).stem if self.cufe_file else "batch"
            self.checkpoint_file = _default_checkpoint_path(
                f"_checkpoint_batch_{stem}.json",
                output_dir=self.output_dir,
            )

    @property
    def output_dir(self) -> str:
        return build_output_dir(self.output_base, self.start_date, self.company_name)


@dataclass
class ListadoExportConfig:
    """Config para el export Excel del listado completo DIAN.

    DIAN tiene una página ``/Document/Export`` que genera un ZIP con un Excel
    listando TODAS las facturas en un rango. El proceso es:
      1. Configurar tipo de doc y rango → clic en "Exportar Excel"
      2. DIAN encola el job server-side (~5 min)
      3. Polleamos la tabla de exports hasta que aparezca el ícono de descarga
      4. Descargamos, descomprimimos y renombramos.
    """

    session: SessionConfig
    date_range: str                   # "YYYY-MM-DD - YYYY-MM-DD"
    output_dir: str                   # carpeta destino (elegida por el usuario)
    # 2=Enviados, 3=Recibidos (default), 4=Eventos
    document_type_index: int = 3
    max_poll_retries: int = int(os.getenv("DIAN_MAX_POLL_RETRIES", "20"))
    poll_interval_s: int = int(os.getenv("DIAN_POLL_INTERVAL_S", "15"))
    # Espera inicial tras disparar el export (DIAN suele tardar 3-5 min)
    export_wait_s: int = int(os.getenv("DIAN_EXPORT_WAIT_S", "300"))


@dataclass
class UnattendedConfig:
    """Configuración del flujo desatendido (modo principal v2).

    El usuario NO especifica empresa. Elige 2 carpetas distintas: una para
    el listado Excel, otra para los .zip. El orquestador garantiza que
    todo lo del listado caiga en recibidos (cruce + descarga + log).
    """

    session: SessionConfig
    start_date: str                      # YYYY/MM/DD
    end_date: str                        # YYYY/MM/DD
    output_listados: str                 # carpeta del Excel
    output_recibidos: str                # carpeta de los .zip
    workers: int = 8                     # 1-10

    @property
    def date_range_dian(self) -> str:
        """Formato que espera ``#export-range`` de DIAN: 'YYYY-MM-DD - YYYY-MM-DD'."""
        return f"{self.start_date.replace('/', '-')} - {self.end_date.replace('/', '-')}"


@dataclass
class SingleCufeConfig:
    """Configuración para descarga de un solo CUFE.

    No necesita checkpoint (es una operación atómica) ni circuit-breaker.
    """

    session: SessionConfig
    company_name: str
    cufe: str
    # Fechas anchas por defecto — DIAN exige un rango pero para búsqueda
    # por CUFE el rango suele ser irrelevante si es amplio.
    start_date: str = "2020/01/01"
    end_date: str = "2030/12/31"
    output_base: str = ""

    def __post_init__(self) -> None:
        if not self.output_base:
            self.output_base = default_output_base()

    @property
    def output_dir(self) -> str:
        return build_output_dir(self.output_base, self.start_date, self.company_name)
