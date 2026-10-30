"""Antarmuka penerjemah mesin, galat, dan perlindungan tag."""
from __future__ import annotations

import re
from typing import Protocol

from ..core.errors import GamelokalError
from ..core.text import MASKABLE


class ProviderError(GamelokalError):
    """Satu permintaan gagal. Permintaan berikutnya mungkin masih berhasil."""


class RateLimited(ProviderError):
    """Batas permintaan atau server sibuk. Sebaiknya berhenti dan lanjut nanti."""


class ServerDown(ProviderError):
    """Server penerjemah tidak bisa dihubungi."""


class ConnectionFailed(ProviderError):
    """Koneksi jaringan gagal."""


class Provider(Protocol):
    name: str
    label: str
    default_batch: int
    default_delay: float

    def translate(self, texts: list[str], source: str, target: str) -> list[str]: ...


def mask(text: str) -> tuple[str, list[str]]:
    """Mengganti tag/placeholder dengan penanda yang jarang diubah mesin penerjemah."""
    tokens: list[str] = []

    def rep(m: re.Match) -> str:
        tokens.append(m.group(0))
        return f"\u27e6{len(tokens) - 1}\u27e7"

    return MASKABLE.sub(rep, text), tokens


def unmask(text: str, tokens: list[str]) -> tuple[str, bool]:
    """Mengembalikan tag asli. Hasil kedua False jika ada penanda hilang, ganda, atau asing."""
    found = [int(n) for n in re.findall(r"\u27e6\s*(\d+)\s*\u27e7", text)]
    ok = sorted(found) == list(range(len(tokens)))

    def rep(m: re.Match) -> str:
        i = int(m.group(1))
        return tokens[i] if i < len(tokens) else m.group(0)

    return re.sub(r"\u27e6\s*(\d+)\s*\u27e7", rep, text), ok


def translate_safe(provider: Provider, texts: list[str], source: str, target: str) -> list[tuple[str, bool]]:
    """Menerjemahkan dengan tag dilindungi. Teks yang hanya berisi tag tidak dikirim ke mesin."""
    masked = [mask(t) for t in texts]
    need = [i for i, (m, _) in enumerate(masked) if re.sub(r"\u27e6\d+\u27e7", "", m).strip()]
    results = provider.translate([masked[i][0] for i in need], source, target) if need else []
    out: list[tuple[str, bool]] = [(t, True) for t in texts]
    for i, r in zip(need, results):
        out[i] = unmask(r, masked[i][1])
    return out
