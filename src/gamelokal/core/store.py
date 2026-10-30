"""Membaca database SQLite game (selalu read-only)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .errors import GamelokalError


class StoreError(GamelokalError):
    pass


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


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def connect_ro(path) -> sqlite3.Connection:
    p = Path(path)
    if not p.is_file():
        raise StoreError(f"file tidak ditemukan: {path}")
    con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        con.execute("select name from sqlite_master limit 1").fetchall()
    except sqlite3.DatabaseError as e:
        con.close()
        raise StoreError(f"{path} tidak bisa dibuka sebagai SQLite ({e}). Kemungkinan file ini terenkripsi "
                         "(misalnya SQLCipher) atau bukan database SQLite.") from e
    return con


def inspect_db(path) -> list[TableInfo]:
    con = connect_ro(path)
    try:
        names = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        out = []
        for t in names:
            cols = tuple(Column(r[1], (r[2] or "").upper(), bool(r[5]))
                         for r in con.execute(f"pragma table_info({quote(t)})"))
            n = con.execute(f"select count(*) from {quote(t)}").fetchone()[0]
            out.append(TableInfo(t, cols, n))
        return out
    finally:
        con.close()


def guess_columns(path) -> Guess | None:
    """Menebak tabel, kolom id, dan kolom teks. Kolom teks = yang rata-rata isinya terpanjang."""
    best, best_score = None, 0.0
    tables = inspect_db(path)
    con = connect_ro(path)
    try:
        for t in tables:
            if t.rows == 0:
                continue
            for c in t.columns:
                if not (c.type == "" or any(k in c.type for k in ("TEXT", "CHAR", "CLOB"))):
                    continue
                score = con.execute(
                    f"select avg(length(x)) from (select {quote(c.name)} as x from {quote(t.name)} limit 200)").fetchone()[0] or 0
                others = [o for o in t.columns if o.name != c.name]
                if not others or score <= best_score:
                    continue
                idc = next((o for o in others if o.pk), others[0])
                best, best_score = Guess(t.name, idc.name, c.name), score
        return best
    finally:
        con.close()


def iter_rows(path, table: str, id_col: str, text_col: str, speaker_col: str | None = None,
              where: str | None = None) -> Iterator[tuple[str, str, str]]:
    """Menghasilkan (kunci, teks, pembicara) untuk baris yang teksnya tidak kosong."""
    con = connect_ro(path)
    try:
        info = con.execute(f"pragma table_info({quote(table)})").fetchall()
        if not info:
            raise StoreError(f"tabel '{table}' tidak ada. Jalankan 'inspect' untuk melihat daftar tabel.")
        have = {r[1] for r in info}
        for c in (id_col, text_col, speaker_col):
            if c and c not in have:
                raise StoreError(f"kolom '{c}' tidak ada di tabel {table}. Kolom yang ada: {', '.join(sorted(have))}")
        sel = f"{quote(id_col)}, {quote(text_col)}, " + (quote(speaker_col) if speaker_col else "''")
        sql = f"select {sel} from {quote(table)} where {quote(text_col)} is not null and trim({quote(text_col)}) != ''"
        if where:
            sql += f" and ({where})"
        for key, text, spk in con.execute(sql):
            yield str(key), str(text), str(spk or "")
    finally:
        con.close()
