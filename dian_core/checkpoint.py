"""
Checkpoints de descargas — permiten reanudar tras expiración de token, crash
o cierre voluntario del usuario.

DateCheckpoint: tracking por nombre de archivo (modo rango de fechas).
CufeCheckpoint: tracking por CUFE con estados Pending/Done/Error (modo batch).

Heredado del proyecto viejo. Sin cambios funcionales, solo adaptación de estilo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable


class DateCheckpoint:
    """Checkpoint de descargas por fecha. Guarda lista de archivos ya bajados."""

    def __init__(self, filepath: str | os.PathLike) -> None:
        self.filepath = str(filepath)
        self.data: dict = {"downloaded_files": [], "total_downloaded": 0}
        self._load()

    def _load(self) -> None:
        if Path(self.filepath).exists():
            with open(self.filepath, "r", encoding="utf-8") as f:
                self.data = json.load(f)

    def save(self) -> None:
        """Persiste a disco. Crea directorio si no existe."""
        parent = Path(self.filepath).parent
        parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def is_downloaded(self, filename: str) -> bool:
        return filename in self.data["downloaded_files"]

    def mark_downloaded(self, filename: str) -> None:
        if filename not in self.data["downloaded_files"]:
            self.data["downloaded_files"].append(filename)
            self.data["total_downloaded"] += 1

    @property
    def total(self) -> int:
        return self.data["total_downloaded"]


class CufeCheckpoint:
    """Checkpoint de descargas por CUFE. Guarda estado por CUFE individual."""

    def __init__(self, filepath: str | os.PathLike) -> None:
        self.filepath = str(filepath)
        self.data: dict = {}
        self._load()

    def _load(self) -> None:
        if Path(self.filepath).exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                # WORKAROUND: archivo corrupto (ej. por crash durante save) —
                # empezamos de cero en vez de explotar.
                self.data = {}

    def save(self) -> None:
        parent = Path(self.filepath).parent
        parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    def initialize(self, cufes: Iterable[str]) -> None:
        """Agrega CUFEs nuevos que aún no estén trackeados."""
        for cufe in cufes:
            if cufe not in self.data:
                self.data[cufe] = {"status": "Pending", "attempts": 0, "last_error": None}
        self.save()

    def mark_done(self, cufe: str) -> None:
        if cufe in self.data:
            self.data[cufe]["status"] = "Done"
            self.data[cufe]["last_error"] = None

    def mark_error(self, cufe: str, error: str) -> None:
        if cufe in self.data:
            self.data[cufe]["status"] = "Error"
            self.data[cufe]["last_error"] = error

    def increment_attempts(self, cufe: str) -> None:
        if cufe in self.data:
            self.data[cufe]["attempts"] += 1

    def get_pending(self) -> list[str]:
        """Lista de CUFEs que aún no están en estado Done."""
        return [c for c, info in self.data.items() if info["status"] != "Done"]

    def reset_errors(self) -> int:
        """Marca todos los Error como Pending (retry tras token fresco).

        Returns: número de CUFEs que fueron reseteados.
        """
        count = 0
        for info in self.data.values():
            if info["status"] == "Error":
                info["status"] = "Pending"
                count += 1
        self.save()
        return count

    def summary(self) -> dict:
        """Conteo por estado — usado en el panel de resultados de la UI."""
        statuses = [v["status"] for v in self.data.values()]
        return {
            "total": len(self.data),
            "done": statuses.count("Done"),
            "pending": statuses.count("Pending"),
            "error": statuses.count("Error"),
        }

    def error_details(self) -> list[dict]:
        """Detalle de los CUFEs con error (para el log del usuario)."""
        return [
            {
                "cufe": c[:15] + "...",
                "error": info["last_error"],
                "attempts": info["attempts"],
            }
            for c, info in self.data.items()
            if info["status"] == "Error"
        ]
