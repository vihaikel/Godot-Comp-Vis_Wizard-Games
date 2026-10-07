class_name SpellCaster
extends Node
## Spawns spell effects for Player.cast_*(). Lives as a child of Player.
## Balancing numbers live in the spell scripts/scenes (fireball.gd, water_wave.gd,
## lightning.gd, earth_wall.gd); aim-assist and placement numbers live here.

@export var player_node: Node3D
@export var camera: Camera3D
@export var projectiles_root: Node3D
@export var fireball_scene: PackedScene
@export var water_scene: PackedScene
@export var wall_scene: PackedScene
@export var aim_cone_deg: float = 45.0
@export var aim_range: float = 45.0
@export var wall_distance: float = 3.0
@export var hand_offset: Vector3 = Vector3(0.25, -0.3, -0.7)  # camera space: right, up, forward(-z)

var _wall: EarthWall = null


func cast_fire() -> Fireball:
	var origin: Vector3 = get_hand_position()
	var target: Enemy = find_aim_target()
	var dir: Vector3 = get_view_forward()
	if target != null:
		dir = (target.get_aim_point() - origin).normalized()
	var fb := fireball_scene.instantiate() as Fireball
	projectiles_root.add_child(fb)
	fb.global_position = origin
	fb.launch(dir, target)
	Fx.flash_light(projectiles_root, origin, Color(1.0, 0.5, 0.15), 3.0, 4.0, 0.12)
	return fb


func cast_water() -> WaterWave:
	var base: Vector3 = player_node.global_position
	var target: Enemy = find_aim_target()
	var dir: Vector3 = Aim.flat(get_view_forward())
	if target != null:
		dir = Aim.flat(target.global_position - base)
	var wave := water_scene.instantiate() as WaterWave
	projectiles_root.add_child(wave)
	wave.global_position = base + dir * 1.2
	wave.launch(dir, base)
	return wave


func cast_lightning() -> LightningStrike:
	var strike := LightningStrike.new()
	strike.name = "Lightning"
	strike.add_to_group("spells")
	projectiles_root.add_child(strike)
	strike.strike(get_hand_position() + Vector3(0, 0.4, 0), find_aim_target(), get_view_forward())
	return strike


func cast_earth() -> EarthWall:
	if _wall != null and is_instance_valid(_wall):
		_wall.remove_now()
	var fwd: Vector3 = Aim.flat(get_view_forward())
	var base: Vector3 = player_node.global_position
	base.y = 0.0
	_wall = wall_scene.instantiate() as EarthWall
	projectiles_root.add_child(_wall)
	_wall.place(base + fwd * wall_distance, fwd)
	return _wall


func get_active_wall() -> EarthWall:
	if _wall != null and is_instance_valid(_wall) and _wall.is_active():
		return _wall
	return null


func find_aim_target() -> Enemy:
	return Aim.find_target(get_tree(), player_node.global_position, get_view_forward(), aim_cone_deg, aim_range)


func get_view_forward() -> Vector3:
	return -camera.global_basis.z


func get_hand_position() -> Vector3:
	return camera.global_transform * hand_offset
