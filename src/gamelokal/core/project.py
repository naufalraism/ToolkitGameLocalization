"""Berkas proyek (gamelokal.json): dari mana teks diambil dan bahasa apa."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Project:
    db: str
    table: str
    id_col: str
    text_col: str
    source_lang: str = "en"
    target_lang: str = "id"
    glossary: str | None = None
    root: Path = field(default_factory=Path, repr=False, compare=False)

    @classmethod
    def load(cls, path) -> "Project":
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        proj = cls(**data)
        proj.root = p.resolve().parent
        return proj

    def save(self, path) -> None:
        data = asdict(self)
        data.pop("root")
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else self.root / p
