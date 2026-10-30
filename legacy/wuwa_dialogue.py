#!/usr/bin/env python3
"""
wuwa_dialogue.py - cari, sunting, versioning, dan terjemahan mesin untuk teks dialog
yang tersimpan di database SQLite (.db) sebuah game. Hanya butuh Python 3.8+ (tanpa pip).

Prinsip: file .db asli game TIDAK PERNAH diubah. Semua kerja ada di workbench.db
(milikmu sendiri). Hasil akhir ditulis ke SALINAN .db lewat perintah export-db.

Alur singkat
  1. Jelajahi database game:
       python wuwa_dialogue.py inspect  contoh.db
       python wuwa_dialogue.py inspect  contoh.db --table NamaTabel --sample 5
       python wuwa_dialogue.py find     contoh.db "potongan kalimat yang kamu tahu"
  2. Impor kolom teks ke workbench:
       python wuwa_dialogue.py import contoh.db --table NamaTabel --id-col Id --text-col Content
  3. Kerja:
       python wuwa_dialogue.py search "Rover" --in source
       python wuwa_dialogue.py show NamaTabel:123
       python wuwa_dialogue.py edit NamaTabel:123            # buka $EDITOR
       python wuwa_dialogue.py edit NamaTabel:123 --text "Halo, Rover." --note "perbaiki nama"
       python wuwa_dialogue.py history NamaTabel:123
       python wuwa_dialogue.py revert NamaTabel:123 1
       python wuwa_dialogue.py mt --untranslated --limit 50 --src en --tgt id
       python wuwa_dialogue.py approve NamaTabel:123
       python wuwa_dialogue.py stats
  4. Tulis hasil ke salinan database:
       python wuwa_dialogue.py export-db contoh.db contoh_id.db
"""
import argparse
from collections import Counter
import difflib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries(
  id      TEXT PRIMARY KEY,           -- "namatabel:nilai_kunci"
  speaker TEXT NOT NULL DEFAULT '',
  source  TEXT NOT NULL,
  target  TEXT NOT NULL DEFAULT '',
  status  TEXT NOT NULL DEFAULT 'new', -- new | mt | edited | approved
  updated REAL
);
CREATE TABLE IF NOT EXISTS versions(
  vid      INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id TEXT NOT NULL REFERENCES entries(id),
  ts       REAL NOT NULL,
  text     TEXT NOT NULL,
  note     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_versions_entry ON versions(entry_id);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""

# Tag, placeholder, dan baris baru dilindungi saat dikirim ke mesin terjemah.
PLACEHOLDER = re.compile(r"<[^>]+>|\{[^}]*\}|\\n|\n|%[sd]")


GAME_DIR = "Client/Content/Aki/ConfigDB/en/"
PAK_MAGIC = 0x5A6F12E1
PAK_VERSION = 12        # nomor versi footer pada WuwaID_1sthalf_P.pak yang terbukti jalan
PAK_MOUNT = "../../../"


def _fstr(s):
    b = s.encode("utf-8") + b"\x00"
    return struct.pack("<i", len(b)) + b


def _rd_fstr(b, p):
    n, = struct.unpack_from("<i", b, p)
    p += 4
    return b[p:p + n - 1].decode("utf-8"), p + n


def path_hash(path, seed=0):
    """FNV64 atas UTF-16LE path huruf kecil (path-hash-index Unreal)."""
    h = (0xCBF29CE484222325 + seed) & 0xFFFFFFFFFFFFFFFF
    for byte in path.lower().encode("utf-16-le"):
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def build_pak(path, data):
    """Bungkus SATU file (tanpa kompresi/enkripsi) jadi pak. Sudah diuji identik
    byte-per-byte dengan WuwaID_1sthalf_P.pak."""
    size = len(data)
    entry = struct.pack("<QQQI", 0, size, size, 0) + hashlib.sha1(data).digest() + b"\x00" + struct.pack("<I", 0)
    body = entry + data
    parts = path.split("/")
    dirs = ["/"] + ["/".join(parts[: i + 1]) + "/" for i in range(len(parts) - 1)]
    fd = struct.pack("<I", len(dirs))
    for d in dirs:
        fd += _fstr(d)
        fd += (struct.pack("<I", 1) + _fstr(parts[-1]) + struct.pack("<i", 0)) if d == dirs[-1] else struct.pack("<I", 0)
    ph = struct.pack("<I", 1) + struct.pack("<Qi", path_hash(path), 0) + struct.pack("<I", 0)
    encoded = struct.pack("<I", 0xE0000000) + b"\x00" + struct.pack("<II", size, 0)
    index_off = len(body)
    prim_len = len(_fstr(PAK_MOUNT)) + 4 + 8 + 4 + 16 + 20 + 4 + 16 + 20 + 4 + len(encoded) + 4
    ph_off = index_off + prim_len
    fd_off = ph_off + len(ph)
    primary = (_fstr(PAK_MOUNT) + struct.pack("<iQ", 1, 0)
               + struct.pack("<I", 1) + struct.pack("<qq", ph_off, len(ph)) + hashlib.sha1(ph).digest()
               + struct.pack("<I", 1) + struct.pack("<qq", fd_off, len(fd)) + hashlib.sha1(fd).digest()
               + struct.pack("<i", len(encoded)) + encoded + struct.pack("<i", 0))
    footer = (b"\x00" * 17 + struct.pack("<IIQQ", PAK_MAGIC, PAK_VERSION, index_off, len(primary))
              + hashlib.sha1(primary).digest() + b"\x00" * 160)
    return body + primary + ph + fd + footer


def read_pak(path):
    """Baca pak berisi satu file tanpa kompresi. Mengembalikan (path_di_game, bytes)."""
    b = Path(path).read_bytes()
    mp = b.rfind(struct.pack("<I", PAK_MAGIC))
    if mp < 17:
        die(f"{path} bukan file pak Unreal")
    ver, ioff, isz = struct.unpack_from("<IQQ", b, mp + 4)
    if ver < 10 or b[mp - 1] != 0:
        die(f"pak versi {ver}/terenkripsi belum didukung oleh pembaca bawaan")
    idx = b[ioff:ioff + isz]
    p = 0
    _, p = _rd_fstr(idx, p)
    p += 12
    for _ in range(2):  # path hash index, lalu full directory index
        has, = struct.unpack_from("<I", idx, p)
        p += 4
        if has:
            off, size = struct.unpack_from("<qq", idx, p)
            p += 36
        last = (off, size) if has else None
    if not last:
        die("pak tanpa full directory index belum didukung")
    fd = b[last[0]:last[0] + last[1]]
    q = 0
    ndirs, = struct.unpack_from("<I", fd, q)
    q += 4
    files = []
    for _ in range(ndirs):
        d, q = _rd_fstr(fd, q)
        nf, = struct.unpack_from("<I", fd, q)
        q += 4
        for _ in range(nf):
            name, q = _rd_fstr(fd, q)
            q += 4
            files.append(d.lstrip("/") + name)
    if len(files) != 1:
        die(f"pak ini berisi {len(files)} file; pembaca bawaan hanya mendukung pak 1 file "
            "(buat satu pak per file, seperti yang dilakukan export-pak)")
    off, csize, usize, comp = struct.unpack_from("<QQQI", b, 0)
    if comp != 0:
        die("pak ini memakai kompresi; belum didukung")
    data = b[53:53 + usize]
    if hashlib.sha1(data).digest() != b[28:48]:
        die("hash isi pak tidak cocok, file mungkin rusak")
    return files[0], data


class RateLimit(Exception):
    pass


class ServerDown(Exception):
    pass


def die(msg, code=1):
    print("Error: " + msg, file=sys.stderr)
    sys.exit(code)


def qi(name):
    """Quote identifier SQL."""
    return '"' + name.replace('"', '""') + '"'


def like_escape(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def short(s, n=100):
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 1] + "…"


# ----------------------------------------------------------------- database

def work_db(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def game_db_ro(path):
    if not os.path.isfile(path):
        die(f"file tidak ditemukan: {path}")
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.DatabaseError as e:
        die(
            f"{path} tidak bisa dibuka sebagai SQLite ({e}). Kemungkinan file ini "
            "terenkripsi (misalnya SQLCipher) atau bukan database SQLite. Tool ini "
            "belum bisa membacanya tanpa dekripsi terlebih dahulu."
        )
    return con


def list_tables(con):
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def table_columns(con, table):
    cols = con.execute(f"PRAGMA table_info({qi(table)})").fetchall()
    if not cols:
        die(f"tabel '{table}' tidak ada. Jalankan 'inspect' untuk melihat daftar tabel.")
    return cols  # (cid, name, type, notnull, dflt, pk)


def get_mappings(con):
    row = con.execute("SELECT v FROM meta WHERE k='mappings'").fetchone()
    return json.loads(row["v"]) if row else {}


def set_target(con, eid, text, status, note, commit=True):
    row = con.execute("SELECT target FROM entries WHERE id=?", (eid,)).fetchone()
    if row is None:
        die(f"entri '{eid}' tidak ada di workbench")
    now = time.time()
    if text != row["target"]:
        con.execute("INSERT INTO versions(entry_id, ts, text, note) VALUES (?,?,?,?)",
                    (eid, now, text, note))
    con.execute("UPDATE entries SET target=?, status=?, updated=? WHERE id=?",
                (text, status if text else "new", now, eid))
    if commit:
        con.commit()


def get_entry(con, eid):
    row = con.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
    if row is None:
        die(f"entri '{eid}' tidak ada. Coba: search \"{eid}\" --in id")
    return row


# ----------------------------------------------------------------- inspect / find / import

def cmd_inspect(a):
    con = game_db_ro(a.game_db)
    if a.table:
        cols = table_columns(con, a.table)
        total = con.execute(f"SELECT COUNT(*) FROM {qi(a.table)}").fetchone()[0]
        print(f"Tabel {a.table}: {total} baris")
        for c in cols:
            print(f"  - {c[1]:<30} {c[2] or '(tanpa tipe)'}{'  [PK]' if c[5] else ''}")
        if a.sample:
            print(f"\n{a.sample} baris pertama:")
            for r in con.execute(f"SELECT * FROM {qi(a.table)} LIMIT ?", (a.sample,)):
                print("  " + " | ".join(short(str(v), 60) for v in r))
        return
    for t in list_tables(con):
        if a.grep and a.grep.lower() not in t.lower():
            continue
        n = con.execute(f"SELECT COUNT(*) FROM {qi(t)}").fetchone()[0]
        cols = ", ".join(c[1] for c in table_columns(con, t))
        print(f"{t} ({n} baris): {short(cols, 110)}")


def cmd_find(a):
    """Cari tabel/kolom mana yang memuat sebuah potongan teks."""
    con = game_db_ro(a.game_db)
    pat = "%" + a.text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    hits = 0
    for t in list_tables(con):
        for c in table_columns(con, t):
            if c[2] and not re.search(r"CHAR|TEXT|CLOB|STR", c[2], re.I):
                continue
            try:
                n = con.execute(
                    f"SELECT COUNT(*) FROM {qi(t)} WHERE CAST({qi(c[1])} AS TEXT) LIKE ? ESCAPE '\\'",
                    (pat,)).fetchone()[0]
            except sqlite3.Error:
                continue
            if n:
                hits += 1
                print(f"{t}.{c[1]}: {n} baris cocok")
    if not hits:
        print("Tidak ketemu. Coba potongan yang lebih pendek, atau teksnya mungkin ada di database lain.")


def cmd_import(a):
    game = game_db_ro(a.game_db)
    cols = {c[1] for c in table_columns(game, a.table)}
    for name in [a.id_col, a.text_col] + ([a.speaker_col] if a.speaker_col else []):
        if name not in cols:
            die(f"kolom '{name}' tidak ada di tabel {a.table}. Kolom yang ada: {', '.join(sorted(cols))}")
    ds = a.name or a.table
    sel = f"{qi(a.id_col)}, {qi(a.text_col)}" + (f", {qi(a.speaker_col)}" if a.speaker_col else ", ''")
    sql = f"SELECT {sel} FROM {qi(a.table)} WHERE {qi(a.text_col)} IS NOT NULL AND TRIM({qi(a.text_col)}) != ''"
    if a.where:
        sql += f" AND ({a.where})"
    work = work_db(a.workdb)
    new = changed = same = 0
    with work:
        for key, text, speaker in game.execute(sql):
            eid = f"{ds}:{key}"
            text = str(text)
            old = work.execute("SELECT source FROM entries WHERE id=?", (eid,)).fetchone()
            if old is None:
                work.execute("INSERT INTO entries(id, speaker, source, updated) VALUES (?,?,?,?)",
                             (eid, str(speaker or ""), text, time.time()))
                new += 1
            elif old["source"] != text:
                work.execute("UPDATE entries SET source=?, speaker=? WHERE id=?",
                             (text, str(speaker or ""), eid))
                changed += 1
            else:
                same += 1
        maps = get_mappings(work)
        maps[ds] = {"table": a.table, "id_col": a.id_col, "text_col": a.text_col,
                    "game_path": a.game_path or GAME_DIR + os.path.basename(a.game_db)}
        work.execute("INSERT INTO meta(k,v) VALUES('mappings',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                     (json.dumps(maps),))
    print(f"[{ds}] impor selesai: {new} baru, {changed} teks asli berubah/terisi, {same} tidak berubah.")
    print(f"Path di game: {maps[ds]['game_path']}")


def cmd_import_translated(a):
    """Masukkan terjemahan yang sudah ada (.pak, .db, atau .json {id: teks}) sebagai target."""
    work = work_db(a.workdb)
    game_path = None
    f = Path(a.file)
    if f.suffix.lower() == ".json":
        pairs = [(k, str(v)) for k, v in json.loads(f.read_text(encoding="utf-8")).items()]
    else:
        if f.suffix.lower() == ".pak":
            game_path, data = read_pak(a.file)
            tmp = Path(tempfile.mkdtemp()) / "x.db"
            tmp.write_bytes(data)
            dbpath = str(tmp)
        else:
            dbpath = a.file
        con = game_db_ro(dbpath)
        table = a.table
        cols = {c[1] for c in table_columns(con, table)}
        for c in (a.id_col, a.text_col):
            if c not in cols:
                die(f"kolom '{c}' tidak ada di tabel {table}. Kolom: {', '.join(sorted(cols))}")
        pairs = [(str(k), str(t)) for k, t in con.execute(
            f"SELECT {qi(a.id_col)}, {qi(a.text_col)} FROM {qi(table)} "
            f"WHERE {qi(a.text_col)} IS NOT NULL AND TRIM({qi(a.text_col)}) != ''")]
    created = applied = 0
    with work:
        for key, text in pairs:
            eid = key if (":" in key and a.file.lower().endswith(".json")) else f"{a.name}:{key}"
            if work.execute("SELECT 1 FROM entries WHERE id=?", (eid,)).fetchone() is None:
                work.execute("INSERT INTO entries(id, speaker, source, updated) VALUES (?,?,?,?)",
                             (eid, "", "", time.time()))
                created += 1
            set_target(work, eid, text, "edited", "Impor terjemahan lama", commit=False)
            applied += 1
        maps = get_mappings(work)
        if a.name not in maps:
            maps[a.name] = {"table": a.table, "id_col": a.id_col, "text_col": a.text_col,
                            "game_path": a.game_path or game_path or GAME_DIR + "lang_multi_text.db"}
            work.execute("INSERT INTO meta(k,v) VALUES('mappings',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                         (json.dumps(maps),))
    print(f"[{a.name}] {applied} terjemahan diimpor ({created} entri baru tanpa teks asli).")
    if created:
        print("Entri tanpa teks asli belum bisa dicari lewat --in source atau diterjemahkan mesin. "
              "Kalau punya db Inggris aslinya, jalankan: import <db> --name " + a.name + " --table ... lagi.")


# ----------------------------------------------------------------- search / show / edit

def status_clause(status):
    if status == "untranslated":
        return "target = ''", []
    return "target != '' AND status = ?", [status]


def cmd_search(a):
    work = work_db(a.workdb)
    where, params = [], []
    if a.query:
        pat = "%" + a.query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cols = {"id": ["id"], "source": ["source"], "target": ["target"],
                "all": ["id", "speaker", "source", "target"]}[a.in_]
        where.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in cols) + ")")
        params += [pat] * len(cols)
    if a.name:
        c, p = dataset_clause(a.name)
        where.append(c)
        params += p
    if a.prefix:
        where.append("id LIKE ? ESCAPE '\\'")
        params.append("%:" + like_escape(a.prefix) + "%")
    if a.status:
        clause, p = status_clause(a.status)
        where.append(clause)
        params += p
    cond = " WHERE " + " AND ".join(where) if where else ""
    total = work.execute(f"SELECT COUNT(*) FROM entries{cond}", params).fetchone()[0]
    rows = work.execute(f"SELECT * FROM entries{cond} ORDER BY id LIMIT ?", params + [a.limit]).fetchall()
    for r in rows:
        st = r["status"] if r["target"] else "new"
        print(f"{r['id']}  [{st}]" + (f"  ({r['speaker']})" if r["speaker"] else ""))
        print(f"    {short(r['source'])}")
        print(f"    → {short(r['target']) if r['target'] else '(belum diterjemahkan)'}")
    print(f"\n{len(rows)} ditampilkan dari {total} cocok.")


def cmd_show(a):
    work = work_db(a.workdb)
    r = get_entry(work, a.id)
    n = work.execute("SELECT COUNT(*) FROM versions WHERE entry_id=?", (a.id,)).fetchone()[0]
    print(f"ID      : {r['id']}")
    if r["speaker"]:
        print(f"Pembicara: {r['speaker']}")
    print(f"Status  : {r['status'] if r['target'] else 'new'}   ({n} versi)")
    print(f"\nAsli:\n{r['source']}\n\nTerjemahan:\n{r['target'] or '(kosong)'}")


def open_editor(initial):
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
    with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(initial)
        path = f.name
    try:
        subprocess.call(editor.split() + [path])
        text = Path(path).read_text(encoding="utf-8")
    finally:
        os.unlink(path)
    return text[:-1] if text.endswith("\n") and not initial.endswith("\n") else text


def cmd_edit(a):
    work = work_db(a.workdb)
    r = get_entry(work, a.id)
    text = a.text
    if text is None:
        print("Asli:\n" + r["source"] + "\n")
        text = open_editor(r["target"] or r["source"])
    status = "approved" if a.approve else "edited"
    set_target(work, a.id, text, status, a.note or "Disunting")
    print("Tersimpan." if text else "Terjemahan dikosongkan.")


def cmd_approve(a):
    work = work_db(a.workdb)
    for eid in a.ids:
        r = get_entry(work, eid)
        if not r["target"]:
            print(f"{eid}: dilewati (belum ada terjemahan)")
            continue
        set_target(work, eid, r["target"], "approved", "")
        print(f"{eid}: disetujui")


def word_diff(old, new):
    x, y = re.split(r"(\s+)", old), re.split(r"(\s+)", new)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
        if op == "equal":
            out.append("".join(x[i1:i2]))
        else:
            if i2 > i1:
                out.append("[-" + "".join(x[i1:i2]) + "-]")
            if j2 > j1:
                out.append("{+" + "".join(y[j1:j2]) + "+}")
    return "".join(out)


def cmd_history(a):
    work = work_db(a.workdb)
    get_entry(work, a.id)
    vers = work.execute("SELECT * FROM versions WHERE entry_id=? ORDER BY vid", (a.id,)).fetchall()
    if not vers:
        print("Belum ada riwayat.")
        return
    prev = ""
    for i, v in enumerate(vers, 1):
        when = datetime.fromtimestamp(v["ts"]).strftime("%Y-%m-%d %H:%M")
        print(f"Versi {i}  {when}" + (f"  - {v['note']}" if v["note"] else ""))
        print("   " + (word_diff(prev, v["text"]) if prev else v["text"]).replace("\n", "\n   "))
        prev = v["text"]
    print("\n[-dihapus-] {+ditambah+} dibandingkan versi sebelumnya. Kembalikan dengan: revert ID NOMOR")


def cmd_revert(a):
    work = work_db(a.workdb)
    get_entry(work, a.id)
    vers = work.execute("SELECT * FROM versions WHERE entry_id=? ORDER BY vid", (a.id,)).fetchall()
    if not 1 <= a.version <= len(vers):
        die(f"versi harus antara 1 dan {len(vers)}")
    set_target(work, a.id, vers[a.version - 1]["text"], "edited", f"Kembali ke versi {a.version}")
    print(f"Dikembalikan ke versi {a.version} (dicatat sebagai versi baru).")


def cmd_stats(a):
    work = work_db(a.workdb)
    total = work.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    if not total:
        print("Workbench masih kosong. Jalankan 'import' dulu.")
        return
    untr = work.execute("SELECT COUNT(*) FROM entries WHERE target=''").fetchone()[0]
    print(f"Total        : {total}")
    print(f"Belum        : {untr}")
    for st in ("mt", "edited", "approved"):
        n = work.execute("SELECT COUNT(*) FROM entries WHERE target!='' AND status=?", (st,)).fetchone()[0]
        print(f"{st:<13}: {n}")
    print(f"Progres      : {(total - untr) / total * 100:.1f}% punya terjemahan")
    if a.by_prefix:
        key = "substr(id, instr(id, ':') + 1)"
        print("\nKategori terbesar (awalan ID sebelum '_'):")
        print(f"  {'awalan':<22}{'total':>8}{'sudah':>8}")
        for p, n, done in work.execute(
                f"SELECT substr({key}, 1, instr({key} || '_', '_') - 1) AS p, COUNT(*), SUM(target != '') "
                f"FROM entries GROUP BY p ORDER BY COUNT(*) DESC LIMIT ?", (a.by_prefix,)):
            print(f"  {p:<22}{n:>8}{done:>8}")


# ----------------------------------------------------------------- machine translation

def protect(text):
    saved = []

    def sub(m):
        saved.append(m.group(0))
        return f"⟦{len(saved) - 1}⟧"

    return PLACEHOLDER.sub(sub, text), saved


def restore(text, saved):
    ok = True
    for i in range(len(saved)):
        if text.count(f"⟦{i}⟧") != 1:      # hilang atau dobel
            ok = False
    if re.search(r"⟦(\d+)⟧", text) and any(int(n) >= len(saved) for n in re.findall(r"⟦(\d+)⟧", text)):
        ok = False                          # token asing yang tidak ada di teks asli
    for i, original in enumerate(saved):
        text = text.replace(f"⟦{i}⟧", original)
    return text, ok


def chunks(s, limit=450):
    parts = [p for p in re.split(r"(?<=[.!?。！？…])\s*", s) if p]
    out, buf = [], ""
    for p in parts:
        if buf and len(buf) + 1 + len(p) > limit:
            out.append(buf)
            buf = p
        else:
            buf = (buf + " " + p).strip()
    if buf:
        out.append(buf)
    return out or [s]


def http_json(url, payload=None, timeout=60, headers=None):
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (429, 529):
            raise RateLimit(f"HTTP {e.code} (batas permintaan / server sibuk)")
        detail = ""
        try:
            detail = " - " + json.load(e).get("error", {}).get("message", "")
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code}{detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"koneksi gagal: {e.reason}")


CLAUDE_SYSTEM = (
    "Kamu penerjemah teks game (cerita, dialog, UI) dari {src} ke bahasa Indonesia yang natural. "
    "Pesan pengguna adalah objek JSON {{id: teks}}. Balas HANYA dengan objek JSON berkunci sama berisi "
    "terjemahannya, tanpa penjelasan dan tanpa pagar kode. Aturan: (1) token seperti ⟦0⟧, ⟦1⟧ adalah "
    "pengganti tag/variabel; salin setiap token persis satu kali di posisi yang wajar. (2) Nada dialog "
    "mengikuti karakter dan konteks; jangan terlalu kaku. (3) Nama diri, nama skill/item/tempat yang "
    "lazim dibiarkan dalam bahasa aslinya kecuali ada di glosarium. (4) Jangan menambah atau menghapus makna."
)


def translate_claude(items, a):
    """items: list (id, teks terlindungi). Mengembalikan dict id -> terjemahan terlindungi."""
    key = a.key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        die("provider claude butuh API key: set env ANTHROPIC_API_KEY (atau --key)")
    system = CLAUDE_SYSTEM.format(src=a.src)
    if a.glossary:
        gl = json.loads(Path(a.glossary).read_text(encoding="utf-8"))
        system += "\nGlosarium wajib (asli -> terjemahan):\n" + "\n".join(f"{k} -> {v}" for k, v in gl.items())
    payload = {"model": a.model, "max_tokens": 8000, "system": system,
               "messages": [{"role": "user", "content": json.dumps(dict(items), ensure_ascii=False)}]}
    j = http_json("https://api.anthropic.com/v1/messages", payload, timeout=180,
                  headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    u = j.get("usage") or {}
    if hasattr(a, "usage"):
        a.usage[0] += u.get("input_tokens", 0)
        a.usage[1] += u.get("output_tokens", 0)
    text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        out = json.loads(text)
    except ValueError:
        raise RuntimeError("balasan Claude bukan JSON yang valid")
    return {k: str(v) for k, v in out.items()}


def translate(text, a):
    protected, saved = protect(text)
    if not re.sub(r"⟦\d+⟧", "", protected).strip():
        return text
    if a.provider == "mymemory":
        pieces = []
        for part in chunks(protected):
            qs = {"q": part, "langpair": f"{a.src}|{a.tgt}"}
            email = a.email or os.environ.get("MYMEMORY_EMAIL")
            if email:
                qs["de"] = email
            j = http_json("https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(qs))
            if str(j.get("responseStatus")) == "429":
                raise RateLimit("batas harian MyMemory tercapai")
            if str(j.get("responseStatus")) != "200":
                raise RuntimeError(j.get("responseDetails") or "MyMemory gagal")
            pieces.append(j["responseData"]["translatedText"])
        out = " ".join(pieces)
    else:
        url = a.url or os.environ.get("LIBRETRANSLATE_URL") or "http://localhost:5000"
        code = lambda c: "zh" if c == "zh-CN" else c
        payload = {"q": protected, "source": code(a.src), "target": code(a.tgt), "format": "text"}
        key = a.key or os.environ.get("LIBRETRANSLATE_KEY")
        if key:
            payload["api_key"] = key
        try:
            out = http_json(url.rstrip("/") + "/translate", payload)["translatedText"]
        except RuntimeError as e:
            if str(e).startswith("koneksi gagal"):
                raise ServerDown(f"tidak bisa menghubungi LibreTranslate di {url}. Pastikan server LibreTranslate "
                                 "sedang berjalan (lihat README), atau tentukan alamatnya dengan --url.")
            raise
    result, ok = restore(out, saved)
    if not ok or tag_problems(text, result):
        raise RuntimeError("placeholder/tag rusak oleh mesin, terjemahkan manual")
    return result


def dataset_clause(name):
    return "substr(id, 1, ?) = ?", [len(name) + 1, name + ":"]


def cmd_mt(a):
    work = work_db(a.workdb)
    if a.ids:
        rows = [get_entry(work, i) for i in a.ids]
    else:
        where, params = ["target = ''", "source != ''"], []
        if a.name:
            c, p = dataset_clause(a.name)
            where.append(c)
            params += p
        if a.match:
            where.append("source LIKE ? ESCAPE '\\'")
            params.append("%" + like_escape(a.match) + "%")
        if a.prefix:
            where.append("id LIKE ? ESCAPE '\\'")
            params.append("%:" + like_escape(a.prefix) + "%")
        rows = work.execute(f"SELECT * FROM entries WHERE {' AND '.join(where)} ORDER BY id LIMIT ?",
                            params + [a.limit]).fetchall()
    if not rows:
        print("Tidak ada entri yang perlu diterjemahkan.")
        return
    label = a.provider + (f"/{a.model}" if a.provider == "claude" else "")
    print(f"Menerjemahkan {len(rows)} entri dengan {label} ({a.src} → {a.tgt})")
    ok = fail = 0

    def save(r, text, i):
        nonlocal ok
        if a.dry_run:
            print(f"[{i}/{len(rows)}] {r['id']}: {short(text)}")
        else:
            set_target(work, r["id"], text, "mt", f"Terjemahan mesin ({label})")
            print(f"[{i}/{len(rows)}] {r['id']}: ok")
        ok += 1

    if a.provider == "claude":
        a.usage = [0, 0]
        sent = 0
        for start in range(0, len(rows), a.batch):
            group = rows[start:start + a.batch]
            chars = sum(len(r["source"]) for r in group)
            if a.max_chars and sent + chars > a.max_chars:
                print(f"berhenti: batas --max-chars {a.max_chars} tercapai ({sent} karakter terkirim). "
                      "Naikkan batasnya kalau memang disengaja.")
                break
            sent += chars
            prot = {r["id"]: protect(r["source"]) for r in group}
            try:
                got = translate_claude([(k, v[0]) for k, v in prot.items()], a)
            except RateLimit as e:
                print(f"berhenti - {e}. Lanjutkan nanti, hasil sebelumnya sudah tersimpan.")
                break
            except RuntimeError as e:
                fail += len(group)
                print(f"batch {start + 1}-{start + len(group)} gagal - {e}")
                continue
            for j, r in enumerate(group, start + 1):
                if r["id"] not in got:
                    fail += 1
                    print(f"[{j}/{len(rows)}] {r['id']}: gagal - tidak ada di balasan")
                    continue
                text, good = restore(got[r["id"]], prot[r["id"]][1])
                if not good or tag_problems(r["source"], text):
                    fail += 1
                    print(f"[{j}/{len(rows)}] {r['id']}: gagal - tag/variabel rusak, terjemahkan manual")
                    continue
                save(r, text, j)
            if start + a.batch < len(rows):
                time.sleep(a.delay)
    else:
        for i, r in enumerate(rows, 1):
            try:
                save(r, translate(r["source"], a), i)
            except RateLimit as e:
                print(f"[{i}/{len(rows)}] {r['id']}: berhenti - {e}. Lanjutkan nanti, hasil sebelumnya sudah tersimpan.")
                break
            except ServerDown as e:
                print(f"berhenti: {e}")
                break
            except RuntimeError as e:
                fail += 1
                print(f"[{i}/{len(rows)}] {r['id']}: gagal - {e}")
            if i < len(rows):
                time.sleep(a.delay)
    print(f"Selesai: {ok} berhasil, {fail} gagal.")
    if a.provider == "claude":
        print(f"Pemakaian token run ini: {a.usage[0]:,} masuk, {a.usage[1]:,} keluar "
              "(kalikan dengan harga model di halaman pricing untuk perkiraan biaya).")


# ----------------------------------------------------------------- export

def cmd_export_json(a):
    work = work_db(a.workdb)
    rows = work.execute("SELECT id, target FROM entries WHERE target != '' ORDER BY id").fetchall()
    Path(a.out).write_text(json.dumps({r["id"]: r["target"] for r in rows}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"{len(rows)} terjemahan ditulis ke {a.out}")


def pick_dataset(work, name):
    maps = get_mappings(work)
    if not maps:
        die("belum ada dataset. Jalankan 'import' atau 'import-translated' dulu.")
    if name is None:
        if len(maps) > 1:
            die("ada beberapa dataset (" + ", ".join(maps) + "); pilih dengan --name")
        name = next(iter(maps))
    if name not in maps:
        die(f"dataset '{name}' tidak ada. Yang ada: {', '.join(maps)}")
    return name, maps[name]


def apply_dataset(con, work, name, m, allowed):
    """Tulis terjemahan satu dataset ke kolom Content di db 'con'. Id dan kolom lain tidak disentuh."""
    decl = {c[1]: (c[2] or "") for c in table_columns(con, m["table"])}
    numeric_id = "INT" in decl.get(m["id_col"], "").upper()
    sql = f"UPDATE {qi(m['table'])} SET {qi(m['text_col'])}=? WHERE {qi(m['id_col'])}=?"
    rows = work.execute(
        f"SELECT id, target FROM entries WHERE substr(id, 1, ?) = ? AND target != '' "
        f"AND status IN ({','.join('?' * len(allowed))})", [len(name) + 1, name + ":", *allowed]).fetchall()
    written = missing = 0
    with con:
        for r in rows:
            key = r["id"][len(name) + 1:]
            if numeric_id and re.fullmatch(r"-?\d+", key):
                key = int(key)
            if con.execute(sql, (r["target"], key)).rowcount:
                written += 1
            else:
                missing += 1
    return written, missing


def write_translated_copy(work, name, m, base, out, only_approved, include=()):
    """Salin db dasar ke 'out', lalu tulis terjemahan dataset utama (dan dataset --include) ke salinan itu.
    Mengembalikan daftar (dataset, ditulis, tidak_ditemukan)."""
    shutil.copyfile(base, out)
    allowed = ("approved",) if only_approved else ("mt", "edited", "approved")
    maps = get_mappings(work)
    con = sqlite3.connect(out)
    detail = []
    try:
        for ds in [name, *include]:
            mm = m if ds == name else maps.get(ds)
            if mm is None:
                die(f"dataset '{ds}' tidak ada. Yang ada: {', '.join(maps)}")
            if mm["table"] != m["table"] or mm["id_col"] != m["id_col"] or mm["text_col"] != m["text_col"]:
                die(f"dataset '{ds}' memakai tabel/kolom yang berbeda dari '{name}', tidak bisa digabung ke satu db")
            detail.append((ds, *apply_dataset(con, work, ds, mm, allowed)))
    finally:
        con.close()
    return detail


CHECK_TAGS = re.compile(r"<[^>]+>|\{[^}]*\}|%[sd]|\\n")
TAG_NAME = re.compile(r"<(/?)([A-Za-z][\w-]*)[^>]*?(/?)>")


def tags_balanced(text):
    """True kalau tag pembuka/penutup (<color=..> ... </color>) bersarang dengan benar."""
    stack = []
    for m in TAG_NAME.finditer(text):
        close, name, selfclose = m.groups()
        if selfclose:
            continue
        if close:
            if not stack or stack.pop() != name:
                return False
        else:
            stack.append(name)
    return not stack


def tag_problems(source, target):
    """Bandingkan tag/variabel asli dengan terjemahan (urutan boleh beda). Mengembalikan daftar masalah."""
    a, b = Counter(CHECK_TAGS.findall(source)), Counter(CHECK_TAGS.findall(target))
    out = [f"hilang: {t}" for t in (a - b).elements()] + [f"kelebihan: {t}" for t in (b - a).elements()]
    if re.search(r"⟦\d+⟧", target):
        out.append("sisa kode sementara ⟦n⟧ di terjemahan")
    if tags_balanced(source) and not tags_balanced(target):
        out.append("urutan tag pembuka/penutup salah")
    return out


def find_problems(work, name=None, statuses=("mt", "edited", "approved")):
    where, params = ["target != ''", "source != ''", f"status IN ({','.join('?' * len(statuses))})"], list(statuses)
    if name:
        c, p = dataset_clause(name)
        where.append(c)
        params += p
    bad = []
    for r in work.execute(f"SELECT id, source, target FROM entries WHERE {' AND '.join(where)} ORDER BY id", params):
        probs = tag_problems(r["source"], r["target"])
        if probs:
            bad.append((r["id"], probs))
    return bad


def cmd_check(a):
    work = work_db(a.workdb)
    bad = find_problems(work, a.name)
    skipped = work.execute("SELECT COUNT(*) FROM entries WHERE target != '' AND source = ''").fetchone()[0]
    for eid, probs in bad[: a.limit]:
        print(f"{eid}: " + "; ".join(probs))
    if len(bad) > a.limit:
        print(f"... dan {len(bad) - a.limit} lagi (naikkan --limit)")
    print(f"\n{len(bad)} entri bermasalah." if bad else "\nSemua tag dan variabel cocok dengan teks asli.")
    if skipped:
        print(f"({skipped} entri tidak bisa dicek karena tidak punya teks asli.)")
    sys.exit(1 if bad else 0)


def export_gate(work, names, only_approved, skip_check):
    statuses = ("approved",) if only_approved else ("mt", "edited", "approved")
    bad = []
    for n in names:
        bad += find_problems(work, n, statuses)
    if bad and not skip_check:
        for eid, probs in bad[:5]:
            print(f"  {eid}: " + "; ".join(probs), file=sys.stderr)
        die(f"{len(bad)} entri punya tag/variabel yang tidak cocok dengan teks asli, ekspor dibatalkan. "
            f"Lihat semuanya dengan 'check --name {names[0]}', perbaiki, lalu ulangi "
            "(atau pakai --skip-check kalau kamu yakin).")


def report_detail(detail, out):
    for ds, written, missing in detail:
        print(f"[{ds}] {written} baris ditulis ke {out}" + (f" ({missing} Id tidak ada di db dasar)" if missing else ""))


def cmd_export_db(a):
    src, dst = Path(a.game_db).resolve(), Path(a.out).resolve()
    if src == dst:
        die("file tujuan tidak boleh sama dengan file database asli")
    if dst.exists() and not a.force:
        die(f"{a.out} sudah ada. Pakai --force untuk menimpa.")
    work = work_db(a.workdb)
    name, m = pick_dataset(work, a.name)
    export_gate(work, [name, *a.include], a.only_approved, a.skip_check)
    report_detail(write_translated_copy(work, name, m, a.game_db, a.out, a.only_approved, a.include), a.out)
    print("Database asli tidak diubah.")


def cmd_export_pak(a):
    work = work_db(a.workdb)
    name, m = pick_dataset(work, a.name)
    export_gate(work, [name, *a.include], a.only_approved, a.skip_check)
    out = a.out or f"WuwaID_{name}_P.pak"
    if os.path.exists(out) and not a.force:
        die(f"{out} sudah ada. Pakai --force untuk menimpa.")
    game_path = a.game_path or m.get("game_path") or GAME_DIR + os.path.basename(a.base)
    tmp = os.path.join(tempfile.mkdtemp(), "translated.db")
    report_detail(write_translated_copy(work, name, m, a.base, tmp, a.only_approved, a.include), out)
    Path(out).write_bytes(build_pak(game_path, Path(tmp).read_bytes()))
    print(f"Path di dalam pak: {game_path}  ({os.path.getsize(out):,} byte)")


def cmd_unpack_pak(a):
    path, data = read_pak(a.pak)
    dest = Path(a.outdir) / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"{path} ({len(data):,} byte) -> {dest}")


# ----------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(description="Workbench terjemahan dialog berbasis SQLite.")
    p.add_argument("--workdb", default=os.environ.get("WW_WORKDB", "workbench.db"),
                   help="file database kerja (default: workbench.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("inspect", help="lihat tabel dan kolom di database game")
    s.add_argument("game_db"); s.add_argument("--table"); s.add_argument("--sample", type=int, default=0)
    s.add_argument("--grep", help="saring nama tabel yang mengandung teks ini")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("find", help="cari tabel/kolom yang memuat potongan teks")
    s.add_argument("game_db"); s.add_argument("text")
    s.set_defaults(fn=cmd_find)

    s = sub.add_parser("import", help="impor satu tabel dari database game ke workbench")
    s.add_argument("game_db"); s.add_argument("--table", required=True)
    s.add_argument("--id-col", required=True); s.add_argument("--text-col", required=True)
    s.add_argument("--speaker-col"); s.add_argument("--where", help="filter SQL tambahan, misalnya \"Id > 1000\"")
    s.add_argument("--name", help="nama dataset (default: nama tabel), misalnya main atau 1sthalf")
    s.add_argument("--game-path", help="path file ini di dalam game (default: Client/Content/Aki/ConfigDB/en/<nama file>)")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("import-translated", help="impor terjemahan yang sudah ada dari .pak, .db, atau .json {id: teks}")
    s.add_argument("file"); s.add_argument("--name", required=True, help="nama dataset tujuan")
    s.add_argument("--table", default="MultiText"); s.add_argument("--id-col", default="Id")
    s.add_argument("--text-col", default="Content"); s.add_argument("--game-path")
    s.set_defaults(fn=cmd_import_translated)

    s = sub.add_parser("search", help="cari dialog")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--in", dest="in_", choices=["all", "id", "source", "target"], default="all")
    s.add_argument("--status", choices=["untranslated", "mt", "edited", "approved"])
    s.add_argument("--prefix", help="hanya ID yang diawali ini, misalnya Quest_ atau Main_")
    s.add_argument("--name", help="batasi ke satu dataset")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("show", help="tampilkan satu entri"); s.add_argument("id"); s.set_defaults(fn=cmd_show)

    s = sub.add_parser("edit", help="sunting terjemahan (tanpa --text akan membuka editor)")
    s.add_argument("id"); s.add_argument("--text"); s.add_argument("--note")
    s.add_argument("--approve", action="store_true", help="tandai langsung sebagai disetujui")
    s.set_defaults(fn=cmd_edit)

    s = sub.add_parser("approve", help="tandai entri sebagai disetujui")
    s.add_argument("ids", nargs="+"); s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("history", help="riwayat versi satu entri"); s.add_argument("id"); s.set_defaults(fn=cmd_history)

    s = sub.add_parser("revert", help="kembalikan ke versi lama")
    s.add_argument("id"); s.add_argument("version", type=int); s.set_defaults(fn=cmd_revert)

    s = sub.add_parser("mt", help="terjemahan mesin")
    s.add_argument("ids", nargs="*", help="ID tertentu; kosongkan untuk semua yang belum diterjemahkan")
    s.add_argument("--untranslated", action="store_true", help="(default bila tanpa ID)")
    s.add_argument("--match", help="hanya teks asli yang mengandung kata ini")
    s.add_argument("--prefix", help="hanya ID yang diawali ini, misalnya Quest_")
    s.add_argument("--name", help="batasi ke satu dataset")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--provider", choices=["claude", "mymemory", "libre"], default="claude")
    s.add_argument("--model", default="claude-sonnet-5-5", help="model Claude (claude-haiku-5-5 lebih murah)")
    s.add_argument("--batch", type=int, default=15, help="jumlah baris per permintaan (provider claude)")
    s.add_argument("--glossary", help="JSON {istilah: terjemahan} agar nama/istilah konsisten (provider claude)")
    s.add_argument("--max-chars", type=int, default=30000,
                   help="batas total karakter teks asli yang dikirim per run (provider claude, 0 = tanpa batas)")
    s.add_argument("--src", default="en"); s.add_argument("--tgt", default="id")
    s.add_argument("--url", help="alamat LibreTranslate (default http://localhost:5000)")
    s.add_argument("--key"); s.add_argument("--email")
    s.add_argument("--delay", type=float, default=1.0, help="jeda antar permintaan (detik)")
    s.add_argument("--dry-run", action="store_true", help="tampilkan hasil tanpa menyimpan")
    s.set_defaults(fn=cmd_mt)

    s = sub.add_parser("stats", help="ringkasan progres")
    s.add_argument("--by-prefix", type=int, nargs="?", const=20, default=0, metavar="N",
                   help="tampilkan N kategori ID terbesar (default 20)")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("check", help="cek semua terjemahan: tag/variabel harus sama dengan teks asli")
    s.add_argument("--name"); s.add_argument("--limit", type=int, default=30)
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("export-json", help="ekspor {id: terjemahan}")
    s.add_argument("out"); s.set_defaults(fn=cmd_export_json)

    s = sub.add_parser("export-db", help="tulis terjemahan ke SALINAN database game")
    s.add_argument("game_db"); s.add_argument("out"); s.add_argument("--name")
    s.add_argument("--only-approved", action="store_true"); s.add_argument("--force", action="store_true")
    s.add_argument("--include", nargs="+", default=[], metavar="DATASET",
                   help="gabungkan juga terjemahan dataset lain (mis. 1sthalf) ke Content baris ber-Id sama; RedirectDbIndex tidak diubah")
    s.add_argument("--skip-check", action="store_true", help="lewati pemeriksaan tag/variabel (tidak disarankan)")
    s.set_defaults(fn=cmd_export_db)

    s = sub.add_parser("export-pak", help="tulis terjemahan ke salinan db lalu bungkus jadi file .pak")
    s.add_argument("--base", required=True, help="db dasar (db asli game, atau db dari pak lama)")
    s.add_argument("--name"); s.add_argument("--out", help="default: WuwaID_<name>_P.pak")
    s.add_argument("--game-path", help="path di dalam game (default: dari saat impor)")
    s.add_argument("--only-approved", action="store_true"); s.add_argument("--force", action="store_true")
    s.add_argument("--include", nargs="+", default=[], metavar="DATASET",
                   help="gabungkan juga terjemahan dataset lain (mis. 1sthalf) ke Content baris ber-Id sama; RedirectDbIndex tidak diubah")
    s.add_argument("--skip-check", action="store_true", help="lewati pemeriksaan tag/variabel (tidak disarankan)")
    s.set_defaults(fn=cmd_export_pak)

    s = sub.add_parser("unpack-pak", help="keluarkan file db dari .pak (pak 1 file)")
    s.add_argument("pak"); s.add_argument("outdir", nargs="?", default="unpacked")
    s.set_defaults(fn=cmd_unpack_pak)
    return p


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
