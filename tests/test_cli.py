import sqlite3

from gamelokal.cli import main
from gamelokal.core.csvio import read_rows, write_rows


def fill(csv_path, mapping):
    rows = read_rows(csv_path)
    for r in rows:
        if r["id"] in mapping:
            r["target"] = mapping[r["id"]]
    write_rows(csv_path, rows)


def test_full_flow(db, tmp_path):
    proj, work, out = tmp_path / "gamelokal.json", tmp_path / "work.csv", tmp_path / "patched.db"
    assert main(["init", str(db), "--out", str(proj)]) == 0
    assert main(["export", str(proj), "--csv", str(work)]) == 0
    assert main(["translate", str(proj), "--csv", str(work), "--provider", "echo"]) == 0

    fill(work, {"1": "Halo {0}, selamat datang di <color=#fff>Wuthering</color>",
                "2": "Rover", "3": "Halo", "4": "Halo", "5": "Tekan %s untuk lanjut\\nLalu tunggu"})
    assert main(["qa", str(proj), "--csv", str(work)]) == 0

    fill(work, {"1": "Halo, selamat datang"})  # tag hilang
    assert main(["qa", str(proj), "--csv", str(work)]) == 1
    fill(work, {"1": "Halo {0}, selamat datang di <color=#fff>Wuthering</color>"})

    assert main(["build", str(proj), "--csv", str(work), "--out", str(out)]) == 0
    con = sqlite3.connect(out)
    assert con.execute("select Content from lang where Id=3").fetchone()[0] == "Halo"
    con.close()


def test_export_keeps_work_and_flags_changed_source(db, tmp_path):
    proj, work = tmp_path / "gamelokal.json", tmp_path / "work.csv"
    main(["init", str(db), "--out", str(proj)])
    main(["export", str(proj), "--csv", str(work)])
    fill(work, {"3": "Halo"})

    con = sqlite3.connect(db)
    con.execute("update lang set Content='Hello again' where Id=3")
    con.commit()
    con.close()

    main(["export", str(proj), "--csv", str(work)])
    row = next(r for r in read_rows(work) if r["id"] == "3")
    assert row["target"] == "Halo" and row["note"] == "sumber berubah"
