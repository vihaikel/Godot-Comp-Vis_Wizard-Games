"""Gesture detectors (Phase 2). Pure Python + numpy; all thresholds in config.py.

Interface contract (other modules depend on it):
    GestureEvent(skill, conf, t_ms)
    GestureEngine(cfg=config).update(t_ms, hands) -> list[GestureEvent]
    GestureEngine.debug_state() -> dict
    GestureEngine.reset()  (drop all detector state, e.g. after a mirror/swap toggle)

`hands` = {'Left': list[HandSample], 'Right': list[HandSample]} (history, old -> new,
may be empty). update() is called once per new detection result. A hand whose
newest sample is older than HAND_STALE_MS relative to t_ms counts as not visible.

Confidence (all skills):
    ratio = metric / threshold           (>= 1 whenever a detector triggers)
    base  = clamp(0.5 + 0.5 * (ratio - 1) / (CONF_SATURATION_RATIO - 1), 0, 1)
    conf  = base * min(handedness score of the hand(s) involved)
  i.e. 0.5 exactly at threshold, 1.0 at CONF_SATURATION_RATIO x threshold, scaled
  by MediaPipe's handedness score. Metric per skill:
    fire      growth / FIRE_GROWTH_MIN
    water     min(growth_L, growth_R) / WATER_GROWTH_MIN
    lightning min(vel / LIGHTNING_MIN_VEL, travel / LIGHTNING_MIN_TRAVEL)
    earth     EARTH has no "overshoot"; ratio = 1 + (1 - worst) * (SAT - 1), where
              worst = max(drift / EARTH_MAX_DRIFT, scale_change / EARTH_MAX_SCALE_CHANGE)
              -> 1.0 for a perfectly still hand, 0.5 at the stillness limit.

Arbitration per update(): candidates are resolved in priority order
water > fire > lightning > earth. Earth additionally requires the left palm center inside
EARTH_ZONE_X / EARTH_ZONE_MAX_Y (upper-middle of the frame); leaving the zone
breaks the hold like a pose break. At most one event per update; any event
starts a global lock of GLOBAL_LOCK_MS. A transient detector (water, fire,
lightning) whose trigger is suppressed by priority or by the lock is consumed
(disarmed, must re-arm) so it does not fire late. Earth is a held gesture: a
suppressed earth stays armed and fires as soon as the lock lifts if the hold
is still valid.
"""
from dataclasses import dataclass

import config
import features as F

LABELS = ("Left", "Right")
SKILLS = ("water", "fire", "lightning", "earth")  # priority order


@dataclass
class GestureEvent:
    skill: str  # 'fire' | 'water' | 'lightning' | 'earth'
    conf: float  # 0..1
    t_ms: int


def _clamp01(v):
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _conf(ratio, score, cfg):
    sat = max(cfg.CONF_SATURATION_RATIO, 1.0 + 1e-6)
    return _clamp01(0.5 + 0.5 * (ratio - 1.0) / (sat - 1.0)) * _clamp01(score)


def _r(v, nd=3):
    return None if v is None else round(float(v), nd)


class _Hand:
    """Per-update view of one hand."""

    def __init__(self, history, t_ms, cfg):
        self.visible = bool(history) and t_ms - history[-1].timestamp_ms <= cfg.HAND_STALE_MS
        self.tail = F.contiguous_tail(history, cfg.HAND_STALE_MS) if self.visible else []
        self.latest = self.tail[-1] if self.tail else None
        self.score = self.latest.score if self.latest else 0.0
        self.pose = None  # stable pose
        self.raw_pose = None  # pose of the newest sample
        if self.tail:
            n = max(1, int(cfg.POSE_STABLE_SAMPLES))
            poses = [F.classify_pose(s, cfg) for s in self.tail[-n:]]
            self.raw_pose = poses[-1]
            if len(poses) >= n and all(p == poses[-1] for p in poses):
                self.pose = poses[-1]


class _FireDetector:
    name = "fire"
    transient = True

    def __init__(self, cfg):
        self.cfg = cfg
        self.armed = True
        self.dbg = {}

    def step(self, t, H):
        c = self.cfg
        r = H["Right"]
        growth, chest_ok = None, None
        if r.visible:
            pair = F.window_pair(r.tail, c.FIRE_LOOKBACK_MS, c)
            growth = F.scale_growth(r.tail, c.FIRE_LOOKBACK_MS, c)
            if pair is not None:  # wrist position at the START of the window
                then_wrist_y = pair[0].landmarks[F.WRIST][1]
                chest_ok = c.FIRE_CHEST_MIN_Y is None or then_wrist_y >= c.FIRE_CHEST_MIN_Y
        if not self.armed and (not r.visible or growth is None or growth < c.FIRE_REARM_GROWTH):
            self.armed = True
        cond = (r.visible and r.pose == F.POSE_FIST and growth is not None
                and growth >= c.FIRE_GROWTH_MIN and bool(chest_ok))
        self.dbg = {"armed": self.armed, "growth": _r(growth), "chest_ok": chest_ok,
                    "pose": r.pose}
        if cond and self.armed:
            return _conf(growth / c.FIRE_GROWTH_MIN, r.score, c)
        return None

    def consume(self):
        self.armed = False


