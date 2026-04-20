"""Package all downloaded files into a single result ZIP."""

from __future__ import annotations

import zipfile
from pathlib import Path

from backend.job_manager import Job


def build_result_zip(job: Job) -> Path:
    empresa = job.empresa or "DIAN"
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in empresa).strip()
    zip_name = f"DIAN_{safe}_{job.start_date}_{job.end_date}.zip"
    result_path = job.work_dir / zip_name

    recibidos_dir = job.work_dir / "output_recibidos"
    listados_dir = job.work_dir / "output_listados"

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
