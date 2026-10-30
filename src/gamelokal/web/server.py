"""Server web lokal untuk menyunting terjemahan (pustaka standar saja).

Keamanan:
- Tanpa token dan tanpa akun, server hanya melayani localhost dan menolak header Host lain (melawan DNS rebinding).
- Untuk dipakai bersama lewat jaringan wajib memakai --token bersama atau akun per orang (perintah user-add).
- Jika ada akun, setiap orang masuk dengan token pribadinya, dan perubahannya tercatat atas namanya.
- Permintaan yang mengubah data harus membawa header X-Gamelokal agar halaman web lain tidak bisa memicunya
  diam-diam dari browser.
- Menyimpan memakai penanda versi (rev); jika entri diubah orang lain sejak dibuka, server menjawab 409.
"""
from __future__ import annotations

import hmac
import json
import threading
import traceback
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..core.errors import GamelokalError
from ..core.glossary import load_glossary
from ..core.workbench import Workbench, WorkbenchError
from ..qa.checks import check_consistency, check_entry
from ..translate import ProviderError, RateLimited, ServerDown, translate_safe

INDEX = Path(__file__).with_name("index.html")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
MAX_BODY = 1_000_000
IN_FIELDS = {"id", "source", "target", "all"}
QA_SHOWN = 1000


class Conflict(GamelokalError):
    def __init__(self, current: dict):
        super().__init__("entri ini diubah orang lain sejak kamu membukanya")
        self.current = current


class MachineTranslator:
    """Saran terjemahan satu entri. Hasil tidak pernah disimpan otomatis."""

    def __init__(self, provider, src: str, tgt: str, budget: int = 0):
        self.provider, self.src, self.tgt, self.budget = provider, src, tgt, budget
        self.used, self._lock = 0, threading.Lock()

    @property
    def label(self) -> str:
        return self.provider.label

    def suggest(self, source: str) -> tuple[str, bool, list[str]]:
        with self._lock:
            if self.budget and self.used + len(source) > self.budget:
                raise ProviderError(f"batas --mt-budget ({self.budget} karakter per sesi server) tercapai")
            self.used += len(source)
        ((text, restored),) = translate_safe(self.provider, [source], self.src, self.tgt)
        problems = (["hasil kosong"] if not text.strip() else
                    [i.message for i in check_entry("", source, text) if i.severity == "error"])
        return text, restored, problems


@dataclass
class Context:
    gl: list
    author: str = ""
    mt: MachineTranslator | None = None


def _hostname(h: str | None) -> str:
    h = (h or "").strip()
    return h[1:h.find("]")] if h.startswith("[") else h.split(":")[0]


def _first(q: dict, key: str, default=None):
    return (q.get(key) or [default])[0]


def _entry(wb: Workbench, eid: str | None, gl) -> dict:
    if not eid:
        raise WorkbenchError("parameter id wajib")
    r = wb.get(eid)
    issues = []
    if r["source"] and r["target"]:
        issues = [{"code": i.code, "severity": i.severity, "message": i.message}
                  for i in check_entry(eid, r["source"], r["target"], gl)]
    hist = [{"n": n, "ts": v["ts"], "text": v["text"], "note": v["note"], "author": v["author"]}
            for n, v in enumerate(wb.history(eid), 1)]
    return {"id": eid, "speaker": r["speaker"], "source": r["source"], "target": r["target"], "editor": r["editor"],
            "rev": r["updated"], "status": r["status"] if r["target"] else "new", "issues": issues, "history": hist}


def _check_rev(wb: Workbench, body: dict, ctx: Context) -> None:
    base = body.get("base")
    if base is not None and wb.get(body["id"])["updated"] != base:
        raise Conflict(_entry(wb, body["id"], ctx.gl))


