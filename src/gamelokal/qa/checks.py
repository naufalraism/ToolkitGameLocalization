"""Pengecekan kualitas terjemahan."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..core.glossary import Term
from ..core.text import placeholders


@dataclass(frozen=True)
class Issue:
    id: str
    code: str
    severity: str  # "error" atau "warning"
    message: str


def check_entry(id_: str, source: str, target: str, glossary: Sequence[Term] = (), max_ratio: float = 1.8) -> list[Issue]:
    if not target.strip():
        return []  # belum diterjemahkan, bukan kesalahan
    out: list[Issue] = []
    a, b = Counter(placeholders(source)), Counter(placeholders(target))
    if a != b:
        parts = []
        if a - b:
            parts.append("hilang: " + " ".join((a - b).elements()))
        if b - a:
            parts.append("berlebih: " + " ".join((b - a).elements()))
        out.append(Issue(id_, "placeholder", "error", "; ".join(parts)))
    s = source.strip()
    if target.strip() == s and len(s) > 3 and any(c.isalpha() for c in s):
        out.append(Issue(id_, "sama_dengan_sumber", "warning", "terjemahan identik dengan sumber"))
    for t in glossary:
        if re.search(rf"(?<!\w){re.escape(t.source)}(?!\w)", source, re.I) and t.target.lower() not in target.lower():
            out.append(Issue(id_, "glosarium", "warning", f"istilah '{t.source}' seharusnya '{t.target}'"))
    if len(target) > max_ratio * len(source) and len(target) - len(source) >= 20:
        out.append(Issue(id_, "panjang", "warning", f"terjemahan {len(target)} karakter, sumber {len(source)}"))
    return out


def check_consistency(rows: Iterable[tuple[str, str, str]]) -> list[Issue]:
    """Sumber yang sama tetapi diterjemahkan berbeda-beda."""
    groups: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for id_, source, target in rows:
        if target.strip():
            groups[source.strip()].setdefault(target.strip(), []).append(id_)
    out: list[Issue] = []
    for variants in groups.values():
        if len(variants) < 2:
            continue
        major = max(variants.values(), key=len)
        for ids in variants.values():
            if ids is major:
                continue
            for i in ids:
                out.append(Issue(i, "tidak_konsisten", "warning", f"sumber yang sama diterjemahkan {len(variants)} cara"))
    return out