class _WaterDetector:
    name = "water"
    transient = True

    def __init__(self, cfg):
        self.cfg = cfg
        self.armed = True
        self.prev_above = {l: False for l in LABELS}
        self.cross_t = {l: None for l in LABELS}
        self.dbg = {}

    def step(self, t, H):
        c = self.cfg
        g = {}
        for l in LABELS:
            h = H[l]
            g[l] = F.scale_growth(h.tail, c.WATER_LOOKBACK_MS, c) if h.visible else None
            above = (h.visible and h.pose == F.POSE_OPEN and g[l] is not None
                     and g[l] >= c.WATER_GROWTH_MIN)
            if above and not self.prev_above[l]:
                self.cross_t[l] = t  # moment this hand crossed the threshold
            self.prev_above[l] = above
            if self.cross_t[l] is not None and t - self.cross_t[l] > c.WATER_SYNC_MS:
                self.cross_t[l] = None  # too old to pair with the other hand
        both_visible = H["Left"].visible and H["Right"].visible
        if not self.armed:
            low = all(g[l] is None or g[l] < c.WATER_REARM_GROWTH for l in LABELS)
            if not both_visible or low:
                self.armed = True
        cl, cr = self.cross_t["Left"], self.cross_t["Right"]
        synced = cl is not None and cr is not None and abs(cl - cr) <= c.WATER_SYNC_MS
        cond = (both_visible and synced and H["Left"].pose == F.POSE_OPEN
                and H["Right"].pose == F.POSE_OPEN)
        self.dbg = {"armed": self.armed, "growth_L": _r(g["Left"]), "growth_R": _r(g["Right"]),
                    "cross_L": cl, "cross_R": cr}
        if cond and self.armed:
            gs = [v for v in g.values() if v is not None]
            gmin = min(gs) if len(gs) == 2 else c.WATER_GROWTH_MIN
            ratio = max(1.0, gmin / c.WATER_GROWTH_MIN)  # a hand may already be slowing
            return _conf(ratio, min(H["Left"].score, H["Right"].score), c)
        return None

    def consume(self):
        self.armed = False
        self.cross_t = {l: None for l in LABELS}


class _LightningDetector:
    name = "lightning"
    transient = True

    def __init__(self, cfg):
        self.cfg = cfg
        self.armed = True
        self.dbg = {}

    def step(self, t, H):
        c = self.cfg
        r = H["Right"]
        dv = F.down_velocity(r.tail, c.LIGHTNING_LOOKBACK_MS, c) if r.visible else None
        vel, travel = dv if dv is not None else (None, None)
        if not self.armed and (dv is None or vel < c.LIGHTNING_MIN_VEL * c.LIGHTNING_REARM_RATIO):
            self.armed = True
        cond = (r.visible and r.pose == F.POSE_TWO and dv is not None
                and vel >= c.LIGHTNING_MIN_VEL and travel >= c.LIGHTNING_MIN_TRAVEL)
        self.dbg = {"armed": self.armed, "vel": _r(vel), "travel": _r(travel), "pose": r.pose}
        if cond and self.armed:
            ratio = min(vel / c.LIGHTNING_MIN_VEL, travel / c.LIGHTNING_MIN_TRAVEL)
            return _conf(ratio, r.score, c)
        return None

    def consume(self):
        self.armed = False


