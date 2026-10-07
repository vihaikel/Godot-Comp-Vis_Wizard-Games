extends SceneTree
## Headless smoke test for phases 4-5 (+ part of 6) and steering (case 12).
## Run (after one `--import` so the global class cache exists):
##   godot --headless --path <project> -s res://tests/smoke_test.gd
## Prints "PASS <case>" / "FAIL <case>: <reason>" and exits 0 when all pass, 1 otherwise.
##
## Time: Engine.time_scale = TIME_SCALE and physics ticks = 60 * TIME_SCALE, so every
## physics step is still 1/60 s of game time (same collision behaviour as normal play)
## while the game runs TIME_SCALE x faster than real time. _sim(t) advances t seconds
## of GAME time by awaiting t * 60 physics frames.

const TIME_SCALE: float = 4.0
const WATCHDOG_REAL_SEC: float = 120.0
## Number of _check() calls in a complete run. A SCRIPT ERROR inside a case aborts
## that case silently, so a lower count means FAIL.
const EXPECTED_CHECKS: int = 61

var _main: GameManager
var _player: Player
var _wm: WaveManager
var _hud: Hud
var _caster: SpellCaster
var _proj: Node3D
var _udp_port: int = 0
var _udp_out := PacketPeerUDP.new()
var _udp_sid: String = ""
var _udp_seq: int = 0

var _passed: int = 0
var _failed: int = 0
var _spawned: Array[Dictionary] = []  # {enemy, pos}
var _rejected: Array[String] = []
var _cast_log: Array[String] = []


func _initialize() -> void:
	create_timer(WATCHDOG_REAL_SEC, true, false, true).timeout.connect(_on_watchdog)
	_run()


func _on_watchdog() -> void:
	print("FAIL watchdog: tes melebihi %.0f s waktu nyata" % WATCHDOG_REAL_SEC)
	quit(1)


# ------------------------------------------------------------------ helpers
func _check(case_name: String, ok: bool, reason: String) -> bool:
	if ok:
		_passed += 1
		print("PASS %s" % case_name)
	else:
		_failed += 1
		print("FAIL %s: %s" % [case_name, reason])
	return ok


func _sim(game_seconds: float) -> void:
	var steps: int = ceili(game_seconds * 60.0 - 0.0001)
	for i: int in steps:
		await physics_frame


func _frames(n: int) -> void:
	for i: int in n:
		await process_frame


## Waits REAL time (for the UDP link timeout, which uses Time.get_ticks_msec()).
func _wait_real_until(cond: Callable, timeout_sec: float) -> bool:
	var deadline: int = Time.get_ticks_msec() + int(timeout_sec * 1000.0)
	while Time.get_ticks_msec() < deadline:
		if cond.call():
			return true
		await process_frame
	return cond.call()


## HP of an enemy, or -1 if it was freed (killed) - avoids script errors in checks.
func _hp(e: Variant) -> float:
	return (e as Enemy).hp if is_instance_valid(e) else -1.0


func _spawn(pos: Vector3, hp: float = 100.0, speed: float = 0.0) -> Enemy:
	return _wm.spawn_enemy_at(pos, hp, speed)


func _isolate() -> void:
	_wm.stop()
	_wm.clear_enemies()
	for child: Node in _proj.get_children():
		child.queue_free()
	await _frames(2)
	await physics_frame


func _dist(e: Node3D) -> float:
	var v: Vector3 = e.global_position - _player.global_position
	v.y = 0.0
	return v.length()


func _children_with_script(parent: Node, script_file: String) -> Array[Node]:
	var out: Array[Node] = []
	for c: Node in parent.get_children():
		var s: Script = c.get_script()
		if s != null and s.resource_path.ends_with(script_file) and not c.is_queued_for_deletion():
			out.append(c)
	return out


func _send_raw(text: String) -> void:
	_udp_out.put_packet(text.to_utf8_buffer())


## Sends steer `value` at 30 packets per GAME second for `game_seconds`.
func _steer_stream(value: float, game_seconds: float) -> void:
	var n: int = maxi(1, roundi(game_seconds * 30.0))
	for i: int in n:
		_send({"type": "steer", "value": value})
		await _sim(1.0 / 30.0)


## Sends one steer 0 and waits until the player has applied it.
func _steer_stop() -> bool:
	_send({"type": "steer", "value": 0})
	return await _wait_real_until(func() -> bool: return _player.get_steer_value() == 0.0, 1.0)


## Signed smallest difference b - a in degrees, (-180, 180].
func _ang_diff(a: float, b: float) -> float:
	return wrapf(b - a, -180.0, 180.0)


func _forward() -> Vector3:
	return Aim.flat(_caster.get_view_forward())


func _send(body: Dictionary) -> void:
	_udp_seq += 1
	var msg: Dictionary = {"v": 1, "sid": _udp_sid, "seq": _udp_seq}
	msg.merge(body)
	var err: Error = _udp_out.put_packet(JSON.stringify(msg).to_utf8_buffer())
	if err != OK:
		print("  (put_packet error %s)" % error_string(err))


