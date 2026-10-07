class_name Fireball
extends Node3D
## Fire spell: fast single-target projectile with light homing toward the aim-assist
## target. Hit test is a swept segment against enemies (no tunnelling at any
## time_scale) plus a ray against world geometry (layer 1). Passes through shields.

const WORLD_MASK: int = 1  # layer 1 "world"

@export var speed: float = 30.0
@export var damage: float = 40.0
@export var hit_radius: float = 0.35
@export var max_distance: float = 45.0
@export var homing_turn_rate: float = 4.0  # rad/s
@export var explosion_color: Color = Color(1.0, 0.45, 0.1)

var direction: Vector3 = Vector3.FORWARD
var target: Enemy = null
var _travelled: float = 0.0
var _done: bool = false


func launch(dir: Vector3, homing_target: Enemy) -> void:
	direction = dir.normalized() if dir.length_squared() > 0.000001 else Vector3.FORWARD
	target = homing_target


func _physics_process(delta: float) -> void:
	if _done:
		return
	if target != null and (not is_instance_valid(target) or not target.is_alive()):
		target = null
	if target != null:
		var desired: Vector3 = (target.get_aim_point() - global_position).normalized()
		direction = _turn_towards(direction, desired, homing_turn_rate * delta)

	var from: Vector3 = global_position
	var step: float = speed * delta
	var to: Vector3 = from + direction * step

	var hit: Enemy = _sweep_enemies(from, to)
	if hit != null:
		global_position = hit.get_aim_point()
		hit.take_damage(damage)
		_explode()
		return

	var query := PhysicsRayQueryParameters3D.create(from, to, WORLD_MASK)
	var result: Dictionary = get_world_3d().direct_space_state.intersect_ray(query)
	if not result.is_empty():
		global_position = result["position"]
		_explode()
		return

	global_position = to
	_travelled += step
	if _travelled >= max_distance:
		_done = true
		queue_free()


func _sweep_enemies(from: Vector3, to: Vector3) -> Enemy:
	var a := Vector2(from.x, from.z)
	var b := Vector2(to.x, to.z)
	var ab := b - a
	var ab_len2: float = ab.length_squared()
	var best: Enemy = null
	var best_t: float = INF
	for node: Node in get_tree().get_nodes_in_group("enemies"):
		var e := node as Enemy
		if e == null or not e.is_alive():
			continue
		var p := Vector2(e.global_position.x, e.global_position.z)
		var t: float = 0.0
		if ab_len2 > 0.0:
			t = clampf((p - a).dot(ab) / ab_len2, 0.0, 1.0)
		if p.distance_to(a + ab * t) > hit_radius + e.get_hit_radius():
			continue
		var y: float = lerpf(from.y, to.y, t)
		var base_y: float = e.global_position.y
		if y < base_y - hit_radius or y > base_y + e.get_body_height() + hit_radius:
			continue
		if t < best_t:
			best_t = t
			best = e
	return best


func _explode() -> void:
	_done = true
	var parent := get_parent()
	if parent != null:
		Fx.burst(parent, global_position, explosion_color, 28, 5.0, 0.13, 0.5)
		Fx.flash_light(parent, global_position, explosion_color, 5.0, 6.0, 0.2)
	queue_free()


static func _turn_towards(current: Vector3, desired: Vector3, max_angle: float) -> Vector3:
	var angle: float = current.angle_to(desired)
	if angle <= max_angle or angle < 0.0001:
		return desired
	return current.slerp(desired, max_angle / angle).normalized()
