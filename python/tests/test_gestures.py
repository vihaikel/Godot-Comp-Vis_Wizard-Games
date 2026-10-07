"""Gesture tests with synthetic hands (no webcam, no mediapipe).

Run:  cd python && python3 -m unittest discover -s tests -v

Synthetic hand model
- World templates (meters, palm facing camera, fingers pointing up = -y,
  WRIST->MIDDLE_MCP = 0.09 m, wrist->middle tip ~0.185 m) for OPEN, FIST, TWO.
  Folded fingers curl toward the camera (-z) and back down, like a real fist.
- Normalized landmarks = orthographic projection of the template: the wrist is
  placed at (cx, cy); `size_px` sets the 2D WRIST->MIDDLE_MCP length in pixels.
- World landmarks are re-centered on the hand's centroid (as MediaPipe does).
- Deterministic jitter: +-1 px on normalized landmarks, +-2 mm on world.
- 30 fps timestamps.
"""
import math
import os
import random
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import features as F  # noqa: E402
from features import HandSample  # noqa: E402
from gestures import GestureEngine, GestureEvent  # noqa: E402
from replay import run_frames  # noqa: E402

FPS = 30
DT = 1000.0 / FPS
PALM_LEN_M = 0.09  # WRIST -> MIDDLE_MCP

# finger -> (mcp_xy, (len mcp-pip, pip-dip, dip-tip)) in meters
_FINGERS = {
    "index": ((-0.025, -0.085), (0.040, 0.025, 0.020)),
    "middle": ((0.000, -0.090), (0.045, 0.028, 0.022)),
    "ring": ((0.020, -0.085), (0.042, 0.026, 0.021)),
    "pinky": ((0.038, -0.075), (0.032, 0.020, 0.018)),
}


def _finger(mcp, segs, extended):
    x, y = mcp
    a, b, c = segs
    if extended:
        return [(x, y, 0.0), (x, y - a, 0.0), (x, y - a - b, 0.0), (x, y - a - b - c, 0.0)]
    # curled: MCP flexes toward camera (-z), PIP back down (+y), DIP back toward palm (+z)
    return [(x, y, 0.0), (x, y, -a), (x, y + b, -a), (x, y + b, -a + c)]


def template(pose):
    ext = {
        "OPEN": dict(index=True, middle=True, ring=True, pinky=True),
        "FIST": dict(index=False, middle=False, ring=False, pinky=False),
        "TWO": dict(index=True, middle=True, ring=False, pinky=False),
    }[pose]
    pts = [(0.0, 0.0, 0.0)]  # wrist
    if pose == "OPEN":
        pts += [(-0.025, -0.025, 0.0), (-0.045, -0.045, 0.0), (-0.060, -0.065, 0.0), (-0.070, -0.085, 0.0)]
    else:  # thumb folded across the front of the fingers
        pts += [(-0.025, -0.025, -0.010), (-0.035, -0.045, -0.030), (-0.020, -0.060, -0.045), (0.000, -0.065, -0.050)]
    for name in ("index", "middle", "ring", "pinky"):
        mcp, segs = _FINGERS[name]
        pts += _finger(mcp, segs, ext[name])
    assert len(pts) == 21
    return pts


class Synth:
    """Builds HandSamples from (pose, wrist center, 2D hand size in px)."""

    def __init__(self, seed=0, jitter_px=1.0, jitter_m=0.002):
        self.rng = random.Random(seed)
        self.jp = jitter_px
        self.jm = jitter_m

    def sample(self, t_ms, pose, cx, cy, size_px, with_world=True, score=0.95):
        tpl = template(pose)
        ppm = size_px / PALM_LEN_M  # pixels per meter
        W, H = config.FRAME_WIDTH, config.FRAME_HEIGHT
        j = lambda s: self.rng.uniform(-s, s)  # noqa: E731
        lms = [(cx + (X * ppm + j(self.jp)) / W,
                cy + (Y * ppm + j(self.jp)) / H,
                (Z * ppm + j(self.jp)) / W) for X, Y, Z in tpl]
        world = []
        if with_world:
            mx = sum(p[0] for p in tpl) / 21
            my = sum(p[1] for p in tpl) / 21
            mz = sum(p[2] for p in tpl) / 21
            world = [(X - mx + j(self.jm), Y - my + j(self.jm), Z - mz + j(self.jm)) for X, Y, Z in tpl]
        return HandSample(timestamp_ms=int(round(t_ms)), landmarks=lms, score=score, world=world)


def lerp(a, b, u):
    u = max(0.0, min(1.0, u))
    return a + (b - a) * u


