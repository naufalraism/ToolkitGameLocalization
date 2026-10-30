import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gamelokal.core.glossary import Term
from gamelokal.core.text import split_sentences
from gamelokal.translate import (Claude, LibreTranslate, MyMemory, ProviderError, RateLimited, ServerDown,
                                 get_provider)
from gamelokal.translate import claude as claude_mod
from gamelokal.translate import mymemory as mm_mod
from gamelokal.translate.base import ConnectionFailed
from gamelokal.translate.http import http_json


def test_split_sentences_respects_limit():
    text = " ".join(f"Kalimat nomor {i} ini cukup panjang." for i in range(30))
    parts = split_sentences(text, 100)
    assert len(parts) > 1 and all(len(p) <= 100 for p in parts)
    assert split_sentences("pendek") == ["pendek"]


def test_mymemory_chunks_email_and_rate_limit(monkeypatch):
    seen = []

    def fake(url, *a, **k):
        seen.append(url)
        return {"responseStatus": 200, "responseData": {"translatedText": "X"}}

    monkeypatch.setattr(mm_mod, "http_json", fake)
    out = MyMemory("a@b.c").translate([" ".join(["Kalimat satu dua tiga empat lima."] * 30), ""], "en", "id")
    assert out[1] == "" and out[0].count("X") == len(seen) > 1 and "de=a%40b.c" in seen[0]

    monkeypatch.setattr(mm_mod, "http_json", lambda *a, **k: {"responseStatus": "429"})
    with pytest.raises(RateLimited):
        MyMemory().translate(["Hello"], "en", "id")
    monkeypatch.setattr(mm_mod, "http_json", lambda *a, **k: {"responseStatus": "403", "responseDetails": "salah"})
    with pytest.raises(ProviderError, match="salah"):
        MyMemory().translate(["Hello"], "en", "id")


def test_claude_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        Claude()


def test_claude_request_and_parsing(monkeypatch):
    captured = {}

    def fake(url, payload, timeout, headers):
        captured.update(url=url, payload=payload, headers=headers)
        body = json.dumps({"0": "Halo", "1": "Dunia"})
        return {"content": [{"type": "text", "text": "```json\n" + body + "\n```"}],
                "usage": {"input_tokens": 10, "output_tokens": 4}}

    monkeypatch.setattr(claude_mod, "http_json", fake)
    c = Claude("kunci-uji", "claude-haiku-5-5", [Term("Echo", "Echo")])
    assert c.translate(["Hello", "World", "Hilang"], "en", "id")[:2] == ["Halo", "Dunia"]
    assert captured["headers"]["x-api-key"] == "kunci-uji" and captured["payload"]["model"] == "claude-haiku-5-5"
    assert "Echo -> Echo" in captured["payload"]["system"]
    assert json.loads(captured["payload"]["messages"][0]["content"]) == {"0": "Hello", "1": "World", "2": "Hilang"}
    assert c.usage == [10, 4] and c.label == "claude/claude-haiku-5-5"
    assert c.translate(["a", "b", "c"], "en", "id")[2] == ""        # id yang tidak dibalas menjadi kosong


def test_claude_invalid_json(monkeypatch):
    monkeypatch.setattr(claude_mod, "http_json", lambda *a, **k: {"content": [{"type": "text", "text": "bukan json"}]})
    with pytest.raises(ProviderError, match="JSON"):
        Claude("k").translate(["x"], "en", "id")


def test_libre_server_down_and_language_code(monkeypatch):
    import gamelokal.translate.libre as lib

    def down(*a, **k):
        raise ConnectionFailed("koneksi gagal: x")

    monkeypatch.setattr(lib, "http_json", down)
    with pytest.raises(ServerDown, match="LibreTranslate"):
        LibreTranslate("http://x").translate(["hi"], "en", "id")
    sent = {}
    monkeypatch.setattr(lib, "http_json", lambda u, p, t: sent.update(p) or {"translatedText": "ok"})
    LibreTranslate("http://x").translate(["hi"], "zh-CN", "id")
    assert sent["source"] == "zh"


def test_get_provider_unknown():
    with pytest.raises(ProviderError):
        get_provider("tidak-ada")


class _H(BaseHTTPRequestHandler):
    def do_POST(self):
        code = 429 if self.path == "/limit" else 200
        body = b'{"ok": true}' if code == 200 else b'{"error": {"message": "pelan-pelan"}}'
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_http_json_against_local_server():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        assert http_json(base + "/ok", {"a": 1}) == {"ok": True}
        with pytest.raises(RateLimited):
            http_json(base + "/limit", {"a": 1})
    finally:
        srv.shutdown()
    with pytest.raises(ConnectionFailed):
        http_json(base + "/ok", {"a": 1}, timeout=1)       # server sudah mati
