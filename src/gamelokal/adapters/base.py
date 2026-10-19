"""Adapter: pengetahuan khusus per game (lokasi berkas, nama kolom)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Adapter:
    name: str
    lang_folders: tuple[str, ...]
    db_pattern: str
    table: str | None = None      # None = ditebak otomatis (lihat `gamelokal inspect`)
    id_col: str | None = None
    text_col: str | None = None
    notes: str = ""

    def find_dbs(self, root, lang: str) -> list[Path]:
        base = Path(root)
        folder = next((p for p in base.rglob(lang) if p.is_dir()), None)
        return sorted(folder.glob(self.db_pattern)) if folder else []