class Script:
    """Accumulates 30 fps frames: list of (t_ms, {'Left': sample|None, 'Right': sample|None})."""

    def __init__(self, seed=0, t0=10_000):
        self.synth = Synth(seed)
        self.t = float(t0)
        self.frames = []

    def seg(self, duration_ms, left=None, right=None):
        """left/right: None (hand absent) or fn(u in [0,1], t_ms) -> dict(pose,cx,cy,size_px[,with_world])."""
        n = max(1, int(round(duration_ms / DT)))
        for i in range(n):
            u = (i + 1) / n
            self.t += DT
            fr = {}
            for label, fn in (("Left", left), ("Right", right)):
                if fn is None:
                    fr[label] = None
                else:
                    kw = dict(fn(u, self.t))
                    fr[label] = self.synth.sample(self.t, **kw)
            self.frames.append((int(round(self.t)), fr))
        return self

    def run(self, engine=None):
        return run_frames(self.frames, engine or GestureEngine(config))


def still(pose, cx, cy, size=100.0, **kw):
    return lambda u, t: dict(pose=pose, cx=cx, cy=cy, size_px=size, **kw)


def grow(pose, cx, cy, s0, s1, **kw):
    return lambda u, t: dict(pose=pose, cx=cx, cy=cy, size_px=lerp(s0, s1, u), **kw)


def move(pose, c0, c1, size=100.0, **kw):
    return lambda u, t: dict(pose=pose, cx=lerp(c0[0], c1[0], u), cy=lerp(c0[1], c1[1], u),
                             size_px=size, **kw)


def wave(pose, cx, cy, amp=0.15, hz=1.5, size=100.0):
    # left-right wave with a small vertical arc, as a real wave has
    return lambda u, t: dict(pose=pose, cx=cx + amp * math.sin(2 * math.pi * hz * t / 1000.0),
                             cy=cy - 0.02 * abs(math.sin(2 * math.pi * hz * t / 1000.0)), size_px=size)


def skills(events):
    return [e.skill for e in events]


# --------------------------------------------------------------------------
class TestFeatures(unittest.TestCase):
    def setUp(self):
        self.syn = Synth(1)

    def test_pose_templates(self):
        for pose in ("OPEN", "FIST", "TWO"):
            s = self.syn.sample(0, pose, 0.5, 0.6, 100)
            self.assertEqual(F.classify_pose(s), pose)
        self.assertTrue(F.is_fist(self.syn.sample(0, "FIST", 0.5, 0.6, 100)))
        self.assertTrue(F.is_open_palm(self.syn.sample(0, "OPEN", 0.5, 0.6, 100)))
        self.assertTrue(F.is_two_fingers(self.syn.sample(0, "TWO", 0.5, 0.6, 100)))
        self.assertFalse(F.is_fist(self.syn.sample(0, "OPEN", 0.5, 0.6, 100)))
        self.assertFalse(F.is_two_fingers(self.syn.sample(0, "FIST", 0.5, 0.6, 100)))

    def test_pose_fallback_without_world(self):
        # 7. world=[] -> classification from normalized landmarks (z*FRAME_WIDTH)
        for pose in ("OPEN", "FIST", "TWO"):
            s = self.syn.sample(0, pose, 0.5, 0.6, 100, with_world=False)
            self.assertEqual(s.world, [])
            self.assertEqual(F.classify_pose(s), pose)

    def test_world_is_used_when_present(self):
        # normalized landmarks say OPEN, world says FIST -> world wins
        s_open = self.syn.sample(0, "OPEN", 0.5, 0.6, 100)
        s_fist = self.syn.sample(0, "FIST", 0.5, 0.6, 100)
        mixed = HandSample(0, s_open.landmarks, 0.9, s_fist.world)
        self.assertEqual(F.classify_pose(mixed), "FIST")

    def test_hand_size_aspect(self):
        s = self.syn.sample(0, "OPEN", 0.5, 0.6, 120)
        self.assertAlmostEqual(F.hand_size(s), 120, delta=3)
        self.assertAlmostEqual(F.hand_size_norm(s), 120 / config.FRAME_WIDTH, delta=0.01)

    def test_scale_growth_and_insufficient_history(self):
        h = [self.syn.sample(i * DT, "FIST", 0.5, 0.6, 100 + 40 * i / 4.5) for i in range(6)]
        self.assertIsNone(F.scale_growth(h[:1], 150))
        self.assertIsNone(F.scale_growth(h[:2], 150))  # covers 33 ms < 0.6*150
        g = F.scale_growth(h, 150)
        # now = sample 5 (t=167 ms); nearest to now-150 = sample 1 (t=33 ms)
        self.assertAlmostEqual(g, (100 + 40 * 5 / 4.5) / (100 + 40 * 1 / 4.5) - 1, delta=0.03)

    def test_down_velocity(self):
        h = [self.syn.sample(i * DT, "TWO", 0.5, 0.3 + i * 0.03, 100) for i in range(8)]
        vel, travel = F.down_velocity(h, 200)
        # 0.03 * 480 px per frame = 14.4 px = 0.144 size per 33 ms -> 4.32 size/s
        self.assertAlmostEqual(vel, 4.32, delta=0.3)
        self.assertGreater(travel, 0.8)
        h_up = [self.syn.sample(i * DT, "TWO", 0.5, 0.6 - i * 0.03, 100) for i in range(8)]
        self.assertLess(F.down_velocity(h_up, 200)[0], 0)

    def test_stillness(self):
        h = [self.syn.sample(i * DT, "OPEN", 0.3, 0.5, 100) for i in range(10)]
        drift, ds = F.stillness(h, 300)
        self.assertLess(drift, 0.1)
        self.assertLess(ds, 0.06)
        hm = [self.syn.sample(i * DT, "OPEN", 0.3 + 0.02 * i, 0.5, 100) for i in range(10)]
        self.assertGreater(F.stillness(hm, 300)[0], 0.5)
        self.assertIsNone(F.stillness(h[:2], 300))


