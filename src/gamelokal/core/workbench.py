"""Workbench: basis data kerja milik penerjemah (workbench.db).

Database asli game tidak pernah diubah. Semua teks asli, terjemahan, status, dan riwayat versi
disimpan di sini. Hasil akhir ditulis ke SALINAN database game (lihat pack.dbpatch).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from typing import Iterable

from .errors import GamelokalError

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries(
  id      TEXT PRIMARY KEY,           -- "dataset:kunci"
  speaker TEXT NOT NULL DEFAULT '',
  source  TEXT NOT NULL,
  target  TEXT NOT NULL DEFAULT '',
  status  TEXT NOT NULL DEFAULT 'new', -- new | mt | edited | approved
  updated REAL,
  editor  TEXT NOT NULL DEFAULT ''     -- terakhir diubah oleh
);
CREATE TABLE IF NOT EXISTS versions(
  vid      INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id TEXT NOT NULL REFERENCES entries(id),
  ts       REAL NOT NULL,
  text     TEXT NOT NULL,
  note     TEXT NOT NULL DEFAULT '',
  author   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_versions_entry ON versions(entry_id);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(
  name TEXT PRIMARY KEY, token_hash TEXT NOT NULL, created REAL NOT NULL
);
"""
STATUSES = ("mt", "edited", "approved")


class WorkbenchError(GamelokalError):
    pass


