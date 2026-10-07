class_name EarthWall
extends StaticBody3D
## Earth spell: a wall that rises from the ground, blocks enemies (layer 4 "shield"),
## has HP and a lifetime. Spells (layer 5) pass through it.

signal destroyed(wall: EarthWall)

@export var max_hp: float = 120.0
@export var lifetime: float = 6.0
@export var rise_time: float = 0.35
@export var sink_time: float = 0.4
@export var sink_depth: float = 2.7
@export var color: Color = Color(0.45, 0.36, 0.2)
@export var damaged_color: Color = Color(0.25, 0.3, 0.16)

var hp: float = 0.0
var _age: float = 0.0
var _active: bool = true
var _material: StandardMaterial3D
var _move_tween: Tween

@onready var _mesh: MeshInstance3D = $Visual/Mesh


func _ready() -> void:
	hp = max_hp
	_material = Fx.make_material(color)
	_mesh.material_override = _material


func _exit_tree() -> void:
	_mesh.material_override = null  # see Enemy._exit_tree (headless renderer quirk)


## Places the wall with its base centre at `ground_pos`, its face toward `facing`
## (horizontal), and animates it rising out of the ground.
func place(ground_pos: Vector3, facing: Vector3) -> void:
	global_transform = Transform3D(Basis.looking_at(Aim.flat(facing), Vector3.UP), ground_pos)
	var final_y: float = position.y
	position.y = final_y - sink_depth
	_move_tween = create_tween()
	_move_tween.tween_property(self, "position:y", final_y, rise_time) \
			.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	var parent := get_parent()
	if parent != null:
		Fx.burst(parent, ground_pos + Vector3(0, 0.2, 0), Color(0.5, 0.4, 0.25), 30, 3.5, 0.16, 0.7)


func _process(delta: float) -> void:
	if not _active:
		return
	_age += delta
	if _age >= lifetime:
		crumble()


func take_damage(amount: float) -> void:
	if not _active:
		return
	hp = maxf(hp - amount, 0.0)
	_material.albedo_color = damaged_color.lerp(color, clampf(hp / maxf(max_hp, 0.001), 0.0, 1.0))
	if hp <= 0.0:
		crumble()


func is_active() -> bool:
	return _active


func get_age() -> float:
	return _age


## Lifetime over or destroyed: stop blocking immediately, sink, then free.
func crumble() -> void:
	if not _active:
		return
	_deactivate()
	var parent := get_parent()
	if parent != null:
		Fx.burst(parent, global_position + Vector3(0, 0.5, 0), Color(0.5, 0.4, 0.25), 24, 3.0, 0.16, 0.6)
	if _move_tween != null:
		_move_tween.kill()
	_move_tween = create_tween()
	_move_tween.tween_property(self, "position:y", position.y - sink_depth, sink_time)
	_move_tween.tween_callback(queue_free)


## Replaced by a newer wall: remove at once.
func remove_now() -> void:
	if _active:
		_deactivate()
	queue_free()


func _deactivate() -> void:
	_active = false
	if is_in_group("shield"):
		remove_from_group("shield")
	set_deferred("collision_layer", 0)
	destroyed.emit(self)
