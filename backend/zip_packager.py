"""Package all downloaded files into a single result ZIP."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from backend.job_manager import Job

logger = logging.getLogger(__name__)

# PDF/XML filenames DIAN emits inside each per-invoice ZIP are CUFE-based (~90
# chars). When the outer ZIP is later extracted into a deep directory tree on
# Windows, the full path often crosses the 260-char MAX_PATH limit and Adobe
# Reader (plus other PDF viewers) refuse to open the file. We rewrap each
# per-invoice ZIP so its PDF and XML share the outer ZIP's basename, which is
# already in the short `Fecha-Factura-Proveedor` convention.
_RENAMEABLE_EXTS = (".pdf", ".xml")


def _rewrap_zip_with_short_names(zip_path: Path) -> None:
    """Open a per-invoice ZIP, rename its PDF/XML to match the outer basename,
    and rewrite the archive in place. No-op if the file is not a valid ZIP or
    contains no PDF/XML payload.
    """
    if not zip_path.is_file():
        return

    basename = zip_path.stem  # e.g. "2025-01-15_FE1234_Proveedor"
    tmp_path = zip_path.with_name(zip_path.name + ".tmp")

    try:
        with zipfile.ZipFile(zip_path, "r") as src:
            entries = [info for info in src.infolist() if not info.is_dir()]
            if not entries:
                return

            # Track used short names so multiple PDFs/XMLs never collide.
            used: set[str] = set()
            with zipfile.ZipFile(
                tmp_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as dst:
                for info in entries:
                    data = src.read(info.filename)
                    ext = Path(info.filename).suffix.lower()
                    original_name = Path(info.filename).name  # strip directories

                    if ext in _RENAMEABLE_EXTS:
                        new_name = f"{basename}{ext}"
                        suffix = 2
                        while new_name in used:
                            new_name = f"{basename}_{suffix}{ext}"
                            suffix += 1
                    else:
                        # Non-PDF/XML: preserve original leaf name.
                        new_name = original_name
                        suffix = 2
                        while new_name in used:
                            stem = Path(original_name).stem
                            new_name = f"{stem}_{suffix}{ext}"
                            suffix += 1

                    used.add(new_name)
                    dst.writestr(new_name, data)

        tmp_path.replace(zip_path)
    except zipfile.BadZipFile:
        logger.warning("Skipping rewrap — not a valid ZIP: %s", zip_path.name)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Rewrap failed for %s: %s", zip_path.name, exc)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def build_result_zip(job: Job) -> Path:
    empresa = job.empresa or "DIAN"
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in empresa).strip()
    zip_name = f"DIAN_{safe}_{job.start_date}_{job.end_date}.zip"
    result_path = job.work_dir / zip_name

    recibidos_dir = job.work_dir / "output_recibidos"
    listados_dir = job.work_dir / "output_listados"

    # Pre-pass: rewrap each per-invoice ZIP so its internal PDF/XML share the
    # outer ZIP's short basename. Runs in place on files in output_recibidos.
    if recibidos_dir.exists():
        for f in sorted(recibidos_dir.iterdir()):
            if f.is_file() and f.suffix.lower() == ".zip":
                _rewrap_zip_with_short_names(f)

    with zipfile.ZipFile(result_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if recibidos_dir.exists():
            for f in sorted(recibidos_dir.iterdir()):
                if f.is_file():
                    zf.write(f, arcname=f"documentos/{f.name}")

        if listados_dir.exists():
            for f in sorted(listados_dir.iterdir()):
                if f.is_file():
                    zf.write(f, arcname=f"listado/{f.name}")

    return result_path
