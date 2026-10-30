"""Adapter: pengetahuan khusus per game (lokasi berkas, nama tabel dan kolom)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Adapter:
    name: str
    lang_folders: tuple[str, ...]
    db_pattern: str
    game_dir: str                 # lokasi berkas di dalam .pak
    table: str | None = None
    id_col: str | None = None
    text_col: str | None = None
    speaker_col: str | None = None
    notes: str = ""

    def find_dbs(self, root, lang: str) -> list[Path]:
        base = Path(root)
        folder = next((p for p in base.rglob(lang) if p.is_dir()), None)
        return sorted(folder.glob(self.db_pattern)) if folder else []
