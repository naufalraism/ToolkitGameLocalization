# Berkontribusi

```bash
git clone <repo>
cd gamelokal
pip install -e ".[dev]"
pytest
```

- Satu pull request, satu perubahan. Sertakan pengujian untuk perilaku baru.
- Pengecekan QA baru: tambahkan fungsi murni di `qa/checks.py` dan uji dengan contoh benar dan salah.
- Adapter game baru: tambahkan file di `adapters/` dan daftarkan di `adapters/__init__.py`.
- Jangan mengunggah berkas asli game. Gunakan database kecil buatan sendiri untuk pengujian.
