# Comp Vis Game — Godot 4 (Fase 3–5)

Game sihir *first-person wave survival*: pemain berdiri di tengah arena dan menembakkan
4 sihir lewat gestur tangan (Python + MediaPipe → UDP) atau tombol 1–4.
Fase 3 (protokol UDP) tetap didokumentasikan di [`README_phase3.md`](README_phase3.md)
(riwayat); spesifikasi paket: [`../python/PROTOCOL.md`](../python/PROTOCOL.md). Protokol tetap
`v:1`; tipe paket baru **`steer`** (kemudi) ditambahkan — lihat §2a.

```
webcam → python/main.py ──UDP 127.0.0.1:4242──▶ Player (player.gd) ──▶ SpellCaster ──▶ Fireball / WaterWave / LightningStrike / EarthWall
                                               cooldown otoritatif          aim assist
```

Visual seluruhnya bentuk primitif Godot (Capsule/Sphere/Box/Cylinder + StandardMaterial3D
emisi + CPUParticles3D); tidak ada aset eksternal. Mesh tiap objek ada di node anak
`Visual`, jadi mudah diganti model 3D nanti.

## 1. Membuka & menjalankan

1. Pasang **Godot 4.3** atau lebih baru (versi standar, bukan .NET).
2. Godot → **Import** → pilih `godot/project.godot` → **Import & Edit**.
   Langkah ini juga membuat folder `.godot/` (cache, termasuk daftar `class_name`).
3. **F5** (Run Project). Output: `[udp] listening on 127.0.0.1:4242` lalu
   `[wave] wave 1 mulai: 6 musuh ...`.

Menjalankan dari terminal tanpa pernah membuka editor: jalankan **sekali**
`godot --headless --path godot --import` dulu. Tanpa itu cache `class_name` belum ada
dan Godot mencetak `Parse Error: Could not find type "Player"` (perilaku standar Godot 4).

Untuk gestur sungguhan jalankan `python/main.py` (lihat README Python); tanpa webcam
gunakan `tools/udp_test_send.py` (contoh di README_phase3.md).

## 2. Kontrol

| Input | Fungsi |
|-------|--------|
| Gestur / `1` | Api — bola api cepat, homing ringan |
| Gestur / `2` | Air — water cannon lebar, menembus, knockback |
| Gestur / `3` | Petir — instan, berantai |
| Gestur / `4` | Tanah — dinding penahan di depan |
| Gestur kemudi (dua telapak terbuka digeser kiri/kanan) | Berputar ke kiri/kanan, makin jauh dari tengah makin cepat (maks 120°/s); putar penuh 360° |
| `←` / `→` | Putar pandangan (yaw) 90°/s, tanpa batas (360°) |
| **Tahan klik kanan** + gerak mouse | Yaw tanpa batas dan pitch ±15° (mouse tidak di-*capture*, jadi jendela webcam tetap bisa dipakai) |
| `R` | Mulai lagi (hanya saat Game Over) |
| Gestur Tanah (telapak kiri) saat Game Over | Mulai lagi |

Tombol 1–4 bisa dimatikan dengan `debug_keys = false` pada node `Player`.

**Aim assist.** Gestur tidak bisa membidik, jadi sihir menarget **musuh hidup terdekat**
dalam kerucut ±45° (horizontal) dari arah pandang kamera **saat ini**, jangkauan 45 m.
Jika tidak ada, sihir meluncur lurus ke depan. Karena musuh datang dari segala arah,
pemain harus berputar (kemudi) menghadap musuh; dinding Tanah juga muncul di arah pandang saat ini.

### 2a. Kemudi (berganti arah)

Python mengirim paket `{"v":1,"type":"steer","sid":"…","seq":N,"value":-0.62}`:
`value` −1..1 (negatif = kiri, positif = kanan dari sudut pandang pemain), `seq` memakai
counter yang sama dengan `cast`/`hb` (dedupe `sid/seq` berlaku), ±30 Hz selama nilai ≠ 0
lalu satu kali `0` saat berhenti. Saat Air dirapal, Python sendiri menahan kemudi ke 0.

