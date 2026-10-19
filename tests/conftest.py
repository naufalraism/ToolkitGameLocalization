import sqlite3

import pytest

ROWS = [
    (1, "Hello {0}, welcome to <color=#fff>Wuthering</color>"),
    (2, "Rover"),
    (3, "Hello"),
    (4, "Hello"),
    (5, "Press %s to continue\\nThen wait"),
]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "lang_test.db"
    con = sqlite3.connect(path)
    con.execute("create table lang (Id INTEGER PRIMARY KEY, Content TEXT, Flag INTEGER)")
    con.executemany("insert into lang values (?, ?, 0)", ROWS)
    con.commit()
    con.close()
    return path
