class_name GameManager
extends Node3D
## Root of main.tscn: wires Player, WaveManager and HUD; handles game over / restart.
## Restart resets state in place (no scene reload), so the UDP socket stays bound.

enum State { PLAYING, GAME_OVER }

@export var player: Player
@export var wave_manager: WaveManager
@export var hud: Hud
@export var projectiles_root: Node3D
@export var restart_skill: String = "earth"  # gesture that restarts from game over

var state: State = State.PLAYING


func _ready() -> void:
	hud.setup(player, wave_manager)
	player.died.connect(_on_player_died)
	player.gesture_received.connect(_on_gesture_received)
	wave_manager.start_game()


func _unhandled_input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key == null or not key.pressed or key.echo:
		return
	if key.keycode == KEY_R and state == State.GAME_OVER:
		get_viewport().set_input_as_handled()
		print("[game] restart (tombol R)")
		restart()


func is_game_over() -> bool:
	return state == State.GAME_OVER


func restart() -> void:
	wave_manager.stop()
	wave_manager.clear_enemies()
	for child: Node in projectiles_root.get_children():
		for group: StringName in [&"shield", &"spells"]:
			if child.is_in_group(group):
				child.remove_from_group(group)
		child.queue_free()
	player.reset_state()
	state = State.PLAYING
	hud.hide_game_over()
	wave_manager.start_game()


func _on_player_died() -> void:
	if state == State.GAME_OVER:
		return
	state = State.GAME_OVER
	wave_manager.stop()
	print("[game] GAME OVER di wave %d" % wave_manager.wave)
	hud.show_game_over(wave_manager.wave)


func _on_gesture_received(skill: String) -> void:
	if state != State.GAME_OVER or skill != restart_skill:
		return
	print("[game] restart (gestur %s)" % skill)
	# Deferred: the same packet's try_cast() runs right after this signal and must
	# still see game over (so it does not also cast an earth wall).
	call_deferred("_restart_if_game_over")


func _restart_if_game_over() -> void:
	if state == State.GAME_OVER:
		restart()
