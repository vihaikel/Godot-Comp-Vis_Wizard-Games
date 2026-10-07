class_name Fx
extends RefCounted
## Small helpers for primitive-only visuals (no external assets).


## Unshaded/emissive material for primitives and particles.
static func make_material(color: Color, emission_energy: float = 0.0, unshaded: bool = false) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = color
	if color.a < 1.0:
		m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	if unshaded:
		m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	if emission_energy > 0.0:
		m.emission_enabled = true
		m.emission = Color(color.r, color.g, color.b)
		m.emission_energy_multiplier = emission_energy
	return m


## One-shot particle burst (explosion, death puff). Frees itself afterwards.
## `parent` must be inside the scene tree.
static func burst(parent: Node, pos: Vector3, color: Color, amount: int = 24,
		speed: float = 4.0, size: float = 0.14, lifetime: float = 0.6) -> CPUParticles3D:
	var p := CPUParticles3D.new()
	var mesh := SphereMesh.new()
	mesh.radius = size
	mesh.height = size * 2.0
	mesh.radial_segments = 6
	mesh.rings = 3
	mesh.material = make_material(color, 2.0, true)
	p.mesh = mesh
	p.amount = maxi(amount, 1)
	p.lifetime = lifetime
	p.one_shot = true
	p.explosiveness = 1.0
	p.direction = Vector3.UP
	p.spread = 180.0
	p.initial_velocity_min = speed * 0.5
	p.initial_velocity_max = speed
	p.gravity = Vector3(0.0, -6.0, 0.0)
	p.scale_amount_min = 0.5
	p.scale_amount_max = 1.0
	p.emitting = false
	parent.add_child(p)
	p.global_position = pos
	p.emitting = true
	parent.get_tree().create_timer(lifetime + 0.3).timeout.connect(p.queue_free)
	return p


## Short-lived point light (muzzle flash, lightning, explosion).
static func flash_light(parent: Node, pos: Vector3, color: Color, energy: float = 4.0,
		light_range: float = 6.0, duration: float = 0.15) -> OmniLight3D:
	var light := OmniLight3D.new()
	light.light_color = color
	light.light_energy = energy
	light.omni_range = light_range
	parent.add_child(light)
	light.global_position = pos
	var tw := light.create_tween()
	tw.tween_property(light, "light_energy", 0.0, duration)
	tw.tween_callback(light.queue_free)
	return light
