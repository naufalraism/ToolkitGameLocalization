"""Permintaan HTTP JSON sederhana tanpa dependensi."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import ConnectionFailed, ProviderError, RateLimited


def http_json(url: str, payload: dict | None = None, timeout: float = 60, headers: dict | None = None):
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (429, 529):
            raise RateLimited(f"HTTP {e.code} (batas permintaan / server sibuk)") from None
        detail = ""
        try:
            detail = " - " + json.load(e).get("error", {}).get("message", "")
        except Exception:
            pass
        raise ProviderError(f"HTTP {e.code}{detail}") from None
    except urllib.error.URLError as e:
        raise ConnectionFailed(f"koneksi gagal: {e.reason}") from None
    except OSError as e:  # termasuk TimeoutError
        raise ConnectionFailed(f"koneksi gagal: {e}") from None
    except ValueError:
        raise ProviderError("balasan server bukan JSON yang valid") from None
