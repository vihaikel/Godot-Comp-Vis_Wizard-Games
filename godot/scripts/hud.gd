class_name Hud
extends CanvasLayer
## HUD: HP bar, wave + enemies-left labels, gesture-link indicator, 4 spell icons
## with cooldown overlays, wave banner, red damage vignette, game-over overlay,
## steering bar and off-screen enemy arrows.
## Driven by signals from Player and WaveManager (see setup()); the off-screen arrows
## are recomputed every frame from the "enemies" group and the player camera.

const LINK_ON_TEXT := "Gestur aktif"
const LINK_OFF_TEXT := "Menunggu Python…"
const LINK_ON_COLOR := Color(0.35, 1.0, 0.45)
const LINK_OFF_COLOR := Color(0.65, 0.65, 0.65)
const STEER_IDLE_ALPHA := 0.35
const MAX_INDICATORS := 16

## Off-screen arrows: distance (m) mapped to brightness (near = bright).
@export var indicator_near_dist: float = 4.0
@export var indicator_far_dist: float = 30.0
@export var indicator_margin: float = 44.0  # px from the screen edge (left/right/top)
@export var indicator_bottom_clearance: float = 210.0  # px kept free above the bottom (skills + steer bar)

@onready var _hp_bar: ProgressBar = %HPBar
@onready var _hp_label: Label = %HPLabel
@onready var _wave_label: Label = %WaveLabel
@onready var _enemies_label: Label = %EnemiesLabel
@onready var _link_label: Label = %LinkLabel
@onready var _banner: Label = %Banner
@onready var _vignette: TextureRect = %DamageVignette
@onready var _game_over: Control = %GameOver
@onready var _game_over_title: Label = %GameOverTitle
@onready var _game_over_hint: Label = %GameOverHint
@onready var _skills: Control = %Skills
@onready var _indicator_root: Control = %OffscreenIndicators
@onready var _steer_label: Label = %SteerLabel
@onready var _steer_fill: ColorRect = %SteerFill

var _icons: Dictionary = {}  # skill -> SkillIcon
var _banner_tween: Tween
var _vignette_tween: Tween
var _last_hp: float = -1.0
var _camera: Camera3D
var _indicators: Array[Polygon2D] = []
var _indicator_targets: Array[Enemy] = []
var _steer: float = 0.0


func _ready() -> void:
	for child: Node in _skills.get_children():
		var icon := child as SkillIcon
		if icon != null:
			_icons[icon.skill] = icon
	_banner.modulate.a = 0.0
	_vignette.modulate.a = 0.0
	_game_over.visible = false
	set_link(false)
	for i: int in MAX_INDICATORS:
		var arrow := Polygon2D.new()
		arrow.name = "Arrow%d" % i
		# Points along +X (rotation = direction angle); tip at (14, 0).
		arrow.polygon = PackedVector2Array([Vector2(14, 0), Vector2(-8, -10), Vector2(-3, 0), Vector2(-8, 10)])
		arrow.visible = false
		_indicator_root.add_child(arrow)
		_indicators.append(arrow)
	set_steer(0.0)


func setup(player: Player, wave_manager: WaveManager) -> void:
	player.hp_changed.connect(set_hp)
	player.cooldown_changed.connect(_on_cooldown_changed)
	player.skill_cast.connect(_on_skill_cast)
	player.skill_rejected.connect(_on_skill_rejected)
	player.gesture_link_changed.connect(set_link)
	player.steer_changed.connect(set_steer)
	_camera = player.camera
	wave_manager.wave_started.connect(_on_wave_started)
	wave_manager.enemies_remaining_changed.connect(set_enemies_remaining)
	set_hp(player.hp, player.max_hp)
	set_link(player.is_gesture_link_connected())
	set_steer(player.get_steer_value())


func _process(_delta: float) -> void:
	update_offscreen_indicators()


func set_hp(hp: float, max_hp: float) -> void:
	_hp_bar.max_value = max_hp
	_hp_bar.value = hp
	_hp_label.text = "HP %d / %d" % [ceili(hp), ceili(max_hp)]
	if _last_hp >= 0.0 and hp < _last_hp:
		_flash_vignette()
	_last_hp = hp


func set_wave(wave: int) -> void:
	_wave_label.text = "Wave %d" % wave


func set_enemies_remaining(remaining: int) -> void:
	_enemies_label.text = "Musuh tersisa: %d" % remaining


func set_link(connected: bool) -> void:
	_link_label.text = LINK_ON_TEXT if connected else LINK_OFF_TEXT
	_link_label.add_theme_color_override("font_color", LINK_ON_COLOR if connected else LINK_OFF_COLOR)


## Steering bar: fills from the centre to the right (value > 0) or left (value < 0).
func set_steer(value: float) -> void:
	_steer = clampf(value, -1.0, 1.0)
	_steer_fill.set_anchor_and_offset(SIDE_LEFT, 0.5 + 0.5 * minf(_steer, 0.0), 0.0)
	_steer_fill.set_anchor_and_offset(SIDE_RIGHT, 0.5 + 0.5 * maxf(_steer, 0.0), 0.0)
	_steer_fill.visible = _steer != 0.0
	_steer_label.text = "Kemudi" if _steer == 0.0 else ("Kemudi %s %d%%" % ["kiri" if _steer < 0.0 else "kanan", roundi(absf(_steer) * 100.0)])
	_steer_label.modulate.a = STEER_IDLE_ALPHA if _steer == 0.0 else 1.0