# --------------------------------------------------------------------------
class TestFire(unittest.TestCase):
    def test_fire_punch_in_chest_zone(self):
        # 1. right fist in chest zone grows 40 % in 150 ms -> exactly one 'fire'
        sc = Script(seed=2)
        sc.seg(400, right=still("FIST", 0.6, 0.6, 100))
        sc.seg(150, right=grow("FIST", 0.6, 0.6, 100, 140))
        sc.seg(600, right=still("FIST", 0.6, 0.6, 140))
        ev = sc.run()
        self.assertEqual(skills(ev), ["fire"])
        self.assertIsInstance(ev[0], GestureEvent)
        self.assertTrue(0.0 < ev[0].conf <= 1.0)

    def test_fire_continuous_growth_fires_once(self):
        # 6. keeps growing (no re-arm) for 1 s -> one event only
        sc = Script(seed=3)
        sc.seg(300, right=still("FIST", 0.6, 0.6, 60))
        # +30 % per 150 ms, sustained for 600 ms (60 px -> ~171 px): growth stays
        # above FIRE_GROWTH_MIN the whole time, so it never re-arms.
        sc.seg(600, right=lambda u, t: dict(pose="FIST", cx=0.6, cy=0.6, size_px=60 * (1.3 ** (u * 4))))
        self.assertEqual(skills(sc.run()), ["fire"])

    def test_fire_rearm_allows_second_punch(self):
        sc = Script(seed=4)
        sc.seg(300, right=still("FIST", 0.6, 0.6, 100))
        sc.seg(150, right=grow("FIST", 0.6, 0.6, 100, 140))
        sc.seg(300, right=grow("FIST", 0.6, 0.6, 140, 100))  # pull back
        sc.seg(400, right=still("FIST", 0.6, 0.6, 100))
        sc.seg(150, right=grow("FIST", 0.6, 0.6, 100, 140))
        sc.seg(300, right=still("FIST", 0.6, 0.6, 140))
        self.assertEqual(skills(sc.run()), ["fire", "fire"])

    def test_fire_without_world(self):
        # 7. same punch with world=[] still classified and fires
        sc = Script(seed=5)
        sc.seg(400, right=still("FIST", 0.6, 0.6, 100, with_world=False))
        sc.seg(150, right=grow("FIST", 0.6, 0.6, 100, 140, with_world=False))
        sc.seg(300, right=still("FIST", 0.6, 0.6, 140, with_world=False))
        self.assertEqual(skills(sc.run()), ["fire"])

    def test_no_fire_open_palm_growing(self):
        sc = Script(seed=6)
        sc.seg(400, right=still("OPEN", 0.6, 0.6, 100))
        sc.seg(150, right=grow("OPEN", 0.6, 0.6, 100, 140))
        sc.seg(400, right=still("OPEN", 0.6, 0.6, 140))
        self.assertEqual(skills(sc.run()), [])

    def test_no_fire_single_frame_pose_glitch(self):
        # Open palm pushing with ONE frame misclassified as fist: POSE_STABLE_SAMPLES
        # must keep this from firing.
        sc = Script(seed=16)
        sc.seg(400, right=still("OPEN", 0.6, 0.6, 100))
        sc.seg(100, right=grow("OPEN", 0.6, 0.6, 100, 127))
        sc.seg(DT, right=still("FIST", 0.6, 0.6, 131))
        sc.seg(50, right=grow("OPEN", 0.6, 0.6, 131, 140))
        sc.seg(300, right=still("OPEN", 0.6, 0.6, 140))
        self.assertEqual(skills(sc.run()), [])

    def test_no_fire_fist_still(self):
        sc = Script(seed=7)
        sc.seg(2000, right=still("FIST", 0.6, 0.6, 100))
        self.assertEqual(skills(sc.run()), [])

    def test_no_fire_slow_growth(self):
        sc = Script(seed=8)
        sc.seg(300, right=still("FIST", 0.6, 0.6, 100))
        sc.seg(1500, right=grow("FIST", 0.6, 0.6, 100, 140))
        self.assertEqual(skills(sc.run()), [])

    def test_no_fire_above_chest_zone(self):
        sc = Script(seed=9)
        sc.seg(400, right=still("FIST", 0.6, 0.2, 100))
        sc.seg(150, right=grow("FIST", 0.6, 0.2, 100, 140))
        sc.seg(300, right=still("FIST", 0.6, 0.2, 140))
        self.assertEqual(skills(sc.run()), [])

    def test_no_fire_left_hand(self):
        sc = Script(seed=10)
        sc.seg(400, left=still("FIST", 0.4, 0.6, 100))
        sc.seg(150, left=grow("FIST", 0.4, 0.6, 100, 140))
        sc.seg(300, left=still("FIST", 0.4, 0.6, 140))
        self.assertEqual(skills(sc.run()), [])


