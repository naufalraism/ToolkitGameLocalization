"""Penerjemah mesin."""
from .base import Provider, ProviderError, mask, translate_safe, unmask
from .libre import LibreTranslate


class Echo:
    """Mengembalikan teks apa adanya. Untuk uji alur kerja tanpa jaringan."""
    name = "echo"

    def translate(self, texts, source, target):
        return list(texts)


def get_provider(name: str, url: str | None = None, api_key: str | None = None):
    if name == "libre":
        return LibreTranslate(url or "http://localhost:5000", api_key)
    if name == "echo":
        return Echo()
    raise ProviderError(f"Penyedia tidak dikenal: {name}")


__all__ = ["Provider", "ProviderError", "mask", "unmask", "translate_safe", "LibreTranslate", "Echo", "get_provider"]
