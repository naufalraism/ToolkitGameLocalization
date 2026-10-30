import sqlite3

from gamelokal.cli import main
from gamelokal.core.csvio import read_rows, write_rows

GAME_PATH = "Client/Content/Aki/ConfigDB/en/lang_multi_text.db"


def run(*args):
    return main([str(x) for x in args])


def content(path, key):
    return sqlite3.connect(path).execute("select Content from MultiText where Id=?", (key,)).fetchone()[0]


def test_full_flow(game_db, tmp_path, capsys):
    wb, out, pak = tmp_path / "wb.db", tmp_path / "out.db", tmp_path / "x.pak"
    assert run("import", game_db, "--workdb", wb, "--adapter", "wuthering-waves", "--name", "story") == 0
    capsys.readouterr()
    run("stats", "--workdb", wb)
    assert "Total        : 5" in capsys.readouterr().out

    assert run("translate", "--workdb", wb, "--provider", "echo") == 0      # echo = tanpa jaringan
    broken = "Halo, selamat datang"
    assert run("edit", "story:Intro_001", "--workdb", wb, "--text", broken) == 0
    assert run("qa", "--workdb", wb) == 1                                    # tag hilang = error
    assert run("export-db", game_db, out, "--workdb", wb) == 1               # gerbang ekspor menolak
    assert not out.exists()

    good = "Halo {0}, selamat datang di <color=#fff>Wuthering</color>"
    assert run("edit", "story:Intro_001", "--workdb", wb, "--text", good, "--approve") == 0
    assert run("qa", "--workdb", wb) == 0
    assert run("export-db", game_db, out, "--workdb", wb) == 0
    assert content(out, "Intro_001") == good and content(game_db, "Intro_001").startswith("Hello")

    assert run("export-pak", "--workdb", wb, "--base", game_db, "--out", pak) == 0
    assert run("unpack-pak", pak, "--outdir", tmp_path / "u") == 0
    assert content(tmp_path / "u" / GAME_PATH, "Intro_001") == good

    wb2 = tmp_path / "wb2.db"
    assert run("import-translated", pak, "--workdb", wb2, "--adapter", "wuthering-waves", "--name", "story") == 0
    capsys.readouterr()
    run("show", "story:Intro_001", "--workdb", wb2)
    assert good in capsys.readouterr().out


def test_history_and_revert_via_cli(game_db, tmp_path, capsys):
    wb = tmp_path / "wb.db"
    run("import", game_db, "--workdb", wb, "--adapter", "wuthering-waves", "--name", "s")
    run("edit", "s:Intro_002", "--workdb", wb, "--text", "Satu")
    run("edit", "s:Intro_002", "--workdb", wb, "--text", "Dua")
    capsys.readouterr()
    assert run("revert", "s:Intro_002", 1, "--workdb", wb) == 0
    run("show", "s:Intro_002", "--workdb", wb)
    assert "Satu" in capsys.readouterr().out


def test_csv_roundtrip(game_db, tmp_path):
    wb, csv_path = tmp_path / "wb.db", tmp_path / "w.csv"
    run("import", game_db, "--workdb", wb, "--adapter", "wuthering-waves", "--name", "s")
    run("export-csv", "--workdb", wb, "--csv", csv_path)
    rows = read_rows(csv_path)
    assert len(rows) == 5 and rows[0]["status"] == "new"
    rows[1]["target"] = "Rover ID"
    write_rows(csv_path, rows)
    assert run("import-csv", "--workdb", wb, "--csv", csv_path) == 0
    out = tmp_path / "o.db"
    run("export-db", game_db, out, "--workdb", wb)
    assert content(out, "Intro_002") == "Rover ID"


def test_errors_are_friendly(tmp_path, capsys):
    assert run("show", "x:1", "--workdb", tmp_path / "wb.db") == 1
    assert "tidak ada" in capsys.readouterr().err
    assert run("inspect", tmp_path / "nope.db") == 1


def test_export_refuses_overwriting_source(game_db, tmp_path):
    wb = tmp_path / "wb.db"
    run("import", game_db, "--workdb", wb, "--adapter", "wuthering-waves", "--name", "s")
    assert run("export-db", game_db, game_db, "--workdb", wb) == 1


def test_missing_files_are_friendly(tmp_path, capsys):
    assert run("unpack-pak", tmp_path / "tidak-ada.pak") == 1
    assert "Error:" in capsys.readouterr().err


# ---------------------------------------------------------------- translate

import pytest  # noqa: E402

from gamelokal import cli  # noqa: E402
from gamelokal.core.workbench import Workbench  # noqa: E402
from gamelokal.translate import RateLimited  # noqa: E402


class Fake:
    label, default_batch, default_delay = "fake", 2, 0

    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def translate(self, texts, source, target):
        self.calls += 1
        return self.fn(self.calls, texts)