class TestWater(unittest.TestCase):
    def _push(self, seed, lag_ms):
        sc = Script(seed=seed)
        sc.seg(400, left=still("OPEN", 0.35, 0.6, 100), right=still("OPEN", 0.65, 0.6, 100))
        t_start = sc.t  # left starts pushing now (+40 % in 150 ms), right lag_ms later

        def push(cx, delay):
            return lambda u, t: dict(pose="OPEN", cx=cx, cy=0.6,
                                     size_px=lerp(100, 140, (t - t_start - delay) / 150.0))
        sc.seg(150 + lag_ms + 400, left=push(0.35, 0), right=push(0.65, lag_ms))
        return sc

    def test_water_two_palms_push(self):
        # 2. both open palms grow together -> exactly one 'water', no 'fire'
        ev = self._push(11, 0).run()
        self.assertEqual(skills(ev), ["water"])

    def test_water_small_lag_ok(self):
        self.assertEqual(skills(self._push(12, 100).run()), ["water"])

    def test_no_water_hands_out_of_sync(self):
        self.assertEqual(skills(self._push(13, 500).run()), [])

    def test_no_water_single_palm(self):
        sc = Script(seed=14)
        sc.seg(400, left=still("OPEN", 0.35, 0.6, 100), right=still("FIST", 0.65, 0.6, 100))
        sc.seg(150, left=grow("OPEN", 0.35, 0.6, 100, 140), right=still("FIST", 0.65, 0.6, 100))
        sc.seg(300, left=still("OPEN", 0.35, 0.6, 140), right=still("FIST", 0.65, 0.6, 100))
        self.assertEqual(skills(sc.run()), [])

    def test_water_beats_fire_and_locks(self):
        # Priority/lock: a fire candidate right after water is suppressed.
        sc = Script(seed=15)
        sc.seg(400, left=still("OPEN", 0.35, 0.6, 100), right=still("OPEN", 0.65, 0.6, 100))
        sc.seg(150, left=grow("OPEN", 0.35, 0.6, 100, 140), right=grow("OPEN", 0.65, 0.6, 100, 140))
        # right hand snaps to a fist and keeps pushing within the lock window
        sc.seg(100, left=still("OPEN", 0.35, 0.6, 140), right=grow("FIST", 0.65, 0.6, 140, 200))
        sc.seg(300, left=still("OPEN", 0.35, 0.6, 140), right=still("FIST", 0.65, 0.6, 200))
        self.assertEqual(skills(sc.run()), ["water"])


class TestLightning(unittest.TestCase):
    def test_lightning_fast_down(self):
        # 3. right two-fingers drops 1.5 sizes in 200 ms -> one 'lightning'
        size = 100.0
        dy = 1.5 * size / config.FRAME_HEIGHT
        sc = Script(seed=20)
        sc.seg(300, right=still("TWO", 0.6, 0.3, size))
        sc.seg(200, right=move("TWO", (0.6, 0.3), (0.6, 0.3 + dy), size))
        sc.seg(500, right=still("TWO", 0.6, 0.3 + dy, size))
        self.assertEqual(skills(sc.run()), ["lightning"])

    def test_no_lightning_slow_down(self):
        size = 100.0
        dy = 1.5 * size / config.FRAME_HEIGHT
        sc = Script(seed=21)
        sc.seg(300, right=still("TWO", 0.6, 0.3, size))
        sc.seg(1500, right=move("TWO", (0.6, 0.3), (0.6, 0.3 + dy), size))
        self.assertEqual(skills(sc.run()), [])

    def test_no_lightning_fast_up(self):
        size = 100.0
        dy = 1.5 * size / config.FRAME_HEIGHT
        sc = Script(seed=22)
        sc.seg(300, right=still("TWO", 0.6, 0.7, size))
        sc.seg(200, right=move("TWO", (0.6, 0.7), (0.6, 0.7 - dy), size))
        sc.seg(300, right=still("TWO", 0.6, 0.7 - dy, size))
        self.assertEqual(skills(sc.run()), [])

    def test_no_lightning_fist_down(self):
        size = 100.0
        dy = 1.5 * size / config.FRAME_HEIGHT
        sc = Script(seed=23)
        sc.seg(300, right=still("FIST", 0.6, 0.3, size))
        sc.seg(200, right=move("FIST", (0.6, 0.3), (0.6, 0.3 + dy), size))
        sc.seg(300, right=still("FIST", 0.6, 0.3 + dy, size))
        self.assertEqual(skills(sc.run()), [])


