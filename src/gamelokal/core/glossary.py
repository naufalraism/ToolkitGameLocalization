"""Glosarium: daftar istilah yang harus diterjemahkan seragam."""
import csv
from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    source: str
    target: str
    note: str = ""


def load_glossary(path) -> list[Term]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [Term(r["source"].strip(), r["target"].strip(), (r.get("note") or "").strip())
                for r in csv.DictReader(f) if (r.get("source") or "").strip()]
