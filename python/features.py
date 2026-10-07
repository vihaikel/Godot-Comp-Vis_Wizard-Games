"""Per-sample and per-history hand features. Pure Python + numpy (no mediapipe/cv2).

Coordinate conventions
- sample.landmarks: 21 (x, y, z); x, y normalized 0-1 (y grows DOWNWARD),
  z relative to the wrist with roughly the same scale as x.
- sample.world: 21 (x, y, z) in meters (MediaPipe hand_world_landmarks), or [].
- "pseudo-pixels": (x*FRAME_WIDTH, y*FRAME_HEIGHT, z*FRAME_WIDTH). Used so the
  4:3 aspect ratio does not distort distances.
- "size": hand_size() in pseudo-pixels. Motion metrics are expressed in sizes
  so they do not depend on how far the player stands from the camera.
"""
import math
from dataclasses import dataclass, field

import numpy as np

import config

WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_TIP = 20
PALM_POINTS = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)

FINGERS = {  # name -> (pip, tip)
    "index": (INDEX_PIP, INDEX_TIP),
    "middle": (MIDDLE_PIP, MIDDLE_TIP),
    "ring": (RING_PIP, RING_TIP),
    "pinky": (PINKY_PIP, PINKY_TIP),
}

EXTENDED = "ext"
FOLDED = "fold"

POSE_FIST = "FIST"
POSE_OPEN = "OPEN"
POSE_TWO = "TWO"


@dataclass
class HandSample:
    timestamp_ms: int
    landmarks: list  # list[(x, y, z)]; x,y normalized 0-1
    score: float
    world: list = field(default_factory=list)  # list[(x, y, z)] meters; [] if unavailable


# --------------------------------------------------------------------------
# Per-sample features
# --------------------------------------------------------------------------
def pixel_points(s, cfg=config):
    """21x3 array in pseudo-pixels (x*W, y*H, z*W)."""
    a = np.asarray(s.landmarks, dtype=float)
    return a * np.array([cfg.FRAME_WIDTH, cfg.FRAME_HEIGHT, cfg.FRAME_WIDTH], dtype=float)


def hand_size(s, cfg=config):
    """Distance WRIST->MIDDLE_MCP in pseudo-pixels.

    HAND_SIZE_MODE '2d' uses x/y only; '3d' also uses z (less sensitive to the
    hand pitching toward the camera, but MediaPipe's z is noisier).
    """
    p = pixel_points(s, cfg)
    d = p[MIDDLE_MCP] - p[WRIST]
    if getattr(cfg, "HAND_SIZE_MODE", "2d") == "3d":
        return float(math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2))
    return float(math.hypot(d[0], d[1]))


def hand_size_norm(s, cfg=config):
    """hand_size expressed as a fraction of the frame width."""
    return hand_size(s, cfg) / cfg.FRAME_WIDTH


def palm_center(s):
    """(x, y) normalized: mean of landmarks 0, 5, 9, 13, 17 (y grows downward)."""
    xs = [s.landmarks[i][0] for i in PALM_POINTS]
    ys = [s.landmarks[i][1] for i in PALM_POINTS]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def in_earth_zone(s, cfg=config):
    """True if the palm center is inside EARTH_ZONE_X / below EARTH_ZONE_MAX_Y.
    Each limit set to None disables that part of the check."""
    x, y = palm_center(s)
    zx = getattr(cfg, "EARTH_ZONE_X", None)
    zy = getattr(cfg, "EARTH_ZONE_MAX_Y", None)
    if zx is not None and not (zx[0] <= x <= zx[1]):
        return False
    if zy is not None and y > zy:
        return False
    return True


def wrist_px(s, cfg=config):
    p = pixel_points(s, cfg)
    return float(p[WRIST][0]), float(p[WRIST][1])


def finger_states(s, cfg=config):
    """{finger: 'ext' | 'fold' | None}. Uses world landmarks (3D meters) if present,
    else the pseudo-pixel 3D landmarks as a fallback."""
    if s.world and len(s.world) == 21:
        p = np.asarray(s.world, dtype=float)
    else:
        p = pixel_points(s, cfg)
    w = p[WRIST]
    out = {}
    for name, (pip, tip) in FINGERS.items():
        d_tip = float(np.linalg.norm(p[tip] - w))
        d_pip = float(np.linalg.norm(p[pip] - w))
        if d_tip > d_pip * cfg.FINGER_EXTENDED_RATIO:
            out[name] = EXTENDED
        elif d_tip < d_pip * cfg.FINGER_FOLDED_RATIO:
            out[name] = FOLDED
        else:
            out[name] = None
    return out


