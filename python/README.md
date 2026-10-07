# Fase 1 - Hand Tracking Debug

Pelacakan dua tangan lewat webcam memakai MediaPipe Hand Landmarker (mode LIVE_STREAM).

## Setup (Windows, Python 3.10-3.12)

```bat
cd python
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python download_model.py
python main_debug.py
```

`download_model.py` mengunduh model ke `models/hand_landmarker.task` (dilewati jika sudah ada).
Semua pengaturan (kamera, ambang kepercayaan, dll.) ada di `config.py`.

Kontrol (berlaku di `main_debug.py`, `main_gestures.py`, dan `main.py` saat jendela preview aktif):

- `q` / ESC: keluar.
- `s`: mirror kamera ON/OFF saat runtime (default dari `MIRROR` di `config.py`).
  Label tangan dikoreksi otomatis: MediaPipe menentukan handedness dengan asumsi
  gambar input ter-mirror (kamera selfie). Jadi saat mirror OFF label MediaPipe
  ditukar secara internal (`swap efektif = SWAP_HANDEDNESS XOR (not mirror)`),
  sehingga tangan kanan fisik tetap berlabel `Right` di kedua mode.
- `h`: tukar label Left/Right secara manual (override di atas koreksi otomatis;
  hanya runtime, tidak menulis file).

Status tampil di overlay sebagai `mirror: ON/OFF  swap: ON/OFF`. Setiap toggle
mengosongkan riwayat tangan (dan me-reset detektor gestur) karena sampel lama
memakai koordinat/label yang berbeda.

## Menyetir (kemudi)

Angkat **kedua telapak terbuka** menghadap webcam (seperti bersiap merapal Air), lalu
geser keduanya bersama ke kiri/kanan dari tengah frame. Makin jauh dari tengah makin
cepat karakter berputar; kembali ke tengah (zona mati ±8 % lebar frame) = berhenti.
Arah selalu arah tubuh pemain: tangan ke kanan = putar kanan (mirror ON maupun OFF).

- Mendorong kedua telapak ke kamera tetap merapal **Air**; selama dorongan dan 0,5 s
  sesudahnya putaran berhenti. Jaga jarak tangan ke kamera tetap saat menyetir.
- Mengepal / menurunkan satu tangan = berhenti menyetir.
- `main_gestures.py` menampilkan bar kemudi (tengah = 0), alasan (`ok`, `deadzone`,
  `pushing`, `suppressed`, `not_open`, `no_hands`, `warmup`), garis tengah frame dan
  garis zona mati. `main.py` menampilkan `steer: +0.45` dan bar kecil di preview.
- `python replay.py <rekaman>` juga mencetak ringkasan kemudi (persen waktu aktif,
  rata-rata |value|). Semua ambang: bagian `# --- Steering` di `config.py`.

Jika kamera gagal dibuka: ubah `CAMERA_INDEX` atau `CAMERA_BACKEND` ('dshow' / 'default') di `config.py`.

## Checklist verifikasi manual Fase 1

- [ ] Jendela debug muncul dan menampilkan gambar webcam (mirror).
- [ ] Tangan kanan fisik berlabel `Right` (tangan kiri berlabel `Left`).
- [ ] Tekan `s` (mirror OFF): gambar terbalik, tetapi tangan kanan fisik TETAP berlabel `Right`. Tekan `s` lagi untuk kembali.
- [ ] Jika label tetap terbalik di kedua mode, tekan `h` lalu cek ulang; jika perlu, set `SWAP_HANDEDNESS = True` di `config.py`.
- [ ] FPS > 25 (cek `cam FPS` dan `det FPS` di pojok kiri atas).
- [ ] Dua tangan terdeteksi bersamaan (`hands: 2`).
- [ ] Titik dan garis tulang menempel pada tangan saat digerakkan.
- [ ] Keluar dengan `q`/ESC tanpa error dan lampu webcam mati.
