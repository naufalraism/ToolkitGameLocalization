"""Claude lewat Anthropic Messages API (berbayar menurut pemakaian; butuh API key).

Biaya dan batas laju: lihat dokumentasi resmi di https://docs.claude.com
"""
from __future__ import annotations

import json
import os
import re
from typing import Sequence

from ..core.glossary import Term
from .base import ProviderError
from .http import http_json

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"   # claude-haiku-5-5 lebih murah

LANG_NAMES = {"id": "bahasa Indonesia", "en": "bahasa Inggris"}
SYSTEM = (
    "Kamu penerjemah teks game (cerita, dialog, UI) dari {src} ke {tgt} yang natural. "
    "Pesan pengguna adalah objek JSON {{id: teks}}. Balas HANYA dengan objek JSON berkunci sama berisi "
    "terjemahannya, tanpa penjelasan dan tanpa pagar kode. Aturan: (1) token seperti \u27e60\u27e7, \u27e61\u27e7 adalah "
    "pengganti tag/variabel; salin setiap token persis satu kali di posisi yang wajar. (2) Nada dialog "
    "mengikuti karakter dan konteks; jangan terlalu kaku. (3) Nama diri, nama skill/item/tempat yang "
    "lazim dibiarkan dalam bahasa aslinya kecuali ada di glosarium. (4) Jangan menambah atau menghapus makna."
)


class Claude:
    name = "claude"
    default_batch = 15
    default_delay = 1.0

    def __init__(self, key: str | None = None, model: str = DEFAULT_MODEL, glossary: Sequence[Term] = (),
                 max_tokens: int = 8000, timeout: float = 180):
        self.key = key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise ProviderError("provider claude butuh API key: set env ANTHROPIC_API_KEY (atau --key)")
        self.model, self.glossary, self.max_tokens, self.timeout = model, list(glossary), max_tokens, timeout
        self.label = f"claude/{model}"
        self.usage = [0, 0]  # token masuk, keluar

    def _system(self, source: str, target: str) -> str:
        s = SYSTEM.format(src=LANG_NAMES.get(source, f"bahasa berkode '{source}'"),
                          tgt=LANG_NAMES.get(target, f"bahasa berkode '{target}'"))
        if self.glossary:
            s += "\nGlosarium wajib (asli -> terjemahan):\n" + "\n".join(f"{t.source} -> {t.target}" for t in self.glossary)
        return s

    def translate(self, texts: list[str], source: str, target: str) -> list[str]:
        payload = {"model": self.model, "max_tokens": self.max_tokens, "system": self._system(source, target),
                   "messages": [{"role": "user",
                                 "content": json.dumps({str(i): t for i, t in enumerate(texts)}, ensure_ascii=False)}]}
        j = http_json(API_URL, payload, self.timeout,
                      headers={"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        u = j.get("usage") or {}
        self.usage[0] += u.get("input_tokens", 0)
        self.usage[1] += u.get("output_tokens", 0)
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            out = json.loads(text)
        except ValueError:
            raise ProviderError("balasan Claude bukan JSON yang valid") from None
        if not isinstance(out, dict):
            raise ProviderError("balasan Claude bukan objek JSON")
        return [str(out.get(str(i), "")) for i in range(len(texts))]  # kosong = tidak ada di balasan
