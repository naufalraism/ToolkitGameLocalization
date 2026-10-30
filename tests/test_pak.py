import pytest

from gamelokal.pack import PakError, build_pak, read_pak

PATH = "Client/Content/Aki/ConfigDB/en/lang_multi_text.db"


def test_roundtrip(tmp_path):
    data = b"SQLite format 3\x00" + bytes(range(256)) * 20
    pak = tmp_path / "a.pak"
    pak.write_bytes(build_pak(PATH, data))
    assert read_pak(pak) == (PATH, data)


def test_build_is_deterministic():
    assert build_pak(PATH, b"abc") == build_pak(PATH, b"abc")


def test_rejects_non_pak(tmp_path):
    f = tmp_path / "x.pak"
    f.write_bytes(b"x" * 200)
    with pytest.raises(PakError):
        read_pak(f)


def test_detects_corruption(tmp_path):
    blob = bytearray(build_pak(PATH, b"hello world, ini isi berkas"))
    blob[60] ^= 0xFF  # ubah satu byte di area data
    f = tmp_path / "x.pak"
    f.write_bytes(bytes(blob))
    with pytest.raises(PakError):
        read_pak(f)