# ------------------------------------------------------------------ main
func _run() -> void:
	Engine.time_scale = TIME_SCALE
	Engine.physics_ticks_per_second = int(60.0 * TIME_SCALE)
	Engine.max_physics_steps_per_frame = 32

	var scene: PackedScene = load("res://scenes/main.tscn")
	_main = scene.instantiate() as GameManager
	_player = _main.get_node("Player") as Player
	_wm = _main.get_node("WaveManager") as WaveManager
	_udp_port = 47000 + randi() % 1500
	_player.listen_port = _udp_port  # avoid clashing with a real game on 4242
	_wm.enemy_spawned.connect(func(e: Enemy) -> void: _spawned.append({"enemy": e, "pos": e.global_position}))
	root.add_child(_main)
	await _frames(2)
	_hud = _main.get_node("HUD") as Hud
	_caster = _player.get_node("SpellCaster") as SpellCaster
	_proj = _main.get_node("Projectiles") as Node3D
	_player.skill_rejected.connect(func(s: String, _r: float) -> void: _rejected.append(s))
	_player.skill_cast.connect(func(s: String) -> void: _cast_log.append(s))
	_udp_sid = "smoke%04d" % (randi() % 10000)
	_udp_out.set_dest_address("127.0.0.1", _udp_port)
	print("info: udp port %d, physics delta %.5f s (game time per step)" % [_udp_port, _main.get_physics_process_delta_time()])

	await _t1_load_and_spawn()
	await _t2_enemies_approach()
	await _t3_fire()
	await _t4_water()
	await _t5_lightning()
	await _t6_earth()
	await _t7_enemy_hits_player()
	await _t8_next_wave()
	await _t9_game_over_and_r()
	await _t10_udp_restart()
	await _t11_hud_cooldown_and_link()
	await _t12_steering()

	var ran: int = _passed + _failed
	_check("0 semua kasus dijalankan sampai selesai", ran == EXPECTED_CHECKS,
			"hanya %d dari %d cek yang berjalan (ada SCRIPT ERROR?)" % [ran, EXPECTED_CHECKS])
	print("RESULT: %d PASS, %d FAIL" % [_passed, _failed])
	_main.queue_free()
	await _frames(3)
	quit(0 if _failed == 0 else 1)


# 1. Scene loads, HUD present, HP 100, wave 1 starts, spawns in arc +-70 deg, r 24-30.
func _t1_load_and_spawn() -> void:
	var ok: bool = _hud != null and _hud.is_inside_tree() and _hud.get_icon("fire") != null \
			and _hud.get_icon("earth") != null
	_check("1a scene+HUD termuat", ok, "HUD/ikon tidak ditemukan")
	_check("1b HP awal 100", is_equal_approx(_player.hp, 100.0) and _hud.get_hp_text() == "HP 100 / 100",
			"hp=%s hud='%s'" % [_player.hp, _hud.get_hp_text()])
	_check("1c wave 1 mulai", _wm.wave == 1 and _wm.get_wave_total() == 6 and _hud.get_wave_text() == "Wave 1",
			"wave=%d total=%d hud='%s'" % [_wm.wave, _wm.get_wave_total(), _hud.get_wave_text()])
	_check("1d socket UDP bound", _player.is_udp_bound(), "tidak bound")
	await _sim(4.0)
	var bad: Array[String] = []
	for rec: Dictionary in _spawned:
		var p: Vector3 = rec["pos"]
		var r: float = Vector2(p.x, p.z).length()
		if r < 23.999 or r > 30.001:
			bad.append("(r %.2f)" % r)
	# Spawn area itself: sample the spawn function many times (spawn_arc_deg = 360).
	var quadrants: Array[int] = [0, 0, 0, 0]  # front, right, back, left (90 deg each)
	var behind: int = 0
	for i: int in 400:
		var q: Vector3 = _wm.random_spawn_position()
		var ang: float = rad_to_deg(atan2(q.x, -q.z))  # 0 = -Z, positive = towards +X
		var rq: float = Vector2(q.x, q.z).length()
		if rq < 23.999 or rq > 30.001:
			bad.append("(sampel r %.2f)" % rq)
		if absf(ang) > 90.0:
			behind += 1
		quadrants[int(fposmod(ang + 45.0, 360.0) / 90.0) % 4] += 1
	_check("1e musuh spawn r 24–30, sekeliling 360° (ada di belakang |sudut|>90°)",
			_wm.spawn_arc_deg == 360.0 and _spawned.size() >= 3 and bad.is_empty() and behind > 100
			and quadrants.min() > 60,
			"arc=%.0f spawned=%d di luar=%s belakang=%d/400 kuadran=%s" % [_wm.spawn_arc_deg, _spawned.size(), str(bad), behind, str(quadrants)])
	print("  info: %d musuh spawn dalam 4 s; sampel 400: belakang=%d, kuadran depan/kanan/belakang/kiri=%s" % [_spawned.size(), behind, str(quadrants)])
	await _t1f_no_obstacles()