class TestEarth(unittest.TestCase):
    def test_earth_hold_1200(self):
        # 4a. left open palm still 1.2 s -> exactly one 'earth'
        sc = Script(seed=30)
        sc.seg(1200, left=still("OPEN", 0.3, 0.55, 100))
        ev = sc.run()
        self.assertEqual(skills(ev), ["earth"])
        t_first = sc.frames[0][0]
        self.assertGreaterEqual(ev[0].t_ms - t_first, config.EARTH_HOLD_MS - DT - 1)

    def test_earth_hold_800_none(self):
        # 4b. still only 0.8 s -> nothing
        sc = Script(seed=31)
        sc.seg(800, left=still("OPEN", 0.3, 0.55, 100))
        sc.seg(500)  # hand leaves
        self.assertEqual(skills(sc.run()), [])

    def test_earth_interrupted_by_disappearance(self):
        # 4c. 0.6 s still, 300 ms gap (hand not detected), 0.6 s still -> nothing
        sc = Script(seed=32)
        sc.seg(600, left=still("OPEN", 0.3, 0.55, 100))
        sc.seg(300)
        sc.seg(600, left=still("OPEN", 0.3, 0.55, 100))
        self.assertEqual(skills(sc.run()), [])

    def test_earth_interrupted_by_pose_change(self):
        sc = Script(seed=33)
        sc.seg(600, left=still("OPEN", 0.3, 0.55, 100))
        sc.seg(300, left=still("FIST", 0.3, 0.55, 100))
        sc.seg(600, left=still("OPEN", 0.3, 0.55, 100))
        self.assertEqual(skills(sc.run()), [])

    def test_earth_interrupted_by_motion(self):
        sc = Script(seed=34)
        sc.seg(600, left=still("OPEN", 0.3, 0.55, 100))
        sc.seg(300, left=move("OPEN", (0.3, 0.55), (0.45, 0.55), 100))
        sc.seg(600, left=still("OPEN", 0.45, 0.55, 100))
        self.assertEqual(skills(sc.run()), [])

    def test_earth_long_hold_fires_once(self):
        sc = Script(seed=35)
        sc.seg(3000, left=still("OPEN", 0.3, 0.55, 100))
        self.assertEqual(skills(sc.run()), ["earth"])

    def test_earth_release_and_hold_again(self):
        sc = Script(seed=36)
        sc.seg(1200, left=still("OPEN", 0.3, 0.55, 100))
        sc.seg(300, left=still("FIST", 0.3, 0.55, 100))
        sc.seg(1200, left=still("OPEN", 0.3, 0.55, 100))
        self.assertEqual(skills(sc.run()), ["earth", "earth"])

    def test_earth_progress_in_debug_state(self):
        sc = Script(seed=37)
        sc.seg(500, left=still("OPEN", 0.3, 0.55, 100))
        eng = GestureEngine(config)
        run_frames(sc.frames, eng)
        p = eng.debug_state()["earth"]["progress"]
        self.assertTrue(0.3 < p < 0.7, p)

    def test_no_earth_right_hand(self):
        sc = Script(seed=38)
        sc.seg(1500, right=still("OPEN", 0.7, 0.55, 100))
        self.assertEqual(skills(sc.run()), [])


class TestNegativesMisc(unittest.TestCase):
    def test_waving_produces_nothing(self):
        # 5. waving left-right for 2 s, in every pose, either hand -> nothing
        for i, pose in enumerate(("OPEN", "FIST", "TWO")):
            for label in ("Left", "Right"):
                with self.subTest(pose=pose, hand=label):
                    sc = Script(seed=40 + i)
                    fn = wave(pose, 0.5, 0.55)
                    sc.seg(2000, **{label.lower(): fn})
                    self.assertEqual(skills(sc.run()), [])

    def test_waving_both_hands(self):
        sc = Script(seed=50)
        sc.seg(2000, left=wave("OPEN", 0.3, 0.55), right=wave("OPEN", 0.7, 0.55))
        self.assertEqual(skills(sc.run()), [])

    def test_empty_and_stale_input(self):
        eng = GestureEngine(config)
        self.assertEqual(eng.update(1000, {"Left": [], "Right": []}), [])
        self.assertEqual(eng.update(1033, {}), [])
        syn = Synth(0)
        old = [syn.sample(t, "FIST", 0.6, 0.6, 100 + t / 3) for t in range(0, 200, 33)]
        # newest sample is 1 s old -> hand not visible -> nothing
        self.assertEqual(eng.update(1200, {"Left": [], "Right": old}), [])
        st = eng.debug_state()
        for k in ("fire", "water", "lightning", "earth", "poses", "lock_remaining_ms"):
            self.assertIn(k, st)


# --------------------------------------------------------------------------
def cfg_with(**overrides):
    """Copy of config (all UPPERCASE names) with overrides; for GestureEngine(cfg)."""
    d = {k: getattr(config, k) for k in dir(config) if k.isupper()}
    d.update(overrides)
    return types.SimpleNamespace(**d)


