import sqlite3

import pytest

from gamelokal.core.workbench import Workbench, WorkbenchError
from gamelokal.pack import write_translated_copy


def make_wb(tmp_path, ds, table, id_col, text_col, rows):
    wb = Workbench(tmp_path / "wb.db")
    wb.import_source(ds, rows, {"table": table, "id_col": id_col, "text_col": text_col, "game_path": "p/x.db"})
    return wb


def test_text_ids_and_source_untouched(game_db, tmp_path):
    wb = make_wb(tmp_path, "s", "MultiText", "Id", "Content", [("Intro_002", "Rover", "")])
    wb.set_target("s:Intro_002", "Rover ID", "edited")
    out = tmp_path / "out.db"
    assert write_translated_copy(wb, "s", game_db, out) == [("s", 1, 0)]
    q = lambda p, k: sqlite3.connect(p).execute("select Content, RedirectDbIndex from MultiText where Id=?", (k,)).fetchone()
    assert q(out, "Intro_002") == ("Rover ID", 0) and q(game_db, "Intro_002") == ("Rover", 0)
    assert q(out, "Intro_003") == ("Hello", 0)


def test_integer_ids(int_db, tmp_path):
    wb = make_wb(tmp_path, "i", "lang", "Id", "Content", [("2", "Rover", "")])
    wb.set_target("i:2", "Rover ID", "mt")
    out = tmp_path / "out.db"
    assert write_translated_copy(wb, "i", int_db, out) == [("i", 1, 0)]
    assert sqlite3.connect(out).execute("select Content from lang where Id=2").fetchone()[0] == "Rover ID"


def test_only_approved_and_missing_ids(int_db, tmp_path):
    wb = make_wb(tmp_path, "i", "lang", "Id", "Content", [("1", "Hello", ""), ("2", "Rover", "")])
    wb.set_target("i:1", "Halo", "mt")
    wb.set_target("i:2", "Rover ID", "approved")
    wb.import_translated("i", [("999", "hantu")])
    assert write_translated_copy(wb, "i", int_db, tmp_path / "a.db", only_approved=True) == [("i", 1, 0)]
    assert write_translated_copy(wb, "i", int_db, tmp_path / "b.db") == [("i", 3 - 1, 1)]


def test_include_requires_same_table(game_db, int_db, tmp_path):
    wb = make_wb(tmp_path, "s", "MultiText", "Id", "Content", [("Intro_002", "Rover", "")])
    wb.import_source("i", [("1", "Hello", "")], {"table": "lang", "id_col": "Id", "text_col": "Content", "game_path": "x"})
    with pytest.raises(WorkbenchError):
        write_translated_copy(wb, "s", game_db, tmp_path / "o.db", include=["i"])