# 1f. Enemies from every direction (every 20 deg, incl. where the old inner pillars
#     stood) walk from r = 30 to the player without getting stuck on arena props.
func _t1f_no_obstacles() -> void:
	var saved_spawned: int = _spawned.size()
	await _isolate()
	_player.hp = 1000000.0  # survive the crowd
	var list: Array[Enemy] = []
	var min_d: Array[float] = []
	for i: int in 18:
		var a: float = deg_to_rad(20.0 * i)
		list.append(_spawn(Vector3(sin(a), 0.0, -cos(a)) * 30.0, 1000.0, 5.0))
		min_d.append(30.0)
	for step: int in 7 * 60:  # 7 s of game time
		await physics_frame
		for i: int in list.size():
			if is_instance_valid(list[i]):
				min_d[i] = minf(min_d[i], _dist(list[i]))
	var stuck: Array[String] = []
	for i: int in list.size():
		if min_d[i] > 4.0:
			stuck.append("%d°: %.1f m" % [20 * i, min_d[i]])
	_check("1f musuh dari 18 arah (tiap 20°) mencapai pemain, tidak tersangkut pilar", stuck.is_empty(),
			"tersangkut: %s" % str(stuck))
	print("  info: jarak minimum terjauh %.2f m" % min_d.max())
	await _isolate()
	_player.reset_state()
	_spawned.resize(saved_spawned)  # keep test 2 working on the wave enemies
	_wm.start_game()
	await _sim(3.0)


# 2. Enemies walk toward the player.
func _t2_enemies_approach() -> void:
	var e: Enemy = null
	for rec: Dictionary in _spawned:
		if is_instance_valid(rec["enemy"]):
			e = rec["enemy"]
			break
	if not _check("2a ada musuh hidup", e != null, "tidak ada musuh"):
		return
	var d0: float = _dist(e)
	await _sim(1.5)
	var d1: float = _dist(e)
	_check("2b musuh mendekat", d0 - d1 > 2.5, "jarak %.2f -> %.2f (speed %.2f)" % [d0, d1, e.speed])
	print("  info: jarak %.2f -> %.2f m dalam 1.5 s" % [d0, d1])
	await _isolate()


# 3. Fire: projectile appears, hits enemy in front (-40), second cast rejected.
func _t3_fire() -> void:
	var e: Enemy = _spawn(Vector3(0, 0, -10))
	await physics_frame
	_rejected.clear()
	var first: bool = _player.try_cast("fire")
	var balls: Array[Node] = _children_with_script(_proj, "fireball.gd")
	_check("3a cast fire -> proyektil muncul", first and balls.size() == 1, "cast=%s fireballs=%d" % [first, balls.size()])
	var second: bool = _player.try_cast("fire")
	_check("3b cast fire kedua DITOLAK (cooldown)", not second and _rejected.has("fire")
			and _children_with_script(_proj, "fireball.gd").size() == 1,
			"second=%s rejected=%s" % [second, str(_rejected)])
	await _sim(0.8)
	_check("3c musuh kena 40 damage", is_equal_approx(_hp(e), 60.0), "hp=%.1f" % _hp(e))
	_check("3d proyektil hilang setelah kena", _children_with_script(_proj, "fireball.gd").is_empty(), "masih ada fireball")
	await _isolate()


# 4. Water: two enemies in a row both take 25 and are pushed away.
func _t4_water() -> void:
	var a: Enemy = _spawn(Vector3(0, 0, -6))
	var b: Enemy = _spawn(Vector3(0, 0, -12))
	await _sim(0.1)
	var da: float = _dist(a)
	var db: float = _dist(b)
	var ok: bool = _player.try_cast("water")
	_check("4a cast water -> gelombang muncul", ok and _children_with_script(_proj, "water_wave.gd").size() == 1, "cast=%s" % ok)
	await _sim(2.2)
	_check("4b kedua musuh kena 25", is_equal_approx(_hp(a), 75.0) and is_equal_approx(_hp(b), 75.0),
			"hp a=%.1f b=%.1f" % [_hp(a), _hp(b)])
	var pa: float = _dist(a) - da
	var pb: float = _dist(b) - db
	_check("4c keduanya terdorong menjauh (~4 m)", pa > 3.0 and pb > 3.0 and pa < 4.5 and pb < 4.5,
			"dorongan a=%.2f b=%.2f" % [pa, pb])
	print("  info: dorongan a=%.2f m, b=%.2f m" % [pa, pb])
	_check("4d gelombang hilang setelah 30 m", _children_with_script(_proj, "water_wave.gd").is_empty(), "masih ada")
	await _isolate()


# 5. Lightning: target -35, chain -25 to max 2 enemies within 6 m, far enemy untouched.
func _t5_lightning() -> void:
	var t: Enemy = _spawn(Vector3(0, 0, -10))
	var n1: Enemy = _spawn(Vector3(3, 0, -12))
	var n2: Enemy = _spawn(Vector3(-2.5, 0, -12.5))
	var n3: Enemy = _spawn(Vector3(0.5, 0, -14.5))
	var far: Enemy = _spawn(Vector3(-14, 0, -18))
	await _sim(0.1)
	var ok: bool = _player.try_cast("lightning")
	await _sim(0.1)
	_check("5a target kena 35", ok and is_equal_approx(_hp(t), 65.0), "cast=%s hp=%.1f" % [ok, _hp(t)])
	var chained: int = 0
	var untouched: int = 0
	for e: Enemy in [n1, n2, n3]:
		if is_equal_approx(_hp(e), 75.0):
			chained += 1
		elif is_equal_approx(_hp(e), 100.0):
			untouched += 1
	_check("5b chain -25 ke tepat 2 musuh dekat (maks 2)", chained == 2 and untouched == 1,
			"hp dekat = %.0f, %.0f, %.0f" % [_hp(n1), _hp(n2), _hp(n3)])
	_check("5c musuh jauh (>6 m) tidak kena", is_equal_approx(_hp(far), 100.0), "hp=%.1f" % _hp(far))
	await _sim(0.4)
	_check("5d efek petir hilang", _children_with_script(_proj, "lightning.gd").is_empty(), "masih ada")
	await _isolate()


