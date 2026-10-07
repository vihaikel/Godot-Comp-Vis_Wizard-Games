class_name LightningStrike
extends Node3D
## Lightning spell: instant hit on the aim-assist target, then chains (hop by hop)
## to at most `max_chain` other enemies, each the nearest un-hit enemy within
## `chain_radius` of the previous hop. Visual: jagged thin cylinders + light flash.

@export var primary_damage: float = 35.0
@export var chain_damage: float = 25.0
@export var chain_radius: float = 6.0
@export var max_chain: int = 2
@export var miss_distance: float = 15.0
@export var duration: float = 0.22
@export var bolt_radius: float = 0.045
@export var bolt_color: Color = Color(0.8, 0.88, 1.0)
@export var glow_color: Color = Color(1.0, 0.95, 0.4)

var hits: Array[Enemy] = []  # enemies struck, in order (primary first)

# One shared unit cylinder (height 1, scaled per segment). Sharing also avoids a
# Godot 4.3 headless-renderer error when a mesh is freed together with its instance.
static var _unit_cylinder: CylinderMesh = null
var _segments: Array[MeshInstance3D] = []


## `parent` must already contain this node. Returns the enemies struck.
func strike(origin: Vector3, target: Enemy, forward: Vector3) -> Array[Enemy]:
	global_transform = Transform3D.IDENTITY
	var points: Array[Vector3] = [origin]
	if target != null and target.is_alive():
		var hit_ids: Dictionary = {}
		var current: Enemy = target
		var dmg: float = primary_damage
		while current != null:
			hit_ids[current.get_instance_id()] = true
			hits.append(current)
			var pos: Vector3 = current.get_aim_point()
			points.append(pos)
			current.take_damage(dmg)
			if hits.size() > max_chain:
				break
			current = Aim.nearest_enemy(get_tree(), pos, chain_radius, hit_ids)
			dmg = chain_damage
	else:
		var end: Vector3 = origin + Aim.flat(forward) * miss_distance
		end.y = 0.0
		points.append(end)

	var mat := Fx.make_material(bolt_color, 6.0, true)
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	for i: int in range(points.size() - 1):
		_draw_bolt(points[i], points[i + 1], mat)
	Fx.flash_light(self, points[1], glow_color, 8.0, 10.0, duration)
	var parent := get_parent()
	for i: int in range(1, points.size()):
		Fx.burst(parent, points[i], glow_color, 10, 3.0, 0.07, 0.3)
	var tw := create_tween()
	tw.tween_property(mat, "albedo_color:a", 0.0, duration)
	tw.tween_callback(queue_free)
	return hits


func _draw_bolt(a: Vector3, b: Vector3, mat: Material) -> void:
	var length: float = a.distance_to(b)
	var n: int = clampi(int(length / 1.2), 2, 14)
	var dir: Vector3 = (b - a).normalized()
	var side: Vector3 = dir.cross(Vector3.UP)
	if side.length_squared() < 0.0001:
		side = Vector3.RIGHT
	side = side.normalized()
	var up: Vector3 = side.cross(dir).normalized()
	var prev: Vector3 = a
	for k: int in range(1, n + 1):
		var p: Vector3 = b
		if k < n:
			p = a.lerp(b, float(k) / n) + side * randf_range(-0.35, 0.35) + up * randf_range(-0.35, 0.35)
		_segment(prev, p, mat)
		prev = p


func _exit_tree() -> void:
	for mi: MeshInstance3D in _segments:
		if is_instance_valid(mi):
			mi.material_override = null


func _segment(a: Vector3, b: Vector3, mat: Material) -> void:
	var length: float = a.distance_to(b)
	if length < 0.001:
		return
	if _unit_cylinder == null:
		_unit_cylinder = CylinderMesh.new()
		_unit_cylinder.top_radius = 1.0
		_unit_cylinder.bottom_radius = 1.0
		_unit_cylinder.height = 1.0
		_unit_cylinder.radial_segments = 4
		_unit_cylinder.rings = 1
	var mi := MeshInstance3D.new()
	mi.mesh = _unit_cylinder
	mi.material_override = mat
	mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(mi)
	_segments.append(mi)
	var dir: Vector3 = (b - a) / length
	var basis := Basis(Vector3.RIGHT, PI) if dir.dot(Vector3.UP) < -0.9999 else Basis(Quaternion(Vector3.UP, dir))
	basis = basis * Basis.from_scale(Vector3(bolt_radius, length, bolt_radius))
	mi.global_transform = Transform3D(basis, (a + b) * 0.5)
