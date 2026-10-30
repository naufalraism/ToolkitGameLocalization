"""MyMemory (gratis dengan batas harian; email menaikkan batasnya)."""
from __future__ import annotations

import os
import urllib.parse

from ..core.text import split_sentences
from .base import ProviderError, RateLimited
from .http import http_json

URL = "https://api.mymemory.translated.net/get?"


class MyMemory:
    name = label = "mymemory"
    default_batch = 1
    default_delay = 1.0

    def __init__(self, email: str | None = None):
        self.email = email or os.environ.get("MYMEMORY_EMAIL")

    def _one(self, text: str, source: str, target: str) -> str:
        pieces = []
        for part in split_sentences(text):
            qs = {"q": part, "langpair": f"{source}|{target}"}
            if self.email:
                qs["de"] = self.email
            j = http_json(URL + urllib.parse.urlencode(qs))
            status = str(j.get("responseStatus"))
            if status == "429":
                raise RateLimited("batas harian MyMemory tercapai")
            if status != "200":
                raise ProviderError(j.get("responseDetails") or "MyMemory gagal")
            pieces.append(j["responseData"]["translatedText"])
        return " ".join(pieces)

    def translate(self, texts: list[str], source: str, target: str) -> list[str]:
        return [self._one(t, source, target) if t.strip() else t for t in texts]
