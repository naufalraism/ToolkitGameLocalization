"""LibreTranslate (gratis, bisa dijalankan sendiri)."""
from __future__ import annotations

import os

from .base import ConnectionFailed, ProviderError, ServerDown
from .http import http_json


class LibreTranslate:
    name = label = "libre"
    default_batch = 1
    default_delay = 0.0

    def __init__(self, url: str | None = None, key: str | None = None, timeout: float = 60):
        self.url = (url or os.environ.get("LIBRETRANSLATE_URL") or "http://localhost:5000").rstrip("/")
        self.key = key or os.environ.get("LIBRETRANSLATE_KEY")
        self.timeout = timeout

    def _post(self, payload: dict) -> dict:
        if self.key:
            payload = {**payload, "api_key": self.key}
        try:
            return http_json(self.url + "/translate", payload, self.timeout)
        except ConnectionFailed:
            raise ServerDown(f"tidak bisa menghubungi LibreTranslate di {self.url}. Pastikan server LibreTranslate "
                             "sedang berjalan, atau tentukan alamatnya dengan --url.") from None

    def translate(self, texts: list[str], source: str, target: str) -> list[str]:
        code = lambda c: "zh" if c == "zh-CN" else c
        out = []
        for t in texts:
            if not t.strip():
                out.append(t)
                continue
            data = self._post({"q": t, "source": code(source), "target": code(target), "format": "text"})
            if "translatedText" not in data:
                raise ProviderError(f"balasan tidak dikenal: {data}")
            out.append(data["translatedText"])
        return out
