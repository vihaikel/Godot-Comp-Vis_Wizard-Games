class_name Player
extends Node3D
## Receives gesture casts from Python over UDP (protocol: python/PROTOCOL.md)
## and owns the AUTHORITATIVE per-skill cooldowns. Python only debounces.
## Phase 4-5: also owns player HP and the first-person camera look (pitch +-15 deg);
## spell effects are spawned by the SpellCaster child.
## Steering: "steer" packets (value -1..1, positive = turn RIGHT) rotate the view at
## value * max_turn_speed_deg deg/s, full 360 deg by default (yaw_limit_deg = 0).
## Internally _yaw_deg is Camera3D.rotation.y in degrees (Godot convention: positive =
## turn LEFT / counter-clockwise seen from above); get_heading_deg() is the clockwise
## compass heading (0 = -Z, 90 = +X).

signal skill_cast(skill: String)
signal skill_rejected(skill: String, remaining: float)
signal cooldown_changed(skill: String, remaining: float, total: float)
signal gesture_link_changed(connected: bool)
## Emitted for every VALID cast packet from UDP (after validation + dedupe),
## BEFORE the cooldown check. GameManager uses it to restart from game over.
signal gesture_received(skill: String)
signal hp_changed(hp: float, max_hp: float)
signal died
## Steering value currently applied (-1..1, positive = right); 0 when stopped.
signal steer_changed(value: float)

const SKILLS := ["fire", "water", "lightning", "earth"]
const PROTOCOL_VERSION := 1
const MAX_PACKET_BYTES := 1024
const MAX_TRACKED_SIDS := 16

@export var listen_port: int = 4242
@export var bind_address: String = "127.0.0.1"
@export var fire_cooldown: float = 1.0
@export var water_cooldown: float = 3.0
@export var lightning_cooldown: float = 2.0
@export var earth_cooldown: float = 6.0
@export var link_timeout_sec: float = 1.5
@export var debug_keys: bool = true

@export_group("Health")
@export var max_hp: float = 100.0

@export_group("Look")
@export var camera: Camera3D
## 0 = unlimited (full 360 deg turning); > 0 = yaw clamped to +-yaw_limit_deg (old behaviour: 60).
@export var yaw_limit_deg: float = 0.0
@export var max_pitch_deg: float = 15.0
@export var key_yaw_speed_deg: float = 90.0  # arrow keys, degrees per second
@export var mouse_sensitivity: float = 0.15  # degrees per pixel (hold right mouse button)

@export_group("Steering")
## Turn rate in degrees per second at steer value 1.0.
@export var max_turn_speed_deg: float = 120.0
## Without a steer packet for this long (game seconds), steering falls back to 0.
@export var steer_timeout_sec: float = 0.3

@export_group("Spells")
@export var spell_caster: SpellCaster

var _udp: PacketPeerUDP = PacketPeerUDP.new()
var _cooldown_remaining: Dictionary = {}  # skill (String) -> seconds left (float)
var _last_seq_by_sid: Dictionary = {}  # sid (String) -> last accepted seq (int)
var _last_packet_msec: int = -1  # Time.get_ticks_msec() of the last accepted packet
var _link_connected: bool = false

var hp: float = 100.0
var casting_enabled: bool = true  # false during game over: try_cast() executes nothing
var _alive: bool = true
var _yaw_deg: float = 0.0
var _pitch_deg: float = 0.0
var steer_value: float = 0.0  # -1..1, positive = turn right
var _steer_age: float = 0.0  # game seconds since the last accepted steer packet


func _ready() -> void:
	for skill: String in SKILLS:
		_cooldown_remaining[skill] = 0.0
	hp = max_hp
	var err: Error = _udp.bind(listen_port, bind_address)
	if err != OK:
		push_error("Player: gagal bind UDP %s:%d (%s). Port mungkin sudah dipakai proses lain (instance Godot kedua?). Ubah listen_port atau tutup proses tersebut." % [bind_address, listen_port, error_string(err)])
	else:
		print("[udp] listening on %s:%d" % [bind_address, listen_port])


func _process(delta: float) -> void:
	_tick_cooldowns(delta)
	_poll_udp()
	_update_link()
	_update_key_look(delta)
	_update_steer(delta)


func _unhandled_input(event: InputEvent) -> void:
	var motion := event as InputEventMouseMotion
	if motion != null:
		if Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT):
			set_look(_yaw_deg - motion.relative.x * mouse_sensitivity,
					_pitch_deg - motion.relative.y * mouse_sensitivity)
		return
	if not debug_keys:
		return
	var key := event as InputEventKey
	if key == null or not key.pressed or key.echo:
		return
	var idx: int = -1
	match key.keycode:
		KEY_1:
			idx = 0
		KEY_2:
			idx = 1
		KEY_3:
			idx = 2
		KEY_4:
			idx = 3
	if idx < 0:
		return
	get_viewport().set_input_as_handled()
	print("[key] debug cast %s" % SKILLS[idx])
	try_cast(SKILLS[idx])


