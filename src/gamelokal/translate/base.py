"""Antarmuka penerjemah mesin dan perlindungan tag."""
from __future__ import annotations

import re
from typing import Protocol

from ..core.text import PLACEHOLDER


class ProviderError(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    def translate(self, texts: list[str], source: str, target: str) -> list[str]: ...


def mask(text: str) -> tuple[str, list[str]]:
    """Mengganti tag/placeholder dengan penanda yang jarang diubah mesin penerjemah."""
    tokens: list[str] = []

    def rep(m: re.Match) -> str:
        tokens.append(m.group(0))
        return f"\u27e6{len(tokens) - 1}\u27e7"

    return PLACEHOLDER.sub(rep, text), tokens


def unmask(text: str, tokens: list[str]) -> tuple[str, bool]:
    """Mengembalikan tag asli. Hasil kedua False jika ada penanda yang hilang."""
    seen: set[int] = set()

    def rep(m: re.Match) -> str:
        i = int(m.group(1))
        if i < len(tokens):
            seen.add(i)
            return tokens[i]
        return m.group(0)

    out = re.sub(r"\u27e6\s*(\d+)\s*\u27e7", rep, text)
    return out, len(seen) == len(tokens)


def translate_safe(provider: Provider, texts: list[str], source: str, target: str) -> list[tuple[str, bool]]:
    masked = [mask(t) for t in texts]
    results = provider.translate([m[0] for m in masked], source, target)
    return [unmask(r, m[1]) for r, m in zip(results, masked)]
