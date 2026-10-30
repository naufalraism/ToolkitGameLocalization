# Rencana

## Tahap 1: fondasi (selesai)
- [x] Workbench: impor idempoten, status, riwayat versi, pencarian, statistik
- [x] Terjemahan mesin dengan perlindungan tag (LibreTranslate)
- [x] QA: tag, urutan tag, sisa penanda, glosarium, konsistensi, panjang
- [x] Ekspor `.db` dan `.pak` dengan gerbang kualitas
- [x] Pengujian otomatis dan CI

## Tahap 2: Wuthering Waves (sebagian)
- [x] Adapter dikunci dari `lang_multi_text.db` asli (tabel `MultiText`, 277.769 teks dari 326.662 baris)
- [x] Penulis dan pembaca `.pak` dipindahkan dari skrip asal
- [x] Impor terjemahan lama dari `.pak`, `.db`, `.json`
- [ ] Uji pak hasil gamelokal langsung di game
- [x] Perintah `audit` untuk memeriksa semua `lang_*.db` terhadap skema adapter
- [ ] Jalankan `audit` pada folder game lengkap (baru `lang_multi_text.db` yang pernah diperiksa)
- [x] Penyedia MyMemory dan Claude, pemotongan teks per 450 karakter, penanganan batas laju, `--max-chars`, `--dry-run`
- [ ] Uji MyMemory dan Claude dengan layanan sungguhan (saat ini hanya diuji dengan server lokal dan penyedia palsu)
- [ ] Glosarium JSON seperti di skrip asal (sekarang memakai CSV yang sama dengan `qa`)
- [ ] Opsional: Docker Compose untuk LibreTranslate

## Tahap 3: kualitas dan versi
- [ ] Pengecekan tambahan: tanda baca, huruf besar, panjang per kotak dialog
- [ ] Laporan HTML hasil QA
- [ ] Rilis bernomor versi di PyPI

## Tahap 4: antarmuka web
- [x] Server lokal, pencarian, filter, penyuntingan, persetujuan, riwayat dan pengembalian versi, pengecekan tag
- [x] Terjemahan mesin dari web (saran, tidak disimpan otomatis, dengan batas karakter per sesi)
- [x] Laporan QA seluruh dataset di web
- [x] Deteksi tabrakan saat dua orang menyunting entri yang sama
- [x] Akun berbasis token dan penandaan siapa yang menyunting
- [ ] Antarmuka dan pesan CLI dalam bahasa Inggris (i18n)
- [ ] HTTPS bawaan atau panduan reverse proxy
- [ ] Pembaruan langsung antarpengguna (saat ini harus memuat ulang daftar)

## Tahap 5: game kedua
- [ ] Adapter game lain untuk membuktikan desain adapter
- [ ] Pembaca format tambahan (JSON, PO)
