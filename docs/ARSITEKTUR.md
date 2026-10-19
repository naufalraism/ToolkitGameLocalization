# Arsitektur

## Prinsip

1. **Tanpa dependensi runtime.** Hanya pustaka standar Python, supaya mudah dipasang dan dipakai di CI.
2. **CSV sebagai format tukar.** Penerjemah manusia bisa membukanya di Excel atau Sheets, dan perbedaannya mudah dibaca di Git.
3. **Sumber tidak pernah diubah.** `build` selalu menyalin `.db` sumber ke berkas baru, dan menolak menimpa sumber.
4. **Aman dilanjutkan.** `translate` menyimpan CSV setiap batch, `export` mempertahankan pekerjaan lama.

## Modul

| Modul | Tanggung jawab |
|---|---|
| `core.store` | membaca `.db` secara read-only, menebak kolom, menulis salinan yang sudah di-patch |
| `core.text` | satu definisi tentang apa itu placeholder (dipakai penerjemah dan QA) |
| `core.project` | `gamelokal.json`: lokasi `.db`, tabel, kolom, bahasa |
| `translate.base` | `mask`/`unmask`: tag diganti penanda `⟦n⟧` sebelum dikirim ke mesin, lalu dipulihkan |
| `translate.*` | penyedia mesin di balik antarmuka `Provider` |
| `qa.checks` | fungsi murni yang mengembalikan daftar `Issue` |
| `adapters` | pengetahuan per game; saat ini hanya lokasi berkas |

## Keputusan

- **Masking tag.** Mesin penerjemah sering menghapus atau mengubah `<color=#fff>` dan `{0}`. Dengan penanda unik, tag dipulihkan setelahnya, dan baris yang penandanya hilang diberi catatan `cek placeholder`, lalu ditangkap QA.
- **ID sebagai teks di CSV, asli di database.** Saat `build`, ID dicocokkan kembali ke nilai aslinya, jadi kolom ID bertipe integer maupun teks sama-sama bekerja.
- **Penebakan kolom.** Kolom bertipe teks dengan rata-rata panjang terbesar dianggap kolom dialog. Hanya tebakan awal, bisa ditimpa lewat `--table --id-col --text-col`.

## Batasan yang diketahui

- Hanya SQLite. Format lain (JSON, PO, CSV mentah) butuh reader baru di `core`.
- Penerjemahan LibreTranslate per baris, jadi lambat untuk data sangat besar.
- Belum ada pengemasan `.pak`.