| Hal | Nilai | Diatur di |
|-----|-------|-----------|
| Laju putar | `value × 120°/s` (value 1 → 120°/s, 0,5 → 60°/s) | `Player.max_turn_speed_deg` |
| Timeout | tanpa paket `steer` selama 0,3 s (waktu game) → kemudi 0 | `Player.steer_timeout_sec` |
| Batas yaw | 0 = tanpa batas (360°, yaw dibungkus ke −180..180); > 0 = dibatasi ±nilai (perilaku lama: 60) | `Player.yaw_limit_deg` |

- `value` bukan angka / NaN / ±inf → paket diabaikan dengan peringatan; di luar −1..1 → di-*clamp*.
- Paket `steer` juga menandakan link hidup (seperti `hb`), tidak terpengaruh cooldown.
- Saat game over kemudi diabaikan dan di-nol-kan; restart juga me-nol-kan kemudi dan arah pandang.
- Konsol mencetak `[steer] mulai +1.00 yaw=… heading=…`, `[steer] berhenti yaw=… heading=…`,
  atau `[steer] timeout …`. `heading` = derajat searah jarum jam dari −Z (0 = arah awal, 90 = kanan/+X);
  `yaw` = `Camera3D.rotation.y` dalam derajat (konvensi Godot, positif = kiri).
- HUD: bar **Kemudi** kecil di atas ikon sihir (tengah = 0, mengisi ke kiri/kanan; teks redup saat 0),
  dan **panah merah** di tepi layar untuk tiap musuh yang tidak terlihat kamera (maks 16, yang terdekat;
  makin dekat makin terang/besar). Panah di bawah = musuh di belakang.

Uji tanpa webcam (game berjalan, terminal lain):

```bash
python tools/udp_test_send.py steer 1 --duration 1           # kanan penuh 1 s (30 Hz) lalu satu 0 → +120°
python tools/udp_test_send.py steer -0.5 --duration 2 --hz 30 # kiri setengah laju 2 s → −120°
python tools/udp_test_send.py steer 0.8 --junk               # plus paket rusak (harus hanya peringatan)
```

## 3. Aturan permainan (angka default)

| Hal | Nilai | Diatur di |
|-----|-------|-----------|
| HP pemain | 100 | `Player.max_hp` (`scripts/player.gd`) |
| Cooldown api/air/petir/tanah | 1 / 3 / 2 / 6 s | `Player.*_cooldown` |
| Api | speed 30, damage 40, single target, homing 4 rad/s, jangkauan 45 m | `scripts/fireball.gd` |
| Air | speed 18, jangkauan 30 m, kotak 2,5 × 1,8 × 1,2 m, damage 25 per musuh (sekali), knockback 4 m menjauhi pemain | `scripts/water_wave.gd` (+ ukuran shape di `scenes/water_wave.tscn`) |
| Petir | target 35, lalu berantai ke maks 2 musuh (tiap lompatan: musuh terdekat yang belum kena dalam 6 m dari musuh sebelumnya) damage 25 | `scripts/lightning.gd` |
| Tanah | 3 m di depan arah pandang, 6 × 2,5 m, HP 120, umur 6 s, naik dari tanah 0,35 s; cast baru menggantikan dinding lama | `scripts/earth_wall.gd`, jarak di `scripts/spell_caster.gd` (`wall_distance`) |
| Aim assist | kerucut ±45°, 45 m | `scripts/spell_caster.gd` (`aim_cone_deg`, `aim_range`) |
| Musuh | damage 10, interval 1 s, jangkauan serang 1,6 m | `scripts/enemy.gd` |
| Brute (mulai wave 3, 1 per wave = musuh terakhir) | HP ×2,5, speed ×0,6, damage ×1,5, ukuran ×1,45 | `scripts/enemy.gd` grup *Brute* |
| Wave n | jumlah `4 + 2n`, HP `50·(1 + 0,15·(n−1))`, speed `min(2,2 + 0,15n, 5)`, interval spawn `max(1,2 − 0,05n, 0,4)` s, jeda antar wave 3 s | `scripts/wave_manager.gd` |
| Area spawn | **sekeliling 360°** di sekitar posisi awal pemain, radius 24–30 m (`spawn_arc_deg` < 360 = busur berpusat di −Z; 140 = perilaku lama ±70°) | `WaveManager.spawn_arc_deg`, `min_radius`, `max_radius` |
| Kemudi | maks 120°/s, timeout 0,3 s, tanpa batas yaw | `Player.max_turn_speed_deg`, `steer_timeout_sec`, `yaw_limit_deg` |

