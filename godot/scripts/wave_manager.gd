class_name WaveManager
extends Node
## Spawns enemy waves around the player's start position: the full 360 deg circle by
## default (spawn_arc_deg = 360); a smaller spawn_arc_deg uses an arc centred on -Z.
## Wave n: count = base_count + per_wave * n, hp = base_hp * (1 + hp_growth * (n - 1)),
## speed = min(base_speed + speed_per_wave * n, max_speed),
## spawn interval = max(base_interval - interval_step * n, min_interval).
## The next wave starts `wave_delay` s after every enemy of the wave is dead.
## From `brute_from_wave` on, the LAST enemy of each wave is a brute (counts toward the total).

signal wave_started(wave: int, total: int)
signal wave_cleared(wave: int)
signal enemies_remaining_changed(remaining: int)
signal enemy_spawned(enemy: Enemy)

@export var enemy_scene: PackedScene
@export var enemies_root: Node3D
@export var player: Player

@export_group("Wave formula")
@export var base_count: int = 4
@export var per_wave: int = 2
@export var base_hp: float = 50.0
@export var hp_growth: float = 0.15
@export var base_speed: float = 2.2
@export var speed_per_wave: float = 0.15
@export var max_speed: float = 5.0
@export var base_interval: float = 1.2
@export var interval_step: float = 0.05
@export var min_interval: float = 0.4
@export var first_spawn_delay: float = 0.5
@export var wave_delay: float = 3.0
@export var brute_from_wave: int = 3

@export_group("Spawn area")
## Total spawn arc in degrees. 360 = all around the player; < 360 = arc centred on -Z
## (the old front-only behaviour was 140, i.e. +-70 deg).
@export_range(0.0, 360.0) var spawn_arc_deg: float = 360.0
@export var min_radius: float = 24.0
@export var max_radius: float = 30.0
@export var rng_seed: int = 0  # 0 = random every run

var wave: int = 0
var running: bool = false

var _total: int = 0
var _to_spawn: int = 0
var _alive: int = 0
var _spawn_timer: float = 0.0
var _next_wave_timer: float = -1.0
var _center: Vector3 = Vector3.ZERO
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	if rng_seed != 0:
		_rng.seed = rng_seed
	else:
		_rng.randomize()
	if player != null:
		_center = player.global_position
		_center.y = 0.0


func start_game() -> void:
	clear_enemies()
	running = true
	_begin_wave(1)


func stop() -> void:
	running = false
	_next_wave_timer = -1.0


func clear_enemies() -> void:
	for child: Node in enemies_root.get_children():
		var e := child as Enemy
		if e != null:
			if e.died.is_connected(_on_enemy_died):
				e.died.disconnect(_on_enemy_died)
			e.despawn()
	_alive = 0
	enemies_remaining_changed.emit(get_remaining())


func count_for_wave(n: int) -> int:
	return base_count + per_wave * n


func hp_for_wave(n: int) -> float:
	return base_hp * (1.0 + hp_growth * float(n - 1))


func speed_for_wave(n: int) -> float:
	return minf(base_speed + speed_per_wave * float(n), max_speed)


func interval_for_wave(n: int) -> float:
	return maxf(base_interval - interval_step * float(n), min_interval)


## Enemies still to kill this wave (alive + not yet spawned).
func get_remaining() -> int:
	return _alive + _to_spawn


func get_wave_total() -> int:
	return _total


func get_alive_count() -> int:
	return _alive


func is_between_waves() -> bool:
	return _next_wave_timer >= 0.0


## Random point in the spawn area. Angle 0 = -Z from the player's start position,
## positive = clockwise seen from above (towards +X).
func random_spawn_position() -> Vector3:
	var half: float = clampf(spawn_arc_deg, 0.0, 360.0) * 0.5
	var a: float = deg_to_rad(_rng.randf_range(-half, half))
	var r: float = _rng.randf_range(min_radius, max_radius)
	return _center + Vector3(sin(a), 0.0, -cos(a)) * r


## Spawns one enemy at `pos` (also used by tests). Counts toward the alive total.
func spawn_enemy_at(pos: Vector3, hp: float, speed: float, brute: bool = false) -> Enemy:
	var e := enemy_scene.instantiate() as Enemy
	e.configure(hp, speed, brute)
	e.target = player
	enemies_root.add_child(e)
	e.global_position = Vector3(pos.x, 0.0, pos.z)
	if player != null:
		var to: Vector3 = player.global_position - e.global_position
		e.rotation.y = atan2(-to.x, -to.z)
	e.died.connect(_on_enemy_died)
	_alive += 1
	enemy_spawned.emit(e)
	enemies_remaining_changed.emit(get_remaining())
	return e


func _process(delta: float) -> void:
	if not running:
		return
	if _next_wave_timer >= 0.0:
		_next_wave_timer -= delta
		if _next_wave_timer <= 0.0:
			_next_wave_timer = -1.0
			_begin_wave(wave + 1)
		return
	if _to_spawn > 0:
		_spawn_timer -= delta
		if _spawn_timer <= 0.0:
			_spawn_timer += interval_for_wave(wave)
			_spawn_next()


func _begin_wave(n: int) -> void:
	wave = n
	_total = count_for_wave(n)
	_to_spawn = _total
	_alive = 0
	_spawn_timer = first_spawn_delay
	print("[wave] wave %d mulai: %d musuh, hp %.1f, speed %.2f, interval %.2fs" % [n, _total, hp_for_wave(n), speed_for_wave(n), interval_for_wave(n)])
	wave_started.emit(n, _total)
	enemies_remaining_changed.emit(get_remaining())


func _spawn_next() -> void:
	var brute: bool = wave >= brute_from_wave and _to_spawn == 1
	_to_spawn -= 1  # before spawn_enemy_at so the remaining count stays consistent
	spawn_enemy_at(random_spawn_position(), hp_for_wave(wave), speed_for_wave(wave), brute)


func _on_enemy_died(_enemy: Enemy) -> void:
	_alive = maxi(_alive - 1, 0)
	enemies_remaining_changed.emit(get_remaining())
	if running and _to_spawn == 0 and _alive == 0 and _next_wave_timer < 0.0:
		print("[wave] wave %d selesai, wave berikutnya dalam %.1fs" % [wave, wave_delay])
		wave_cleared.emit(wave)
		_next_wave_timer = wave_delay