func _exit_tree() -> void:
	_udp.close()


# --------------------------------------------------------------- casting
func try_cast(skill: String) -> bool:
	if not _cooldown_remaining.has(skill):
		push_warning("Player.try_cast: skill tidak dikenal '%s'" % skill)
		return false
	if not casting_enabled:
		print("[cast] %s diabaikan (game over)" % skill)
		return false
	var remaining: float = _cooldown_remaining[skill]
	if remaining > 0.0:
		print("[cast] %s DITOLAK (cooldown %.2fs)" % [skill, remaining])
		skill_rejected.emit(skill, remaining)
		return false
	var total: float = get_cooldown_total(skill)
	_cooldown_remaining[skill] = total
	match skill:
		"fire":
			cast_fire()
		"water":
			cast_water()
		"lightning":
			cast_lightning()
		"earth":
			cast_earth()
	skill_cast.emit(skill)
	cooldown_changed.emit(skill, total, total)
	return true


func cast_fire() -> void:
	print("[cast] FIRE")
	if spell_caster != null:
		spell_caster.cast_fire()


func cast_water() -> void:
	print("[cast] WATER")
	if spell_caster != null:
		spell_caster.cast_water()


func cast_lightning() -> void:
	print("[cast] LIGHTNING")
	if spell_caster != null:
		spell_caster.cast_lightning()


func cast_earth() -> void:
	print("[cast] EARTH")
	if spell_caster != null:
		spell_caster.cast_earth()


func get_cooldown_remaining(skill: String) -> float:
	return _cooldown_remaining.get(skill, 0.0)


func get_cooldown_total(skill: String) -> float:
	match skill:
		"fire":
			return fire_cooldown
		"water":
			return water_cooldown
		"lightning":
			return lightning_cooldown
		"earth":
			return earth_cooldown
	return 0.0


func is_gesture_link_connected() -> bool:
	return _link_connected


func is_udp_bound() -> bool:
	return _udp.is_bound()


# --------------------------------------------------------------- health
func take_damage(amount: float) -> void:
	if not _alive or amount <= 0.0:
		return
	hp = maxf(hp - amount, 0.0)
	hp_changed.emit(hp, max_hp)
	if hp <= 0.0:
		_alive = false
		casting_enabled = false
		_set_steer(0.0)
		print("[player] MATI")
		died.emit()


func is_alive() -> bool:
	return _alive


## Restart: full HP, cooldowns cleared, casting enabled. The UDP socket, the
## sid/seq dedupe table and the link state are deliberately left untouched.
func reset_state() -> void:
	hp = max_hp
	_alive = true
	casting_enabled = true
	for skill: String in SKILLS:
		_cooldown_remaining[skill] = 0.0
		cooldown_changed.emit(skill, 0.0, get_cooldown_total(skill))
	_set_steer(0.0)
	set_look(0.0, 0.0)
	hp_changed.emit(hp, max_hp)


# --------------------------------------------------------------- look
## yaw_deg uses the Godot convention (positive = left). Wrapped to [-180, 180) when
## yaw_limit_deg is 0, otherwise clamped to +-yaw_limit_deg.
func set_look(yaw_deg: float, pitch_deg: float) -> void:
	if yaw_limit_deg > 0.0:
		_yaw_deg = clampf(yaw_deg, -yaw_limit_deg, yaw_limit_deg)
	else:
		_yaw_deg = wrapf(yaw_deg, -180.0, 180.0)
	_pitch_deg = clampf(pitch_deg, -max_pitch_deg, max_pitch_deg)
	if camera != null:
		camera.rotation = Vector3(deg_to_rad(_pitch_deg), deg_to_rad(_yaw_deg), 0.0)


func get_yaw_deg() -> float:
	return _yaw_deg


## Clockwise heading in degrees, [0, 360): 0 = -Z (start direction), 90 = +X (right).
func get_heading_deg() -> float:
	return fposmod(-_yaw_deg, 360.0)


func get_steer_value() -> float:
	return steer_value


func _update_key_look(delta: float) -> void:
	var dir: float = 0.0
	if Input.is_key_pressed(KEY_LEFT):
		dir += 1.0
	if Input.is_key_pressed(KEY_RIGHT):
		dir -= 1.0
	if dir != 0.0:
		set_look(_yaw_deg + dir * key_yaw_speed_deg * delta, _pitch_deg)


## Applies the current steer value; drops it to 0 after steer_timeout_sec without packets.
func _update_steer(delta: float) -> void:
	if steer_value == 0.0:
		return
	# Positive steer = turn right = clockwise from above = Godot yaw DEcreases.
	set_look(_yaw_deg - steer_value * max_turn_speed_deg * delta, _pitch_deg)
	_steer_age += delta
	if _steer_age > steer_timeout_sec:
		print("[steer] timeout (%.2fs tanpa paket)" % steer_timeout_sec)
		_set_steer(0.0)


