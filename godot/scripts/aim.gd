class_name Aim
extends RefCounted
## Aim assist: gestures cannot point, so spells pick the NEAREST living enemy whose
## horizontal direction lies within +-max_angle_deg of the camera's view direction.


static func flat(v: Vector3) -> Vector3:
	var f := Vector3(v.x, 0.0, v.z)
	if f.length_squared() < 0.000001:
		return Vector3.FORWARD
	return f.normalized()


## Returns the nearest living Enemy inside the cone, or null.
static func find_target(tree: SceneTree, origin: Vector3, forward: Vector3,
		max_angle_deg: float = 45.0, max_range: float = 45.0) -> Enemy:
	var fwd := flat(forward)
	var cos_limit := cos(deg_to_rad(max_angle_deg))
	var best: Enemy = null
	var best_dist := INF
	for node: Node in tree.get_nodes_in_group("enemies"):
		var e := node as Enemy
		if e == null or not e.is_alive():
			continue
		var to := e.global_position - origin
		to.y = 0.0
		var dist := to.length()
		if dist > max_range or dist < 0.001:
			continue
		if fwd.dot(to / dist) < cos_limit:
			continue
		if dist < best_dist:
			best_dist = dist
			best = e
	return best


## Nearest living enemy to `from` (horizontal distance) within `radius`,
## excluding instance ids that are keys of `exclude`.
static func nearest_enemy(tree: SceneTree, from: Vector3, radius: float, exclude: Dictionary) -> Enemy:
	var best: Enemy = null
	var best_dist := INF
	for node: Node in tree.get_nodes_in_group("enemies"):
		var e := node as Enemy
		if e == null or not e.is_alive() or exclude.has(e.get_instance_id()):
			continue
		var dv := e.global_position - from
		dv.y = 0.0
		var d := dv.length()
		if d <= radius and d < best_dist:
			best_dist = d
			best = e
	return best
