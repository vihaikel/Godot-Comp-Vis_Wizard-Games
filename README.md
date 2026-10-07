# TUNING — Setup, Kalibrasi Gestur & Uji Akhir (Windows)

Panduan praktis untuk menjalankan dan menyetel game di perangkat nyata.
Semua ambang gestur ada di `python/config.py`; angka balancing game ada di `@export`
skrip Godot (bisa diubah lewat Inspector).

---

## 1. Setup (sekali)

```bat
:: Disarankan Python 3.10–3.12 (64-bit)
cd python
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python download_model.py        :: -> python\models\hand_landmarker.task
```

Jika unduhan gagal (proxy/firewall): unduh manual URL di `config.MODEL_URL` dan simpan
sebagai `python\models\hand_landmarker.task`.

Godot 4.3+ (versi standar, bukan .NET):
1. Godot → **Import** → pilih `godot\project.godot` → **Import & Edit** (membuat cache `.godot\`).
2. **F5** → Output harus berisi `[udp] listening on 127.0.0.1:4242`.

## 2. Urutan menjalankan game

1. Jalankan game di Godot (F5). HUD menampilkan **"Menunggu Python…"**.
2. Terminal (venv aktif): `cd python` lalu `python main.py`
   (opsi: `--no-window`, `--port 4243`, `--host 127.0.0.1`).
3. HUD berubah menjadi **"Gestur aktif"** (heartbeat tiap 0,5 s).
4. Jendela preview kecil: `s` = mirror ON/OFF (label otomatis dikoreksi), `h` = tukar
   label Kiri/Kanan manual, `q`/ESC = keluar. Tombol hanya berlaku bila jendela preview fokus.

Tanpa webcam, uji Godot saja: tombol `1`–`4`, atau `python godot\tools\udp_test_send.py fire --count 2 --interval 0.2`.

## 3. Melihat metrik gestur: `main_gestures.py`

```bat
python main_gestures.py
```
Overlay menampilkan:

| Baris | Arti | Bandingkan dengan |
|-------|------|-------------------|
| `cam FPS / det FPS` | FPS kamera / deteksi MediaPipe | target > 25 |
| `L: … R: …` | pose stabil tiap tangan (`FIST`/`OPEN`/`TWO`/`-`) dan sisa `lock` | — |
| `fire growth x/0.25 chest …` | pembesaran tangan kanan dalam 150 ms | `FIRE_GROWTH_MIN` |
| `water gL gR /0.2` | pembesaran tiap tangan dalam 200 ms | `WATER_GROWTH_MIN` |
| `light down v/4.0 travel t/0.8` | kecepatan & jarak turun (satuan = ukuran tangan) | `LIGHTNING_MIN_VEL`, `LIGHTNING_MIN_TRAVEL` |
| `earth drift / dscale / zone` + bar | kestabilan telapak kiri, di zona atau tidak, progres tahan 1 s | `EARTH_MAX_DRIFT`, `EARTH_MAX_SCALE_CHANGE` |

Kotak hijau tipis = zona Tanah. Saat gestur terdeteksi, nama skill berkedip besar dan
`[event] …` tercetak di konsol. **Cara menyetel:** lakukan gestur 5–10 kali, catat nilai
puncak metrik saat gestur yang *dimaksud* dan saat gerakan biasa, lalu letakkan ambang
di antaranya (lebih dekat ke nilai gerakan biasa bila sering gagal, lebih dekat ke nilai
gestur bila sering salah picu).

### Rekam & putar ulang
- Di `main_gestures.py` tekan `r` untuk mulai/berhenti merekam → `python\recordings\rec_YYYYmmdd_HHMMSS.jsonl`.
- Ubah `config.py`, lalu uji ulang tanpa kamera:
  ```bat
  python replay.py recordings\rec_20261007_153000.jsonl
  ```
  Output: daftar event (`[ ms ] skill conf`) + jumlah per skill. Rekam satu file per gestur
  (mis. 20× Api) dan satu file "gerakan bebas" (ngobrol, melambai, garuk kepala) untuk
  menghitung false positive.
- Catatan: perekam hanya menyimpan sampel terbaru per update; bila det FPS tinggi/tersendat
  hasil replay bisa sedikit berbeda dari live. Selalu konfirmasi ulang secara live.

## 4. Ambang gestur (`python/config.py`)

Satuan: *size* = jarak pergelangan→pangkal jari tengah (piksel); *growth* = size_sekarang/size_dulu − 1;
y ternormalisasi (0 = atas frame, 1 = bawah).

| Nama | Default | Terlalu TINGGI → | Terlalu RENDAH → | Arah penyesuaian |
|------|---------|------------------|------------------|------------------|
| `POSE_STABLE_SAMPLES` | 3 | gestur cepat (tebasan) gagal karena pose belum "stabil" | glitch 1 frame memicu skill | turunkan ke 2 bila Petir sering gagal |
| `FINGER_EXTENDED_RATIO` | 1.15 | telapak/dua-jari tidak dikenali (pose `-`) | jari setengah tekuk dianggap lurus | turunkan 0.05 bila `OPEN`/`TWO` sulit muncul |
| `FINGER_FOLDED_RATIO` | 1.0 | jari setengah terbuka dianggap tertekuk (kepalan longgar) | kepalan tidak dikenali (`FIST` jarang) | naikkan 0.05 bila `FIST` sulit muncul |
| `HAND_SIZE_MODE` | `"2d"` | — | — | coba `"3d"` bila Api/Air gagal saat tangan miring |
| `WINDOW_MIN_COVERAGE` | 0.6 | metrik sering kosong saat FPS rendah | metrik dihitung dari jendela terlalu pendek (noise) | turunkan ke 0.5 bila det FPS < 20 |
| `CONF_SATURATION_RATIO` | 2.0 | — (hanya nilai `conf`, informatif) | — | biarkan |
| `FIRE_CHEST_MIN_Y` | 0.35 | pukulan dari dada tidak terdeteksi (kamera rendah) | pukulan dari depan wajah ikut terhitung | sesuaikan dengan posisi kamera; `None` = mati |
| `FIRE_LOOKBACK_MS` | 150 | dorongan lambat ikut terhitung | dorongan cepat terpotong (growth kecil) | 120–200 |
| `FIRE_GROWTH_MIN` | 0.25 | Api sulit keluar | maju-mundur kecil memicu Api | lihat `growth` puncak; set ±70 % nilai pukulan |
| `FIRE_REARM_GROWTH` | 0.08 | Api ganda dari satu pukulan panjang | Api kedua perlu jeda lama | jarang perlu diubah |
| `WATER_LOOKBACK_MS` | 200 | dorongan lambat ikut terhitung | dorongan terpotong | 150–250 |
| `WATER_GROWTH_MIN` | 0.20 | Air sulit keluar | condong ke kamera memicu Air | ±70 % nilai `gL/gR` puncak |
| `WATER_REARM_GROWTH` | 0.08 | Air ganda | Air kedua perlu jeda | jarang diubah |
| `WATER_SYNC_MS` | 200 | dua tangan tidak serempak tetap lolos | dorongan sedikit tidak serempak gagal | naikkan ke 250–300 bila sering gagal |
| `LIGHTNING_LOOKBACK_MS` | 250 | tebasan lambat lolos | tebasan panjang terpotong | 200–300 |
| `LIGHTNING_MIN_VEL` | 4.0 | Petir sulit keluar | menurunkan tangan biasa memicu Petir | ±70 % nilai `down` puncak |
| `LIGHTNING_MIN_TRAVEL` | 0.8 | butuh tebasan sangat panjang | gerak turun pendek memicu | 0.6–1.2 |
| `LIGHTNING_REARM_RATIO` | 0.5 | Petir kedua sulit keluar setelah tebasan pertama | satu tebasan memicu dua kali | Petir siap lagi setelah kecepatan turun < rasio × `LIGHTNING_MIN_VEL` |
| `EARTH_STILL_WINDOW_MS` | 300 | lebih ketat terhadap gerak lambat | lebih toleran | biarkan |
| `EARTH_STILL_MIN_SPAN_MS` | 150 | penilaian diam terlambat | penilaian diam dari data sedikit | biarkan |
| `EARTH_MAX_DRIFT` | 0.25 | tangan yang bergerak pelan dianggap diam | tangan gemetar tidak pernah "diam" | naikkan ke 0.35 bila bar progres sering reset |
| `EARTH_MAX_SCALE_CHANGE` | 0.10 | maju-mundur dianggap diam | jitter ukuran me-reset hold | naikkan ke 0.15 bila perlu |
| `EARTH_HOLD_MS` | 1000 | Tanah terasa lambat | Tanah terpicu tak sengaja | spesifikasi: 1000; naikkan bila sering salah picu |
| `EARTH_GAP_TOLERANCE_MS` | 150 | pose rusak sebentar tetap dianggap tahan | kedip deteksi 1–2 frame me-reset hold | naikkan ke 200 bila det FPS rendah |
| `EARTH_ZONE_X` | (0.2, 0.8) | (lebar) telapak di tepi ikut terhitung | harus tepat di tengah | sempitkan bila salah picu |
| `EARTH_ZONE_MAX_Y` | 0.65 | telapak rendah (perut) ikut terhitung | harus diangkat tinggi | turunkan ke 0.5 untuk mengurangi salah picu |
| `GLOBAL_LOCK_MS` | 350 | kombinasi cepat 2 skill hilang | satu gerakan memicu 2 skill | 250–400 |

### Kemudi (`# --- Steering` di `config.py`)

Kedua telapak terbuka digeser bersama ke kiri/kanan dari tengah frame. *offset* = rata-rata
x pusat telapak kedua tangan − 0,5 (dibalik saat mirror OFF agar arah = arah fisik pemain).
Baca baris `steer … raw … off … <reason> g …` dan bar di bawah layar `main_gestures.py`.

| Nama | Default | Terlalu TINGGI → | Terlalu RENDAH → | Arah penyesuaian |
|------|---------|------------------|------------------|------------------|
| `STEER_DEADZONE` | 0.08 | harus menggeser jauh sebelum mulai berputar; terasa "mati" di tengah | karakter berputar pelan sendiri saat tangan sedikit miring dari tengah | lihat `off` saat tangan "di tengah"; set sedikit di atas nilai itu |
| `STEER_FULL_OFFSET` | 0.30 | putaran penuh butuh tangan sampai tepi frame (tangan keluar frame) | terlalu sensitif, cepat mentok kecepatan maksimum | turunkan bila lengan pemain pendek/kamera dekat |
| `STEER_EXPONENT` | 1.0 | sulit berputar pelan lalu tiba-tiba cepat di tepi | sulit membidik halus dekat tengah | 1.5–2.0 bila perlu kontrol halus saat membidik |
| `STEER_SMOOTHING` | 0.5 | gemetar/jitter ikut terasa sebagai goyangan kamera | putaran terasa lambat merespons / "licin" | 0.3–0.6; turunkan bila kamera goyang |
| `STEER_SNAP_ZERO` | 0.02 | berhenti terasa memotong | sisa putaran sangat pelan lama sekali | jarang perlu diubah |
| `STEER_LOOKBACK_MS` | 150 | condong lambat tetap terdeteksi `pushing` (bagus) tapi jeda deteksi dorongan lebih lama | jitter ukuran tangan memicu `pushing` | 120–200 |
| `STEER_MAX_GROWTH` | 0.08 | dorongan pelan/condong tetap memutar karakter saat merapal Air | jitter ukuran tangan sering memutus kemudi (`pushing` berkedip) | lihat `g` saat tangan diam; set ±2× nilai jitter, tetap < `WATER_GROWTH_MIN` |
| `STEER_SUPPRESS_AFTER_WATER_MS` | 500 | kemudi terlalu lama "mati" setelah Air | karakter berputar saat tangan ditarik kembali setelah Air | 300–700 |
| `STEER_HAND_LOST_MS` | 50 | karakter terus berputar sebentar setelah tangan hilang | kemudi putus-putus saat deteksi tangan berkedip | ≥ 1,5 × interval deteksi (≈100 bila det FPS < 20) |
| `STEER_POSE_GLITCH_SAMPLES` | 1 | menutup telapak tidak menghentikan putaran dengan cepat | salah klasifikasi pose 1 frame memutus kemudi | 0 = tanpa toleransi; 1 disarankan |
| `STEER_SEND_HZ` | 30 | paket UDP lebih banyak (tidak masalah di localhost) | putaran Godot tersendat | ≥ det FPS |
| `STEER_SEND_EPS` | 0.02 | perubahan kecil tertunda sampai keep-alive (≤ 0,1 s) | paket lebih banyak | jarang diubah |
| `STEER_KEEPALIVE_S` | 0.1 | **≥ 0,3 s → Godot menganggap 0 dan putaran tersendat** | paket lebih banyak | harus jauh < timeout steer Godot (0,3 s) |

Konflik dengan Air: kemudi hanya aktif saat jarak tangan ke kamera stabil
(`|growth| ≤ STEER_MAX_GROWTH` kedua tangan). Dorongan maju tetap memicu Air kapan saja;
kemudi = 0 selama dorongan dan `STEER_SUPPRESS_AFTER_WATER_MS` sesudah Air. Tanah tidak
terpicu saat menyetir karena telapak kanan terbuka (`EARTH_RIGHT_HAND = "not_open"`).

Terkait (bukan ambang gestur, tapi berpengaruh):

| Nama | Default | Catatan |
|------|---------|---------|
| `HISTORY_LEN` | 15 | harus mencakup ≥ 300 ms pada det FPS nyata (mis. 60 FPS → naikkan ke 25) |
| `HAND_STALE_MS` | 200 | tangan dianggap hilang setelah ini |
| `MIN_HAND_DETECTION/PRESENCE/TRACKING_CONFIDENCE` | 0.5 | naikkan (0.6–0.7) bila muncul tangan "hantu"; turunkan bila tangan sering hilang |
| `SEND_DEBOUNCE_MS` | 100 | hanya anti-banjir paket; cooldown asli ada di Godot |
| `HEARTBEAT_INTERVAL_S` | 0.5 | harus < `link_timeout_sec` Godot (1,5 s) |
| `CAMERA_STALE_S` | 1.0 | heartbeat berhenti bila kamera tidak mengirim frame selama ini, sehingga HUD menampilkan "Menunggu Python…" |

**Tanah vs. tangan kanan (`EARTH_RIGHT_HAND`, default `"not_open"`):** Tanah tidak terpicu
selama telapak **kanan** juga terbuka. Ini mencegah Tanah keluar saat kedua telapak
diangkat (bersiap atau menahan setelah Air), dan mencegah Air "tertelan". Tangan kanan
yang mengepal atau tidak terlihat tetap boleh.
- Bila Tanah masih keluar saat tangan kiri sekadar istirahat sambil meninju dengan kanan,
  pakai `"absent"`: tangan kanan harus di luar frame.
- `"any"` = perilaku lama.

## 5. Balancing Godot (`@export`, ubah lewat Inspector)

| File (node) | `@export` | Default |
|-------------|-----------|---------|
| `scripts/player.gd` (Player) | `fire_cooldown`, `water_cooldown`, `lightning_cooldown`, `earth_cooldown` | 1 / 3 / 2 / 6 s |
| | `max_hp` | 100 |
| | `link_timeout_sec` | 1.5 s |
| | `max_yaw_deg`, `max_pitch_deg`, `key_yaw_speed_deg`, `mouse_sensitivity` | 60°, 15°, 90°/s, 0.15 |
| | `listen_port`, `bind_address`, `debug_keys` | 4242, 127.0.0.1, true |
| `scripts/spell_caster.gd` (Player/SpellCaster) | `aim_cone_deg`, `aim_range`, `wall_distance`, `hand_offset` | 45°, 45 m, 3 m |
| `scripts/fireball.gd` | `speed`, `damage`, `hit_radius`, `max_distance`, `homing_turn_rate` | 30, 40, 0.35, 45 m, 4 rad/s |
| `scripts/water_wave.gd` | `speed`, `max_distance`, `damage`, `knockback_distance` | 18, 30 m, 25, 4 m (lebar: shape di `scenes/water_wave.tscn`) |
| `scripts/lightning.gd` | `primary_damage`, `chain_damage`, `chain_radius`, `max_chain` | 35, 25, 6 m, 2 |
| `scripts/earth_wall.gd` | `max_hp`, `lifetime`, `rise_time` | 120, 6 s, 0.35 s |
| `scripts/enemy.gd` | `damage`, `attack_interval`, `attack_range`; grup Brute: `brute_hp_mult`, `brute_speed_mult`, `brute_damage_mult` | 10, 1 s, 1.6 m; 2.5, 0.6, 1.5 |
| `scripts/wave_manager.gd` (WaveManager) | `base_count`, `per_wave`, `base_hp`, `hp_growth`, `base_speed`, `speed_per_wave`, `max_speed` | 4, 2, 50, 0.15, 2.2, 0.15, 5 |
| | `base_interval`, `interval_step`, `min_interval`, `first_spawn_delay`, `wave_delay`, `brute_from_wave` | 1.2, 0.05, 0.4, 0.5, 3 s, 3 |
| | `arc_half_angle_deg`, `min_radius`, `max_radius`, `rng_seed` | 70°, 24 m, 30 m, 0 |

Patokan: musuh wave 1 tiba ±10 s setelah spawn; 6 musuh × 10 dmg/s menghabiskan 100 HP
dalam beberapa detik bila tidak dilawan. Bila deteksi gestur di perangkat nyata masih
sering gagal, mulai dengan **menurunkan `base_speed` / menaikkan `max_hp`**, bukan
melonggarkan ambang gestur.

## 6. Checklist uji akhir di perangkat nyata

- [ ] `main_gestures.py`: cam FPS & det FPS > 25, `hands: 2` saat dua tangan di depan kamera.
- [ ] **Mirror ON** (default): tangan kanan fisik berlabel `Right`, kiri `Left`.
- [ ] Tekan `s` (**mirror OFF**): gambar terbalik, label tangan kanan fisik **tetap** `Right`.
- [ ] Bila label salah di kedua mode: tekan `h`; jika benar, set `SWAP_HANDEDNESS = True`.
- [ ] 20 percobaan per gestur (jeda > cooldown), isi tabel:

| Gestur | Hit / 20 | Salah skill | Catatan |
|--------|----------|-------------|---------|
| Api (kepalan kanan didorong) | | | |
| Air (dua telapak didorong) | | | |
| Petir (dua jari kanan ditebas turun) | | | |
| Tanah (telapak kiri diam 1 s, tengah-atas) | | | |

- [ ] False positive, 60 s tiap skenario (target 0 event): ngobrol + gerak tangan bebas,
      melambai, garuk kepala/minum, kedua tangan diam di pangkuan, **dua telapak terbuka diam**
      (di tengah frame: kemudi harus tetap 0, tidak ada Air/Tanah).
- [ ] Latensi: bandingkan `unix=` di `[cast] … sent (unix=…)` (Python) dengan
      `[udp] recv cast … unix=…` (Godot Output). Selisih di mesin yang sama biasanya hanya
      beberapa ms; catat juga jeda gerakan→efek yang dirasakan (target < ~200 ms).
- [ ] Cooldown: ulangi Api < 1 s → Godot mencetak `DITOLAK`, ikon bergoyang merah.
- [ ] Game over → tahan telapak kiri 1 s → game mulai lagi (tanpa ikut memunculkan dinding).
- [ ] Tutup `main.py` → HUD kembali "Menunggu Python…" dalam ±1,5 s.
- [ ] **Kemudi** (`main_gestures.py`, lalu game):
  - [ ] Dua telapak terbuka di tengah → `steer +0.00`, reason `deadzone`; karakter diam.
  - [ ] Geser kedua tangan ke **kanan tubuh** → bar ke kanan, nilai positif, karakter
        berputar ke kanan; makin jauh makin cepat. Ke kiri → sebaliknya.
  - [ ] Tekan `s` (mirror OFF) dan ulangi: arah putar **tetap** sama dengan arah fisik.
  - [ ] Kembali ke tengah → berhenti (< ±0,2 s). Turunkan satu tangan / kepalkan →
        berhenti (`no_hands` / `not_open`).
  - [ ] Sambil menyetir di samping, dorong kedua telapak ke kamera → Air keluar
        **sekali**, reason `pushing` lalu `suppressed`, karakter berhenti berputar ±0,5 s,
        lalu berputar lagi bila tangan tetap di samping.
  - [ ] Menyetir 10 s ke kiri-kanan → tidak ada Tanah/Api/Petir/Air yang tidak disengaja.
  - [ ] Tutup `main.py` saat sedang berputar → karakter berhenti (paket 0 atau timeout 0,3 s di Godot).
  - [ ] `python replay.py <rekaman>` → baris `steer aktif …%` masuk akal untuk rekaman itu.

## 7. Troubleshooting

| Gejala | Penyebab / solusi |
|--------|-------------------|
| `Cannot open camera (index=0, backend='dshow')` | Ubah `CAMERA_INDEX` (0, 1, 2…) atau `CAMERA_BACKEND` (`"dshow"` ↔ `"default"`) di `config.py`; tutup aplikasi lain yang memakai webcam (Zoom, Teams, browser). |
| Kamera terbuka tapi layar hitam / FPS rendah | Coba backend lain; kurangi `FRAME_WIDTH/HEIGHT`; nyalakan lampu ruangan. |
| `Model file not found` | Jalankan `python download_model.py` (atau unduh manual, lihat §1). |
| Godot: `gagal bind UDP 127.0.0.1:4242` | Port dipakai (biasanya instance Godot kedua). Tutup instance itu, atau cek `netstat -ano \| findstr 4242`. Bisa juga ganti `listen_port` di node Player **dan** jalankan `python main.py --port <sama>`. |
| HUD tetap "Menunggu Python…" | `main.py` belum jalan / port berbeda / firewall memblokir loopback UDP. Cek baris `[net] sending to 127.0.0.1:4242`. |
| HUD "Gestur aktif" tapi tidak ada cast | Heartbeat tetap terkirim walau kamera macet. Cek jendela preview `main.py` dan det FPS di `main_gestures.py`. |
| Godot: `Parse Error: Could not find type "Player"` | Proyek belum di-import: buka sekali di editor, atau `godot --headless --path godot --import`. |
| Label Kiri/Kanan terbalik | Tekan `h`; permanen: `SWAP_HANDEDNESS = True`. |
| Tanah keluar sendiri | Lihat "Salah picu yang diketahui" di §4. |
| `pip install mediapipe` gagal | Pakai Python 3.10–3.12 64-bit (`py -3.11`). |
