import pytest

from gamelokal.core.store import StoreError, guess_columns, inspect_db, iter_rows


def test_inspect(game_db):
    (t,) = inspect_db(game_db)
    assert t.name == "MultiText" and t.rows == 7
    assert [c.name for c in t.columns] == ["Id", "Content", "RedirectDbIndex"]


def test_guess_columns(game_db):
    g = guess_columns(game_db)
    assert (g.table, g.id_col, g.text_col) == ("MultiText", "Id", "Content")


def test_iter_rows_skips_blank_and_null(game_db):
    rows = list(iter_rows(game_db, "MultiText", "Id", "Content"))
    assert len(rows) == 5 and rows[1] == ("Intro_002", "Rover", "")


def test_iter_rows_where_and_errors(game_db):
    assert len(list(iter_rows(game_db, "MultiText", "Id", "Content", where="Id like 'Quest%'"))) == 2
    with pytest.raises(StoreError):
        list(iter_rows(game_db, "Nope", "Id", "Content"))
    with pytest.raises(StoreError):
        list(iter_rows(game_db, "MultiText", "Id", "Nope"))


def test_not_sqlite(tmp_path):
    bad = tmp_path / "x.db"
    bad.write_bytes(b"bukan sqlite" * 50)
    with pytest.raises(StoreError):
        inspect_db(bad)