def wrist_for_palm(px, py, pose="OPEN", size=100.0):
    """Wrist (cx, cy) that puts the jitter-free palm center at (px, py)."""
    ox, oy = F.palm_center(Synth(0, 0.0, 0.0).sample(0, pose, 0.0, 0.0, size))
    return px - ox, py - oy


class TestEarthZone(unittest.TestCase):
    def _hold(self, seed, px, py, ms=1200, cfg=None):
        cx, cy = wrist_for_palm(px, py)
        sc = Script(seed=seed)
        sc.seg(ms, left=still("OPEN", cx, cy, 100))
        eng = GestureEngine(cfg or config)
        return skills(run_frames(sc.frames, eng, cfg=cfg or config)), eng

    def test_palm_center_definition(self):
        s = Synth(0, 0.0, 0.0).sample(0, "OPEN", 0.3, 0.55, 100)
        pts = [s.landmarks[i] for i in (0, 5, 9, 13, 17)]
        x, y = F.palm_center(s)
        self.assertAlmostEqual(x, sum(p[0] for p in pts) / 5)
        self.assertAlmostEqual(y, sum(p[1] for p in pts) / 5)
        # existing earth tests (wrist 0.3,0.55) have their palm center inside the zone
        self.assertTrue(F.in_earth_zone(s))

    def test_earth_in_zone_fires(self):
        # (a) left palm still 1.2 s at chest/face height, middle of frame -> 1 earth
        ev, eng = self._hold(60, 0.5, 0.4)
        self.assertEqual(ev, ["earth"])
        self.assertIs(eng.debug_state()["earth"]["in_zone"], True)

    def test_no_earth_low_in_frame(self):
        # (b) palm center at y=0.85 (bottom of frame) -> nothing
        ev, eng = self._hold(61, 0.5, 0.85)
        self.assertEqual(ev, [])
        self.assertIs(eng.debug_state()["earth"]["in_zone"], False)
        self.assertEqual(eng.debug_state()["earth"]["progress"], 0.0)

    def test_no_earth_left_edge(self):
        # (c) palm center at x=0.1 (left edge) -> nothing
        ev, eng = self._hold(62, 0.1, 0.4)
        self.assertEqual(ev, [])
        self.assertIs(eng.debug_state()["earth"]["in_zone"], False)

    def test_zone_disabled_fires_anywhere(self):
        # (d) EARTH_ZONE_X = EARTH_ZONE_MAX_Y = None -> fires at the positions of (b) and (c)
        cfg = cfg_with(EARTH_ZONE_X=None, EARTH_ZONE_MAX_Y=None)
        for i, (px, py) in enumerate(((0.5, 0.85), (0.1, 0.4), (0.92, 0.9))):
            with self.subTest(px=px, py=py):
                ev, _ = self._hold(63 + i, px, py, cfg=cfg)
                self.assertEqual(ev, ["earth"])

    def test_zone_parts_disable_independently(self):
        self.assertEqual(self._hold(66, 0.5, 0.85, cfg=cfg_with(EARTH_ZONE_MAX_Y=None))[0], ["earth"])
        self.assertEqual(self._hold(67, 0.1, 0.4, cfg=cfg_with(EARTH_ZONE_X=None))[0], ["earth"])
        self.assertEqual(self._hold(68, 0.1, 0.85, cfg=cfg_with(EARTH_ZONE_X=None))[0], [])

    def test_leaving_zone_breaks_hold(self):
        # Palm drifts slowly (within stillness limits) from just inside the zone
        # (y=0.62) to just below it (y=0.68) and stays there. Without the zone check
        # this is a valid 1.7 s still hold; with it the hold breaks at y > 0.65.
        a, b = wrist_for_palm(0.5, 0.62), wrist_for_palm(0.5, 0.68)
        sc = Script(seed=69)
        sc.seg(600, left=still("OPEN", a[0], a[1], 100))
        sc.seg(500, left=move("OPEN", a, b, 100))
        sc.seg(600, left=still("OPEN", b[0], b[1], 100))
        self.assertEqual(skills(sc.run()), [])
        # control: same motion with the zone disabled -> earth fires
        cfg = cfg_with(EARTH_ZONE_X=None, EARTH_ZONE_MAX_Y=None)
        self.assertEqual(skills(run_frames(sc.frames, GestureEngine(cfg), cfg=cfg)), ["earth"])

    def test_engine_reset(self):
        sc = Script(seed=70)
        sc.seg(500, left=still("OPEN", 0.3, 0.55, 100))
        eng = GestureEngine(config)
        run_frames(sc.frames, eng)
        self.assertGreater(eng.debug_state()["earth"]["progress"], 0.3)
        eng.reset()
        st = eng.debug_state()
        self.assertEqual(st["earth"]["progress"], 0.0)
        self.assertIsNone(st["t_ms"])
        self.assertEqual(st["lock_remaining_ms"], 0)


# --------------------------------------------------------------------------
# Mirror / handedness (tracker.py). tracker imports mediapipe + cv2 at module level;
# HandTracker is instantiated WITHOUT start(), the callback is fed fake results.
try:
    import tracker as T  # noqa: E402
