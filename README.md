# gamelokal

Toolkit lokalisasi game untuk penerjemah dan modder. Mengambil teks game dari database SQLite, menerjemahkannya dengan mesin tanpa merusak tag, memeriksa kualitasnya, lalu menulis patch.

*English: a game localization toolkit that exports text from SQLite game databases, machine-translates it while protecting tags/placeholders, runs QA checks (placeholders, glossary, consistency), and builds a patched database. Zero runtime dependencies.*

> Status: **0.1 (awal)**. Alur ekspor, terjemahan, QA, dan build sudah berjalan dan diuji. Pengemasan ke `.pak` dan antarmuka web belum ada. Lihat [docs/RENCANA.md](docs/RENCANA.md).

## Kenapa

Menerjemahkan puluhan ribu baris dialog game memunculkan masalah yang berulang: tag format (`<color=...>`, `{0}`, `%s`) rusak oleh mesin penerjemah, istilah yang sama diterjemahkan berbeda-beda, dan terjemahan lama hilang atau basi setiap game diperbarui. gamelokal menangani ketiganya.

## Alur kerja

```
.db game ──export──▶ work.csv ──translate──▶ work.csv ──qa──▶ laporan
                        │                                       │
                   (edit manual di Excel/Sheets)                ▼
                        └──────────────build──────────────▶ patched.db
```

## Mulai

Butuh Python 3.10+. Tidak ada dependensi lain.

```bash
pip install -e .

gamelokal inspect lang_xxx.db                         # lihat tabel dan tebak kolom teks
gamelokal init lang_xxx.db --glossary examples/glossary.csv
gamelokal export gamelokal.json                       # buat work.csv
gamelokal translate gamelokal.json --provider libre   # LibreTranslate di localhost:5000
gamelokal qa gamelokal.json                           # periksa tag, glosarium, konsistensi
gamelokal build gamelokal.json --out patched.db
```

Mengekspor ulang setelah game diperbarui mempertahankan terjemahan lama dan menandai baris yang teks aslinya berubah dengan catatan `sumber berubah`.

## Pengecekan kualitas

| Kode | Tingkat | Arti |
|---|---|---|
| `placeholder` | error | tag atau placeholder hilang/berlebih dibanding teks asli |
| `glosarium` | peringatan | istilah glosarium tidak diterjemahkan sesuai daftar |
| `tidak_konsisten` | peringatan | teks asli yang sama diterjemahkan dengan cara berbeda |
| `sama_dengan_sumber` | peringatan | terjemahan identik dengan teks asli |
| `panjang` | peringatan | terjemahan jauh lebih panjang dari teks asli |

`gamelokal qa` mengembalikan kode keluar 1 jika ada error, jadi bisa dipasang di CI.

## Struktur

```
src/gamelokal/
  core/        akses SQLite, proyek, CSV, glosarium
  adapters/    pengetahuan khusus per game (saat ini: wuthering-waves, belum lengkap)
  translate/   penyedia mesin (LibreTranslate, echo) dan perlindungan tag
  qa/          pengecekan kualitas
  pack/        pembuatan patch
  cli.py       perintah
tests/         pengujian otomatis
docs/          arsitektur dan rencana
```

Detail desain ada di [docs/ARSITEKTUR.md](docs/ARSITEKTUR.md).

## Catatan penting

- Jangan memasukkan berkas asli game ke repo. `.gitignore` sudah mengecualikan `*.db` dan `*.pak`.
- Baca ketentuan penggunaan game sebelum membagikan mod.
- Adapter Wuthering Waves belum mengunci nama tabel dan kolom. Gunakan `inspect`, lalu bantu lengkapi lewat pull request.

## Berkontribusi

Lihat [CONTRIBUTING.md](CONTRIBUTING.md). Lisensi: MIT.
