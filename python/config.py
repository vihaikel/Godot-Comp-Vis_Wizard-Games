"""All tunable values (Phases 1-3). Nothing tunable should live outside this file."""
import os
import sys

# --- Camera ---------------------------------------------------------------
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
TARGET_FPS = 30
# 'dshow' | 'default'. DirectShow is only honoured on Windows (win32).
CAMERA_BACKEND = "dshow" if sys.platform == "win32" else "default"
# Startup default for the horizontal flip (selfie view). Runtime: 's' toggles it
# (tracker.set_mirror). Handedness labels are corrected automatically: MediaPipe
# assumes a mirrored (selfie) input, so with MIRROR off the labels are swapped
# internally and your physical right hand still reads 'Right'.
MIRROR = True
CAPTURE_RETRY_SLEEP_S = 0.005  # pause after a failed cap.read()
CAPTURE_JOIN_TIMEOUT_S = 2.0

# --- Handedness -----------------------------------------------------------
# Manual override ON TOP of the automatic mirror correction (see MIRROR).
# effective swap = SWAP_HANDEDNESS XOR (not mirror). Runtime toggle: 'h' key
# (runtime copy only, never written back to this file).
SWAP_HANDEDNESS = False

# --- MediaPipe Hand Landmarker -------------------------------------------
NUM_HANDS = 2
MIN_HAND_DETECTION_CONFIDENCE = 0.5
MIN_HAND_PRESENCE_CONFIDENCE = 0.5
MIN_TRACKING_CONFIDENCE = 0.5
HISTORY_LEN = 15  # samples kept per hand (~500 ms @ 30 fps; gestures look back <= 300 ms)

_HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_HERE, "models", "hand_landmarker.task")
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)

# --- Debug window / overlay ----------------------------------------------
DEBUG_WINDOW = True
WINDOW_TITLE = "Phase 1 - Hand Tracking Debug"
FPS_AVG_WINDOW = 30  # moving-average window (number of frame intervals)
HAND_STALE_MS = 200  # a hand sample older than this is treated as "not visible"
MAIN_IDLE_SLEEP_S = 0.001  # sleep when no new frame is available
CONSOLE_FPS_INTERVAL_S = 1.0  # console FPS print when DEBUG_WINDOW is False
QUIT_KEYS = (ord("q"), 27)  # q or ESC
MIRROR_KEY = ord("s")  # toggle camera mirror (labels auto-corrected)
SWAP_KEY = ord("h")  # toggle manual Left/Right label override

LANDMARK_RADIUS_PX = 4
BONE_THICKNESS_PX = 2
LANDMARK_COLOR_BGR = (0, 255, 255)
BONE_COLOR_BGR = (0, 200, 0)
LABEL_COLOR_BGR = (255, 255, 255)
TEXT_COLOR_BGR = (0, 255, 0)
TEXT_SCALE = 0.6
TEXT_THICKNESS = 2
LABEL_OFFSET_PX = (10, -10)  # offset from wrist

# --- Gesture debug overlay / recording (main_gestures.py) ------------------
GESTURE_WINDOW_TITLE = "Phase 2 - Gesture Debug"
EVENT_FLASH_MS = 500  # ms, how long the big skill name stays on screen
EVENT_FLASH_PERIOD_MS = 100  # ms, blink period of the big skill name
EVENT_TEXT_SCALE = 2.0
EVENT_TEXT_THICKNESS = 4
EVENT_COLORS_BGR = {
    "fire": (0, 80, 255),
    "water": (255, 160, 0),
    "lightning": (0, 255, 255),
    "earth": (60, 140, 90),
}
RECORD_KEY = ord("r")
RECORDINGS_DIR = os.path.join(_HERE, "recordings")

# --- Gestures (Phase 2) ----------------------------------------------------
# Units: "size" = hand_size() = 2D distance WRIST(0)->MIDDLE_MCP(9) in
# pseudo-pixels (x*FRAME_WIDTH, y*FRAME_HEIGHT). "growth" = size_now/size_then - 1.
# Normalized y: 0 = top of image, 1 = bottom.
HAND_SIZE_MODE = "2d"  # '2d' (default, x/y only) | '3d' (also uses z*FRAME_WIDTH; rotation-robust but z is noisier)
POSE_STABLE_SAMPLES = 3  # samples; the last N samples must share the same pose
FINGER_EXTENDED_RATIO = 1.15  # dimensionless; dist(tip,wrist) > dist(pip,wrist)*this -> extended
FINGER_FOLDED_RATIO = 1.0  # dimensionless; dist(tip,wrist) < dist(pip,wrist)*this -> folded
WINDOW_MIN_COVERAGE = 0.6  # fraction; history must reach back >= lookback*this or metric is None
CONF_SATURATION_RATIO = 2.0  # metric/threshold ratio at which the confidence reaches 1.0

FIRE_CHEST_MIN_Y = 0.35  # normalized y of the wrist at window start must be >= this; None disables
FIRE_LOOKBACK_MS = 150  # ms
FIRE_GROWTH_MIN = 0.25  # growth (fraction) within FIRE_LOOKBACK_MS needed to fire
FIRE_REARM_GROWTH = 0.08  # growth (fraction) must fall below this before fire can trigger again

