# gamelokal

[English](README.md) | Bahasa Indonesia

Toolkit lokalisasi game untuk penerjemah dan modder. Mengambil teks dari database SQLite game, menyimpannya di workbench dengan status dan riwayat versi, menerjemahkan dengan mesin tanpa merusak tag, memeriksa kualitasnya, lalu menulis patch (`.db` atau `.pak`).

*English: a game localization toolkit. Imports text from SQLite game databases into a workbench with per-line status and version history, machine-translates while protecting tags, runs QA checks, and builds a patched database or a single-file Unreal `.pak`. No runtime dependencies.*

> Status: **0.2 (awal)**. Dikembangkan dari skrip pribadi untuk mod terjemahan Wuthering Waves. Alur impor, edit, QA, ekspor `.db` dan `.pak` sudah berjalan dan diuji. Antarmuka web dan game lain belum ada. Lihat [docs/RENCANA.md](docs/RENCANA.md).

## Kenapa

Menerjemahkan puluhan ribu baris dialog menimbulkan masalah berulang: tag format (`<color=...>`, `{0}`, `%s`) rusak oleh mesin penerjemah, istilah yang sama diterjemahkan berbeda, dan terjemahan lama hilang atau basi setiap game diperbarui. gamelokal menangani semuanya, dan database asli game tidak pernah diubah.

## Alur kerja

```
database game ──import──▶ workbench.db ◀──edit / approve / revert / import-csv
                              │   ▲
                   translate ─┘   └─ import-translated (.pak/.db/.json lama)
                              │
                  qa ◀────────┤
                              ▼
              export-db ──▶ salinan .db      export-pak ──▶ .pak siap pasang
```

## Mulai

Butuh Python 3.10+. Tidak ada dependensi lain.

```bash
pip install -e .

gamelokal inspect lang_multi_text.db                    # lihat tabel dan kolom
gamelokal audit wuthering-waves <folder game> --lang en  # cocokkan semua lang_*.db dengan skema adapter
gamelokal import lang_multi_text.db --adapter wuthering-waves --name story
gamelokal serve --open                                  # antarmuka web lokal untuk menyunting
gamelokal stats --by-prefix 10                          # progres per kategori
gamelokal translate --limit 50                          # LibreTranslate di localhost:5000 (gratis)
gamelokal search "Rover" --in source                    # cari entri
gamelokal edit story:Intro_001 --text "Halo {0}"        # tanpa --text: buka editor
gamelokal history story:Intro_001                       # riwayat dengan selisih per kata
gamelokal qa --glossary examples/glossary.csv           # tag, glosarium, konsistensi
gamelokal export-pak --base lang_multi_text.db --out WuwaID_story_P.pak
```

Melanjutkan terjemahan lama: `gamelokal import-translated WuwaID_1sthalf_P.pak --name story --adapter wuthering-waves`.

## Perintah

| Perintah | Fungsi |
|---|---|
| `inspect`, `find` | menjelajah database dan mencari berkas lewat adapter |
| `audit` | memeriksa semua `lang_*.db` di folder game terhadap skema adapter |
| `serve` | antarmuka web: sunting, setujui, riwayat, laporan QA, saran mesin, deteksi tabrakan edit |
| `user-add`, `user-list`, `user-remove` | akun penyunting (token pribadi) supaya perubahan tercatat atas nama |
| `import` | impor teks asli (aman diulang; perubahan teks asli setelah update game dihitung) |
| `import-translated` | impor terjemahan lama dari `.pak`, `.db`, atau `.json` |
| `search`, `show`, `stats` | cari, lihat satu entri, ringkasan progres |
| `edit`, `approve`, `history`, `revert` | menyunting dengan status (`mt`, `edited`, `approved`) dan riwayat versi |
| `translate` | terjemahan mesin untuk entri kosong: `libre` (gratis, lokal), `mymemory` (gratis, ada batas harian), atau `claude` (berbayar). Disimpan per batch; berhenti rapi saat kena batas laju (kode keluar 3, aman dilanjutkan) |
| `qa` | periksa kualitas; kode keluar 1 jika ada error, jadi bisa dipasang di CI |
| `export-db`, `export-pak`, `unpack-pak` | tulis salinan database atau pak, dan bongkar pak |
| `export-csv`, `import-csv`, `export-json` | pertukaran dengan penerjemah lain |

Ekspor menolak berjalan kalau ada tag atau variabel yang tidak cocok dengan teks asli (bisa dilewati dengan `--skip-check`), dan `--only-approved` hanya menulis entri yang sudah disetujui.

