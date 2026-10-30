"""Penulis dan pembaca berkas .pak Unreal Engine (satu berkas, tanpa kompresi atau enkripsi).

Dipindahkan dari wuwa_dialogue.py. Menurut catatan di skrip asal, penulisnya sudah diuji identik
byte-per-byte dengan WuwaID_1sthalf_P.pak buatan pengguna. Pengujian di repo ini hanya memeriksa
bolak-balik (build lalu read) karena berkas pak asli tidak disertakan.
"""
import hashlib
import struct
from pathlib import Path

from ..core.errors import GamelokalError


class PakError(GamelokalError):
    pass


PAK_MAGIC = 0x5A6F12E1
PAK_VERSION = 12        # nomor versi footer pada WuwaID_1sthalf_P.pak yang terbukti jalan
PAK_MOUNT = "../../../"


def _fstr(s):
    b = s.encode("utf-8") + b"\x00"
    return struct.pack("<i", len(b)) + b


def _rd_fstr(b, p):
    n, = struct.unpack_from("<i", b, p)
    p += 4
    return b[p:p + n - 1].decode("utf-8"), p + n


def path_hash(path, seed=0):
    """FNV64 atas UTF-16LE path huruf kecil (path-hash-index Unreal)."""
    h = (0xCBF29CE484222325 + seed) & 0xFFFFFFFFFFFFFFFF
    for byte in path.lower().encode("utf-16-le"):
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def build_pak(path, data):
    """Bungkus SATU file (tanpa kompresi/enkripsi) jadi pak. Sudah diuji identik
    byte-per-byte dengan WuwaID_1sthalf_P.pak."""
    size = len(data)
    entry = struct.pack("<QQQI", 0, size, size, 0) + hashlib.sha1(data).digest() + b"\x00" + struct.pack("<I", 0)
    body = entry + data
    parts = path.split("/")
    dirs = ["/"] + ["/".join(parts[: i + 1]) + "/" for i in range(len(parts) - 1)]
    fd = struct.pack("<I", len(dirs))
    for d in dirs:
        fd += _fstr(d)
        fd += (struct.pack("<I", 1) + _fstr(parts[-1]) + struct.pack("<i", 0)) if d == dirs[-1] else struct.pack("<I", 0)
    ph = struct.pack("<I", 1) + struct.pack("<Qi", path_hash(path), 0) + struct.pack("<I", 0)
    encoded = struct.pack("<I", 0xE0000000) + b"\x00" + struct.pack("<II", size, 0)
    index_off = len(body)
    prim_len = len(_fstr(PAK_MOUNT)) + 4 + 8 + 4 + 16 + 20 + 4 + 16 + 20 + 4 + len(encoded) + 4
    ph_off = index_off + prim_len
    fd_off = ph_off + len(ph)
    primary = (_fstr(PAK_MOUNT) + struct.pack("<iQ", 1, 0)
               + struct.pack("<I", 1) + struct.pack("<qq", ph_off, len(ph)) + hashlib.sha1(ph).digest()
               + struct.pack("<I", 1) + struct.pack("<qq", fd_off, len(fd)) + hashlib.sha1(fd).digest()
               + struct.pack("<i", len(encoded)) + encoded + struct.pack("<i", 0))
    footer = (b"\x00" * 17 + struct.pack("<IIQQ", PAK_MAGIC, PAK_VERSION, index_off, len(primary))
              + hashlib.sha1(primary).digest() + b"\x00" * 160)
    return body + primary + ph + fd + footer


def read_pak(path):
    """Baca pak berisi satu file tanpa kompresi. Mengembalikan (path_di_game, bytes)."""
    b = Path(path).read_bytes()
    mp = b.rfind(struct.pack("<I", PAK_MAGIC))
    if mp < 17:
        raise PakError(f"{path} bukan file pak Unreal")
    ver, ioff, isz = struct.unpack_from("<IQQ", b, mp + 4)
    if ver < 10 or b[mp - 1] != 0:
        raise PakError(f"pak versi {ver}/terenkripsi belum didukung oleh pembaca bawaan")
    idx = b[ioff:ioff + isz]
    p = 0
    _, p = _rd_fstr(idx, p)
    p += 12
    for _ in range(2):  # path hash index, lalu full directory index
        has, = struct.unpack_from("<I", idx, p)
        p += 4
        if has:
            off, size = struct.unpack_from("<qq", idx, p)
            p += 36
        last = (off, size) if has else None
    if not last:
        raise PakError("pak tanpa full directory index belum didukung")
    fd = b[last[0]:last[0] + last[1]]
    q = 0
    ndirs, = struct.unpack_from("<I", fd, q)
    q += 4
    files = []
    for _ in range(ndirs):
        d, q = _rd_fstr(fd, q)
        nf, = struct.unpack_from("<I", fd, q)
        q += 4
        for _ in range(nf):
            name, q = _rd_fstr(fd, q)
            q += 4
            files.append(d.lstrip("/") + name)
    if len(files) != 1:
        raise PakError(f"pak ini berisi {len(files)} file; pembaca bawaan hanya mendukung pak 1 file "
            "(buat satu pak per file, seperti yang dilakukan export-pak)")
    off, csize, usize, comp = struct.unpack_from("<QQQI", b, 0)
    if comp != 0:
        raise PakError("pak ini memakai kompresi; belum didukung")
    data = b[53:53 + usize]
    if hashlib.sha1(data).digest() != b[28:48]:
        raise PakError("hash isi pak tidak cocok, file mungkin rusak")
    return files[0], data