WATER_LOOKBACK_MS = 200  # ms
WATER_GROWTH_MIN = 0.20  # growth (fraction) each hand needs within WATER_LOOKBACK_MS
WATER_REARM_GROWTH = 0.08  # growth (fraction) both hands must fall below to re-arm
WATER_SYNC_MS = 200  # ms; max time between the two hands crossing WATER_GROWTH_MIN

LIGHTNING_LOOKBACK_MS = 250  # ms
LIGHTNING_MIN_VEL = 4.0  # sizes/second, mean downward speed of index+middle tips
LIGHTNING_MIN_TRAVEL = 0.8  # sizes, net downward travel within LIGHTNING_LOOKBACK_MS
LIGHTNING_REARM_RATIO = 0.5  # re-arm once downward speed < LIGHTNING_MIN_VEL * this

EARTH_STILL_WINDOW_MS = 300  # ms, window over which stillness is measured
EARTH_STILL_MIN_SPAN_MS = 150  # ms, minimum history span before stillness is judged
EARTH_MAX_DRIFT = 0.25  # sizes, max wrist travel (pairwise extent) inside the window
EARTH_MAX_SCALE_CHANGE = 0.10  # fraction, max (size_max/size_min - 1) inside the window
EARTH_HOLD_MS = 1000  # ms the left open palm must be held still
EARTH_GAP_TOLERANCE_MS = 150  # ms; pose/stillness/zone breaks longer than this reset the hold
# Earth zone: the left palm center (mean of landmarks 0,5,9,13,17, normalized) must
# be in the upper-middle of the frame (chest/face height). Leaving the zone counts
# as breaking the pose (same gap tolerance). Set either value to None to disable it.
EARTH_ZONE_X = (0.2, 0.8)  # normalized x range (inclusive)
EARTH_ZONE_MAX_Y = 0.65  # normalized y; palm center y must be <= this (0 = top)
# What the RIGHT hand may be doing while Earth is held:
#   "not_open" (default): right hand hidden or not an open palm -> prevents Earth
#                firing while both palms are held up getting ready for Water
#   "absent":   right hand must not be visible at all (strictest)
#   "any":      ignore the right hand (original behaviour)
EARTH_RIGHT_HAND = "not_open"

GLOBAL_LOCK_MS = 350  # ms; after any event no detector may emit (game cooldowns live in Godot)

# --- Steering ----------------------------------------------------------------
# Kemudi: both palms OPEN facing the camera, slid together left/right of the frame
# center. offset = mean palm-center x of both hands - 0.5 (negated for a raw,
# non-mirrored frame so the direction is always the player's PHYSICAL left/right).
# Output value in [-1, 1] (negative = turn left). See steering.py / PROTOCOL.md.
STEER_LOOKBACK_MS = 150  # ms; window for the "not pushing" check
STEER_MAX_GROWTH = 0.08  # fraction; |scale_growth| of EACH hand must stay <= this (else 'pushing')
STEER_DEADZONE = 0.08  # normalized x; |offset| <= this -> 0
STEER_FULL_OFFSET = 0.30  # normalized x; |offset| >= this -> full turn (+-1)
STEER_EXPONENT = 1.0  # response curve on the post-deadzone fraction (1 = linear, >1 = finer near center)
STEER_SMOOTHING = 0.5  # EMA factor per update: value += k * (raw - value)
STEER_SNAP_ZERO = 0.02  # when raw == 0 and |value| < this, value snaps to exactly 0
STEER_SUPPRESS_AFTER_WATER_MS = 500  # ms; steering forced to 0 after a 'water' event
STEER_HAND_LOST_MS = 50  # ms; a hand whose newest sample is older than this counts as gone
#   (tolerates ONE missed detection at 30 fps; raise to ~100 if det FPS < 20)
STEER_POSE_GLITCH_SAMPLES = 1  # once engaged, up to this many non-OPEN samples among the
#   last POSE_STABLE_SAMPLES are tolerated (single-frame pose glitch); engaging needs a
#   fully stable OPEN pose (same rule as gestures.py)
# Sending (sender.send_steer):
STEER_SEND_HZ = 30  # max steer packets per second (the single "back to 0" packet is exempt)
STEER_SEND_EPS = 0.02  # a non-zero value that changed by more than this is sent at once (rate-limited)
STEER_KEEPALIVE_S = 0.1  # unchanged non-zero value is re-sent this often (Godot zeroes steer after 0.3 s silence)
STEER_BAR_COLOR_BGR = (255, 200, 0)  # overlay bar (main.py preview / main_gestures.py)

# --- Network (Phase 3) ---
UDP_HOST = "127.0.0.1"
UDP_PORT = 4242
PROTOCOL_VERSION = 1
SEND_DEBOUNCE_MS = 100      # per skill
HEARTBEAT_INTERVAL_S = 0.5
# Heartbeats are only sent while the camera delivers frames; if no new frame for
# this long, heartbeats stop and Godot shows "Menunggu Python..." after its timeout.
CAMERA_STALE_S = 1.0