class _EarthDetector:
    name = "earth"
    transient = False

    def __init__(self, cfg):
        self.cfg = cfg
        self.armed = True
        self.hold_start = None
        self.last_ok = None
        self.release_since = None
        self.dbg = {"progress": 0.0}

    def _backdate(self, tail):
        """Earliest timestamp from which the hand has been continuously OPEN, without
        gaps > EARTH_GAP_TOLERANCE_MS, inside the stillness window (which was just
        verified to be still)."""
        c = self.cfg
        t_new = tail[-1].timestamp_ms
        start = t_new
        for i in range(len(tail) - 1, -1, -1):
            s = tail[i]
            if t_new - s.timestamp_ms > c.EARTH_STILL_WINDOW_MS:
                break
            if i < len(tail) - 1 and tail[i + 1].timestamp_ms - s.timestamp_ms > c.EARTH_GAP_TOLERANCE_MS:
                break
            if F.classify_pose(s, c) != F.POSE_OPEN or not F.in_earth_zone(s, c):
                break
            start = s.timestamp_ms
        return start

    def _right_hand_ok(self, r):
        """EARTH_RIGHT_HAND policy (see config.py). Uses the raw (unstabilised) pose so
        a right palm that is merely opening still blocks Earth."""
        policy = getattr(self.cfg, "EARTH_RIGHT_HAND", "any")
        if policy == "absent":
            return not r.visible
        if policy == "not_open":
            return (not r.visible) or r.raw_pose != F.POSE_OPEN
        return True

    def step(self, t, H):
        c = self.cfg
        h = H["Left"]
        st = None
        if h.visible:
            tail = F.contiguous_tail(h.tail, c.EARTH_GAP_TOLERANCE_MS)
            st = F.stillness(tail, c.EARTH_STILL_WINDOW_MS, c.EARTH_STILL_MIN_SPAN_MS, c)
        drift, dscale = st if st is not None else (None, None)
        in_zone = F.in_earth_zone(h.latest, c) if h.visible else None
        right_ok = self._right_hand_ok(H["Right"])
        ok = (h.visible and h.pose == F.POSE_OPEN and bool(in_zone) and right_ok
              and st is not None
              and drift <= c.EARTH_MAX_DRIFT and dscale <= c.EARTH_MAX_SCALE_CHANGE)

        # Hold timer with gap tolerance.
        if ok:
            if self.hold_start is None:
                self.hold_start = self._backdate(tail)
            self.last_ok = t
        elif self.hold_start is not None and t - self.last_ok > c.EARTH_GAP_TOLERANCE_MS:
            self.hold_start = None

        # Re-arm only after the pose has been released for > gap tolerance
        # (leaving the zone counts as a release, like a pose break).
        released = (not h.visible) or h.raw_pose != F.POSE_OPEN or not in_zone
        if released:
            if self.release_since is None:
                self.release_since = t
        else:
            self.release_since = None
        if (not self.armed and self.release_since is not None
                and t - self.release_since > c.EARTH_GAP_TOLERANCE_MS):
            self.armed = True
            self.hold_start = None

        held = 0 if self.hold_start is None else t - self.hold_start
        progress = _clamp01(held / c.EARTH_HOLD_MS) if self.armed else 0.0
        self.dbg = {"armed": self.armed, "progress": round(progress, 3), "held_ms": held,
                    "drift": _r(drift), "scale_change": _r(dscale), "pose": h.pose,
                    "in_zone": in_zone, "right_ok": right_ok}
        if ok and self.armed and held >= c.EARTH_HOLD_MS:
            worst = max(drift / c.EARTH_MAX_DRIFT, dscale / c.EARTH_MAX_SCALE_CHANGE)
            ratio = 1.0 + (1.0 - _clamp01(worst)) * (c.CONF_SATURATION_RATIO - 1.0)
            return _conf(ratio, h.score, c)
        return None

    def consume(self):
        self.armed = False
        self.hold_start = None
        self.release_since = None


class GestureEngine:
    def __init__(self, cfg=config):
        self.cfg = cfg
        self.reset()

    def reset(self):
        """Drop all detector/lock state (fresh engine, same cfg)."""
        cfg = self.cfg
        self._detectors = {
            "water": _WaterDetector(cfg),
            "fire": _FireDetector(cfg),
            "lightning": _LightningDetector(cfg),
            "earth": _EarthDetector(cfg),
        }
        self._lock_until = None
        self._last_t = None
        self._poses = {l: None for l in LABELS}
        self._last_events = []

    def update(self, t_ms: int, hands: dict) -> list:
        c = self.cfg
        t = int(t_ms)
        self._last_t = t
        H = {l: _Hand(list(hands.get(l) or []), t, c) for l in LABELS}
        self._poses = {l: H[l].pose for l in LABELS}

        cands = {}
        for name in SKILLS:  # every detector steps every update (keeps its state fresh)
            conf = self._detectors[name].step(t, H)
            if conf is not None:
                cands[name] = conf

        events = []
        for name in SKILLS:
            if name not in cands:
                continue
            det = self._detectors[name]
            locked = self._lock_until is not None and t < self._lock_until
            if locked or events:
                if det.transient:
                    det.consume()  # suppressed (priority/lock): must re-arm, never fires late
                continue
            events.append(GestureEvent(skill=name, conf=round(cands[name], 3), t_ms=t))
            det.consume()
            self._lock_until = t + c.GLOBAL_LOCK_MS
        self._last_events = events
        return events

    def debug_state(self) -> dict:
        lock_left = 0
        if self._lock_until is not None and self._last_t is not None:
            lock_left = max(0, self._lock_until - self._last_t)
        d = {name: dict(det.dbg) for name, det in self._detectors.items()}
        d["poses"] = dict(self._poses)
        d["lock_remaining_ms"] = lock_left
        d["t_ms"] = self._last_t
        d["last_events"] = [(e.skill, e.conf) for e in self._last_events]
        return d
