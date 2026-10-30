import http.client
import json
import threading

import pytest

from gamelokal.core.errors import GamelokalError
from gamelokal.core.workbench import Workbench
from gamelokal.web.server import make_server

MAP = {"table": "T", "id_col": "Id", "text_col": "C", "game_path": "x/y.db"}


def start(tmp_path, token=None):
    path = tmp_path / "wb.db"
    with Workbench(path) as wb:
        wb.import_source("s", [("a_1", "Hello {0} <b>x</b>", "Rover"), ("b_1", "Bye", "")], MAP)
    srv = make_server(path, port=0, token=token)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def srv(tmp_path):
    s = start(tmp_path)
    yield s
    s.shutdown()


def call(srv, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body)
        h["Content-Type"] = "application/json"
    c.request(method, path, data, h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw


POST = {"X-Gamelokal": "1"}


def test_serves_page_and_stats(srv):
    code, html = call(srv, "GET", "/")
    assert code == 200 and b"gamelokal" in html
    code, s = call(srv, "GET", "/api/stats")
    assert code == 200 and s["datasets"] == ["s"] and s["total"] == 2 and s["untranslated"] == 2


def test_entries_search_paging_and_entry(srv):
    code, j = call(srv, "GET", "/api/entries?q=hello&in=source")
    assert code == 200 and j["total"] == 1 and j["rows"][0]["id"] == "s:a_1"
    code, j = call(srv, "GET", "/api/entries?limit=1&offset=1")
    assert [r["id"] for r in j["rows"]] == ["s:b_1"] and j["total"] == 2
    assert call(srv, "GET", "/api/entries?in=sql")[0] == 400
    code, e = call(srv, "GET", "/api/entry?id=s:a_1")
    assert e["speaker"] == "Rover" and e["status"] == "new" and e["history"] == []
    assert call(srv, "GET", "/api/entry?id=s:nope")[0] == 400


def test_save_reports_tag_errors_and_approve_and_revert(srv):
    code, e = call(srv, "POST", "/api/save", {"id": "s:a_1", "text": "Halo"}, POST)
    assert code == 200 and e["status"] == "edited" and {i["code"] for i in e["issues"]} >= {"placeholder"}
    good = "Halo {0} <b>x</b>"
    code, e = call(srv, "POST", "/api/save", {"id": "s:a_1", "text": good, "approve": True}, POST)
    assert e["status"] == "approved" and e["issues"] == [] and [v["text"] for v in e["history"]] == ["Halo", good]
    code, e = call(srv, "POST", "/api/revert", {"id": "s:a_1", "version": 1}, POST)
    assert e["target"] == "Halo" and e["status"] == "edited" and len(e["history"]) == 3
    assert call(srv, "POST", "/api/save", {"id": "s:b_1", "text": " ", "approve": True}, POST)[0] == 400
    assert call(srv, "GET", "/api/stats")[1]["by_status"]["edited"] == 1


def test_post_needs_custom_header_and_valid_json(srv):
    assert call(srv, "POST", "/api/save", {"id": "s:a_1", "text": "x"})[0] == 403
    assert call(srv, "POST", "/api/save", {"id": "s:a_1"}, POST)[0] == 400       # field text hilang


def test_rejects_foreign_host_header(srv):
    assert call(srv, "GET", "/api/stats", headers={"Host": "evil.example"})[0] == 403
    assert call(srv, "GET", "/", headers={"Host": "evil.example"})[0] == 403


def test_token_mode(tmp_path):
    s = start(tmp_path, token="rahasia")
    try:
        assert call(s, "GET", "/")[0] == 200                       # halaman tanpa data
        assert call(s, "GET", "/api/stats")[0] == 401
        assert call(s, "GET", "/api/stats", headers={"X-Token": "salah"})[0] == 401
        assert call(s, "GET", "/api/stats", headers={"X-Token": "rahasia"})[0] == 200
        assert call(s, "GET", "/api/stats?token=rahasia")[0] == 200
        assert call(s, "POST", "/api/save", {"id": "s:a_1", "text": "x"}, POST)[0] == 401
    finally:
        s.shutdown()


def test_non_loopback_requires_token_and_workbench_must_exist(tmp_path):
    start(tmp_path).shutdown()
    with pytest.raises(GamelokalError, match="token"):
        make_server(tmp_path / "wb.db", host="0.0.0.0")
    with pytest.raises(GamelokalError, match="tidak ditemukan"):
        make_server(tmp_path / "tidak-ada.db")


# ------------------------------------------------------------ konflik, akun, QA, saran mesin

class Upper:
    label, default_batch, default_delay = "fake", 1, 0

    def translate(self, texts, source, target):
        return [t.upper() for t in texts]


def start_with(tmp_path, **kw):
    path = tmp_path / "wb.db"
    with Workbench(path) as wb:
        wb.import_source("s", [("a_1", "Hello {0} <b>x</b>", "Rover"), ("b_1", "Bye", ""), ("c_1", "Bye", "")], MAP)
    srv = make_server(path, port=0, **kw)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, path


def test_conflict_detection_and_resolution(tmp_path):
    srv, _ = start_with(tmp_path)
    try:
        _, e = call(srv, "GET", "/api/entry?id=s:b_1")
        base = e["rev"]
        assert call(srv, "POST", "/api/save", {"id": "s:b_1", "text": "Dah A", "base": base}, POST)[0] == 200
        code, j = call(srv, "POST", "/api/save", {"id": "s:b_1", "text": "Dah B", "base": base}, POST)   # basi
        assert code == 409 and j["conflict"] and j["current"]["target"] == "Dah A"
        code, j2 = call(srv, "POST", "/api/save", {"id": "s:b_1", "text": "Dah B", "base": j["current"]["rev"]}, POST)
        assert code == 200 and j2["target"] == "Dah B"
        code, _ = call(srv, "POST", "/api/revert", {"id": "s:b_1", "version": 1, "base": base}, POST)
        assert code == 409
    finally:
        srv.shutdown()


def test_accounts_authenticate_and_attribute_edits(tmp_path):
    srv, path = start_with(tmp_path)
    with Workbench(path) as wb:
        t_ani, t_budi = wb.add_user("Ani"), wb.add_user("Budi")
    try:
        assert call(srv, "GET", "/api/stats")[0] == 401
        assert call(srv, "GET", "/api/stats", headers={"X-Token": "salah"})[0] == 401
        assert call(srv, "GET", "/api/stats", headers={"X-Token": t_ani})[1]["user"] == "Ani"
        call(srv, "POST", "/api/save", {"id": "s:b_1", "text": "Dari Ani"}, {**POST, "X-Token": t_ani})
        _, e = call(srv, "POST", "/api/save", {"id": "s:b_1", "text": "Dari Budi", "approve": True},
                    {**POST, "X-Token": t_budi})
        assert e["editor"] == "Budi" and [h["author"] for h in e["history"]] == ["Ani", "Budi"]
        with Workbench(path) as wb:
            wb.remove_user("Ani")
        assert call(srv, "GET", "/api/stats", headers={"X-Token": t_ani})[0] == 401
    finally:
        srv.shutdown()


def test_accounts_allow_network_binding_without_shared_token(tmp_path):
    path = tmp_path / "wb.db"
    with Workbench(path) as wb:
        wb.import_source("s", [("a", "x", "")], MAP)
        wb.add_user("Ani")
    make_server(path, host="127.0.0.1", port=0).server_close()
    srv = make_server(path, host="0.0.0.0", port=0)       # boleh, karena ada akun
    srv.server_close()


def test_qa_endpoint(tmp_path):
    srv, path = start_with(tmp_path)
    with Workbench(path) as wb:
        wb.set_target("s:a_1", "Halo", "edited")                  # tag hilang
        wb.set_target("s:b_1", "Dah", "edited")
        wb.set_target("s:c_1", "Pergi", "edited")                 # sumber sama, terjemahan beda
    try:
        _, q = call(srv, "GET", "/api/qa?name=s")
        assert q["checked"] == 3 and q["errors"] >= 1 and q["counts"]["tidak_konsisten"] == 1
        assert q["issues"][0]["severity"] == "error"
        _, only = call(srv, "GET", "/api/qa?code=tidak_konsisten")
        assert {i["code"] for i in only["issues"]} == {"tidak_konsisten"}
        _, st = call(srv, "GET", "/api/entries?q=Halo&in=target")
        assert st["rows"][0]["err"] is True
    finally:
        srv.shutdown()


def test_machine_suggestion_is_not_saved_and_respects_budget(tmp_path):
    srv, path = start_with(tmp_path, provider=Upper(), mt_budget=30)
    try:
        assert call(srv, "GET", "/api/stats")[1]["mt"] == "fake"
        code, j = call(srv, "POST", "/api/translate", {"id": "s:a_1"}, POST)
        assert code == 200 and j["text"] == "HELLO {0} <b>X</b>" and j["ok"] is True and j["label"] == "fake"
        assert call(srv, "GET", "/api/entry?id=s:a_1")[1]["target"] == ""            # tidak disimpan otomatis
        code, j = call(srv, "POST", "/api/translate", {"id": "s:a_1"}, POST)         # 18 + 18 > 30
        assert code == 400 and "mt-budget" in j["error"]
    finally:
        srv.shutdown()


def test_machine_suggestion_disabled_by_default(srv):
    assert call(srv, "GET", "/api/stats")[1]["mt"] is None
    code, j = call(srv, "POST", "/api/translate", {"id": "s:a_1"}, POST)
    assert code == 400 and "tidak diaktifkan" in j["error"]