Semua angka di atas adalah `@export`, jadi bisa juga diubah dari Inspector
(node `Player`, `Player/SpellCaster`, `WaveManager`, atau dengan membuka scene spell).

Musuh yang menabrak dinding Tanah berhenti dan menyerang dinding (10/s); setelah
dinding hancur/habis umurnya, musuh lanjut berjalan. Sihir **menembus** dinding sendiri.

## 4. Layer fisik

Nama layer ada di `project.godot` (`[layer_names]`).

| Layer | Nama | Dipakai oleh | Mask |
|-------|------|--------------|------|
| 1 | `world` | lantai, pilar (`StaticBody3D`) | – |
| 2 | `player` | dicadangkan (pemain tidak punya body; musuh memakai jarak) | – |
| 3 | `enemies` | `Enemy` (`CharacterBody3D`, *floating*) | world + enemies + shield (= 13) |
| 4 | `shield` | `EarthWall` (`StaticBody3D`, grup `shield`) | – |
| 5 | `spells` | `WaterWave` (`Area3D`) | enemies (= 4) |

Bola api tidak memakai body: tiap physics step ia menyapu segmen geraknya terhadap
musuh di grup `enemies` (tidak bisa "menembus" musuh walau cepat) dan memakai raycast
ke layer `world` untuk pilar/lantai.

## 5. Struktur

```
scenes/main.tscn           Main (GameManager)
├─ WorldEnvironment, Sun   langit prosedural senja + kabut + glow
├─ Arena                   Floor (lantai + piringan arena + lingkaran sihir), Pillars (instance pillar.tscn), Rocks
├─ Player (player.gd)      UDP + cooldown + HP + look
│  ├─ Camera3D             y = 1,6 m
│  └─ SpellCaster          membuat efek sihir (aim assist)
├─ Enemies                 induk musuh
├─ Projectiles             induk bola api, gelombang air, petir, dinding tanah
├─ WaveManager             spawn & wave
└─ HUD (hud.tscn)          CanvasLayer
scenes/enemy.tscn, fireball.tscn, water_wave.tscn, earth_wall.tscn, pillar.tscn, skill_icon.tscn, hud.tscn
```

| Skrip | `class_name` | Isi |
|-------|--------------|-----|
| `player.gd` | `Player` | UDP (Fase 3 + paket `steer`), cooldown, HP, kamera + kemudi, `cast_*` → SpellCaster |
| `spell_caster.gd` | `SpellCaster` | instansiasi spell, posisi tangan, aim assist, satu dinding aktif |
| `aim.gd` | `Aim` | helper statis aim assist / musuh terdekat |
| `fireball.gd`, `water_wave.gd`, `lightning.gd`, `earth_wall.gd` | `Fireball`, `WaterWave`, `LightningStrike`, `EarthWall` | logika & angka tiap sihir |
| `enemy.gd` | `Enemy` | gerak, serang pemain/dinding, damage flash, knockback, mati |
| `wave_manager.gd` | `WaveManager` | rumus wave, spawn bertahap, jeda 3 s |
| `game_manager.gd` | `GameManager` | wiring, game over, restart |
| `hud.gd`, `skill_icon.gd` | `Hud`, `SkillIcon` | HUD |
| `fx.gd` | `Fx` | material & partikel ledakan sederhana |

### Alur sinyal