# 6. Earth: wall in front, blocks a walking enemy which damages it; wall expires.
func _t6_earth() -> void:
	_player.set_look(0.0, 0.0)
	var ok: bool = _player.try_cast("earth")
	await _sim(0.5)
	var wall: EarthWall = _caster.get_active_wall()
	var placed: bool = wall != null and absf(wall.global_position.x) < 0.05 \
			and absf(wall.global_position.z + 3.0) < 0.05 and absf(wall.global_position.y) < 0.05
	_check("6a dinding muncul 3 m di depan", ok and placed,
			"cast=%s wall=%s" % [ok, str(wall.global_position) if wall != null else "null"])
	if wall == null:
		return
	var e: Enemy = _spawn(Vector3(0, 0, -12), 1000.0, 4.0)
	await _sim(4.0)
	_check("6b musuh tertahan dinding", e.is_blocked_by_shield() and _dist(e) > 3.0 and is_equal_approx(_player.hp, 100.0),
			"blocked=%s jarak=%.2f hpPemain=%.0f" % [e.is_blocked_by_shield(), _dist(e), _player.hp])
	_check("6c HP dinding berkurang", wall.hp < wall.max_hp, "hp dinding=%.0f" % wall.hp)
	print("  info: jarak musuh %.2f m, HP dinding %.0f/%.0f, umur %.2f s" % [_dist(e), wall.hp, wall.max_hp, wall.get_age()])
	await _sim(2.5)  # 7.0 s after cast > lifetime 6 s + sink 0.4 s
	_check("6d dinding hilang setelah umur habis", not is_instance_valid(wall) and get_nodes_in_group("shield").is_empty(),
			"dinding masih ada")


# 7. Enemy reaches player -> 10 damage per second; HUD follows.
func _t7_enemy_hits_player() -> void:
	var waited: float = 0.0
	while _player.hp >= 100.0 and waited < 4.0:
		await _sim(0.1)
		waited += 0.1
	var hp1: float = _player.hp
	_check("7a musuh mencapai pemain & menyerang", is_equal_approx(hp1, 90.0), "hp=%.1f setelah %.1f s" % [hp1, waited])
	await _sim(2.5)
	_check("7b 10 damage per detik", is_equal_approx(_player.hp, hp1 - 20.0), "hp %.1f -> %.1f dalam 2.5 s" % [hp1, _player.hp])
	var expect: String = "HP %d / 100" % ceili(_player.hp)
	_check("7c HUD HP ikut berubah", _hud.get_hp_text() == expect and is_equal_approx(_hud.get_hp_bar_value(), _player.hp),
			"hud='%s' bar=%.1f hp=%.1f" % [_hud.get_hp_text(), _hud.get_hp_bar_value(), _player.hp])
	await _isolate()
	_player.reset_state()


# 8. All enemies of wave 1 dead -> wave 2 starts after 3 s with 8 enemies.
func _t8_next_wave() -> void:
	_main.restart()
	await _frames(1)
	var waited: float = 0.0
	while not _wm.is_between_waves() and waited < 30.0:
		await _sim(0.25)
		waited += 0.25
		for n: Node in get_nodes_in_group("enemies"):
			(n as Enemy).take_damage(9999.0)
	_check("8a wave 1 tuntas", _wm.is_between_waves() and _wm.wave == 1, "wave=%d jeda=%s" % [_wm.wave, _wm.is_between_waves()])
	await _sim(2.5)
	var still_one: bool = _wm.wave == 1
	await _sim(0.75)
	_check("8b wave 2 mulai setelah jeda 3 s", still_one and _wm.wave == 2 and _hud.get_wave_text() == "Wave 2"
			and _hud.get_banner_text() == "Wave 2",
			"t+2.5 wave1=%s, t+3.25 wave=%d" % [still_one, _wm.wave])
	_check("8c jumlah musuh wave 2 = 8", _wm.get_wave_total() == 8 and _wm.get_remaining() == 8,
			"total=%d remaining=%d" % [_wm.get_wave_total(), _wm.get_remaining()])
	var start_idx: int = _spawned.size()
	await _sim(10.0)
	_check("8d 8 musuh benar-benar di-spawn", _spawned.size() - start_idx == 8, "spawned=%d" % (_spawned.size() - start_idx))
	var brute: Enemy = _wm.spawn_enemy_at(Vector3(0, 0, -25), _wm.hp_for_wave(3), _wm.speed_for_wave(3), true)
	await physics_frame
	_check("8e varian brute (HP x2.5, lambat, lebih besar)", is_equal_approx(brute.max_hp, _wm.hp_for_wave(3) * 2.5)
			and brute.speed < _wm.speed_for_wave(3) and brute.get_hit_radius() > 0.6 and _wm.count_for_wave(3) == 10,
			"max_hp=%.1f speed=%.2f r=%.2f" % [brute.max_hp, brute.speed, brute.get_hit_radius()])


