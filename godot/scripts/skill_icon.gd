class_name SkillIcon
extends Control
## One spell icon: coloured panel, dark cooldown overlay that shrinks from the top
## (height = remaining / total), seconds left, key hint. Pulses on cast, shakes red
## on rejection.

@export var skill: String = "fire"
@export var display_name: String = "Api"
@export var key_hint: String = "1"
@export var color: Color = Color(1.0, 0.4, 0.15)

var _ratio: float = 0.0
var _remaining: float = 0.0
var _pulse_tween: Tween
var _shake_tween: Tween
var _style: StyleBoxFlat

@onready var _box: Panel = $Box
@onready var _overlay: ColorRect = $Box/Overlay
@onready var _name_label: Label = $Box/NameLabel
@onready var _cd_label: Label = $Box/CooldownLabel
@onready var _key_label: Label = $KeyLabel


func _ready() -> void:
	_style = StyleBoxFlat.new()
	_style.bg_color = color
	_style.set_corner_radius_all(10)
	_style.set_border_width_all(3)
	_style.border_color = color.lightened(0.45)
	_box.add_theme_stylebox_override("panel", _style)
	_name_label.text = display_name
	_key_label.text = "[%s]" % key_hint
	_box.pivot_offset = _box.size * 0.5
	set_cooldown(0.0, 1.0)


func set_cooldown(remaining: float, total: float) -> void:
	_remaining = maxf(remaining, 0.0)
	_ratio = clampf(_remaining / total, 0.0, 1.0) if total > 0.0 else 0.0
	var w: float = _box.size.x
	var h: float = _box.size.y
	_overlay.position = Vector2(0.0, h * (1.0 - _ratio))
	_overlay.size = Vector2(w, h * _ratio)
	_overlay.visible = _ratio > 0.0
	_cd_label.text = ("%.1f" % _remaining) if _remaining > 0.0 else ""
	_style.border_color = color.lightened(0.45) if _ratio <= 0.0 else Color(0.25, 0.25, 0.25)


func get_cooldown_ratio() -> float:
	return _ratio


func get_overlay_height() -> float:
	return _overlay.size.y if _overlay.visible else 0.0


func pulse() -> void:
	if _pulse_tween != null:
		_pulse_tween.kill()
	_box.pivot_offset = _box.size * 0.5
	_box.scale = Vector2(1.18, 1.18)
	_box.modulate = Color(1.6, 1.6, 1.6)
	_pulse_tween = create_tween().set_parallel(true)
	_pulse_tween.tween_property(_box, "scale", Vector2.ONE, 0.25).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	_pulse_tween.tween_property(_box, "modulate", Color.WHITE, 0.25)


func shake() -> void:
	if _shake_tween != null:
		_shake_tween.kill()
	_box.position.x = 0.0
	_box.modulate = Color(1.0, 0.35, 0.35)
	_shake_tween = create_tween()
	for offset: float in [-8.0, 8.0, -6.0, 6.0, -3.0, 0.0]:
		_shake_tween.tween_property(_box, "position:x", offset, 0.035)
	_shake_tween.tween_property(_box, "modulate", Color.WHITE, 0.15)