def is_fist(s, cfg=config, states=None):
    st = states or finger_states(s, cfg)
    return all(st[f] == FOLDED for f in FINGERS)


def is_open_palm(s, cfg=config, states=None):
    # Thumb is deliberately ignored.
    st = states or finger_states(s, cfg)
    return all(st[f] == EXTENDED for f in FINGERS)


def is_two_fingers(s, cfg=config, states=None):
    st = states or finger_states(s, cfg)
    return (st["index"] == EXTENDED and st["middle"] == EXTENDED
            and st["ring"] == FOLDED and st["pinky"] == FOLDED)


def classify_pose(s, cfg=config):
    """'FIST' | 'OPEN' | 'TWO' | None."""
    st = finger_states(s, cfg)
    if is_fist(s, cfg, st):
        return POSE_FIST
    if is_open_palm(s, cfg, st):
        return POSE_OPEN
    if is_two_fingers(s, cfg, st):
        return POSE_TWO
    return None


# --------------------------------------------------------------------------
# History helpers (history = list[HandSample], old -> new)
# --------------------------------------------------------------------------
def contiguous_tail(history, max_gap_ms):
    """Newest run of samples with no gap larger than max_gap_ms between neighbours."""
    if not history:
        return []
    i = len(history) - 1
    while i > 0 and history[i].timestamp_ms - history[i - 1].timestamp_ms <= max_gap_ms:
        i -= 1
    return list(history[i:])


def window_pair(history, lookback_ms, cfg=config):
    """(then, now): newest sample and the sample closest to now - lookback_ms.

    None if there are < 2 samples or the history does not reach back at least
    lookback_ms * WINDOW_MIN_COVERAGE.
    """
    if len(history) < 2:
        return None
    now = history[-1]
    target = now.timestamp_ms - lookback_ms
    if now.timestamp_ms - history[0].timestamp_ms < lookback_ms * cfg.WINDOW_MIN_COVERAGE:
        return None
    then = min(history[:-1], key=lambda s: abs(s.timestamp_ms - target))
    if now.timestamp_ms - then.timestamp_ms <= 0:
        return None
    return then, now


def scale_growth(history, lookback_ms, cfg=config):
    """size_now / size_then - 1 over ~lookback_ms, or None if history is too short."""
    pair = window_pair(history, lookback_ms, cfg)
    if pair is None:
        return None
    then, now = pair
    s_then = hand_size(then, cfg)
    if s_then <= 1e-6:
        return None
    return hand_size(now, cfg) / s_then - 1.0


def _tips_y_px(s, cfg):
    return 0.5 * (s.landmarks[INDEX_TIP][1] + s.landmarks[MIDDLE_TIP][1]) * cfg.FRAME_HEIGHT


def down_velocity(history, lookback_ms, cfg=config):
    """(velocity, travel) of the mean of the index+middle tips over ~lookback_ms.

    Image y grows downward, so moving DOWN is positive.
    travel   = net vertical displacement / mean(size_then, size_now)   [sizes]
    velocity = travel / elapsed seconds                                [sizes/s]
    None if history is too short.
    """
    pair = window_pair(history, lookback_ms, cfg)
    if pair is None:
        return None
    then, now = pair
    size_ref = 0.5 * (hand_size(then, cfg) + hand_size(now, cfg))
    if size_ref <= 1e-6:
        return None
    travel = (_tips_y_px(now, cfg) - _tips_y_px(then, cfg)) / size_ref
    dt_s = (now.timestamp_ms - then.timestamp_ms) / 1000.0
    return travel / dt_s, travel


def stillness(history, window_ms, min_span_ms=None, cfg=config):
    """(drift, scale_change) over the samples inside the last window_ms.

    drift        = max pairwise wrist distance / mean size   [sizes]
    scale_change = size_max / size_min - 1                   [fraction, >= 0]
    None if fewer than 2 samples or the samples span less than min_span_ms
    (default window_ms * WINDOW_MIN_COVERAGE).
    """
    if len(history) < 2:
        return None
    if min_span_ms is None:
        min_span_ms = window_ms * cfg.WINDOW_MIN_COVERAGE
    t_now = history[-1].timestamp_ms
    win = [s for s in history if t_now - s.timestamp_ms <= window_ms]
    if len(win) < 2 or t_now - win[0].timestamp_ms < min_span_ms:
        return None
    sizes = np.array([hand_size(s, cfg) for s in win])
    if sizes.min() <= 1e-6:
        return None
    wr = np.array([wrist_px(s, cfg) for s in win])
    diff = wr[:, None, :] - wr[None, :, :]
    extent = float(np.sqrt((diff ** 2).sum(-1)).max())
    return extent / float(sizes.mean()), float(sizes.max() / sizes.min() - 1.0)