# 9. HP 0 -> game over overlay; try_cast does nothing; R restarts.
func _t9_game_over_and_r() -> void:
	var reached_wave: int = _wm.wave
	_player.take_damage(1000.0)
	await _frames(1)
	_check("9a game over + overlay terlihat", _main.is_game_over() and _hud.is_game_over_visible(),
			"state=%s overlay=%s" % [_main.state, _hud.is_game_over_visible()])
	var cast: bool = _player.try_cast("lightning")
	await _frames(1)
	_check("9b try_cast tidak mengeksekusi saat game over",
			not cast and _player.get_cooldown_remaining("lightning") == 0.0 and _children_with_script(_proj, "lightning.gd").is_empty(),
			"cast=%s cd=%.2f" % [cast, _player.get_cooldown_remaining("lightning")])
	var n_before: int = _spawned.size()
	await _sim(2.0)
	_check("9c tidak ada spawn saat game over", _spawned.size() == n_before, "spawn bertambah %d" % (_spawned.size() - n_before))
	var old: Array[Node] = get_nodes_in_group("enemies")
	var ev := InputEventKey.new()
	ev.keycode = KEY_R
	ev.physical_keycode = KEY_R
	ev.pressed = true
	root.push_input(ev)
	var ev_up := ev.duplicate() as InputEventKey
	ev_up.pressed = false
	root.push_input(ev_up)
	await _frames(2)
	var all_gone: bool = true
	for n: Node in old:
		if is_instance_valid(n):
			all_gone = false
	_check("9d tombol R -> restart (HP 100, wave 1, musuh lama dibersihkan)",
			not _main.is_game_over() and not _hud.is_game_over_visible() and is_equal_approx(_player.hp, 100.0)
			and _wm.wave == 1 and all_gone and _hud.get_hp_text() == "HP 100 / 100",
			"over=%s hp=%.0f wave=%d old_gone=%s (old=%d, dicapai wave %d)" % [_main.is_game_over(), _player.hp, _wm.wave, all_gone, old.size(), reached_wave])


# 10. Restart via a real UDP earth cast while game over; socket stays bound.
func _t10_udp_restart() -> void:
	await _sim(1.0)
	_player.take_damage(1000.0)
	await _frames(1)
	_check("10a game over lagi", _main.is_game_over(), "bukan game over")
	_cast_log.clear()
	_send({"type": "hb"})
	_send({"type": "cast", "skill": "earth", "conf": 0.9})
	var restarted: bool = await _wait_real_until(func() -> bool: return not _main.is_game_over(), 2.0)
	await _frames(2)
	_check("10b paket cast earth (UDP) -> restart", restarted and is_equal_approx(_player.hp, 100.0) and _wm.wave == 1,
			"restarted=%s hp=%.0f wave=%d" % [restarted, _player.hp, _wm.wave])
	_check("10c paket restart tidak ikut meng-cast earth", _caster.get_active_wall() == null
			and _player.get_cooldown_remaining("earth") == 0.0 and not _cast_log.has("earth"),
			"wall=%s cd=%.2f" % [_caster.get_active_wall(), _player.get_cooldown_remaining("earth")])
	_send({"type": "cast", "skill": "fire", "conf": 0.9})
	var got_fire: bool = await _wait_real_until(func() -> bool: return _cast_log.has("fire"), 2.0)
	_check("10d socket tetap bound & menerima setelah restart", _player.is_udp_bound() and got_fire,
			"bound=%s fire_diterima=%s" % [_player.is_udp_bound(), got_fire])


# 11. HUD cooldown overlay + gesture-link indicator.
func _t11_hud_cooldown_and_link() -> void:
	_wm.stop()
	_wm.clear_enemies()
	await _sim(1.2)  # let the UDP fire cooldown from test 10 expire
	var icon: SkillIcon = _hud.get_icon("fire")
	var base_ok: bool = icon.get_overlay_height() == 0.0
	_player.try_cast("fire")
	await _frames(1)
	var h: float = icon.get_overlay_height()
	_check("11a overlay cooldown api > 0 setelah cast", base_ok and h > 40.0 and icon.get_cooldown_ratio() > 0.5,
			"awal0=%s tinggi=%.1f rasio=%.2f" % [base_ok, h, icon.get_cooldown_ratio()])
	await _sim(1.2)
	_check("11b overlay kembali 0 setelah ~1 s", icon.get_overlay_height() == 0.0 and icon.get_cooldown_ratio() == 0.0,
			"tinggi=%.1f" % icon.get_overlay_height())

	var off: bool = await _wait_real_until(func() -> bool: return _hud.get_link_text() == Hud.LINK_OFF_TEXT, 3.0)
	_send({"type": "hb"})
	var t0: int = Time.get_ticks_msec()
	var on: bool = await _wait_real_until(func() -> bool: return _hud.get_link_text() == Hud.LINK_ON_TEXT, 1.0)
	_check("11c indikator link 'Gestur aktif' saat hb diterima", off and on and _player.is_gesture_link_connected(),
			"awal_off=%s on=%s teks='%s'" % [off, on, _hud.get_link_text()])
	var off2: bool = await _wait_real_until(func() -> bool: return _hud.get_link_text() == Hud.LINK_OFF_TEXT, 3.0)
	var elapsed: float = (Time.get_ticks_msec() - t0) / 1000.0
	_check("11d indikator kembali 'Menunggu Python…' setelah timeout", off2 and elapsed > 1.3 and elapsed < 2.2,
			"off=%s setelah %.2f s" % [off2, elapsed])
	print("  info: link timeout teramati %.2f s (link_timeout_sec %.1f)" % [elapsed, _player.link_timeout_sec])


