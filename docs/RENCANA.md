# Rencana

## Tahap 1: fondasi (selesai)
- [x] Ekspor/impor CSV dengan pelestarian pekerjaan lama
- [x] Penerjemahan mesin dengan perlindungan tag
- [x] QA: placeholder, glosarium, konsistensi, panjang
- [x] Build `.db` hasil terjemahan
- [x] Pengujian otomatis dan CI

## Tahap 2: Wuthering Waves
- [ ] Kunci nama tabel dan kolom di adapter berdasarkan `inspect` pada `lang_*.db` asli
- [ ] Pindahkan fitur pencarian dan pengeditan dialog dari skrip lama ke `core`
- [ ] Pengemasan `.pak` lewat adapter
- [ ] Penyedia mesin tambahan dengan batas laju dan cache
- [ ] Opsional: Docker Compose untuk LibreTranslate

## Tahap 3: kualitas dan versi
- [ ] Riwayat versi terjemahan per baris
- [ ] Pengecekan tambahan: tanda baca, huruf besar, panjang per kotak dialog
- [ ] Laporan HTML hasil QA
- [ ] Rilis bernomor versi di PyPI

## Tahap 4: antarmuka web
- [ ] Server lokal kecil dengan antarmuka untuk menerjemahkan bersama
- [ ] Pencarian dan filter, status per baris (belum, draf, selesai)

## Tahap 5: game kedua
- [ ] Adapter game lain untuk membuktikan desain adapter
- [ ] Reader format tambahan (JSON, PO)