func _set_steer(value: float) -> void:
	if value == steer_value:
		return
	if steer_value == 0.0:
		print("[steer] mulai %+.2f yaw=%.1f heading=%.1f" % [value, _yaw_deg, get_heading_deg()])
	elif value == 0.0:
		print("[steer] berhenti yaw=%.1f heading=%.1f" % [_yaw_deg, get_heading_deg()])
	steer_value = value
	steer_changed.emit(value)


# --------------------------------------------------------------- internals
func _tick_cooldowns(delta: float) -> void:
	for skill: String in SKILLS:
		var remaining: float = _cooldown_remaining[skill]
		if remaining > 0.0:
			remaining = maxf(remaining - delta, 0.0)
			_cooldown_remaining[skill] = remaining
			cooldown_changed.emit(skill, remaining, get_cooldown_total(skill))


func _poll_udp() -> void:
	if not _udp.is_bound():
		return
	while _udp.get_available_packet_count() > 0:
		var bytes: PackedByteArray = _udp.get_packet()
		_handle_packet(bytes)


func _handle_packet(bytes: PackedByteArray) -> void:
	var sender_ip: String = _udp.get_packet_ip()
	if bytes.is_empty() or bytes.size() > MAX_PACKET_BYTES:
		push_warning("[udp] paket diabaikan dari %s: ukuran %d byte" % [sender_ip, bytes.size()])
		return
	var parsed: Variant = JSON.parse_string(bytes.get_string_from_utf8())
	if not (parsed is Dictionary):
		push_warning("[udp] paket diabaikan dari %s: bukan objek JSON" % sender_ip)
		return
	var msg: Dictionary = parsed

	var v: Variant = msg.get("v")
	if not _is_whole_number(v) or int(v) != PROTOCOL_VERSION:
		push_warning("[udp] paket diabaikan: versi protokol %s (harus %d)" % [str(v), PROTOCOL_VERSION])
		return
	var type_v: Variant = msg.get("type")
	if not (type_v is String) or not (type_v == "cast" or type_v == "hb" or type_v == "steer"):
		push_warning("[udp] paket diabaikan: type tidak dikenal %s" % str(type_v))
		return
	var sid_v: Variant = msg.get("sid")
	var seq_v: Variant = msg.get("seq")
	if not (sid_v is String) or (sid_v as String).is_empty() or not _is_whole_number(seq_v) or float(seq_v) < 0.0:
		push_warning("[udp] paket diabaikan: sid/seq tidak valid (sid=%s seq=%s)" % [str(sid_v), str(seq_v)])
		return
	var msg_type: String = type_v
	var sid: String = sid_v
	var seq: int = int(seq_v)
	var skill: String = ""
	if msg_type == "cast":
		var skill_v: Variant = msg.get("skill")
		if not (skill_v is String) or not SKILLS.has(skill_v):
			push_warning("[udp] paket diabaikan: skill tidak dikenal %s" % str(skill_v))
			return
		skill = skill_v
	var steer: float = 0.0
	if msg_type == "steer":
		var value_v: Variant = msg.get("value")
		if not (value_v is float or value_v is int) or not is_finite(float(value_v)):
			push_warning("[udp] paket steer diabaikan: value tidak valid %s" % str(value_v))
			return
		steer = clampf(float(value_v), -1.0, 1.0)

	# sid/seq dedupe: drop duplicates and late/out-of-order packets per session.
	if _last_seq_by_sid.has(sid):
		var last_seq: int = _last_seq_by_sid[sid]
		if seq <= last_seq:
			print("[udp] buang seq=%d (terakhir %d) sid=%s" % [seq, last_seq, sid])
			return
	else:
		if _last_seq_by_sid.size() >= MAX_TRACKED_SIDS:
			_last_seq_by_sid.clear()
		print("[udp] sesi baru sid=%s dari %s" % [sid, sender_ip])
	_last_seq_by_sid[sid] = seq
	_last_packet_msec = Time.get_ticks_msec()

	if msg_type == "cast":
		var conf_v: Variant = msg.get("conf", 0.0)
		var conf: float = float(conf_v) if (conf_v is float or conf_v is int) else 0.0
		print("[udp] recv cast %s conf=%.2f seq=%d unix=%.3f" % [skill, conf, seq, Time.get_unix_time_from_system()])
		gesture_received.emit(skill)
		try_cast(skill)
	elif msg_type == "steer":
		if not _alive:
			return  # game over: steering ignored (steer_value was zeroed on death)
		_steer_age = 0.0
		_set_steer(steer)


func _update_link() -> void:
	var connected: bool = _last_packet_msec >= 0 \
			and Time.get_ticks_msec() - _last_packet_msec <= int(link_timeout_sec * 1000.0)
	if connected != _link_connected:
		_link_connected = connected
		print("[udp] gesture link: %s" % ("TERHUBUNG" if connected else "TERPUTUS"))
		gesture_link_changed.emit(connected)


static func _is_whole_number(x: Variant) -> bool:
	if x is int:
		return true
	if x is float:
		return is_finite(x) and x == floorf(x)
	return false
