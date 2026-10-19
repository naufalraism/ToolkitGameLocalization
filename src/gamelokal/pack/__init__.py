"""Pembuatan patch.

Saat ini hanya menghasilkan berkas .db yang sudah diterjemahkan (lihat core.store.write_patch).
Pengemasan ke .pak bergantung pada game dan alatnya, dan akan ditambahkan per adapter.
"""
from ..core.store import write_patch

__all__ = ["write_patch"]
