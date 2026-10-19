"""Pengenalan bagian teks yang tidak boleh diubah saat menerjemahkan."""
import re

# {0} {nama}, <color=#fff> </color>, %s %d, \n literal, [tag:isi]
PLACEHOLDER = re.compile(r"\{[^{}]*\}|<[^<>]+>|%[-+0-9.]*[sdif]|\\n|\[[A-Za-z_]+:[^\]]*\]")


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER.findall(text)
