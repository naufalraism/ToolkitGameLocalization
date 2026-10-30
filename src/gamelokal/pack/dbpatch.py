"""Menulis terjemahan dari workbench ke SALINAN database game."""
from __future__ import annotations

import re
import shutil
import sqlite3

from ..core.store import quote
from ..core.workbench import STATUSES, Workbench, WorkbenchError


def _apply(con: sqlite3.Connection, wb: Workbench, name: str, m: dict, statuses) -> tuple[int, int]:
    """Hanya kolom teks yang diubah. Id dan kolom lain tidak disentuh."""
    decl = {r[1]: (r[2] or "") for r in con.execute(f"PRAGMA table_info({quote(m['table'])})")}
    if not decl:
        raise WorkbenchError(f"tabel '{m['table']}' tidak ada di database dasar")
    numeric_id = "INT" in decl.get(m["id_col"], "").upper()
    sql = f"UPDATE {quote(m['table'])} SET {quote(m['text_col'])}=? WHERE {quote(m['id_col'])}=?"
    written = missing = 0
    with con:
        for r in wb.targets_for(name, statuses):
            key = r["id"][len(name) + 1:]
            if numeric_id and re.fullmatch(r"-?\d+", key):
                key = int(key)
            if con.execute(sql, (r["target"], key)).rowcount:
                written += 1
            else:
                missing += 1
    return written, missing


def write_translated_copy(wb: Workbench, name: str, base, out, only_approved: bool = False,
                          include=()) -> list[tuple[str, int, int]]:
    """Menyalin database dasar ke 'out' lalu menulis terjemahan. Mengembalikan [(dataset, ditulis, tidak_ditemukan)]."""
    allowed = ("approved",) if only_approved else STATUSES
    maps = wb.mappings()
    m = maps[name]
    shutil.copyfile(base, out)
    con = sqlite3.connect(out)
    detail = []
    try:
        for ds in [name, *include]:
            mm = maps.get(ds)
            if mm is None:
                raise WorkbenchError(f"dataset '{ds}' tidak ada. Yang ada: {', '.join(maps)}")
            if (mm["table"], mm["id_col"], mm["text_col"]) != (m["table"], m["id_col"], m["text_col"]):
                raise WorkbenchError(f"dataset '{ds}' memakai tabel/kolom berbeda dari '{name}', tidak bisa digabung")
            detail.append((ds, *_apply(con, wb, ds, mm, allowed)))
    finally:
        con.close()
    return detail