## Antarmuka web

`gamelokal serve` membuka penyunting di `http://localhost:8000`:

- daftar dengan pencarian dan filter (status, awalan ID), serta bilah progres bertingkat;
- tag di teks asli diberi warna dan bisa disisipkan sekali klik, dengan peringatan tag langsung saat disimpan;
- tab **Laporan QA** untuk seluruh dataset, bisa disaring per jenis masalah;
- tombol **Saran mesin** (aktifkan dengan `--provider libre|mymemory|claude`): saran tampil terpisah dan baru disimpan kalau kamu memakainya; `--mt-budget` membatasi karakter terkirim per sesi (bawaan 200.000 untuk Claude);
- **deteksi tabrakan**: kalau orang lain mengubah entri yang sama sejak kamu membukanya, kamu memilih antara memakai versi mereka atau menimpanya;
- riwayat dengan nama penyunting dan tombol kembalikan.

Bekerja bersama: buat akun per orang dengan `gamelokal user-add NAMA` (token ditampilkan sekali), lalu jalankan `gamelokal serve --host 0.0.0.0`. Setiap orang membuka tautan pribadinya (`?token=...`), dan perubahannya tercatat atas namanya. Tanpa akun, alamat selain localhost wajib memakai `--token` bersama. Lalu lintas tidak dienkripsi: pakai di jaringan tepercaya, atau di belakang proxy HTTPS. Aplikasi ini tidak dirancang untuk internet terbuka.

## Penerjemah mesin

| Penyedia | Biaya | Catatan |
|---|---|---|
| `libre` (default) | gratis | server LibreTranslate sendiri; alamat lewat `--url` atau env `LIBRETRANSLATE_URL` |
| `mymemory` | gratis, ada batas harian | `--email` atau env `MYMEMORY_EMAIL` menaikkan batas; teks dipotong per 450 karakter |
| `claude` | berbayar menurut pemakaian | butuh API key (env `ANTHROPIC_API_KEY`); mengirim glosarium (`--glossary`) sebagai istilah wajib; `--max-chars` membatasi total karakter terkirim sebagai pengaman biaya; harga dan batas laju ada di dokumentasi resmi (docs.claude.com) |

Semua penyedia memakai perlindungan tag yang sama. Hasil yang tag atau variabelnya rusak tidak disimpan dan dihitung gagal. `--limit` default 50 per jalan (`--limit 0` untuk semua), dan `--dry-run` menampilkan hasil tanpa menyimpan.

## Pengecekan kualitas

| Kode | Tingkat | Arti |
|---|---|---|
| `placeholder` | error | tag atau variabel hilang/berlebih dibanding teks asli |
| `urutan_tag` | error | tag pembuka dan penutup tidak bersarang dengan benar |
| `sisa_penanda` | error | kode sementara penerjemah mesin tertinggal di hasil |
| `glosarium` | peringatan | istilah glosarium tidak diterjemahkan sesuai daftar |
| `tidak_konsisten` | peringatan | teks asli yang sama diterjemahkan berbeda-beda |
| `sama_dengan_sumber` | peringatan | terjemahan identik dengan teks asli |
| `panjang` | peringatan | terjemahan jauh lebih panjang dari teks asli |

## Struktur

```
src/gamelokal/
  core/        database game (read-only), workbench, CSV, glosarium, teks
  adapters/    pengetahuan per game (Wuthering Waves: skema dan lokasi di pak)
  translate/   penyedia mesin dan perlindungan tag
  qa/          pengecekan kualitas
  pack/        salinan database terjemahan dan penulis/pembaca .pak
  web/         server dan antarmuka web lokal
  cli.py       perintah
tests/         70 pengujian otomatis
legacy/        skrip asal wuwa_dialogue.py (bagian yang belum dipindahkan ada di docs/RENCANA.md)
docs/          arsitektur dan rencana
```

## Catatan penting

- Jangan memasukkan berkas asli game ke repo. `.gitignore` mengecualikan `*.db` dan `*.pak`.
- Baca ketentuan penggunaan game sebelum membagikan mod.
- Adapter Wuthering Waves baru diperiksa pada `lang_multi_text.db`. Berkas `lang_*.db` lain belum diperiksa, dan pak hasil gamelokal belum diuji dimuat langsung oleh game.

## Berkontribusi

Lihat [CONTRIBUTING.md](CONTRIBUTING.md). Lisensi: MIT.