def handle(wb: Workbench, ctx: Context, path: str, q: dict, body: dict | None):
    if path == "/api/stats":
        name = _first(q, "name") or None
        return {"datasets": list(wb.mappings()), "user": ctx.author, "mt": ctx.mt.label if ctx.mt else None,
                **wb.stats(dataset=name)}
    if path == "/api/entries":
        in_ = _first(q, "in", "all")
        if in_ not in IN_FIELDS:
            raise ValueError("nilai 'in' tidak dikenal")
        rows, total = wb.search(_first(q, "q") or None, in_, _first(q, "name") or None, _first(q, "status") or None,
                                _first(q, "prefix") or None, min(max(int(_first(q, "limit", "50")), 1), 200),
                                max(int(_first(q, "offset", "0")), 0))
        out = []
        for r in rows:
            bad = bool(r["source"] and r["target"]) and any(
                i.severity == "error" for i in check_entry(r["id"], r["source"], r["target"]))
            out.append({"id": r["id"], "speaker": r["speaker"], "source": r["source"], "target": r["target"],
                        "status": r["status"] if r["target"] else "new", "err": bad})
        return {"total": total, "rows": out}
    if path == "/api/entry":
        return _entry(wb, _first(q, "id"), ctx.gl)
    if path == "/api/qa":
        name, code = _first(q, "name") or None, _first(q, "code") or None
        rows = wb.entries(name)
        issues = []
        for r in rows:
            issues += check_entry(r["id"], r["source"], r["target"], ctx.gl)
        issues += check_consistency((r["id"], r["source"], r["target"]) for r in rows)
        errors = sum(1 for i in issues if i.severity == "error")
        shown = sorted((i for i in issues if not code or i.code == code), key=lambda i: (i.severity != "error", i.code, i.id))
        return {"checked": len(rows), "pending": wb.stats(dataset=name)["untranslated"], "errors": errors,
                "warnings": len(issues) - errors, "counts": dict(Counter(i.code for i in issues)),
                "issues": [{"id": i.id, "code": i.code, "severity": i.severity, "message": i.message}
                           for i in shown[:QA_SHOWN]]}
    if body is not None and path == "/api/save":
        text, approve = str(body["text"]), bool(body.get("approve"))
        if approve and not text.strip():
            raise WorkbenchError("tidak bisa menyetujui terjemahan kosong")
        _check_rev(wb, body, ctx)
        wb.set_target(body["id"], text, "approved" if approve else "edited", "Disunting (web)", ctx.author)
        return _entry(wb, body["id"], ctx.gl)
    if body is not None and path == "/api/revert":
        _check_rev(wb, body, ctx)
        wb.revert(body["id"], int(body["version"]), ctx.author)
        return _entry(wb, body["id"], ctx.gl)
    if body is not None and path == "/api/translate":
        if ctx.mt is None:
            raise WorkbenchError("penerjemah mesin tidak diaktifkan. Jalankan serve dengan --provider.")
        r = wb.get(body["id"])
        if not r["source"]:
            raise WorkbenchError("entri ini tidak punya teks asli untuk diterjemahkan")
        text, restored, problems = ctx.mt.suggest(r["source"])
        return {"text": text, "ok": restored and not problems, "problems": problems, "label": ctx.mt.label}
    return None


def make_server(workdb, host: str = "127.0.0.1", port: int = 8000, token: str | None = None,
                glossary: str | None = None, provider=None, src: str = "en", tgt: str = "id",
                mt_budget: int = 0) -> ThreadingHTTPServer:
    if not Path(workdb).is_file():
        raise WorkbenchError(f"workbench tidak ditemukan: {workdb}. Jalankan 'import' dulu.")
    with Workbench(workdb) as wb:
        has_users = wb.user_count() > 0
    if host not in LOOPBACK and not token and not has_users:
        raise GamelokalError("alamat selain localhost wajib memakai --token atau akun (perintah user-add) supaya "
                             "orang lain di jaringan tidak bisa mengubah terjemahanmu")
    gl = load_glossary(glossary) if glossary else []
    mt = MachineTranslator(provider, src, tgt, mt_budget) if provider else None

    class Handler(BaseHTTPRequestHandler):
        server_version = "gamelokal"

        def log_message(self, *a):
            pass

        def _send(self, code: int, data: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")

        def _dispatch(self, method: str) -> None:
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            try:
                with Workbench(workdb) as wb:
                    users = wb.user_count() > 0
                    secured = users or token is not None
                    if not secured and _hostname(self.headers.get("Host")) not in LOOPBACK:
                        return self._json(403, {"error": "Host tidak diizinkan"})
                    if method == "GET" and u.path in ("/", "/index.html"):
                        return self._send(200, INDEX.read_bytes(), "text/html")   # halaman tanpa data
                    author = ""
                    if secured:
                        supplied = self.headers.get("X-Token") or _first(q, "token", "")
                        if users:
                            author = wb.user_for_token(supplied) if supplied else None
                            if author is None:
                                return self._json(401, {"error": "Token salah atau tidak ada"})
                        elif not hmac.compare_digest(supplied.encode(), token.encode()):
                            return self._json(401, {"error": "Token salah atau tidak ada"})
                    body = None
                    if method == "POST":
                        if self.headers.get("X-Gamelokal") != "1":
                            return self._json(403, {"error": "header X-Gamelokal wajib"})
                        n = int(self.headers.get("Content-Length") or 0)
                        if n > MAX_BODY:
                            return self._json(413, {"error": "permintaan terlalu besar"})
                        try:
                            body = json.loads(self.rfile.read(n) or b"{}")
                        except ValueError:
                            return self._json(400, {"error": "JSON tidak valid"})
                    result = handle(wb, Context(gl, author, mt), u.path, q, body)
                    if result is None:
                        return self._json(404, {"error": "tidak ditemukan"})
                    self._json(200, result)
            except Conflict as e:
                self._json(409, {"error": str(e), "conflict": True, "current": e.current})
            except RateLimited as e:
                self._json(429, {"error": str(e)})
            except ServerDown as e:
                self._json(503, {"error": str(e)})
            except GamelokalError as e:
                self._json(400, {"error": str(e)})
            except (KeyError, ValueError, TypeError) as e:
                self._json(400, {"error": f"permintaan tidak valid: {e}"})
            except Exception:
                traceback.print_exc()
                self._json(500, {"error": "kesalahan di server, lihat terminal"})

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

    return ThreadingHTTPServer((host, port), Handler)