- `Player.skill_cast / skill_rejected / cooldown_changed` → `Hud` (pulse ikon / goyang merah / overlay cooldown).
- `Player.gesture_link_changed` → `Hud` ("Gestur aktif" hijau / "Menunggu Python…" abu).
- `Player.steer_changed(value)` → `Hud` (bar kemudi). Panah musuh di luar layar dihitung `Hud`
  tiap frame dari grup `enemies` + kamera pemain (`Camera3D.is_position_in_frustum`).
- `Player.hp_changed` → `Hud` (bar + angka + vignette merah saat HP turun).
- `Player.died` → `GameManager` → game over: `WaveManager.stop()`, overlay, `casting_enabled = false`
  (try_cast tidak mengeksekusi apa pun).
- `Player.gesture_received(skill)` — dipancarkan untuk tiap paket cast UDP yang **valid**
  (setelah validasi + dedupe, **sebelum** cek cooldown). Saat game over dan skill = `earth`,
  `GameManager` memanggil restart secara *deferred*, sehingga paket yang sama tidak ikut
  memunculkan dinding.
- `WaveManager.wave_started / enemies_remaining_changed` → `Hud` (label + banner "Wave N").
- `Enemy.died` → `WaveManager` (hitung sisa; jeda 3 s → wave berikutnya).

**Restart** tidak me-*reload* scene: musuh/proyektil/dinding dihapus, HP & cooldown
di-reset, wave 1 dimulai lagi. Socket UDP (dan tabel dedupe `sid/seq`) tetap utuh.

## 6. Smoke test otomatis

```bash
godot --headless --path godot --import                       # sekali (atau buka di editor)
godot --headless --path godot -s res://tests/smoke_test.gd   # exit code 0 = lulus
```

`tests/smoke_test.gd` memuat `main.tscn`, memakai port UDP acak 47000–48499 (tidak
bentrok dengan game di 4242), mempercepat waktu 4× (`Engine.time_scale` + physics
240 Hz, jadi tiap physics step tetap 1/60 s waktu game) dan menguji: spawn 360° & radius,
musuh dari 18 arah tidak tersangkut pilar,
gerak musuh, api (+cooldown menolak cast ke-2), air (tembus + knockback), petir (chain
maks 2, musuh >6 m aman), tanah (menahan musuh, HP dinding turun, hilang setelah 6 s),
serangan musuh 10/s + HUD, wave 2 = 8 musuh setelah jeda 3 s, varian brute,
game over + tombol R, restart lewat paket UDP `earth` asli, overlay cooldown HUD, dan
indikator link, serta kemudi (kasus 12: arah & laju paket `steer` lewat UDP asli, timeout,
putaran >360°, aim assist & dinding Tanah setelah berbalik, game over/restart, panah musuh
di luar layar, nilai tidak valid, `yaw_limit_deg`). Durasi ±20 s. Tiap kasus mencetak `PASS ...` / `FAIL ...: alasan`;
akhir: `RESULT: N PASS, M FAIL`.

Catatan: jangan biarkan folder `.godot/` hasil import masuk ke git (cache lokal).

## 7. Batasan / catatan

- Diuji otomatis di Godot 4.3 **headless** (Linux). Tampilan GPU (warna, glow, kabut,
  partikel), editor GUI, dan Windows belum diuji di mesin nyata.
- Arena datar: musuh tidak memakai gravitasi (y selalu 0, `motion_mode` *floating*).
  Musuh boleh saling dorong. Karena musuh datang dari segala arah, semua pilar kini berada di
  cincin luar (r ≈ 33–34 m, tiap 40°) di luar radius spawn 24–30 m, dan batu dekorasi (tanpa
  collision) dipindah ke luar arena, sehingga tidak ada penghalang di jalur musuh.
- `conf` dari Python masih hanya dicetak.
- Renderer headless (dummy) Godot 4.3 mencetak `Parameter "m" is null` bila instance
  dengan `material_override` dibebaskan setelah mesh-nya; karena itu `Enemy`/`EarthWall`/
  `LightningStrike` melepas override di `_exit_tree()` dan petir memakai satu mesh silinder bersama.
