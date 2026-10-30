# Arsitektur

## Prinsip

1. **Database game tidak pernah diubah.** Dibuka read-only; hasil selalu ditulis ke salinan, dan penulisan ke berkas yang sama dengan sumber ditolak.
2. **Workbench sebagai satu-satunya sumber kebenaran kerja.** Teks asli, terjemahan, status, dan riwayat versi ada di `workbench.db` (SQLite). Hasil ekspor bisa dibuat ulang kapan saja.
3. **Tanpa dependensi runtime.** Hanya pustaka standar Python, supaya mudah dipasang dan dipakai di CI.
4. **Aman diulang dan dilanjutkan.** `import` idempoten dan menghitung teks asli yang berubah; `translate` menyimpan tiap batch.
5. **Gerbang kualitas sebelum ekspor.** Tag yang tidak cocok menghentikan ekspor, bukan sekadar peringatan, karena itu bisa merusak tampilan atau membuat game error.

## Modul

| Modul | Tanggung jawab |
|---|---|
| `core.store` | membuka database game read-only, menebak kolom, membaca baris |
| `core.workbench` | skema, impor, riwayat versi, status, pencarian, statistik |
| `core.text` | definisi placeholder dan pengecekan tag bersarang, satu sumber untuk penerjemah dan QA |
| `translate.base` | `mask`/`unmask`: tag diganti penanda `⟦n⟧` sebelum dikirim ke mesin, lalu dipulihkan |
| `translate.*` | penyedia mesin di balik antarmuka `Provider` |
| `qa.checks` | fungsi murni yang mengembalikan daftar `Issue` |
| `pack.dbpatch` | menyalin database dasar dan menulis hanya kolom teks |
| `pack.pak` | penulis dan pembaca `.pak` Unreal (satu berkas, tanpa kompresi/enkripsi) |
| `web.server` | server HTTP lokal (pustaka standar) dengan API JSON; satu koneksi workbench per permintaan |
| `web/index.html` | antarmuka satu berkas tanpa dependensi |
| `adapters` | pengetahuan per game: skema, folder bahasa, lokasi berkas di pak |

## Keputusan

- **Masking tag.** Mesin penerjemah sering menghapus atau mengubah `<color=#fff>` dan `{0}`. Dengan penanda unik, tag dipulihkan setelahnya. Baris yang penandanya hilang tidak disimpan.
- **Id sebagai teks di workbench, tipe asli di database.** Saat ekspor, id dikonversi sesuai tipe kolom, jadi kolom `INTEGER` maupun `TEXT` sama-sama bekerja.
- **Id entri `dataset:kunci`.** Beberapa dataset (misalnya cerita utama dan misi sampingan) bisa hidup di satu workbench dan digabung saat ekspor selama memakai tabel yang sama.
- **Terjemahan tanpa teks asli tetap diterima.** Saat mengimpor `.pak` lama, entri yang belum punya teks asli dibuat dengan sumber kosong, ditulis ke database, tetapi tidak ikut QA.

## Keamanan server web

- Bawaan hanya localhost, dan header Host selain localhost ditolak (melawan DNS rebinding).
- Alamat selain localhost wajib memakai `--token` bersama atau akun. Akun berupa token acak per orang; hanya hash SHA-256 yang disimpan, dan perbandingan memakai `hmac.compare_digest`. Jika ada akun, token bersama tidak dipakai.
- Permintaan yang mengubah data wajib membawa header `X-Gamelokal` dan JSON, sehingga halaman web lain tidak bisa memicunya dari browser tanpa preflight.
- Penyimpanan memakai penanda versi (`rev`, nilai `updated` entri). Jika entri berubah sejak dibuka, server menjawab 409 dan klien memilih memakai versi lain atau menimpa.
- Saran mesin tidak pernah disimpan otomatis, dan `--mt-budget` membatasi karakter terkirim per sesi server.
- Semua data dari klien dipakai lewat parameter SQL, dan ukuran badan permintaan dibatasi 1 MB.
- Tidak ada enkripsi atau akun pengguna. Server ini untuk komputer sendiri atau jaringan tepercaya, bukan untuk internet.

## Batasan yang diketahui

- Hanya SQLite. Format lain (JSON, PO) butuh pembaca baru di `core`.
- Penerjemahan LibreTranslate per baris, jadi lambat untuk data sangat besar.
- Penulis `.pak` hanya menghasilkan pak satu berkas versi 12 tanpa kompresi dan enkripsi.
