"""Penerjemah mesin."""
from .base import (ConnectionFailed, Provider, ProviderError, RateLimited, ServerDown, mask,
                   translate_safe, unmask)
from .claude import DEFAULT_MODEL, Claude
from .libre import LibreTranslate
from .mymemory import MyMemory


class Echo:
    """Mengembalikan teks apa adanya. Untuk menguji alur kerja tanpa jaringan."""
    name = label = "echo"
    default_batch = 20
    default_delay = 0.0

    def translate(self, texts, source, target):
        return list(texts)


def get_provider(name: str, url=None, key=None, email=None, model: str = DEFAULT_MODEL, glossary=()):
    if name == "libre":
        return LibreTranslate(url, key)
    if name == "mymemory":
        return MyMemory(email)
    if name == "claude":
        return Claude(key, model, glossary)
    if name == "echo":
        return Echo()
    raise ProviderError(f"penyedia tidak dikenal: {name}")


__all__ = ["Provider", "ProviderError", "RateLimited", "ServerDown", "ConnectionFailed", "mask", "unmask",
           "translate_safe", "LibreTranslate", "MyMemory", "Claude", "Echo", "DEFAULT_MODEL", "get_provider"]
