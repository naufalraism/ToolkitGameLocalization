"""Membaca dan menulis teks game yang disimpan dalam SQLite (.db)."""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    pk: bool


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: tuple[Column, ...]
    rows: int


@dataclass(frozen=True)
class Guess:
    table: str
    id_col: str
    text_col: str


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect_ro(path) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def inspect_db(path) -> list[TableInfo]:
    con = _connect_ro(path)
    try:
        names = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        out = []
        for t in names:
            cols = tuple(Column(r[1], (r[2] or "").upper(), bool(r[5]))
                         for r in con.execute(f"pragma table_info({_q(t)})"))
            n = con.execute(f"select count(*) from {_q(t)}").fetchone()[0]
            out.append(TableInfo(t, cols, n))
        return out
    finally:
        con.close()


def guess_columns(path) -> Guess | None:
    """Menebak tabel, kolom id, dan kolom teks. Pilih kolom teks dengan rata-rata isi terpanjang."""
    best, best_score = None, 0.0
    tables = inspect_db(path)
    con = _connect_ro(path)
    try:
        for t in tables:
            if t.rows == 0:
                continue
            for c in t.columns:
                if not (c.type == "" or any(k in c.type for k in ("TEXT", "CHAR", "CLOB"))):
                    continue
                score = con.execute(
                    f"select avg(length(x)) from (select {_q(c.name)} as x from {_q(t.name)} limit 200)").fetchone()[0] or 0
                others = [o for o in t.columns if o.name != c.name]
                if not others or score <= best_score:
                    continue
                idc = next((o for o in others if o.pk), others[0])
                best, best_score = Guess(t.name, idc.name, c.name), score
        return best
    finally:
        con.close()


def load_entries(path, table: str, id_col: str, text_col: str) -> Iterator[tuple[str, str]]:
    con = _connect_ro(path)
    try:
        for id_, text in con.execute(f"select {_q(id_col)}, {_q(text_col)} from {_q(table)} order by rowid"):
            yield str(id_), "" if text is None else str(text)
    finally:
        con.close()


def write_patch(src, dst, table: str, id_col: str, text_col: str, translations: Mapping[str, str]) -> int:
    """Menyalin .db sumber ke dst lalu mengganti teks sesuai terjemahan. Mengembalikan jumlah baris yang berubah."""
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if src == dst:
        raise ValueError("Berkas keluaran tidak boleh sama dengan berkas sumber.")
    shutil.copyfile(src, dst)
    con = sqlite3.connect(dst)
    try:
        originals = {str(r[0]): r[0] for r in con.execute(f"select {_q(id_col)} from {_q(table)}")}
        params = [(text, originals[i]) for i, text in translations.items() if i in originals]
        con.executemany(f"update {_q(table)} set {_q(text_col)} = ? where {_q(id_col)} = ?", params)
        con.commit()
        return len(params)
    finally:
        con.close()
