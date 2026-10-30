"""Antarmuka baris perintah."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .adapters import ADAPTERS
from .core.csvio import read_rows, write_rows
from .core.errors import GamelokalError
from .core.glossary import load_glossary
from .core.store import StoreError, guess_columns, inspect_db, iter_rows
from .core.text import short, word_diff
from .core.workbench import STATUSES, Workbench, WorkbenchError
from .pack import build_pak, read_pak, write_translated_copy
from .qa.checks import check_consistency, check_entry
from .translate import DEFAULT_MODEL, ProviderError, RateLimited, ServerDown, get_provider, translate_safe


# ------------------------------------------------------------------ penjelajahan

def cmd_inspect(a) -> int:
    for t in inspect_db(a.db):
        print(f"{t.name}  ({t.rows} baris)")
        for c in t.columns:
            print(f"    {c.name} {c.type}{' PK' if c.pk else ''}")
    g = guess_columns(a.db)
    print(f"\nTebakan: tabel={g.table} id={g.id_col} teks={g.text_col}" if g else "\nKolom teks tidak bisa ditebak.")
    return 0


def cmd_find(a) -> int:
    dbs = ADAPTERS[a.adapter].find_dbs(a.root, a.lang)
    for p in dbs:
        print(p)
    print(f"{len(dbs)} berkas ditemukan", file=sys.stderr)
    return 0


# ------------------------------------------------------------------ impor

def _resolve(a, dbpath=None):
    """Menentukan adapter, tabel, kolom id, dan kolom teks dari opsi, adapter, atau tebakan."""
    ad = ADAPTERS.get(a.adapter) if a.adapter else None
    use = ad if ad and (not a.table or a.table == ad.table) else None
    t = a.table or (ad.table if ad else None)
    i = a.id_col or (use.id_col if use else None)
    x = a.text_col or (use.text_col if use else None)
    if not (t and i and x) and dbpath is not None:
        g = guess_columns(dbpath)
        if g and (not t or t == g.table):
            t, i, x = t or g.table, i or g.id_col, x or g.text_col
    return ad, t, i, x


def _need(t, i, x):
    if not (t and i and x):
        raise WorkbenchError("kolom tidak bisa ditentukan. Jalankan `inspect`, lalu isi --table --id-col --text-col "
                             "(atau pakai --adapter).")


def cmd_import(a) -> int:
    ad, t, i, x = _resolve(a, a.game_db)
    _need(t, i, x)
    ds = a.name or t
    game_path = a.game_path or (ad.game_dir + os.path.basename(a.game_db) if ad else None)
    speaker = a.speaker_col or (ad.speaker_col if ad else None)
    mapping = {"table": t, "id_col": i, "text_col": x, "game_path": game_path}
    with Workbench(a.workdb) as wb:
        new, changed, same = wb.import_source(ds, iter_rows(a.game_db, t, i, x, speaker, a.where), mapping)
    print(f"[{ds}] impor selesai: {new} baru, {changed} teks asli berubah, {same} tidak berubah.")
    if game_path:
        print(f"Path di game: {game_path}")
    return 0


def cmd_import_translated(a) -> int:
    f = Path(a.file)
    ds = a.name
    game_path = None
    with tempfile.TemporaryDirectory() as td:
        if f.suffix.lower() == ".json":
            ad, t, i, x = _resolve(a)
            data = json.loads(f.read_text(encoding="utf-8"))
            pairs = [(k if ":" in k else f"{ds}:{k}", str(v)) for k, v in data.items()]
            full = True
        else:
            if f.suffix.lower() == ".pak":
                game_path, blob = read_pak(f)
                dbp = Path(td) / "x.db"
                dbp.write_bytes(blob)
            else:
                dbp = f
            ad, t, i, x = _resolve(a, dbp)
            _need(t, i, x)
            pairs = [(k, text) for k, text, _ in iter_rows(dbp, t, i, x)]
            full = False
    game_path = a.game_path or game_path or (ad.game_dir + f.name if ad and f.suffix.lower() == ".db" else None)
    mapping = {"table": t, "id_col": i, "text_col": x, "game_path": game_path} if (t and i and x) else None
    with Workbench(a.workdb) as wb:
        applied, created = wb.import_translated(ds, pairs, full_ids=full, mapping=mapping)
    print(f"[{ds}] {applied} terjemahan diimpor ({created} entri baru tanpa teks asli).")
    if created:
        print(f"Entri tanpa teks asli belum bisa dicari lewat --in source atau diterjemahkan mesin. "
              f"Impor db sumbernya dengan: import <db> --name {ds}")
    if mapping is None:
        print("Peringatan: tabel/kolom tidak diketahui, jadi dataset ini belum bisa diekspor. Impor ulang dengan --adapter atau --table.",
              file=sys.stderr)
    return 0


# ------------------------------------------------------------------ kerja

def cmd_search(a) -> int:
    with Workbench(a.workdb) as wb:
        rows, total = wb.search(a.query, a.in_, a.name, a.status, a.prefix, a.limit)
    for r in rows:
        st = r["status"] if r["target"] else "new"
        print(f"{r['id']}  [{st}]" + (f"  ({r['speaker']})" if r["speaker"] else ""))
        print(f"    {short(r['source'])}")
        print(f"    \u2192 {short(r['target']) if r['target'] else '(belum diterjemahkan)'}")
    print(f"\n{len(rows)} ditampilkan dari {total} cocok.")
    return 0


def cmd_show(a) -> int:
    with Workbench(a.workdb) as wb:
        r = wb.get(a.id)
        n = len(wb.history(a.id))
    print(f"ID      : {r['id']}")
    if r["speaker"]:
        print(f"Pembicara: {r['speaker']}")
    print(f"Status  : {r['status'] if r['target'] else 'new'}   ({n} versi)")
    print(f"\nAsli:\n{r['source']}\n\nTerjemahan:\n{r['target'] or '(kosong)'}")
    return 0


def _open_editor(initial: str) -> str:
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


def cmd_edit(a) -> int:
    with Workbench(a.workdb) as wb:
        r = wb.get(a.id)
        text = a.text
        if text is None:
            print("Asli:\n" + r["source"] + "\n")
            text = _open_editor(r["target"] or r["source"])
        wb.set_target(a.id, text, "approved" if a.approve else "edited", a.note or "Disunting", a.author)
    print("Tersimpan." if text else "Terjemahan dikosongkan.")
    return 0


def cmd_approve(a) -> int:
    with Workbench(a.workdb) as wb:
        for eid in a.ids:
            print(f"{eid}: disetujui" if wb.approve(eid, a.author) else f"{eid}: dilewati (belum ada terjemahan)")
    return 0


def cmd_history(a) -> int:
    with Workbench(a.workdb) as wb:
        vers = wb.history(a.id)
    if not vers:
        print("Belum ada riwayat.")
        return 0
    prev = ""
    for n, v in enumerate(vers, 1):
        when = datetime.fromtimestamp(v["ts"]).strftime("%Y-%m-%d %H:%M")
        print(f"Versi {n}  {when}" + (f"  - {v['note']}" if v["note"] else ""))
        print("   " + (word_diff(prev, v["text"]) if prev else v["text"]).replace("\n", "\n   "))
        prev = v["text"]
    print("\n[-dihapus-] {+ditambah+} dibandingkan versi sebelumnya. Kembalikan dengan: revert ID NOMOR")
    return 0


def cmd_revert(a) -> int:
    with Workbench(a.workdb) as wb:
        wb.revert(a.id, a.version, a.author)
    print(f"Dikembalikan ke versi {a.version} (dicatat sebagai versi baru).")
    return 0


def cmd_stats(a) -> int:
    with Workbench(a.workdb) as wb:
        s = wb.stats(a.by_prefix)
    if not s["total"]:
        print("Workbench masih kosong. Jalankan 'import' dulu.")
        return 0
    print(f"Total        : {s['total']}\nBelum        : {s['untranslated']}")
    for st in STATUSES:
        print(f"{st:<13}: {s['by_status'][st]}")
    print(f"Progres      : {(s['total'] - s['untranslated']) / s['total'] * 100:.1f}% punya terjemahan")
    if a.by_prefix:
        print("\nKategori terbesar (awalan ID sebelum '_'):")
        print(f"  {'awalan':<22}{'total':>8}{'sudah':>8}")
        for p, n, done in s["prefixes"]:
            print(f"  {p:<22}{n:>8}{done:>8}")
    return 0


def cmd_translate(a) -> int:
    gl = load_glossary(a.glossary) if a.glossary else []
    prov = get_provider(a.provider, url=a.url, key=a.key, email=a.email, model=a.model, glossary=gl)
    size = a.batch or prov.default_batch
    delay = a.delay if a.delay is not None else prov.default_delay
    ok = fail = sent = 0
    stopped = False
    with Workbench(a.workdb) as wb:
        if a.ids:
            rows = [wb.get(i) for i in a.ids]
        else:
            name, _ = wb.pick_dataset(a.name)
            rows = wb.untranslated(name, a.limit, a.match, a.prefix)
        if not rows:
            print("Tidak ada entri yang perlu diterjemahkan.")
            return 0
        print(f"Menerjemahkan {len(rows)} entri dengan {prov.label} ({a.src} \u2192 {a.tgt})")
        for start in range(0, len(rows), size):
            group = rows[start: start + size]
            chars = sum(len(r["source"]) for r in group)
            if a.max_chars and sent + chars > a.max_chars:
                print(f"berhenti: batas --max-chars {a.max_chars} tercapai ({sent} karakter terkirim). "
                      "Naikkan batasnya kalau memang disengaja.")
                break
            sent += chars
            try:
                res = translate_safe(prov, [r["source"] for r in group], a.src, a.tgt)
            except (RateLimited, ServerDown) as e:
                print(f"berhenti - {str(e).rstrip('.')}. Lanjutkan nanti, hasil sebelumnya sudah tersimpan.")
                stopped = True
                break
            except ProviderError as e:
                fail += len(group)
                print(f"[{start + 1}-{start + len(group)}] gagal - {e}")
                continue
            good = []
            for n, (r, (text, restored)) in enumerate(zip(group, res), start + 1):
                broken = (not text.strip()) or any(i.severity == "error" for i in check_entry(r["id"], r["source"], text))
                if not restored or broken:
                    fail += 1
                    print(f"[{n}/{len(rows)}] {r['id']}: gagal - tag/variabel rusak atau hasil kosong, terjemahkan manual")
                    continue
                good.append((r["id"], text))
                ok += 1
                print(f"[{n}/{len(rows)}] {r['id']}: " + (short(text) if a.dry_run else "ok"))
            if good and not a.dry_run:
                wb.set_targets(good, "mt", f"Terjemahan mesin ({prov.label})")  # disimpan tiap batch
            if start + size < len(rows) and delay:
                time.sleep(delay)
    print(f"Selesai: {ok} berhasil, {fail} gagal." + (" (dry-run: tidak disimpan)" if a.dry_run else ""))
    if getattr(prov, "usage", None):
        print(f"Pemakaian token run ini: {prov.usage[0]:,} masuk, {prov.usage[1]:,} keluar "
              "(kalikan dengan harga model di dokumentasi resmi untuk perkiraan biaya).")
    return 3 if stopped else 0  # 3 = berhenti di tengah jalan, aman dilanjutkan


# ------------------------------------------------------------------ kualitas dan ekspor

def cmd_qa(a) -> int:
    gl = load_glossary(a.glossary) if a.glossary else []
    with Workbench(a.workdb) as wb:
        rows = wb.entries(a.name)
        pending = wb.stats()["untranslated"]
    issues = []
    for r in rows:
        issues += check_entry(r["id"], r["source"], r["target"], gl, a.max_ratio)
    issues += check_consistency((r["id"], r["source"], r["target"]) for r in rows)
    for i in issues[: a.limit]:
        print(f"[{i.severity}] {i.id} {i.code}: {i.message}")
    if len(issues) > a.limit:
        print(f"... dan {len(issues) - a.limit} lagi (naikkan --limit)")
    errors = sum(1 for i in issues if i.severity == "error")
    print(f"\n{len(rows)} entri diperiksa, {pending} belum diterjemahkan, {errors} error, {len(issues) - errors} peringatan")
    return 1 if errors else 0


def _gate(wb: Workbench, names, only_approved: bool, skip: bool) -> None:
    statuses = ("approved",) if only_approved else STATUSES
    bad = []
    for n in names:
        for r in wb.entries(n, statuses):
            errs = [i.message for i in check_entry(r["id"], r["source"], r["target"]) if i.severity == "error"]
            if errs:
                bad.append((r["id"], errs))
    if bad and not skip:
        for eid, errs in bad[:5]:
            print(f"  {eid}: " + "; ".join(errs), file=sys.stderr)
        raise WorkbenchError(f"{len(bad)} entri punya tag/variabel yang tidak cocok dengan teks asli, ekspor dibatalkan. "
                             f"Lihat semuanya dengan 'qa --name {names[0]}', perbaiki, lalu ulangi (atau pakai --skip-check).")


def _report(detail, out) -> None:
    for ds, written, missing in detail:
        print(f"[{ds}] {written} baris ditulis ke {out}" + (f" ({missing} Id tidak ada di db dasar)" if missing else ""))


def cmd_export_db(a) -> int:
    src, dst = Path(a.game_db).resolve(), Path(a.out).resolve()
    if src == dst:
        raise WorkbenchError("file tujuan tidak boleh sama dengan file database asli")
    if dst.exists() and not a.force:
        raise WorkbenchError(f"{a.out} sudah ada. Pakai --force untuk menimpa.")
    with Workbench(a.workdb) as wb:
        name, _ = wb.pick_dataset(a.name)
        _gate(wb, [name, *a.include], a.only_approved, a.skip_check)
        _report(write_translated_copy(wb, name, a.game_db, a.out, a.only_approved, a.include), a.out)
    print("Database asli tidak diubah.")
    return 0


def cmd_export_pak(a) -> int:
    with Workbench(a.workdb) as wb:
        name, m = wb.pick_dataset(a.name)
        _gate(wb, [name, *a.include], a.only_approved, a.skip_check)
        out = a.out or f"{name}_P.pak"
        if os.path.exists(out) and not a.force:
            raise WorkbenchError(f"{out} sudah ada. Pakai --force untuk menimpa.")
        game_path = a.game_path or m.get("game_path")
        if not game_path:
            raise WorkbenchError("path di dalam game belum diketahui. Pakai --game-path atau impor dengan --adapter.")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "translated.db"
            _report(write_translated_copy(wb, name, a.base, tmp, a.only_approved, a.include), out)
            Path(out).write_bytes(build_pak(game_path, tmp.read_bytes()))
    print(f"Path di dalam pak: {game_path}  ({os.path.getsize(out):,} byte)")
    return 0


def cmd_unpack_pak(a) -> int:
    path, data = read_pak(a.pak)
    dest = Path(a.outdir) / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"{path} ({len(data):,} byte) -> {dest}")
    return 0


def cmd_export_csv(a) -> int:
    with Workbench(a.workdb) as wb:
        rows = [dict(r) for r in wb.dump(a.name)]
    write_rows(a.csv, rows)
    print(f"{len(rows)} baris ditulis ke {a.csv}")
    return 0


def cmd_import_csv(a) -> int:
    rows = [r for r in read_rows(a.csv) if r["target"].strip()]
    with Workbench(a.workdb) as wb:
        changed, unknown, same = wb.apply_targets(((r["id"], r["target"]) for r in rows), "edited", "Impor CSV", a.author)
    print(f"{changed} diubah, {same} sama, {unknown} id tidak dikenal.")
    return 0


def cmd_export_json(a) -> int:
    with Workbench(a.workdb) as wb:
        rows = [r for r in wb.dump(a.name) if r["target"]]
    Path(a.out).write_text(json.dumps({r["id"]: r["target"] for r in rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(rows)} terjemahan ditulis ke {a.out}")
    return 0


def cmd_audit(a) -> int:
    ad = ADAPTERS[a.adapter]
    dbs = ad.find_dbs(a.root, a.lang)
    if not dbs:
        print(f"Tidak ada {ad.db_pattern} di folder '{a.lang}' dalam {a.root}.", file=sys.stderr)
        return 1
    match = other = 0
    for p in dbs:
        try:
            tables = inspect_db(p)
        except StoreError as e:
            print(f"galat   {p.name}: {e}")
            other += 1
            continue
        t = next((t for t in tables if t.name == ad.table), None)
        if t and {ad.id_col, ad.text_col} <= {c.name for c in t.columns}:
            print(f"cocok   {p.name}: {ad.table} {t.rows} baris")
            match += 1
        else:
            g = guess_columns(p)
            print(f"beda    {p.name}: tabel {', '.join(x.name for x in tables) or '(kosong)'}"
                  + (f"; tebakan {g.table}.{g.text_col} (id {g.id_col})" if g else ""))
            other += 1
    print(f"\n{match} cocok dengan skema adapter, {other} berbeda atau bermasalah. "
          "Yang berbeda bisa diimpor dengan --table --id-col --text-col.")
    return 0 if not other else 1


def cmd_user_add(a) -> int:
    with Workbench(a.workdb) as wb:
        token = wb.add_user(a.name)
    print(f"Pengguna '{a.name}' dibuat. Token pribadi (hanya ditampilkan sekali, simpan baik-baik):\n\n    {token}\n")
    print(f"Tautan masuk: http://<alamat-server>:8000/?token={token}")
    return 0


def cmd_user_list(a) -> int:
    with Workbench(a.workdb) as wb:
        users = wb.users()
    for u in users:
        print(f"{u['name']}  (dibuat {datetime.fromtimestamp(u['created']).strftime('%Y-%m-%d')})")
    print(f"{len(users)} pengguna." if users else "Belum ada pengguna. Tanpa akun, server memakai --token bersama atau hanya localhost.")
    return 0


def cmd_user_remove(a) -> int:
    with Workbench(a.workdb) as wb:
        wb.remove_user(a.name)
    print(f"Pengguna '{a.name}' dihapus. Riwayat suntingannya tetap tersimpan.")
    return 0


def cmd_serve(a) -> int:
    import secrets
    import webbrowser

    from .web.server import make_server

    token = secrets.token_urlsafe(12) if a.token == "auto" else a.token
    provider = None
    if a.provider:
        gl = load_glossary(a.glossary) if a.glossary else []
        provider = get_provider(a.provider, url=a.url, key=a.key, email=a.email, model=a.model, glossary=gl)
    budget = a.mt_budget if a.mt_budget is not None else (200_000 if a.provider == "claude" else 0)
    srv = make_server(a.workdb, a.host, a.port, token, a.glossary, provider, a.src, a.tgt, budget)
    port = srv.server_address[1]
    with Workbench(a.workdb) as wb:
        users = wb.user_count()
    suffix = f"/?token={token}" if token and not users else "/"
    if users:
        print(f"{users} akun terdaftar: tiap orang membuka tautan pribadi dari user-add (alamat di atas + ?token=...).")
    if provider:
        print(f"Saran mesin aktif: {provider.label}" + (f", batas {budget:,} karakter per sesi server." if budget else "."))
    print(f"Buka: http://{'localhost' if a.host in ('127.0.0.1', '::1') else a.host}:{port}{suffix}")
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print("Peringatan: dibuka untuk jaringan. Siapa pun yang punya token bisa mengubah terjemahan, dan lalu lintas "
              "tidak dienkripsi. Jika memakai 0.0.0.0, ganti dengan alamat IP komputermu saat membagikan tautan. "
              "Dua orang yang menyunting entri yang sama: yang terakhir menyimpan menang, dan keduanya tercatat di riwayat.")
    print("Tekan Ctrl+C untuk berhenti.")
    if a.open:
        webbrowser.open(f"http://localhost:{port}{suffix}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nBerhenti.")
    finally:
        srv.server_close()
    return 0


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="gamelokal", description="Toolkit lokalisasi game.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workdb", default="workbench.db", help="berkas workbench (default: workbench.db)")
    common.add_argument("--as", dest="author", default=os.environ.get("GAMELOKAL_USER", ""),
                        help="nama penyunting yang dicatat di riwayat (default: env GAMELOKAL_USER)")

    def add(name, fn, help_, work=True):
        s = sub.add_parser(name, help=help_, parents=[common] if work else [])
        s.set_defaults(fn=fn)
        return s

    def cols(s):
        s.add_argument("--adapter", choices=sorted(ADAPTERS))
        s.add_argument("--table")
        s.add_argument("--id-col")
        s.add_argument("--text-col")
        s.add_argument("--game-path", help="lokasi berkas di dalam .pak")

    s = add("inspect", cmd_inspect, "lihat tabel dan kolom, dan tebak kolom teks", work=False)
    s.add_argument("db")
    s = add("find", cmd_find, "cari berkas .db game lewat adapter", work=False)
    s.add_argument("adapter", choices=sorted(ADAPTERS))
    s.add_argument("root")
    s.add_argument("--lang", default="en")

    s = add("audit", cmd_audit, "periksa semua lang_*.db di folder game terhadap skema adapter", work=False)
    s.add_argument("adapter", choices=sorted(ADAPTERS))
    s.add_argument("root")
    s.add_argument("--lang", default="en")

    s = add("serve", cmd_serve, "jalankan antarmuka web lokal untuk menyunting")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--token", help="wajib jika --host bukan localhost; 'auto' membuat token acak")
    s.add_argument("--glossary", help="CSV glosarium untuk pengecekan di web (dan istilah wajib untuk Claude)")
    s.add_argument("--open", action="store_true", help="buka browser otomatis")
    s.add_argument("--provider", choices=["libre", "mymemory", "claude", "echo"], help="aktifkan tombol Saran mesin")
    s.add_argument("--model", default=DEFAULT_MODEL)
    s.add_argument("--url")
    s.add_argument("--key", "--api-key", dest="key")
    s.add_argument("--email")
    s.add_argument("--src", default="en")
    s.add_argument("--tgt", default="id")
    s.add_argument("--mt-budget", type=int, help="batas karakter terkirim per sesi server (default 200000 untuk claude, 0 = tanpa batas)")

    s = add("user-add", cmd_user_add, "buat akun (token pribadi) untuk penyunting")
    s.add_argument("name")
    add("user-list", cmd_user_list, "daftar akun")
    s = add("user-remove", cmd_user_remove, "hapus akun")
    s.add_argument("name")

    s = add("import", cmd_import, "impor teks asli dari database game ke workbench")
    s.add_argument("game_db")
    cols(s)
    s.add_argument("--speaker-col")
    s.add_argument("--name", help="nama dataset (default: nama tabel)")
    s.add_argument("--where", help="saring baris dengan kondisi SQL")

    s = add("import-translated", cmd_import_translated, "impor terjemahan yang sudah ada (.pak, .db, atau .json)")
    s.add_argument("file")
    s.add_argument("--name", required=True)
    cols(s)

    s = add("search", cmd_search, "cari entri")
    s.add_argument("query", nargs="?")
    s.add_argument("--in", dest="in_", choices=["id", "source", "target", "all"], default="all")
    s.add_argument("--name")
    s.add_argument("--prefix")
    s.add_argument("--status", choices=["untranslated", *STATUSES])
    s.add_argument("--limit", type=int, default=20)

    s = add("show", cmd_show, "tampilkan satu entri")
    s.add_argument("id")
    s = add("edit", cmd_edit, "sunting terjemahan (tanpa --text membuka editor)")
    s.add_argument("id")
    s.add_argument("--text")
    s.add_argument("--note")
    s.add_argument("--approve", action="store_true")
    s = add("approve", cmd_approve, "tandai entri sebagai disetujui")
    s.add_argument("ids", nargs="+")
    s = add("history", cmd_history, "riwayat versi satu entri")
    s.add_argument("id")
    s = add("revert", cmd_revert, "kembalikan ke versi lama")
    s.add_argument("id")
    s.add_argument("version", type=int)
    s = add("stats", cmd_stats, "ringkasan progres")
    s.add_argument("--by-prefix", type=int, default=0, metavar="N")

    s = add("translate", cmd_translate, "terjemahan mesin untuk entri yang masih kosong")
    s.add_argument("--name")
    s.add_argument("--ids", nargs="*", help="terjemahkan entri tertentu (menimpa, riwayat tetap tersimpan)")
    s.add_argument("--match", help="hanya teks asli yang memuat kata ini")
    s.add_argument("--prefix", help="hanya ID yang diawali ini, misalnya Quest_")
    s.add_argument("--limit", type=int, default=50, help="maksimum entri per jalan (0 = semua)")
    s.add_argument("--provider", default="libre", choices=["libre", "mymemory", "claude", "echo"])
    s.add_argument("--model", default=DEFAULT_MODEL, help="model Claude (claude-haiku-5-5 lebih murah)")
    s.add_argument("--glossary", help="CSV glosarium, dikirim ke Claude sebagai istilah wajib")
    s.add_argument("--src", default="en")
    s.add_argument("--tgt", default="id")
    s.add_argument("--batch", type=int, help="baris per permintaan (default tergantung penyedia)")
    s.add_argument("--delay", type=float, help="jeda antar permintaan, detik (default tergantung penyedia)")
    s.add_argument("--max-chars", type=int, default=0, help="batas karakter terkirim, pengaman biaya (Claude)")
    s.add_argument("--url", help="alamat LibreTranslate")
    s.add_argument("--key", "--api-key", dest="key", help="API key (atau env ANTHROPIC_API_KEY / LIBRETRANSLATE_KEY)")
    s.add_argument("--email", help="email untuk MyMemory (menaikkan batas harian)")
    s.add_argument("--dry-run", action="store_true", help="tampilkan hasil tanpa menyimpan")

    s = add("qa", cmd_qa, "periksa kualitas: tag, glosarium, konsistensi")
    s.add_argument("--name")
    s.add_argument("--glossary")
    s.add_argument("--max-ratio", type=float, default=1.8)
    s.add_argument("--limit", type=int, default=50)

    def export_opts(s):
        s.add_argument("--name")
        s.add_argument("--include", nargs="*", default=[], help="dataset lain yang digabung ke satu db")
        s.add_argument("--only-approved", action="store_true")
        s.add_argument("--skip-check", action="store_true")
        s.add_argument("--force", action="store_true")

    s = add("export-db", cmd_export_db, "tulis terjemahan ke SALINAN database game")
    s.add_argument("game_db")
    s.add_argument("out")
    export_opts(s)
    s = add("export-pak", cmd_export_pak, "tulis terjemahan ke salinan db lalu bungkus jadi .pak")
    s.add_argument("--base", required=True, help="database game asli")
    s.add_argument("--out")
    s.add_argument("--game-path")
    export_opts(s)
    s = add("unpack-pak", cmd_unpack_pak, "keluarkan database dari .pak (pak 1 berkas)", work=False)
    s.add_argument("pak")
    s.add_argument("--outdir", default="unpacked")

    s = add("export-csv", cmd_export_csv, "ekspor ke CSV untuk dikerjakan di Excel/Sheets")
    s.add_argument("--csv", default="work.csv")
    s.add_argument("--name")
    s = add("import-csv", cmd_import_csv, "terapkan terjemahan dari CSV")
    s.add_argument("--csv", default="work.csv")
    s = add("export-json", cmd_export_json, "ekspor {id: terjemahan}")
    s.add_argument("out")
    s.add_argument("--name")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a) or 0
    except BrokenPipeError:  # misalnya `gamelokal search ... | head`
        return 0
    except (GamelokalError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
