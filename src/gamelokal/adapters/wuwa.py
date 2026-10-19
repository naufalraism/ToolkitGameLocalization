from .base import Adapter

WUTHERING_WAVES = Adapter(
    name="wuthering-waves",
    lang_folders=("base", "en", "ja", "zh-Hans"),
    db_pattern="lang_*.db",
    notes="Nama tabel dan kolom belum dikunci. Jalankan `gamelokal inspect` pada satu lang_*.db lalu isi di sini.",
)
