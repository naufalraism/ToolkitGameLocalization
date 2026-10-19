"""Penyedia LibreTranslate (gratis, bisa dijalankan sendiri)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .base import ProviderError


class LibreTranslate:
    name = "libretranslate"

    def __init__(self, url: str = "http://localhost:5000", api_key: str | None = None, timeout: int = 30, retries: int = 2):
        self.url, self.api_key, self.timeout, self.retries = url.rstrip("/"), api_key, timeout, retries

    def _post(self, payload: dict) -> dict:
        if self.api_key:
            payload = {**payload, "api_key": self.api_key}
        req = urllib.request.Request(
            self.url + "/translate", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last = e
                time.sleep(0.5 * (attempt + 1))
        raise ProviderError(f"LibreTranslate tidak bisa dihubungi di {self.url}: {last}")

    def translate(self, texts: list[str], source: str, target: str) -> list[str]:
        out = []
        for t in texts:
            if not t.strip():
                out.append(t)
                continue
            data = self._post({"q": t, "source": source, "target": target, "format": "text"})
            if "translatedText" not in data:
                raise ProviderError(f"Balasan tidak dikenal: {data}")
            out.append(data["translatedText"])
        return out
