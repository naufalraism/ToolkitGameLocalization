import sqlite3

import pytest

TEXT_ROWS = [
    ("Intro_001", "Hello {0}, welcome to <color=#fff>Wuthering</color>"),
    ("Intro_002", "Rover"),
    ("Intro_003", "Hello"),
    ("Quest_001", "Hello"),
    ("Quest_002", "Press %s to continue\\nThen wait"),
    ("Empty_001", ""),
    ("Null_001", None),
]


@pytest.fixture
def game_db(tmp_path):
    """Meniru skema lang_multi_text.db: MultiText(Id TEXT PK, Content TEXT, RedirectDbIndex INT)."""
    folder = tmp_path / "game" / "en"
    folder.mkdir(parents=True)
    path = folder / "lang_multi_text.db"
    con = sqlite3.connect(path)
    con.execute("create table MultiText (Id TEXT PRIMARY KEY, Content TEXT, RedirectDbIndex INT)")
    con.executemany("insert into MultiText values (?, ?, 0)", TEXT_ROWS)
    con.commit()
    con.close()
    return path


@pytest.fixture
def int_db(tmp_path):
    path = tmp_path / "ints.db"
    con = sqlite3.connect(path)
    con.execute("create table lang (Id INTEGER PRIMARY KEY, Content TEXT, Flag INTEGER)")
    con.executemany("insert into lang values (?, ?, 0)", [(1, "Hello"), (2, "Rover"), (3, "Bye")])
    con.commit()
    con.close()
    return path
