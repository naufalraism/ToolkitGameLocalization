"""Pertukaran data dengan penerjemah lewat CSV (bisa dibuka di Excel/Sheets)."""
import csv
from pathlib import Path

FIELDS = ["id", "source", "target", "note"]


def read_rows(path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k: (r.get(k) or "") for k in FIELDS} for r in csv.DictReader(f)]


def write_rows(path, rows: list[dict]) -> None:
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in FIELDS} for r in rows)
    tmp.replace(path)
