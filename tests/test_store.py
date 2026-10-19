import sqlite3

import pytest

from gamelokal.core.store import guess_columns, inspect_db, load_entries, write_patch


def test_inspect(db):
    (t,) = inspect_db(db)
    assert t.name == "lang" and t.rows == 5
    assert [c.name for c in t.columns] == ["Id", "Content", "Flag"]


def test_guess_columns(db):
    g = guess_columns(db)
    assert (g.table, g.id_col, g.text_col) == ("lang", "Id", "Content")


def test_load_entries_ids_are_strings(db):
    rows = list(load_entries(db, "lang", "Id", "Content"))
    assert rows[1] == ("2", "Rover")


def test_write_patch_roundtrip_with_integer_ids(db, tmp_path):
    out = tmp_path / "patched.db"
    n = write_patch(db, out, "lang", "Id", "Content", {"2": "Rover ID", "999": "tidak ada"})
    assert n == 1
    con = sqlite3.connect(out)
    assert con.execute("select Content from lang where Id=2").fetchone()[0] == "Rover ID"
    assert con.execute("select Content from lang where Id=3").fetchone()[0] == "Hello"
    con.close()
    con = sqlite3.connect(db)  # sumber tidak berubah
    assert con.execute("select Content from lang where Id=2").fetchone()[0] == "Rover"
    con.close()


def test_write_patch_refuses_same_file(db):
    with pytest.raises(ValueError):
        write_patch(db, db, "lang", "Id", "Content", {})
