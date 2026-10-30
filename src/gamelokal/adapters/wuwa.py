from .base import Adapter

WUTHERING_WAVES = Adapter(
    name="wuthering-waves",
    lang_folders=("base", "en", "ja", "zh-Hans"),
    db_pattern="lang_*.db",
    game_dir="Client/Content/Aki/ConfigDB/en/",
    table="MultiText",
    id_col="Id",
    text_col="Content",
    notes="Skema lang_multi_text.db: MultiText(Id TEXT PK, Content TEXT, RedirectDbIndex INT), 326.662 baris. "
          "Diperiksa pada berkas milik pengguna; lang_*.db lain belum diperiksa.",
)
