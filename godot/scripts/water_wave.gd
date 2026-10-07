class_name WaterWave
extends Area3D
## Water spell: wide piercing water cannon (Area3D box ~2.5 m wide). Damages every
## enemy it passes ONCE and knocks it back away from the player.
## Collision: layer 5 "spells", mask 3 "enemies". Passes through shields.

@export var speed: float = 18.0
@export var max_distance: float = 30.0
@export var damage: float = 25.0
@export var knockback_distance: float = 4.0
@export var splash_color: Color = Color(0.35, 0.7, 1.0)

var direction: Vector3 = Vector3.FORWARD
var push_origin: Vector3 = Vector3.ZERO  # knockback points away from here (the player)
var _travelled: float = 0.0
var _hit: Dictionary = {}  # instance_id -> true
var _done: bool = false


func launch(dir: Vector3, knockback_origin: Vector3) -> void:
	direction = Aim.flat(dir)
	push_origin = knockback_origin
	global_basis = Basis.looking_at(direction, Vector3.UP)


func _physics_process(delta: float) -> void:
	if _done:
		return
	for body: Node3D in get_overlapping_bodies():
		_try_hit(body)
	var step: float = speed * delta
	global_position += direction * step
	_travelled += step
	if _travelled >= max_distance:
		_done = true
		var parent := get_parent()
		if parent != null:
			Fx.burst(parent, global_position + Vector3(0, 0.6, 0), splash_color, 20, 3.0, 0.12, 0.5)
		queue_free()


func get_hit_count() -> int:
	return _hit.size()


func _try_hit(body: Node3D) -> void:
	var e := body as Enemy
	if e == null or not e.is_alive():
		return
	var id: int = e.get_instance_id()
	if _hit.has(id):
		return
	_hit[id] = true
	var away: Vector3 = e.global_position - push_origin
	away.y = 0.0
	if away.length_squared() < 0.0001:
		away = direction
	e.take_damage(damage)
	if e.is_alive():
		e.apply_knockback(away.normalized(), knockback_distance)
	var parent := get_parent()
	if parent != null:
		Fx.burst(parent, e.get_aim_point(), splash_color, 16, 3.5, 0.1, 0.45)
