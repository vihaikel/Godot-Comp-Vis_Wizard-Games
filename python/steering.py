"""Kemudi (berganti arah) dengan dua telapak terbuka. Pure Python (no mediapipe/cv2).

Interface:
    SteerController(cfg=config)
    .update(t_ms, hands, mirrored, events=()) -> float   # -1..1, negative = turn left
    .reset()
    .debug_state() -> dict  # raw, value, active, reason, offset, growth_L, growth_R, ...

`hands` has the same shape as for GestureEngine.update ({'Left': [HandSample..],
'Right': [..]}, history old -> new). `events` = the list returned by
GestureEngine.update() on the SAME update (used to detect 'water').
Call update() once per new detection result, right after engine.update().

Algorithm (all numbers in config.py, section "Steering"):
1. Both hands present: each hand's newest sample must be <= STEER_HAND_LOST_MS old
   (stricter than HAND_STALE_MS so the character stops within ~2 updates when a
   hand leaves; one missed detection at 30 fps is still tolerated).
   Otherwise reason 'no_hands' and the value is set to 0 IMMEDIATELY (hard stop).
2. Pose: both hands OPEN (features.classify_pose, same classifier as gestures).
   Hysteresis: ENGAGING needs the last POSE_STABLE_SAMPLES samples of each hand all
   OPEN (gestures' stable-pose rule, glitch-proof); once engaged, a hand stays OK
   while at most STEER_POSE_GLITCH_SAMPLES of its last POSE_STABLE_SAMPLES samples
   are not OPEN. So a single-frame misclassification does not change the value at
   all, while a real fist releases after 2 frames. Failing -> 'not_open' (raw 0,
   value decays through the EMA).
3. Water suppression: if `events` contains 'water', or within
   STEER_SUPPRESS_AFTER_WATER_MS after one -> 'suppressed', value 0 IMMEDIATELY.
4. Not pushing: scale_growth over STEER_LOOKBACK_MS for each hand must exist
   (else 'warmup', raw 0) and |growth| <= STEER_MAX_GROWTH; else 'pushing', value 0
   IMMEDIATELY (so a Water push never turns the camera; first push frame below the
   threshold is the only latency).
5. offset = mean(palm_center.x of both hands) - 0.5; negated when mirrored=False
   (raw camera image) so a positive offset is always the player's physical right.
6. raw = offset_to_raw(offset): deadzone STEER_DEADZONE -> 0 ('deadzone'), linear
   up to STEER_FULL_OFFSET -> +-1, optional STEER_EXPONENT curve ('ok').
7. EMA: value += STEER_SMOOTHING * (raw - value); if raw == 0 and
   |value| < STEER_SNAP_ZERO -> exactly 0. (Hard stops in 1/3/4 bypass the EMA.)
"""
import math

import config
import features as F

LABELS = ("Left", "Right")

NO_HANDS = "no_hands"
NOT_OPEN = "not_open"
SUPPRESSED = "suppressed"
WARMUP = "warmup"
PUSHING = "pushing"
DEADZONE = "deadzone"
OK = "ok"
HARD_STOP_REASONS = frozenset({NO_HANDS, SUPPRESSED, PUSHING})


def offset_to_raw(offset, cfg=config):
    """Map a (direction-corrected) offset from the frame center to a raw steer value."""
    dz = float(cfg.STEER_DEADZONE)
    mag = abs(float(offset))
    if mag <= dz:
        return 0.0
    span = max(float(cfg.STEER_FULL_OFFSET) - dz, 1e-6)
    u = min(1.0, (mag - dz) / span)
    exp = float(getattr(cfg, "STEER_EXPONENT", 1.0))
    if exp != 1.0:
        u = u ** exp
    return math.copysign(u, offset)


def _r(v, nd=3):
    return None if v is None else round(float(v), nd)


class SteerController:
    def __init__(self, cfg=config):
        self.cfg = cfg
        self.reset()

    def reset(self):
        """Drop all state (e.g. after a mirror/swap toggle or a camera stall)."""
        self._value = 0.0
        self._engaged = False  # pose hysteresis: both hands were OPEN-ok last update
        self._suppress_until = None
        self._dbg = {"raw": 0.0, "value": 0.0, "active": False, "reason": NO_HANDS,
                     "offset": None, "growth_L": None, "growth_R": None,
                     "suppress_remaining_ms": 0, "t_ms": None}

    @property
    def value(self):
        return self._value

    # ------------------------------------------------------------- helpers
    def _present_tail(self, history, t):
        if not history or t - history[-1].timestamp_ms > self.cfg.STEER_HAND_LOST_MS:
            return None
        return F.contiguous_tail(history, self.cfg.HAND_STALE_MS)

    def _open_ok(self, tail):
        c = self.cfg
        n = max(1, int(c.POSE_STABLE_SAMPLES))
        poses = [F.classify_pose(s, c) for s in tail[-n:]]
        bad = sum(1 for p in poses if p != F.POSE_OPEN)
        if len(poses) >= n and bad == 0:
            return True  # stable OPEN: may engage
        if self._engaged:
            return bad <= int(getattr(c, "STEER_POSE_GLITCH_SAMPLES", 0))
        return False

    # ----------------------------------------------------------------- API
    def update(self, t_ms, hands, mirrored, events=()):
        c = self.cfg
        t = int(t_ms)
        if any(getattr(e, "skill", None) == "water" for e in (events or ())):
            self._suppress_until = t + c.STEER_SUPPRESS_AFTER_WATER_MS
        suppressed = self._suppress_until is not None and t < self._suppress_until

        hands = hands or {}
        tails = {l: self._present_tail(list(hands.get(l) or []), t) for l in LABELS}
        offset = None
        growth = {l: None for l in LABELS}
        raw = 0.0

        if any(tails[l] is None for l in LABELS):
            reason = NO_HANDS
            self._engaged = False
        else:
            pose_ok = all(self._open_ok(tails[l]) for l in LABELS)
            self._engaged = pose_ok
            xs = [F.palm_center(tails[l][-1])[0] for l in LABELS]
            offset = sum(xs) / len(xs) - 0.5
            if not mirrored:
                offset = -offset  # raw image: physical right is image left
            for l in LABELS:
                growth[l] = F.scale_growth(tails[l], c.STEER_LOOKBACK_MS, c)
            if suppressed:
                reason = SUPPRESSED
            elif not pose_ok:
                reason = NOT_OPEN
            elif any(growth[l] is None for l in LABELS):
                reason = WARMUP
            elif any(abs(growth[l]) > c.STEER_MAX_GROWTH for l in LABELS):
                reason = PUSHING
            else:
                raw = offset_to_raw(offset, c)
                reason = OK if raw != 0.0 else DEADZONE

        if reason in HARD_STOP_REASONS:
            self._value = 0.0
        else:
            self._value += c.STEER_SMOOTHING * (raw - self._value)
            if raw == 0.0 and abs(self._value) < c.STEER_SNAP_ZERO:
                self._value = 0.0
        self._value = max(-1.0, min(1.0, self._value))

        self._dbg = {
            "raw": _r(raw), "value": _r(self._value), "active": reason == OK,
            "reason": reason, "offset": _r(offset),
            "growth_L": _r(growth["Left"]), "growth_R": _r(growth["Right"]),
            "suppress_remaining_ms": max(0, self._suppress_until - t) if suppressed else 0,
            "t_ms": t,
        }
        return self._value

    def debug_state(self):
        return dict(self._dbg)
