class_name Enemy
extends CharacterBody3D
## Walks straight at the player on a flat arena (y stays 0), attacks in melee range.
## If an EarthWall (group "shield") blocks the path, it stops and attacks the wall.
## Collision: layer 3 "enemies"; mask world(1) + enemies(3) + shield(4).

signal died(enemy: Enemy)
signal damaged(enemy: Enemy, amount: float)

@export var max_hp: float = 50.0
@export var speed: float = 2.35
@export var damage: float = 10.0
@export var attack_interval: float = 1.0
@export var attack_range: float = 1.6
@export var knockback_time: float = 0.25
@export var body_color: Color = Color(0.36, 0.22, 0.5)
@export var death_color: Color = Color(0.7, 0.4, 1.0)

@export_group("Brute")
@export var brute_hp_mult: float = 2.5
@export var brute_speed_mult: float = 0.6
@export var brute_damage_mult: float = 1.5
@export var brute_scale: float = 1.45
@export var brute_color: Color = Color(0.55, 0.16, 0.14)

var hp: float = 0.0
var target: Player = null
var is_brute: bool = false

var _configured: bool = false
var _dead: bool = false
var _knock_velocity: Vector3 = Vector3.ZERO
var _knock_left: float = 0.0
var _attack_timer: float = 0.0
var _shield: EarthWall = null
var _material: StandardMaterial3D
var _base_color: Color
var _flash_tween: Tween
var _radius: float = 0.45
var _height: float = 1.8

@onready var _visual: Node3D = $Visual
@onready var _body_mesh: MeshInstance3D = $Visual/Body
@onready var _shape: CollisionShape3D = $CollisionShape3D


## Call BEFORE adding to the tree.
func configure(hp_value: float, speed_value: float, brute: bool = false) -> void:
	is_brute = brute
	max_hp = hp_value * (brute_hp_mult if brute else 1.0)
	speed = speed_value * (brute_speed_mult if brute else 1.0)
	if brute:
		damage *= brute_damage_mult
	hp = max_hp
	_configured = true


func _ready() -> void:
	if not _configured:
		hp = max_hp
	var base_shape := _shape.shape as CapsuleShape3D
	_radius = base_shape.radius
	_height = base_shape.height
	if is_brute:
		var s := CapsuleShape3D.new()
		s.radius = _radius * brute_scale
		s.height = _height * brute_scale
		_shape.shape = s
		_shape.position.y = s.height * 0.5 + 0.05
		_visual.scale = Vector3.ONE * brute_scale
		_radius = s.radius
		_height = s.height
	_material = Fx.make_material(brute_color if is_brute else body_color)
	_base_color = _material.albedo_color
	_body_mesh.material_override = _material


func _exit_tree() -> void:
	# Godot 4.3 dummy (headless) renderer prints "Parameter m is null" when an
	# instance with a material_override outlives its mesh during shutdown.
	_body_mesh.material_override = null


func _physics_process(delta: float) -> void:
	if _dead:
		return
	_attack_timer = maxf(_attack_timer - delta, 0.0)

	if _knock_left > 0.0:
		var step: float = minf(delta, _knock_left)
		_knock_left -= step
		velocity = _knock_velocity * (step / delta)
		move_and_slide()
		position.y = 0.0
		return

	if target == null or not is_instance_valid(target) or not target.is_alive():
		velocity = Vector3.ZERO
		return

	if _shield != null:
		if is_instance_valid(_shield) and _shield.is_active():
			velocity = Vector3.ZERO
			if _attack_timer <= 0.0:
				_shield.take_damage(damage)
				_attack_timer = attack_interval
				_lunge()
			return
		_shield = null

	var to: Vector3 = target.global_position - global_position
	to.y = 0.0
	var dist: float = to.length()
	if dist > 0.01:
		rotation.y = atan2(-to.x, -to.z)
	if dist <= attack_range:
		velocity = Vector3.ZERO
		if _attack_timer <= 0.0:
			target.take_damage(damage)
			_attack_timer = attack_interval
			_lunge()
		return

	velocity = to / dist * speed
	move_and_slide()
	position.y = 0.0
	for i: int in get_slide_collision_count():
		var wall := get_slide_collision(i).get_collider() as EarthWall
		if wall != null and wall.is_active():
			_shield = wall
			break


func take_damage(amount: float) -> void:
	if _dead:
		return
	hp = maxf(hp - amount, 0.0)
	damaged.emit(self, amount)
	_flash()
	if hp <= 0.0:
		_die()


## Pushes the enemy `distance` metres along `dir` (horizontal) over knockback_time.
func apply_knockback(dir: Vector3, distance: float) -> void:
	if _dead:
		return
	var d := Aim.flat(dir)
	_knock_velocity = d * (distance / knockback_time)
	_knock_left = knockback_time
	_shield = null


## Removes the enemy without a death event (restart / cleanup).
func despawn() -> void:
	_dead = true
	if is_in_group("enemies"):
		remove_from_group("enemies")
	queue_free()


func is_alive() -> bool:
	return not _dead and hp > 0.0


func is_blocked_by_shield() -> bool:
	return _shield != null and is_instance_valid(_shield) and _shield.is_active()


func get_aim_point() -> Vector3:
	return global_position + Vector3(0.0, _height * 0.5 + 0.05, 0.0)


func get_hit_radius() -> float:
	return _radius


func get_body_height() -> float:
	return _height


# --------------------------------------------------------------- internals
func _die() -> void:
	_dead = true
	if is_in_group("enemies"):
		remove_from_group("enemies")
	velocity = Vector3.ZERO
	set_deferred("collision_layer", 0)
	set_deferred("collision_mask", 0)
	var parent := get_parent()
	if parent != null:
		Fx.burst(parent, get_aim_point(), death_color, 30, 4.5, 0.12, 0.7)
	died.emit(self)
	queue_free()


func _flash() -> void:
	if _material == null:
		return
	if _flash_tween != null:
		_flash_tween.kill()
	_material.albedo_color = Color(1.0, 0.15, 0.1)
	_flash_tween = create_tween()
	_flash_tween.tween_property(_material, "albedo_color", _base_color, 0.2)


func _lunge() -> void:
	var tw := create_tween()
	tw.tween_property(_visual, "position:z", -0.35, 0.08)
	tw.tween_property(_visual, "position:z", 0.0, 0.15)