@pytest.fixture
def imported(game_db, tmp_path):
    wb = tmp_path / "wb.db"
    run("import", game_db, "--workdb", wb, "--adapter", "wuthering-waves", "--name", "s")
    return wb


def count_translated(wb):
    with Workbench(wb) as w:
        return w.con.execute("select count(*) from entries where target != '' and status = 'mt'").fetchone()[0]


def test_translate_saves_per_batch_and_restores_tags(imported, monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_provider", lambda *a, **k: Fake(lambda n, texts: ["ID:" + t for t in texts]))
    assert run("translate", "--workdb", imported) == 0
    assert count_translated(imported) == 5
    with Workbench(imported) as w:
        assert w.get("s:Intro_001")["target"] == "ID:Hello {0}, welcome to <color=#fff>Wuthering</color>"
    assert "5 berhasil, 0 gagal" in capsys.readouterr().out


def test_translate_rejects_machine_that_breaks_tags(imported, monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_provider", lambda *a, **k: Fake(lambda n, texts: ["bebas" for _ in texts]))
    run("translate", "--workdb", imported)
    out = capsys.readouterr().out
    assert count_translated(imported) == 3 and "2 gagal" in out      # Intro_001 dan Quest_002 punya tag


def test_translate_stops_on_rate_limit_but_keeps_earlier_batches(imported, monkeypatch, capsys):
    def fn(n, texts):
        if n == 2:
            raise RateLimited("HTTP 429")
        return ["ID:" + t for t in texts]

    monkeypatch.setattr(cli, "get_provider", lambda *a, **k: Fake(fn))
    assert run("translate", "--workdb", imported) == 3
    assert count_translated(imported) == 2 and "berhenti" in capsys.readouterr().out


def test_translate_max_chars_and_dry_run(imported, monkeypatch, capsys):
    fake = Fake(lambda n, texts: ["ID:" + t for t in texts])
    monkeypatch.setattr(cli, "get_provider", lambda *a, **k: fake)
    run("translate", "--workdb", imported, "--max-chars", "10")
    assert fake.calls == 0 and "--max-chars" in capsys.readouterr().out
    run("translate", "--workdb", imported, "--dry-run")
    assert count_translated(imported) == 0
    run("translate", "--workdb", imported, "--limit", "2", "--prefix", "Quest_")
    assert count_translated(imported) == 2


def test_translate_ids_overwrites_and_keeps_history(imported, monkeypatch):
    monkeypatch.setattr(cli, "get_provider", lambda *a, **k: Fake(lambda n, texts: ["BARU" for _ in texts]))
    run("edit", "s:Intro_002", "--workdb", imported, "--text", "Lama")
    run("translate", "--workdb", imported, "--ids", "s:Intro_002")
    with Workbench(imported) as w:
        assert w.get("s:Intro_002")["target"] == "BARU"
        assert [v["text"] for v in w.history("s:Intro_002")] == ["Lama", "BARU"]


def test_audit(game_db, tmp_path, capsys):
    import sqlite3
    root = game_db.parent.parent                                   # tmp/game, berisi folder en
    other = game_db.parent / "lang_lain.db"
    con = sqlite3.connect(other)
    con.execute("create table Strings (Key TEXT PRIMARY KEY, Value TEXT)")
    con.execute("insert into Strings values ('k', 'teks yang cukup panjang')")
    con.commit()
    con.close()
    (game_db.parent / "lang_rusak.db").write_bytes(b"bukan sqlite" * 50)
    assert run("audit", "wuthering-waves", root) == 1
    out = capsys.readouterr().out
    assert "cocok   lang_multi_text.db" in out and "beda    lang_lain.db" in out and "galat   lang_rusak.db" in out
    assert "Strings.Value" in out
    assert run("audit", "wuthering-waves", tmp_path / "kosong") == 1


def test_user_commands_and_author_flag(imported, capsys):
    assert run("user-add", "Ani", "--workdb", imported) == 0
    token = [ln.strip() for ln in capsys.readouterr().out.splitlines() if ln.startswith("    ")][0]
    assert len(token) >= 20
    assert run("user-add", "Ani", "--workdb", imported) == 1                       # duplikat
    run("edit", "s:Intro_002", "--workdb", imported, "--text", "Rover ID", "--as", "Ani")
    with Workbench(imported) as w:
        assert w.get("s:Intro_002")["editor"] == "Ani" and w.user_for_token(token) == "Ani"
    run("user-list", "--workdb", imported)
    assert "Ani" in capsys.readouterr().out
    assert run("user-remove", "Ani", "--workdb", imported) == 0
    assert run("user-remove", "Ani", "--workdb", imported) == 1