# 12. Steering (type "steer"): direction, rate, timeout, 360 deg, aim follows, game over,
#     off-screen enemy indicators, invalid values.
func _t12_steering() -> void:
	await _isolate()
	_player.reset_state()
	await _frames(2)

	# 12a: +1 for 0.5 s -> +60 deg to the RIGHT (forward from -Z towards +X).
	var h0: float = _player.get_heading_deg()
	var f0: Vector3 = _forward()
	var bar_during: float = 0.0
	await _steer_stream(1.0, 7.0 / 30.0)  # 7 + 8 = 15 packets = 0.5 s at 30 Hz
	bar_during = _hud.get_steer_display()
	var alpha_during: float = _hud.get_steer_label_alpha()
	var link_on: bool = _player.is_gesture_link_connected()
	await _steer_stream(1.0, 8.0 / 30.0)
	var stopped: bool = await _steer_stop()
	var da: float = _ang_diff(h0, _player.get_heading_deg())
	var f1: Vector3 = _forward()
	_check("12a steer +1 selama 0,5 s -> +60° ke kanan (±15%), forward ke +X",
			stopped and absf(da - 60.0) <= 9.0 and f0.z < -0.99 and f1.x > 0.75 and f1.z < -0.35
			and is_equal_approx(bar_during, 1.0) and alpha_during == 1.0 and _hud.get_steer_display() == 0.0
			and _hud.get_steer_label_alpha() < 0.5 and link_on,
			"stop=%s delta=%.1f f0=%s f1=%s bar=%.2f/%.2f alpha=%.2f/%.2f link=%s" % [stopped, da, str(f0), str(f1),
			bar_during, _hud.get_steer_display(), alpha_during, _hud.get_steer_label_alpha(), link_on])
	print("  info: 12a heading %.1f -> %.1f (delta %.2f°, target 60), forward %s" % [h0, _player.get_heading_deg(), da, str(f1)])

	# 12b: -0.5 for 0.5 s -> -30 deg (left, half the rate).
	var h1: float = _player.get_heading_deg()
	await _steer_stream(-0.5, 0.5)
	stopped = await _steer_stop()
	var db: float = _ang_diff(h1, _player.get_heading_deg())
	_check("12b steer -0,5 -> ke kiri, laju setengah (-30° ±15%)", stopped and absf(db + 30.0) <= 4.5,
			"stop=%s delta=%.1f" % [stopped, db])
	print("  info: 12b delta %.2f° (target -30), rasio thd 12a %.3f" % [db, db / da if da != 0.0 else 0.0])

	# 12c: stop sending (no explicit 0) -> steering ends after steer_timeout_sec.
	var h2: float = _player.get_heading_deg()
	await _steer_stream(1.0, 0.1)
	await _sim(_player.steer_timeout_sec + 0.3)
	var h3: float = _player.get_heading_deg()
	var zero_after: bool = _player.get_steer_value() == 0.0
	await _sim(0.5)
	var h4: float = _player.get_heading_deg()
	var dc: float = _ang_diff(h2, h3)
	var expect_c: float = _player.max_turn_speed_deg * (0.1 + _player.steer_timeout_sec)
	_check("12c tanpa paket -> setelah steer_timeout_sec rotasi berhenti", zero_after
			and absf(_ang_diff(h3, h4)) < 0.001 and dc > expect_c * 0.75 and dc < expect_c * 1.25
			and _hud.get_steer_display() == 0.0,
			"steer=%.2f delta=%.1f (harap ~%.0f) drift=%.3f" % [_player.get_steer_value(), dc, expect_c, _ang_diff(h3, h4)])
	print("  info: 12c berputar %.1f° (0,1 s paket + timeout %.2f s ~ %.0f°), lalu diam" % [dc, _player.steer_timeout_sec, expect_c])

	# 12d: more than one full turn (no limit), yaw stays normalised; then face 180 deg:
	#      aim assist and the earth wall follow the new view direction.
	_player.reset_state()
	await _frames(1)
	var total: float = 0.0
	var last: float = _player.get_heading_deg()
	var max_abs_yaw: float = 0.0
	for i: int in roundi(3.3 * 30.0):
		_send({"type": "steer", "value": 1.0})
		for k: int in 2:
			await physics_frame
			var h: float = _player.get_heading_deg()
			total += _ang_diff(last, h)
			last = h
			max_abs_yaw = maxf(max_abs_yaw, absf(_player.get_yaw_deg()))
	await _steer_stop()
	total += _ang_diff(last, _player.get_heading_deg())
	_check("12d-1 putar >360° tanpa batas, yaw ternormalisasi", _player.yaw_limit_deg == 0.0 and total > 360.0
			and max_abs_yaw <= 180.0,
			"total=%.1f max|yaw|=%.1f" % [total, max_abs_yaw])
	print("  info: 12d total putaran %.1f° (target ~396), heading akhir %.1f" % [total, _player.get_heading_deg()])
	_player.reset_state()
	await _frames(1)
	await _steer_stream(1.0, 1.5)
	await _steer_stop()
	var fwd: Vector3 = _forward()
	var front: Enemy = _spawn(Vector3(0, 0, -8))
	var back: Enemy = _spawn(Vector3(0, 0, 10))
	await _sim(0.1)
	var aim: Enemy = _caster.find_aim_target()
	var earth_ok: bool = _player.try_cast("earth")
	await _sim(0.5)
	var wall: EarthWall = _caster.get_active_wall()
	var expect_pos: Vector3 = fwd * _caster.wall_distance
	var wall_ok: bool = wall != null and Vector2(wall.global_position.x - expect_pos.x, wall.global_position.z - expect_pos.z).length() < 0.05 \
			and wall.global_position.z > 2.5
	_check("12d-2 setelah berputar ~180°: dinding Tanah muncul di arah pandang baru",
			fwd.z > 0.95 and earth_ok and wall_ok,
			"heading=%.1f fwd=%s cast=%s wall=%s" % [_player.get_heading_deg(), str(fwd), earth_ok, str(wall.global_position) if wall != null else "null"])
	var fire_ok: bool = _player.try_cast("fire")
	await _sim(0.8)
	_check("12d-3 aim-assist mengikuti arah baru (target musuh di belakang posisi awal)",
			aim == back and fire_ok and is_equal_approx(_hp(back), 60.0) and is_equal_approx(_hp(front), 100.0),
			"aim=%s hp back=%.0f front=%.0f" % ["back" if aim == back else ("front" if aim == front else "null"), _hp(back), _hp(front)])
	print("  info: 12d heading %.1f, dinding di %s" % [_player.get_heading_deg(), str(wall.global_position) if wall != null else "-"])
	await _isolate()

	# 12e: steering ignored during game over; restart zeroes steering.
	_player.reset_state()
	await _steer_stream(1.0, 0.2)
	var active_before: bool = _player.get_steer_value() == 1.0
	_player.take_damage(100000.0)
	await _frames(1)
	var zero_on_death: bool = _player.get_steer_value() == 0.0 and _hud.get_steer_display() == 0.0
	var h_dead: float = _player.get_heading_deg()
	await _steer_stream(1.0, 0.5)
	await _frames(2)
	var ignored: bool = _player.get_steer_value() == 0.0 and absf(_ang_diff(h_dead, _player.get_heading_deg())) < 0.001
	_check("12e-1 steer di-nol-kan saat mati & diabaikan saat game over", _main.is_game_over() and active_before
			and zero_on_death and ignored,
			"over=%s aktif=%s nol=%s abaikan=%s heading %.1f -> %.1f" % [_main.is_game_over(), active_before, zero_on_death,
			ignored, h_dead, _player.get_heading_deg()])
	_main.restart()
	await _frames(1)
	await _steer_stream(-1.0, 0.2)
	var active_again: bool = _player.get_steer_value() == -1.0
	_main.restart()
	await _frames(1)
	_check("12e-2 restart me-nol-kan steer (dan heading)", active_again and _player.get_steer_value() == 0.0
			and _hud.get_steer_display() == 0.0 and absf(_player.get_yaw_deg()) < 0.001,
			"aktif=%s steer=%.2f yaw=%.2f" % [active_again, _player.get_steer_value(), _player.get_yaw_deg()])
	await _sim(0.2)
	_check("12e-3 setelah restart steer tetap 0 (timer tidak berputar sendiri)", absf(_player.get_yaw_deg()) < 0.001,
			"yaw=%.2f" % _player.get_yaw_deg())
	await _isolate()

	# 12f: off-screen indicators.
	_player.reset_state()
	await _frames(2)
	var none_at_start: bool = _hud.get_offscreen_indicator_count() == 0
	var behind_e: Enemy = _spawn(Vector3(0, 0, 12))
	await _frames(2)
	var screen: Vector2 = _hud.get_offscreen_indicator(0).get_viewport_rect().size
	var arrow: Polygon2D = _hud.get_offscreen_indicator(0)
	var targets: Array = _hud.get_offscreen_targets()
	_check("12f-1 indikator muncul untuk musuh di belakang (bawah tengah, menunjuk ke bawah)",
			none_at_start and _hud.get_offscreen_indicator_count() == 1 and targets.size() == 1 and targets[0] == behind_e
			and arrow.visible and arrow.position.y > screen.y * 0.5 and absf(arrow.position.x - screen.x * 0.5) < 2.0
			and absf(wrapf(arrow.rotation - PI * 0.5, -PI, PI)) < 0.05,
			"awal0=%s n=%d pos=%s rot=%.2f layar=%s" % [none_at_start, _hud.get_offscreen_indicator_count(), str(arrow.position),
			arrow.rotation, str(screen)])
	var front_e: Enemy = _spawn(Vector3(0, 0, -12))
	await _frames(2)
	_check("12f-2 musuh yang terlihat kamera tidak diberi indikator", _hud.get_offscreen_indicator_count() == 1
			and _hud.get_offscreen_targets()[0] == behind_e,
			"n=%d" % _hud.get_offscreen_indicator_count())
	_player.set_look(180.0, 0.0)
	await _frames(2)
	var swapped: bool = _hud.get_offscreen_indicator_count() == 1 and _hud.get_offscreen_targets()[0] == front_e
	var right_e: Enemy = _spawn(Vector3(-10, 0, 0))  # facing +Z, -X is to the RIGHT
	await _frames(2)
	var right_ok: bool = false
	for i: int in _hud.get_offscreen_indicator_count():
		if _hud.get_offscreen_targets()[i] == right_e:
			var ra: Polygon2D = _hud.get_offscreen_indicator(i)
			right_ok = ra.position.x > screen.x * 0.75 and absf(wrapf(ra.rotation, -PI, PI)) < 0.05
	_check("12f-3 setelah berbalik: indikator berpindah ke musuh lain; musuh di kanan -> panah di kanan", swapped and right_ok,
			"swapped=%s kanan=%s n=%d" % [swapped, right_ok, _hud.get_offscreen_indicator_count()])
	right_e.take_damage(9999.0)
	front_e.take_damage(9999.0)
	await _frames(2)
	# Still facing +Z: behind_e (z = +12) is in view now -> no arrow at all.
	var gone_when_visible: bool = _hud.get_offscreen_indicator_count() == 0
	_player.set_look(0.0, 0.0)
	await _frames(2)
	var back_again: bool = _hud.get_offscreen_indicator_count() == 1 and _hud.get_offscreen_targets()[0] == behind_e
	behind_e.take_damage(9999.0)
	await _frames(2)
	_check("12f-4 indikator hilang ketika musuh terlihat / mati", gone_when_visible and back_again
			and _hud.get_offscreen_indicator_count() == 0,
			"saat_terlihat=%s muncul_lagi=%s n_akhir=%d" % [gone_when_visible, back_again, _hud.get_offscreen_indicator_count()])
	var near_e: Enemy = _spawn(Vector3(3, 0, 5))
	var far_e: Enemy = _spawn(Vector3(-15, 0, 22))
	for i: int in 20:
		var a: float = deg_to_rad(120.0 + 6.0 * i)
		_spawn(Vector3(sin(a), 0.0, -cos(a)) * 27.0)
	await _frames(2)
	var near_c: Color = Color()
	var far_c: Color = Color()
	var tg: Array = _hud.get_offscreen_targets()
	for i: int in tg.size():
		if tg[i] == near_e:
			near_c = _hud.get_offscreen_indicator(i).color
		elif tg[i] == far_e:
			far_c = _hud.get_offscreen_indicator(i).color
	_check("12f-5 maks 16 indikator (pool), terdekat lebih terang/merah", _hud.get_offscreen_indicator_count() == Hud.MAX_INDICATORS
			and tg.size() == Hud.MAX_INDICATORS and tg[0] == near_e and near_c.a > 0.9 and near_c.r > far_c.r
			and near_c.a > far_c.a and far_c.a > 0.0,
			"n=%d pertama_dekat=%s dekat=%s jauh=%s" % [_hud.get_offscreen_indicator_count(), tg.size() > 0 and tg[0] == near_e, str(near_c), str(far_c)])
	await _isolate()
	await _frames(2)
	_check("12f-6 restart/bersih -> indikator 0", _hud.get_offscreen_indicator_count() == 0,
			"n=%d" % _hud.get_offscreen_indicator_count())

	# 12g: invalid / out-of-range steer values are ignored or clamped, no script error.
	_player.reset_state()
	await _frames(1)
	var hg: float = _player.get_heading_deg()
	for body: Dictionary in [{"type": "steer", "value": "kanan"}, {"type": "steer", "value": true},
			{"type": "steer", "value": null}, {"type": "steer"}, {"type": "steer", "value": [1]}]:
		_send(body)
	_udp_seq += 1
	_send_raw('{"v":1,"type":"steer","sid":"%s","seq":%d,"value":NaN}' % [_udp_sid, _udp_seq])
	_udp_seq += 1
	_send_raw('{"v":1,"type":"steer","sid":"%s","seq":%d,"value":1e999}' % [_udp_sid, _udp_seq])
	_udp_seq += 1
	_send_raw('{"v":1,"type":"steer","sid":"%s","seq":%d,"value":-1e999}' % [_udp_sid, _udp_seq])
	await _sim(0.3)
	var invalid_ignored: bool = _player.get_steer_value() == 0.0 and absf(_ang_diff(hg, _player.get_heading_deg())) < 0.001
	_send({"type": "steer", "value": 5})
	var clamped_hi: bool = await _wait_real_until(func() -> bool: return _player.get_steer_value() == 1.0, 1.0)
	_send({"type": "steer", "value": -7.5})
	var clamped_lo: bool = await _wait_real_until(func() -> bool: return _player.get_steer_value() == -1.0, 1.0)
	var stop_ok: bool = await _steer_stop()
	_check("12g value tidak valid diabaikan, di luar rentang di-clamp", invalid_ignored and clamped_hi and clamped_lo
			and stop_ok and _hud.get_steer_display() == 0.0,
			"abaikan=%s clamp+=%s clamp-=%s stop=%s" % [invalid_ignored, clamped_hi, clamped_lo, stop_ok])
	_player.set_look(0.0, 0.0)
	_player.yaw_limit_deg = 60.0
	_player.set_look(-200.0, 0.0)
	var limited: float = _player.get_yaw_deg()
	_player.yaw_limit_deg = 0.0
	_player.set_look(-200.0, 0.0)
	_check("12h yaw_limit_deg > 0 membatasi (perilaku lama), 0 = membungkus 360°", is_equal_approx(limited, -60.0)
			and is_equal_approx(_player.get_yaw_deg(), 160.0),
			"limit60=%.1f tanpa_batas=%.1f" % [limited, _player.get_yaw_deg()])
	_player.set_look(0.0, 0.0)
