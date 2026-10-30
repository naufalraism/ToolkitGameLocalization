import pytest

from gamelokal.core.workbench import Workbench, WorkbenchError

MAP = {"table": "T", "id_col": "Id", "text_col": "C", "game_path": "x/y.db"}


@pytest.fixture
def wb(tmp_path):
    w = Workbench(tmp_path / "wb.db")
    w.import_source("ds", [("a_1", "Hello", "Rover"), ("a_2", "Bye", ""), ("b_1", "Yes", "")], MAP)
    yield w
    w.close()


def test_import_counts_and_idempotent(wb):
    assert wb.import_source("ds", [("a_1", "Hello", ""), ("a_2", "Bye CHANGED", ""), ("c_1", "New", "")], MAP) == (1, 1, 1)
    assert wb.get("ds:a_2")["source"] == "Bye CHANGED"


def test_history_revert_and_status(wb):
    wb.set_target("ds:a_1", "Halo", "mt", "mesin")
    wb.set_target("ds:a_1", "Halo, Rover", "edited", "perbaiki")
    wb.set_target("ds:a_1", "Halo, Rover", "approved")      # teks sama: tidak menambah versi
    assert [v["text"] for v in wb.history("ds:a_1")] == ["Halo", "Halo, Rover"]
    wb.revert("ds:a_1", 1)
    r = wb.get("ds:a_1")
    assert r["target"] == "Halo" and r["status"] == "edited" and len(wb.history("ds:a_1")) == 3
    with pytest.raises(WorkbenchError):
        wb.revert("ds:a_1", 99)


def test_empty_target_resets_status_and_approve_needs_text(wb):
    assert wb.approve("ds:a_2") is False
    wb.set_target("ds:a_2", "Dah", "edited")
    assert wb.approve("ds:a_2") is True
    wb.set_target("ds:a_2", "", "edited")
    assert wb.get("ds:a_2")["status"] == "new"


def test_search_and_stats(wb):
    wb.set_target("ds:a_1", "Halo", "mt")
    rows, total = wb.search("hello", in_="source")
    assert total == 1 and rows[0]["id"] == "ds:a_1"
    assert wb.search(status="untranslated")[1] == 2
    assert wb.search(prefix="b")[1] == 1
    assert wb.search("50%_", in_="source")[1] == 0          # karakter LIKE dianggap biasa
    s = wb.stats(by_prefix=5)
    assert (s["total"], s["untranslated"], s["by_status"]["mt"]) == (3, 2, 1)
    assert {p[0] for p in s["prefixes"]} == {"a", "b"}


def test_import_translated_creates_entries_without_source(wb):
    applied, created = wb.import_translated("ds", [("a_1", "Halo"), ("z_9", "Baru")])
    assert (applied, created) == (2, 1)
    assert wb.get("ds:z_9")["source"] == "" and wb.get("ds:a_1")["status"] == "edited"
    assert "ds:z_9" not in [r["id"] for r in wb.entries("ds")]   # tanpa teks asli: tidak ikut QA
    assert "ds:z_9" in [r["id"] for r in wb.targets_for("ds")]   # tetap ikut ditulis ke database


def test_pick_dataset(wb):
    assert wb.pick_dataset()[0] == "ds"
    with pytest.raises(WorkbenchError):
        wb.pick_dataset("nope")


def test_author_tracking_keeps_last_editor_when_anonymous(wb):
    wb.set_target("ds:a_1", "Satu", "edited", "", "Ani")
    wb.set_target("ds:a_1", "Dua", "edited")                      # tanpa nama: editor tidak terhapus
    assert wb.get("ds:a_1")["editor"] == "Ani"
    assert [v["author"] for v in wb.history("ds:a_1")] == ["Ani", ""]
    wb.approve("ds:a_1", "Budi")
    assert wb.get("ds:a_1")["editor"] == "Budi"


def test_users_tokens_are_hashed_and_validated(wb):
    token = wb.add_user("Ani")
    assert wb.user_for_token(token) == "Ani" and wb.user_for_token("salah") is None
    assert token not in wb.con.execute("SELECT token_hash FROM users").fetchone()[0]
    with pytest.raises(WorkbenchError):
        wb.add_user("Ani")
    with pytest.raises(WorkbenchError):
        wb.add_user("../../etc")
    wb.remove_user("Ani")
    assert wb.user_count() == 0 and wb.user_for_token(token) is None
    with pytest.raises(WorkbenchError):
        wb.remove_user("Ani")


def test_old_workbench_is_migrated(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.executescript("""
      CREATE TABLE entries(id TEXT PRIMARY KEY, speaker TEXT NOT NULL DEFAULT '', source TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new', updated REAL);
      CREATE TABLE versions(vid INTEGER PRIMARY KEY AUTOINCREMENT, entry_id TEXT NOT NULL, ts REAL NOT NULL,
        text TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
      CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
      INSERT INTO entries(id, source, target, status, updated) VALUES ('d:1', 'Hi', 'Halo', 'edited', 1.0);
      INSERT INTO versions(entry_id, ts, text) VALUES ('d:1', 1.0, 'Halo');
    """)
    con.commit()
    con.close()
    with Workbench(p) as wb:
        assert wb.get("d:1")["editor"] == "" and wb.history("d:1")[0]["author"] == ""
        wb.set_target("d:1", "Hai", "edited", "", "Ani")
        assert wb.get("d:1")["editor"] == "Ani"