except ImportError as _e:  # pragma: no cover
    T = None
    _TRACKER_IMPORT_ERROR = str(_e)


def _fake_result(hands):
    """hands: list of (mediapipe_label, score, x_offset). Builds a HandLandmarkerResult-like object."""
    ns = types.SimpleNamespace
    lms, worlds, hd = [], [], []
    for label, score, x0 in hands:
        lms.append([ns(x=x0 + 0.001 * i, y=0.5, z=0.0) for i in range(21)])
        worlds.append([ns(x=0.01 + 0.001 * i, y=0.0, z=0.0) for i in range(21)])
        hd.append([ns(category_name=label, score=score)])
    return ns(hand_landmarks=lms, hand_world_landmarks=worlds, handedness=hd)


@unittest.skipIf(T is None, "tracker/mediapipe not importable")
class TestMirrorHandedness(unittest.TestCase):
    def test_effective_swap_truth_table(self):
        # MediaPipe assumes a mirrored input: raw frame -> swap; manual override XORs.
        self.assertFalse(T.effective_swap(False, True))   # mirror ON, no override
        self.assertTrue(T.effective_swap(False, False))   # mirror OFF -> auto swap
        self.assertTrue(T.effective_swap(True, True))     # override only
        self.assertFalse(T.effective_swap(True, False))   # override cancels auto swap

    def test_labels_physical_right_both_modes(self):
        for mirror, mp_label in ((True, "Right"), (False, "Left")):
            with self.subTest(mirror=mirror):
                tr = T.HandTracker(swap_handedness=False, mirror=mirror)
                ts = tr._register_frame(1000, mirrored=mirror)
                tr._on_result(_fake_result([(mp_label, 0.9, 0.6)]), None, ts)
                self.assertIsNotNone(tr.get_latest("Right"))
                self.assertIsNone(tr.get_latest("Left"))
                tr.set_swap(True)  # manual override flips it
                self.assertIsNone(tr.get_latest("Right"))  # history cleared
                ts = tr._register_frame(1100, mirrored=mirror)
                tr._on_result(_fake_result([(mp_label, 0.9, 0.6)]), None, ts)
                self.assertIsNotNone(tr.get_latest("Left"))

    def test_mirror_toggle_race_uses_frame_state(self):
        tr = T.HandTracker(swap_handedness=False, mirror=True)
        ts_old = tr._register_frame(1000, mirrored=True)  # submitted before the toggle
        T.set_mirror(None, tr, False)  # 's' pressed while ts_old is still in flight
        self.assertFalse(tr.mirror)
        ts_new = tr._register_frame(1033, mirrored=False)

        # Old (mirrored) frame returns late: physical right -> MediaPipe 'Right'.
        # Global state (mirror OFF) would wrongly swap it to 'Left'.
        tr._on_result(_fake_result([("Right", 0.9, 0.7)]), None, ts_old)
        s = tr.get_latest("Right")
        self.assertIsNotNone(s)
        self.assertIsNone(tr.get_latest("Left"))
        self.assertEqual(s.timestamp_ms, ts_old)
        # coordinates converted to the CURRENT (non-mirrored) space: x -> 1 - x
        self.assertAlmostEqual(s.landmarks[0][0], 0.3, places=6)
        self.assertAlmostEqual(s.world[0][0], -0.01, places=6)

        # New raw frame: physical right -> MediaPipe 'Left' -> auto-swapped to 'Right'.
        tr._on_result(_fake_result([("Left", 0.9, 0.3)]), None, ts_new)
        s = tr.get_latest("Right")
        self.assertEqual(s.timestamp_ms, ts_new)
        self.assertAlmostEqual(s.landmarks[0][0], 0.3, places=6)  # untouched
        self.assertIsNone(tr.get_latest("Left"))
        self.assertEqual(len(tr.get_history("Right")), 2)
        self.assertEqual(tr._ts_mirror, {})

    def test_set_mirror_clears_history_and_resets_engine(self):
        tr = T.HandTracker(mirror=True)
        tr._on_result(_fake_result([("Right", 0.9, 0.6)]), None, tr._register_frame(1000, True))
        self.assertEqual(len(tr.get_history("Right")), 1)
        cam = types.SimpleNamespace(mirror=True)
        eng = GestureEngine(config)
        eng.update(5000, {"Left": [], "Right": []})
        T.set_mirror(cam, tr, False, eng)
        self.assertFalse(cam.mirror)
        self.assertFalse(tr.mirror)
        self.assertEqual(tr.get_history("Right"), [])
        self.assertIsNone(eng.debug_state()["t_ms"])  # engine was reset

    def test_ts_mirror_pruning_and_fallback(self):
        tr = T.HandTracker(mirror=True)
        a = tr._register_frame(1000, True)
        b = tr._register_frame(1000, True)  # same clock -> strictly increasing ts
        c = tr._register_frame(1000, False)
        self.assertEqual((b - a, c - b), (1, 1))
        # MediaPipe dropped a and b (busy); c returns -> older entries are pruned
        tr._on_result(_fake_result([("Left", 0.9, 0.3)]), None, c)
        self.assertEqual(tr._ts_mirror, {})
        # c was raw (mirror OFF) -> 'Left' swapped to 'Right'; then flipped to the
        # current mirrored space since tracker.mirror is still True
        self.assertAlmostEqual(tr.get_latest("Right").landmarks[0][0], 0.7, places=6)
        # unknown ts (never registered) -> falls back to the current mirror state
        tr._on_result(_fake_result([("Right", 0.9, 0.6)]), None, 9999)
        self.assertEqual(tr.get_latest("Right").timestamp_ms, 9999)
        # bounded even if callbacks never arrive
        for i in range(T._TS_MIRROR_MAX + 50):
            tr._register_frame(20000 + i, True)
        self.assertEqual(len(tr._ts_mirror), T._TS_MIRROR_MAX)

    def test_toggle_keys(self):
        tr = T.HandTracker(swap_handedness=False, mirror=True)
        cam = types.SimpleNamespace(mirror=True)
        self.assertTrue(T.handle_toggle_key(config.MIRROR_KEY, cam, tr))
        self.assertEqual((cam.mirror, tr.mirror, tr.swap_handedness), (False, False, False))
        self.assertTrue(T.handle_toggle_key(config.SWAP_KEY, cam, tr))
        self.assertEqual((cam.mirror, tr.mirror, tr.swap_handedness), (False, False, True))
        self.assertFalse(T.handle_toggle_key(ord("x"), cam, tr))
        self.assertEqual(T.status_text(tr), "mirror: OFF  swap: ON")
        self.assertEqual((config.MIRROR_KEY, config.SWAP_KEY), (ord("s"), ord("h")))


