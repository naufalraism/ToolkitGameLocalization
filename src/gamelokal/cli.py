"""Antarmuka baris perintah."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .adapters import ADAPTERS
from .core.csvio import read_rows, write_rows
from .core.glossary import load_glossary
from .core.project import Project
from .core.store import guess_columns, inspect_db, load_entries, write_patch
from .qa.checks import check_consistency, check_entry
from .translate import ProviderError, get_provider, translate_safe


def cmd_inspect(a) -> int:
    for t in inspect_db(a.db):
        print(f"{t.name}  ({t.rows} baris)")
        for c in t.columns:
            print(f"    {c.name} {c.type}{' PK' if c.pk else ''}")
    g = guess_columns(a.db)
    print(f"\nTebakan: tabel={g.table} id={g.id_col} teks={g.text_col}" if g else "\nKolom teks tidak bisa ditebak.")
    return 0


def cmd_init(a) -> int:
    g = guess_columns(a.db)
    table = a.table or (g.table if g else None)
    id_col = a.id_col or (g.id_col if g else None)
    text_col = a.text_col or (g.text_col if g else None)
    if not (table and id_col and text_col):
        print("Kolom tidak bisa ditebak. Jalankan `inspect`, lalu isi --table --id-col --text-col.", file=sys.stderr)
        return 2
    out = Path(a.out)
    try:
        db = os.path.relpath(a.db, out.resolve().parent)
    except ValueError:
        db = str(Path(a.db).resolve())
    Project(db=db, table=table, id_col=id_col, text_col=text_col,
            source_lang=a.source, target_lang=a.target, glossary=a.glossary).save(out)
    print(f"Proyek ditulis ke {out} (tabel={table}, id={id_col}, teks={text_col})")
    return 0


def cmd_find(a) -> int:
    dbs = ADAPTERS[a.adapter].find_dbs(a.root, a.lang)
    for p in dbs:
        print(p)
    print(f"{len(dbs)} berkas ditemukan", file=sys.stderr)
    return 0


def cmd_export(a) -> int:
    p = Project.load(a.project)
    out = Path(a.csv)
    old = {r["id"]: r for r in read_rows(out)} if out.exists() else {}
    rows, changed = [], 0
    for id_, text in load_entries(p.path(p.db), p.table, p.id_col, p.text_col):
        prev = old.get(id_, {})
        note = prev.get("note", "")
        if prev.get("target") and prev.get("source") != text:
            note, changed = "sumber berubah", changed + 1
        rows.append({"id": id_, "source": text, "target": prev.get("target", ""), "note": note})
    write_rows(out, rows)
    print(f"{len(rows)} baris ditulis ke {out}" + (f", {changed} sumber berubah sejak ekspor sebelumnya" if changed else ""))
    return 0


def cmd_translate(a) -> int:
    p = Project.load(a.project)
    rows = read_rows(Path(a.csv))
    prov = get_provider(a.provider, a.url, a.api_key)
    todo = [r for r in rows if not r["target"].strip() and r["source"].strip()]
    if a.limit:
        todo = todo[: a.limit]
    done = 0
    try:
        for i in range(0, len(todo), a.batch):
            chunk = todo[i: i + a.batch]
            results = translate_safe(prov, [r["source"] for r in chunk], p.source_lang, p.target_lang)
            for r, (text, ok) in zip(chunk, results):
                r["target"] = text
                if not ok:
                    r["note"] = "cek placeholder"
            write_rows(Path(a.csv), rows)  # simpan tiap batch agar bisa dilanjutkan
            done += len(chunk)
            print(f"{done}/{len(todo)}", end="\r")
    except ProviderError as e:
        print(f"\nBerhenti: {e}\n{done} baris sudah tersimpan, jalankan lagi untuk melanjutkan.", file=sys.stderr)
        return 3
    print(f"\n{done} baris diterjemahkan dengan {prov.name}")
    return 0


def cmd_qa(a) -> int:
    p = Project.load(a.project)
    rows = read_rows(Path(a.csv))
    gl = []
    if p.glossary and p.path(p.glossary).exists():
        gl = load_glossary(p.path(p.glossary))
    issues = []
    for r in rows:
        issues += check_entry(r["id"], r["source"], r["target"], gl, a.max_ratio)
    issues += check_consistency((r["id"], r["source"], r["target"]) for r in rows)
    for i in issues:
        print(f"[{i.severity}] #{i.id} {i.code}: {i.message}")
    errors = sum(1 for i in issues if i.severity == "error")
    pending = sum(1 for r in rows if not r["target"].strip())
    print(f"\n{len(rows)} baris, {pending} belum diterjemahkan, {errors} error, {len(issues) - errors} peringatan")
    return 1 if errors else 0


def cmd_build(a) -> int:
    p = Project.load(a.project)
    rows = read_rows(Path(a.csv))
    tr = {r["id"]: r["target"] for r in rows if r["target"].strip()}
    n = write_patch(p.path(p.db), a.out, p.table, p.id_col, p.text_col, tr)
    print(f"{n} baris diterjemahkan ditulis ke {a.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="gamelokal", description="Toolkit lokalisasi game.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("inspect", help="lihat isi berkas .db dan tebak kolom teks")
    s.add_argument("db")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("init", help="buat berkas proyek dari sebuah .db")
    s.add_argument("db")
    s.add_argument("--out", default="gamelokal.json")
    s.add_argument("--table")
    s.add_argument("--id-col")
    s.add_argument("--text-col")
    s.add_argument("--source", default="en")
    s.add_argument("--target", default="id")
    s.add_argument("--glossary")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("find", help="cari berkas .db game lewat adapter")
    s.add_argument("adapter", choices=sorted(ADAPTERS))
    s.add_argument("root")
    s.add_argument("--lang", default="en")
    s.set_defaults(fn=cmd_find)

    for name, fn, h in (("export", cmd_export, "ekspor teks ke CSV (hasil kerja lama dipertahankan)"),
                        ("translate", cmd_translate, "terjemahkan baris kosong dengan mesin"),
                        ("qa", cmd_qa, "periksa kualitas terjemahan"),
                        ("build", cmd_build, "tulis .db hasil terjemahan")):
        s = sub.add_parser(name, help=h)
        s.add_argument("project")
        s.add_argument("--csv", default="work.csv")
        s.set_defaults(fn=fn)
        if name == "translate":
            s.add_argument("--provider", default="libre", choices=["libre", "echo"])
            s.add_argument("--url")
            s.add_argument("--api-key")
            s.add_argument("--batch", type=int, default=20)
            s.add_argument("--limit", type=int, default=0)
        if name == "qa":
            s.add_argument("--max-ratio", type=float, default=1.8)
        if name == "build":
            s.add_argument("--out", required=True)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.fn(a)