func get_steer_display() -> float:
	return _steer


func get_steer_label_alpha() -> float:
	return _steer_label.modulate.a


## Shows one red arrow at the screen edge for each living enemy the camera cannot see
## (nearest MAX_INDICATORS first). Direction is the enemy's bearing relative to the
## camera seen from above: straight up = ahead, down = behind, right = to the right.
func update_offscreen_indicators() -> void:
	_indicator_targets.clear()
	var candidates: Array = []  # [distance, Enemy, screen direction]
	if _camera != null and is_instance_valid(_camera) and not _game_over.visible:
		var cam_pos: Vector3 = _camera.global_position
		for node: Node in get_tree().get_nodes_in_group("enemies"):
			var e := node as Enemy
			if e == null or not e.is_alive():
				continue
			if _camera.is_position_in_frustum(e.get_aim_point()):
				continue
			var local: Vector3 = _camera.to_local(e.global_position)
			var dir := Vector2(local.x, local.z)  # camera space: +x right, +z behind (= screen down)
			if dir.length_squared() < 0.0001:
				continue
			var flat: Vector3 = e.global_position - cam_pos
			flat.y = 0.0
			candidates.append([flat.length(), e, dir.normalized()])
		candidates.sort_custom(func(a: Array, b: Array) -> bool: return a[0] < b[0])
	var screen: Vector2 = _indicator_root.get_viewport_rect().size
	var center: Vector2 = screen * 0.5
	var half_w: float = maxf(center.x - indicator_margin, 40.0)
	var half_top: float = maxf(center.y - indicator_margin, 40.0)
	var half_bottom: float = maxf(center.y - indicator_bottom_clearance, 60.0)
	for i: int in MAX_INDICATORS:
		var arrow: Polygon2D = _indicators[i]
		if i >= candidates.size():
			arrow.visible = false
			continue
		var dist: float = candidates[i][0]
		var dir: Vector2 = candidates[i][2]
		var t: float = clampf(inverse_lerp(indicator_far_dist, indicator_near_dist, dist), 0.0, 1.0)
		arrow.position = center + Vector2(dir.x * half_w, dir.y * (half_bottom if dir.y > 0.0 else half_top))
		arrow.rotation = dir.angle()
		arrow.scale = Vector2.ONE * lerpf(0.8, 1.35, t)
		arrow.color = Color(lerpf(0.55, 1.0, t), lerpf(0.05, 0.25, t), lerpf(0.05, 0.18, t), lerpf(0.45, 1.0, t))
		arrow.visible = true
		_indicator_targets.append(candidates[i][1])


func get_offscreen_indicator_count() -> int:
	var n: int = 0
	for arrow: Polygon2D in _indicators:
		if arrow.visible:
			n += 1
	return n


## Enemies that currently have an arrow (same order as the visible arrows).
func get_offscreen_targets() -> Array:
	return _indicator_targets.duplicate()


func get_offscreen_indicator(i: int) -> Polygon2D:
	return _indicators[i] if i >= 0 and i < _indicators.size() else null


func show_banner(text: String) -> void:
	_banner.text = text
	if _banner_tween != null:
		_banner_tween.kill()
	_banner.modulate.a = 0.0
	_banner_tween = create_tween()
	_banner_tween.tween_property(_banner, "modulate:a", 1.0, 0.25)
	_banner_tween.tween_interval(1.4)
	_banner_tween.tween_property(_banner, "modulate:a", 0.0, 0.5)


func show_game_over(wave: int) -> void:
	_game_over_title.text = "Game Over — mencapai Wave %d" % wave
	_game_over_hint.text = "Tekan R atau tahan telapak kiri (Tanah) untuk mulai lagi"
	_game_over.visible = true


func hide_game_over() -> void:
	_game_over.visible = false


func is_game_over_visible() -> bool:
	return _game_over.visible


func get_icon(skill: String) -> SkillIcon:
	return _icons.get(skill)


func get_hp_text() -> String:
	return _hp_label.text


func get_hp_bar_value() -> float:
	return _hp_bar.value


func get_link_text() -> String:
	return _link_label.text


func get_wave_text() -> String:
	return _wave_label.text


func get_banner_text() -> String:
	return _banner.text


# --------------------------------------------------------------- internals
func _on_wave_started(wave: int, _total: int) -> void:
	set_wave(wave)
	show_banner("Wave %d" % wave)


func _on_cooldown_changed(skill: String, remaining: float, total: float) -> void:
	var icon: SkillIcon = _icons.get(skill)
	if icon != null:
		icon.set_cooldown(remaining, total)


func _on_skill_cast(skill: String) -> void:
	var icon: SkillIcon = _icons.get(skill)
	if icon != null:
		icon.pulse()


func _on_skill_rejected(skill: String, _remaining: float) -> void:
	var icon: SkillIcon = _icons.get(skill)
	if icon != null:
		icon.shake()


func _flash_vignette() -> void:
	if _vignette_tween != null:
		_vignette_tween.kill()
	_vignette.modulate.a = 0.85
	_vignette_tween = create_tween()
	_vignette_tween.tween_property(_vignette, "modulate:a", 0.0, 0.45)