def _like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Workbench:
    def __init__(self, path):
        self.con = sqlite3.connect(str(path))
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        for table, col in (("entries", "editor"), ("versions", "author")):   # workbench versi lama
            if col not in {r["name"] for r in self.con.execute(f"PRAGMA table_info({table})")}:
                self.con.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Workbench":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- dataset
    def mappings(self) -> dict:
        r = self.con.execute("SELECT v FROM meta WHERE k='mappings'").fetchone()
        return json.loads(r["v"]) if r else {}

    def _save_mappings(self, m: dict) -> None:
        self.con.execute("INSERT INTO meta(k,v) VALUES('mappings',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                         (json.dumps(m),))

    def pick_dataset(self, name: str | None = None) -> tuple[str, dict]:
        maps = self.mappings()
        if not maps:
            raise WorkbenchError("belum ada dataset. Jalankan 'import' atau 'import-translated' dulu.")
        if name is None:
            if len(maps) > 1:
                raise WorkbenchError("ada beberapa dataset (" + ", ".join(maps) + "); pilih dengan --name")
            name = next(iter(maps))
        if name not in maps:
            raise WorkbenchError(f"dataset '{name}' tidak ada. Yang ada: {', '.join(maps)}")
        return name, maps[name]

    # ---- impor
    def import_source(self, ds: str, rows: Iterable[tuple[str, str, str]], mapping: dict) -> tuple[int, int, int]:
        new = changed = same = 0
        with self.con:
            for key, text, speaker in rows:
                eid = f"{ds}:{key}"
                old = self.con.execute("SELECT source FROM entries WHERE id=?", (eid,)).fetchone()
                if old is None:
                    self.con.execute("INSERT INTO entries(id, speaker, source, updated) VALUES (?,?,?,?)",
                                     (eid, speaker, text, time.time()))
                    new += 1
                elif old["source"] != text:
                    self.con.execute("UPDATE entries SET source=?, speaker=? WHERE id=?", (text, speaker, eid))
                    changed += 1
                else:
                    same += 1
            m = self.mappings()
            m[ds] = mapping
            self._save_mappings(m)
        return new, changed, same

    def import_translated(self, ds: str, pairs: Iterable[tuple[str, str]], full_ids: bool = False,
                          mapping: dict | None = None, note: str = "Impor terjemahan lama") -> tuple[int, int]:
        created = applied = 0
        with self.con:
            for key, text in pairs:
                eid = key if full_ids else f"{ds}:{key}"
                if self.con.execute("SELECT 1 FROM entries WHERE id=?", (eid,)).fetchone() is None:
                    self.con.execute("INSERT INTO entries(id, speaker, source, updated) VALUES (?,?,?,?)",
                                     (eid, "", "", time.time()))
                    created += 1
                self._set(eid, text, "edited", note)
                applied += 1
            m = self.mappings()
            if mapping and ds not in m:
                m[ds] = mapping
                self._save_mappings(m)
        return applied, created

    # ---- entri
    def get(self, eid: str) -> sqlite3.Row:
        r = self.con.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
        if r is None:
            raise WorkbenchError(f"entri '{eid}' tidak ada. Coba: search \"{eid}\" --in id")
        return r

    def _set(self, eid: str, text: str, status: str, note: str, author: str = "") -> None:
        row = self.get(eid)
        now = time.time()
        if text != row["target"]:
            self.con.execute("INSERT INTO versions(entry_id, ts, text, note, author) VALUES (?,?,?,?,?)",
                             (eid, now, text, note, author))
        self.con.execute("UPDATE entries SET target=?, status=?, updated=?, editor=? WHERE id=?",
                         (text, status if text else "new", now, author or row["editor"], eid))

    def set_target(self, eid: str, text: str, status: str, note: str = "", author: str = "") -> None:
        with self.con:
            self._set(eid, text, status, note, author)

    def set_targets(self, items: Iterable[tuple[str, str]], status: str, note: str = "", author: str = "") -> None:
        with self.con:
            for eid, text in items:
                self._set(eid, text, status, note, author)

    def approve(self, eid: str, author: str = "") -> bool:
        r = self.get(eid)
        if not r["target"]:
            return False
        self.set_target(eid, r["target"], "approved", "", author)
        return True

    def history(self, eid: str) -> list[sqlite3.Row]:
        self.get(eid)
        return self.con.execute("SELECT * FROM versions WHERE entry_id=? ORDER BY vid", (eid,)).fetchall()

    def revert(self, eid: str, n: int, author: str = "") -> None:
        vers = self.history(eid)
        if not 1 <= n <= len(vers):
            raise WorkbenchError(f"versi harus antara 1 dan {len(vers)}")
        self.set_target(eid, vers[n - 1]["text"], "edited", f"Kembali ke versi {n}", author)

    # ---- kueri
    def search(self, query: str | None = None, in_: str = "all", dataset: str | None = None,
               status: str | None = None, prefix: str | None = None, limit: int = 20, offset: int = 0):
        where: list[str] = []
        params: list = []
        if query:
            pat = "%" + _like(query) + "%"
            cols = {"id": ["id"], "source": ["source"], "target": ["target"],
                    "all": ["id", "speaker", "source", "target"]}[in_]
            where.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in cols) + ")")
            params += [pat] * len(cols)
        if dataset:
            where.append("substr(id, 1, ?) = ?")
            params += [len(dataset) + 1, dataset + ":"]
        if prefix:
            where.append("id LIKE ? ESCAPE '\\'")
            params.append("%:" + _like(prefix) + "%")
        if status == "untranslated":
            where.append("target = ''")
        elif status:
            where.append("target != '' AND status = ?")
            params.append(status)
        cond = " WHERE " + " AND ".join(where) if where else ""
        total = self.con.execute(f"SELECT COUNT(*) FROM entries{cond}", params).fetchone()[0]
        rows = self.con.execute(f"SELECT * FROM entries{cond} ORDER BY id LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
        return rows, total

    def stats(self, by_prefix: int = 0, dataset: str | None = None) -> dict:
        cond, cp = ("substr(id, 1, ?) = ?", [len(dataset) + 1, dataset + ":"]) if dataset else ("1 = 1", [])
        q = self.con.execute
        total = q(f"SELECT COUNT(*) FROM entries WHERE {cond}", cp).fetchone()[0]
        untr = q(f"SELECT COUNT(*) FROM entries WHERE {cond} AND target = ''", cp).fetchone()[0]
        by = {st: q(f"SELECT COUNT(*) FROM entries WHERE {cond} AND target != '' AND status = ?", cp + [st]).fetchone()[0]
              for st in STATUSES}
        prefixes = []
        if by_prefix:
            key = "substr(id, instr(id, ':') + 1)"
            prefixes = q(f"SELECT substr({key}, 1, instr({key} || '_', '_') - 1) AS p, COUNT(*), SUM(target != '') "
                         f"FROM entries WHERE {cond} GROUP BY p ORDER BY COUNT(*) DESC LIMIT ?", cp + [by_prefix]).fetchall()
        return {"total": total, "untranslated": untr, "by_status": by, "prefixes": prefixes}

    def untranslated(self, dataset: str, limit: int = 0, match: str | None = None,
                     prefix: str | None = None) -> list[sqlite3.Row]:
        where = ["target = ''", "source != ''", "substr(id, 1, ?) = ?"]
        params: list = [len(dataset) + 1, dataset + ":"]
        if match:
            where.append("source LIKE ? ESCAPE '\\'")
            params.append("%" + _like(match) + "%")
        if prefix:
            where.append("id LIKE ? ESCAPE '\\'")
            params.append("%:" + _like(prefix) + "%")
        return self.con.execute(
            f"SELECT id, source FROM entries WHERE {' AND '.join(where)} ORDER BY id LIMIT ?",
            params + [limit if limit else -1]).fetchall()

    def entries(self, dataset: str | None = None, statuses=STATUSES) -> list[sqlite3.Row]:
        """Entri yang punya teks asli dan terjemahan (untuk QA)."""
        where = ["target != ''", "source != ''", f"status IN ({','.join('?' * len(statuses))})"]
        params: list = list(statuses)
        if dataset:
            where.append("substr(id, 1, ?) = ?")
            params += [len(dataset) + 1, dataset + ":"]
        return self.con.execute(
            f"SELECT id, source, target, status FROM entries WHERE {' AND '.join(where)} ORDER BY id", params).fetchall()

    def targets_for(self, dataset: str, statuses=STATUSES) -> list[sqlite3.Row]:
        """Semua terjemahan satu dataset (termasuk yang tidak punya teks asli), untuk ditulis ke database."""
        return self.con.execute(
            f"SELECT id, target FROM entries WHERE substr(id, 1, ?) = ? AND target != '' "
            f"AND status IN ({','.join('?' * len(statuses))}) ORDER BY id",
            [len(dataset) + 1, dataset + ":", *statuses]).fetchall()

    def dump(self, dataset: str | None = None) -> list[sqlite3.Row]:
        cond, params = ("WHERE substr(id, 1, ?) = ?", [len(dataset) + 1, dataset + ":"]) if dataset else ("", [])
        return self.con.execute(
            f"SELECT id, source, target, CASE WHEN target = '' THEN 'new' ELSE status END AS status "
            f"FROM entries {cond} ORDER BY id", params).fetchall()

    def apply_targets(self, pairs: Iterable[tuple[str, str]], status: str = "edited",
                      note: str = "", author: str = "") -> tuple[int, int, int]:
        """Menerapkan terjemahan dari luar (misalnya CSV). Mengembalikan (diubah, id_tidak_dikenal, sama)."""
        changed = unknown = same = 0
        with self.con:
            for eid, text in pairs:
                row = self.con.execute("SELECT target FROM entries WHERE id=?", (eid,)).fetchone()
                if row is None:
                    unknown += 1
                elif row["target"] == text:
                    same += 1
                else:
                    self._set(eid, text, status, note, author)
                    changed += 1
        return changed, unknown, same

    # ---- akun: token acak per orang, hanya hash-nya yang disimpan
    def add_user(self, name: str) -> str:
        if not re.fullmatch(r"[\w .-]{1,40}", name or ""):
            raise WorkbenchError("nama pengguna 1-40 karakter: huruf, angka, spasi, titik, strip, atau garis bawah")
        if self.con.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
            raise WorkbenchError(f"pengguna '{name}' sudah ada. Hapus dulu untuk membuat token baru.")
        token = secrets.token_urlsafe(16)
        with self.con:
            self.con.execute("INSERT INTO users(name, token_hash, created) VALUES (?,?,?)",
                             (name, hashlib.sha256(token.encode()).hexdigest(), time.time()))
        return token

    def remove_user(self, name: str) -> None:
        with self.con:
            if not self.con.execute("DELETE FROM users WHERE name=?", (name,)).rowcount:
                raise WorkbenchError(f"pengguna '{name}' tidak ada")

    def users(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT name, created FROM users ORDER BY name").fetchall()

    def user_count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def user_for_token(self, token: str) -> str | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        found = None
        for r in self.con.execute("SELECT name, token_hash FROM users"):
            if hmac.compare_digest(r["token_hash"], digest):
                found = r["name"]
        return found