if __name__ == "__main__":
    unittest.main()


class TestEarthRightHandPolicy(unittest.TestCase):
    """Regression (Phase 6 verifier bug #1): Earth must not fire while both palms are
    up (getting ready for / finishing Water), and must not swallow a Water push."""

    def _palms(self, sc, ms, size=100):
        sc.seg(ms, left=still("OPEN", 0.35, 0.6, size), right=still("OPEN", 0.65, 0.6, size))

    def _push(self, sc):
        sc.seg(200, left=grow("OPEN", 0.35, 0.6, 100, 140), right=grow("OPEN", 0.65, 0.6, 100, 140))

    def test_water_then_hold_both_palms_no_earth(self):
        sc = Script(seed=11)
        self._palms(sc, 400)
        self._push(sc)
        self._palms(sc, 1500, size=140)
        self.assertEqual(skills(sc.run()), ["water"])

    def test_palms_ready_long_then_water_not_swallowed(self):
        sc = Script(seed=12)
        self._palms(sc, 1200)
        self._push(sc)
        self._palms(sc, 300, size=140)
        self.assertEqual(skills(sc.run()), ["water"])

    def test_left_palm_with_right_fist_still_allows_earth(self):
        # Policy "not_open" only blocks an OPEN right palm.
        sc = Script(seed=13)
        sc.seg(1300, left=still("OPEN", 0.35, 0.5, 100), right=still("FIST", 0.65, 0.6, 100))
        self.assertEqual(skills(sc.run()), ["earth"])

    def test_policy_absent_blocks_any_visible_right_hand(self):
        sc = Script(seed=13)
        sc.seg(1300, left=still("OPEN", 0.35, 0.5, 100), right=still("FIST", 0.65, 0.6, 100))
        self.assertEqual(skills(sc.run(GestureEngine(cfg_with(EARTH_RIGHT_HAND="absent")))), [])

    def test_policy_any_restores_old_behaviour(self):
        sc = Script(seed=12)
        self._palms(sc, 1200)
        self.assertEqual(skills(sc.run(GestureEngine(cfg_with(EARTH_RIGHT_HAND="any")))), ["earth"])


class TestRecorderKeepsAllSamples(unittest.TestCase):
    """Regression (Phase 6 verifier bug #4): samples between two writes must not be lost."""

    def test_two_results_between_writes(self):
        import json
        import tempfile
        old_dir = config.RECORDINGS_DIR
        config.RECORDINGS_DIR = tempfile.mkdtemp()
        try:
            import main_gestures as MG
            syn = Synth(1)
            h = [syn.sample(t, "OPEN", .5, .5, 100) for t in (0, 33, 66)]
            r = MG.Recorder()
            r.toggle()
            r.write(0, {"Left": h[:1], "Right": []})
            r.write(66, {"Left": h[:3], "Right": []})
            r.write(66, {"Left": h[:3], "Right": []})  # nothing new
            r.toggle()
            with open(r.path, encoding="utf-8") as f:
                lines = [json.loads(l) for l in f]
            got = [s["timestamp_ms"] for l in lines for s in (l["hands"]["Left"] or [])]
            self.assertEqual(got, [0, 33, 66])
            self.assertIsNone(lines[2]["hands"]["Left"])
        finally:
            config.RECORDINGS_DIR = old_dir
