"""Pengenalan bagian teks yang tidak boleh diubah saat menerjemahkan."""
import difflib
import re

# {0} {nama}, <color=#fff> </color>, %s %d, \n literal, [tag:isi]
PLACEHOLDER = re.compile(r"\{[^{}]*\}|<[^<>]+>|%[-+0-9.]*[sdif]|\\n|\[[A-Za-z_]+:[^\]]*\]")
# Untuk dikirim ke mesin: baris baru sungguhan juga dilindungi.
MASKABLE = re.compile(PLACEHOLDER.pattern + r"|\n")
LEFTOVER = re.compile(r"\u27e6\d+\u27e7")
TAG_NAME = re.compile(r"<(/?)([A-Za-z][\w-]*)[^<>]*?(/?)>")


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER.findall(text)


def tags_balanced(text: str) -> bool:
    """True kalau tag pembuka dan penutup (<color=..> ... </color>) bersarang dengan benar."""
    stack: list[str] = []
    for m in TAG_NAME.finditer(text):
        close, name, selfclose = m.groups()
        if selfclose:
            continue
        if close:
            if not stack or stack.pop() != name:
                return False
        else:
            stack.append(name)
    return not stack


def short(s: str, n: int = 100) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 1] + "\u2026"


def word_diff(old: str, new: str) -> str:
    x, y = re.split(r"(\s+)", old), re.split(r"(\s+)", new)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
        if op == "equal":
            out.append("".join(x[i1:i2]))
        else:
            if i2 > i1:
                out.append("[-" + "".join(x[i1:i2]) + "-]")
            if j2 > j1:
                out.append("{+" + "".join(y[j1:j2]) + "+}")
    return "".join(out)


def split_sentences(s: str, limit: int = 450) -> list[str]:
    """Memotong teks panjang per kalimat agar tiap potongan <= limit karakter (batas MyMemory)."""
    parts = [p for p in re.split(r"(?<=[.!?\u3002\uff01\uff1f\u2026])\s*", s) if p]
    out, buf = [], ""
    for p in parts:
        if buf and len(buf) + 1 + len(p) > limit:
            out.append(buf)
            buf = p
        else:
            buf = (buf + " " + p).strip()
    if buf:
        out.append(buf)
    return out or [s]
