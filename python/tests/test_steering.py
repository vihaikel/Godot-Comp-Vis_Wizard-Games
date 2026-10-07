"""Steering (kemudi) tests with synthetic hands (no webcam, no mediapipe).

Run:  cd python && python3 -m unittest discover -s tests -v

Reuses the synthetic hand generator of test_gestures.py (Synth/Script/still/grow/
move, 30 fps, deterministic jitter). Both palms OPEN facing the camera; "mid" is
the mean x of the two palm centers (Left palm at mid - D, Right palm at mid + D,
as seen in the default mirrored/selfie view).
"""
import math
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import config  # noqa: E402
from gestures import GestureEngine, GestureEvent  # noqa: E402
from replay import run_frames  # noqa: E402
from steering import SteerController, offset_to_raw  # noqa: E402
from test_gestures import (DT, Script, cfg_with, grow, move, still,  # noqa: E402
                           wrist_for_palm)

D = 0.12  # half distance between the two palm centers
Y = 0.5  # palm center height


def wr(px, pose="OPEN", size=100.0):
    return wrist_for_palm(px, Y, pose, size)


def palms(sc, ms, mid, size=100.0, pose_l="OPEN", pose_r="OPEN", left=True, right=True):
    """Both hands still, palm centers at mid -+ D."""
    l, r = wr(mid - D, pose_l, size), wr(mid + D, pose_r, size)
    sc.seg(ms, left=still(pose_l, l[0], l[1], size) if left else None,
           right=still(pose_r, r[0], r[1], size) if right else None)
    return sc


def slide(sc, ms, mid0, mid1, size=100.0):
    sc.seg(ms, left=move("OPEN", wr(mid0 - D), wr(mid1 - D), size),
           right=move("OPEN", wr(mid0 + D), wr(mid1 + D), size))
    return sc


def push(sc, ms, mid, s0=100.0, s1=140.0):
    """Both palms grow s0 -> s1 in ms (wrists fixed at the size-100 position)."""
    l, r = wr(mid - D), wr(mid + D)
    sc.seg(ms, left=grow("OPEN", l[0], l[1], s0, s1), right=grow("OPEN", r[0], r[1], s0, s1))
    return sc


def run(sc, mirrored=True, cfg=config):
    """-> (updates, events); updates = list of dict(t, value, reason, skills, active)."""
    st = SteerController(cfg)
    ups = []

    def on_update(t, evs, v):
        d = st.debug_state()
        ups.append(dict(t=t, value=v, reason=d["reason"], active=d["active"],
                        skills=[e.skill for e in evs], dbg=d))

    frames = [(t, fr, mirrored) for t, fr in sc.frames]
    events = run_frames(frames, GestureEngine(cfg), cfg=cfg, steer=st, on_update=on_update)
    return ups, events


def first_index(ups, pred):
    for i, u in enumerate(ups):
        if pred(u):
            return i
    return None


class TestMapping(unittest.TestCase):
    def test_offset_to_raw(self):
        self.assertEqual(offset_to_raw(0.0), 0.0)
        self.assertEqual(offset_to_raw(0.08), 0.0)  # deadzone edge inclusive
        self.assertEqual(offset_to_raw(-0.05), 0.0)
        self.assertAlmostEqual(offset_to_raw(0.19), 0.5)  # (0.19-0.08)/(0.30-0.08)
        self.assertAlmostEqual(offset_to_raw(-0.19), -0.5)
        self.assertEqual(offset_to_raw(0.30), 1.0)
        self.assertEqual(offset_to_raw(0.49), 1.0)  # clamped
        self.assertEqual(offset_to_raw(-0.49), -1.0)
        cfg = cfg_with(STEER_EXPONENT=2.0)
        self.assertAlmostEqual(offset_to_raw(0.19, cfg), 0.25)
        self.assertAlmostEqual(offset_to_raw(-0.19, cfg), -0.25)

    def test_debug_state_and_reset(self):
        st = SteerController()
        d = st.debug_state()
        for k in ("raw", "value", "active", "reason", "offset", "growth_L", "growth_R"):
            self.assertIn(k, d)
        sc = palms(Script(seed=100), 400, 0.75)
        st2 = SteerController()
        run_frames(sc.frames, GestureEngine(), steer=st2)
        self.assertGreater(st2.value, 0.5)
        st2.reset()
        self.assertEqual(st2.value, 0.0)
        self.assertEqual(st2.debug_state()["reason"], "no_hands")
        self.assertEqual(st2.update(0, {}, mirrored=True), 0.0)


class TestDirection(unittest.TestCase):
    def test_1_right_positive_left_negative(self):
        for mid, sign in ((0.75, 1), (0.25, -1)):
            with self.subTest(mid=mid):
                ups, ev = run(palms(Script(seed=101), 600, mid))
                self.assertEqual(ev, [])
                i = first_index(ups, lambda u: u["reason"] == "ok")
                self.assertIsNotNone(i)
                self.assertLessEqual(i, 5)  # engages after ~4 updates (stable pose + growth window)
                # ~5 updates after engaging the EMA is past 0.5
                self.assertGreater(sign * ups[i + 4]["value"], 0.5)
                self.assertGreater(sign * ups[-1]["value"], 0.5)
                self.assertAlmostEqual(sign * ups[-1]["value"], (0.25 - 0.08) / 0.22, delta=0.03)

    def test_2_raw_frame_flips_sign(self):
        # mirrored=False: same image coordinates mean the opposite physical side
        for mid, sign in ((0.75, -1), (0.25, 1)):
            with self.subTest(mid=mid):
                ups, _ = run(palms(Script(seed=102), 600, mid), mirrored=False)
                self.assertGreater(sign * ups[-1]["value"], 0.5)
                self.assertGreater(ups[-1]["dbg"]["offset"] * sign, 0)

    def test_3_deadzone(self):
        for mid in (0.53, 0.47, 0.5):
            with self.subTest(mid=mid):
                ups, _ = run(palms(Script(seed=103), 800, mid))
                self.assertTrue(all(u["value"] == 0.0 for u in ups))
                self.assertEqual(ups[-1]["reason"], "deadzone")


class TestInactive(unittest.TestCase):
    def test_4_one_palm_or_fists(self):
        cases = {
            "left palm only": dict(right=False),
            "right palm only": dict(left=False),
            "right fist": dict(pose_r="FIST"),
            "left fist": dict(pose_l="FIST"),
            "two fists": dict(pose_l="FIST", pose_r="FIST"),
        }
        for name, kw in cases.items():
            with self.subTest(name):
                ups, _ = run(palms(Script(seed=104), 800, 0.8, **kw))
                self.assertTrue(all(u["value"] == 0.0 for u in ups), name)
                self.assertIn(ups[-1]["reason"], ("no_hands", "not_open"))

    def test_7_hands_lost_zero_within_two_updates(self):
        for name, kw in (("both", dict(left=False, right=False)), ("right", dict(right=False)),
                         ("left", dict(left=False))):
            with self.subTest(name):
                sc = palms(Script(seed=107), 600, 0.75)
                n0 = len(sc.frames)
                palms(sc, 300, 0.75, **kw)
                ups, _ = run(sc)
                self.assertGreater(ups[n0 - 1]["value"], 0.5)
                self.assertEqual(ups[n0 + 1]["value"], 0.0)  # <= 2 updates
                self.assertEqual(ups[n0 + 1]["reason"], "no_hands")
                self.assertTrue(all(u["value"] == 0.0 for u in ups[n0 + 1:]))

    def test_one_missed_detection_is_tolerated(self):
        # A single frame without the right hand (MediaPipe dropout) keeps the value.
        sc = palms(Script(seed=108), 600, 0.75)
        n0 = len(sc.frames)
        palms(sc, DT, 0.75, right=False)
        palms(sc, 300, 0.75)
        ups, _ = run(sc)
        v = ups[n0 - 1]["value"]
        self.assertAlmostEqual(ups[n0]["value"], v, delta=0.03)
        self.assertEqual(ups[n0]["reason"], "ok")


class TestSlideAndPush(unittest.TestCase):
    def test_5_slow_slide_monotonic_no_water(self):
        sc = palms(Script(seed=105), 300, 0.5)
        n0 = len(sc.frames)
        slide(sc, 1000, 0.5, 0.8)
        ups, ev = run(sc)
        self.assertEqual(ev, [])  # in particular no 'water'
        vals = [u["value"] for u in ups[n0:]]
        for a, b in zip(vals, vals[1:]):
            self.assertGreaterEqual(b, a - 0.01)
        self.assertEqual(vals[0], 0.0)
        self.assertGreater(vals[-1], 0.8)
        self.assertTrue(all(u["reason"] in ("deadzone", "ok") for u in ups[n0:]))

    def _push_case(self, push_ms, seed):
        sc = palms(Script(seed=seed), 600, 0.7)
        n_push = len(sc.frames)
        push(sc, push_ms, 0.7)
        n_after = len(sc.frames)
        palms_big = [wr(0.7 - D), wr(0.7 + D)]
        sc.seg(1200, left=still("OPEN", *palms_big[0], 140), right=still("OPEN", *palms_big[1], 140))
        return sc, n_push, n_after

    def test_6_push_triggers_water_once_and_stops_steering(self):
        for push_ms, seed in ((150, 106), (200, 116)):
            with self.subTest(push_ms=push_ms):
                sc, n_push, n_after = self._push_case(push_ms, seed)
                ups, ev = run(sc)
                self.assertEqual([e.skill for e in ev], ["water"])
                self.assertGreater(ups[n_push - 1]["value"], 0.4)  # steering before the push
                t_water = ev[0].t_ms
                # 0 from the 2nd push update (the 1st may still be under STEER_MAX_GROWTH:
                # one update of latency) until >= 400 ms after the Water event
                window = [u for u in ups[n_push + 1:] if u["t"] <= t_water + 400]
                self.assertGreater(len(window), 12)
                for u in window:
                    self.assertEqual(u["value"], 0.0, u)
                    self.assertIn(u["reason"], ("pushing", "suppressed"))
                self.assertLessEqual(ups[n_push]["value"], ups[n_push - 1]["value"] + 0.01)
                # after suppression, hands still at 0.7 -> steering again
                self.assertGreater(ups[-1]["value"], 0.4)
                self.assertEqual(ups[-1]["reason"], "ok")

    def test_6b_slow_push_without_water_pauses_steering(self):
        # Leaning in at a constant relative rate of 0.075 %/ms for 500 ms (+45 %):
        # ~12 % per STEER_LOOKBACK_MS (> STEER_MAX_GROWTH 8 %) but only ~16 % per
        # WATER_LOOKBACK_MS (< WATER_GROWTH_MIN 20 %) -> no Water, yet not a stable
        # distance -> steering paused ('pushing'), resumes once still again.
        # Growth is measured over STEER_LOOKBACK_MS, so a slow push is only seen once
        # it has accumulated > STEER_MAX_GROWTH (~110 ms -> checked from the 5th update).
        k = 0.00075
        sc = palms(Script(seed=126), 600, 0.7)
        n_push = len(sc.frames)
        t0 = sc.t
        size = lambda t: 100.0 * math.exp(k * (t - t0))  # noqa: E731
        (lx, ly), (rx, ry) = wr(0.7 - D), wr(0.7 + D)
        sc.seg(500, left=lambda u, t: dict(pose="OPEN", cx=lx, cy=ly, size_px=size(t)),
               right=lambda u, t: dict(pose="OPEN", cx=rx, cy=ry, size_px=size(t)))
        n_after = len(sc.frames)
        s1 = size(sc.t)
        sc.seg(800, left=still("OPEN", lx, ly, s1), right=still("OPEN", rx, ry, s1))
        ups, ev = run(sc)
        self.assertEqual(ev, [])
        during = ups[n_push + 4:n_after]
        self.assertGreaterEqual(len(during), 10)
        self.assertTrue(all(u["value"] == 0.0 and u["reason"] == "pushing" for u in during),
                        [(u["reason"], round(u["dbg"]["growth_L"] or 0, 3)) for u in during])
        self.assertGreater(ups[-1]["value"], 0.4)

    def test_water_event_suppresses_for_window(self):
        # Direct: an injected 'water' event zeroes steering for STEER_SUPPRESS_AFTER_WATER_MS.
        sc = palms(Script(seed=127), 1500, 0.75)
        st = SteerController()
        hist = {"Left": [], "Right": []}
        out = []
        t_water = sc.frames[20][0]
        for t, fr in sc.frames:
            for l in ("Left", "Right"):
                hist[l] = (hist[l] + [fr[l]])[-config.HISTORY_LEN:]
            evs = [GestureEvent("water", 0.9, t)] if t == t_water else []
            if t == sc.frames[10][0]:
                evs = [GestureEvent("fire", 0.9, t)]  # other skills do not suppress
            out.append((t, st.update(t, hist, mirrored=True, events=evs)))
        before = [v for t, v in out if t < t_water]
        sup = [v for t, v in out if t_water <= t < t_water + config.STEER_SUPPRESS_AFTER_WATER_MS]
        self.assertGreater(before[-1], 0.5)
        self.assertGreater(min(before[10:]), 0.5)  # 'fire' did not suppress
        self.assertTrue(all(v == 0.0 for v in sup))
        self.assertGreater(out[-1][1], 0.5)


class TestGlitchAndRegression(unittest.TestCase):
    def test_8_single_frame_pose_glitch_keeps_value(self):
        sc = palms(Script(seed=108), 600, 0.75)
        n0 = len(sc.frames)
        palms(sc, DT, 0.75, pose_r="FIST")  # one misclassified frame
        palms(sc, 300, 0.75)
        ups, _ = run(sc)
        v = ups[n0 - 1]["value"]
        self.assertGreater(v, 0.5)
        for u in ups[n0:n0 + 4]:  # the glitch stays in the 3-sample pose window for 3 updates
            self.assertGreaterEqual(u["value"], 0.95 * v)
            self.assertEqual(u["reason"], "ok")

    def test_8b_real_fist_releases_and_decays(self):
        sc = palms(Script(seed=118), 600, 0.75)
        n0 = len(sc.frames)
        palms(sc, 500, 0.75, pose_r="FIST")
        ups, _ = run(sc)
        self.assertEqual(ups[n0]["reason"], "ok")  # 1 non-open sample tolerated
        self.assertEqual(ups[n0 + 1]["reason"], "not_open")  # 2nd fist frame releases
        vals = [u["value"] for u in ups[n0 + 1:]]
        for a, b in zip(vals, vals[1:]):
            self.assertLessEqual(b, a)
        self.assertEqual(vals[9], 0.0)  # EMA decay + snap within ~10 updates
        self.assertEqual(vals[-1], 0.0)

    def test_9_steering_does_not_trigger_earth(self):
        sc = palms(Script(seed=109), 500, 0.7)
        slide(sc, 700, 0.7, 0.3)
        palms(sc, 300, 0.3)  # 1.5 s total
        ups, ev = run(sc)
        self.assertEqual([e.skill for e in ev], [])  # no 'earth' (nor anything else)
        self.assertTrue(any(u["value"] > 0.5 for u in ups))
        self.assertLess(ups[-1]["value"], -0.5)


class TestRecordingReplay(unittest.TestCase):
    """Recorder stores "mirrored"; replay.py runs SteerController and prints a summary."""

    def test_recorder_mirrored_field_and_replay_summary(self):
        import contextlib
        import io
        import json
        import tempfile

        import replay
        try:
            import main_gestures as MG
        except ImportError as e:  # pragma: no cover (cv2 missing)
            self.skipTest(f"main_gestures not importable: {e}")
        old_dir = config.RECORDINGS_DIR
        config.RECORDINGS_DIR = tempfile.mkdtemp()
        try:
            sc = palms(Script(seed=130), 600, 0.75)
            palms(sc, 600, 0.5)
            for mirrored, sign in ((True, 1), (False, -1)):
                with self.subTest(mirrored=mirrored):
                    rec = MG.Recorder()
                    rec.toggle()
                    hist = {"Left": [], "Right": []}
                    for t, fr in sc.frames:
                        for l in ("Left", "Right"):
                            hist[l] = (hist[l] + [fr[l]])[-config.HISTORY_LEN:]
                        rec.write(t, hist, mirrored=mirrored)
                    rec.toggle()
                    with open(rec.path, encoding="utf-8") as f:
                        first = json.loads(f.readline())
                    self.assertIs(first["mirrored"], mirrored)
                    frames = replay.load_frames(rec.path)
                    self.assertEqual(frames[0][2], mirrored)
                    st = SteerController()
                    vals = []
                    replay.run_frames(frames, steer=st, on_update=lambda t, e, v: vals.append(v))
                    self.assertGreater(sign * max(vals, key=abs), 0.5)
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        self.assertEqual(replay.main(["replay.py", rec.path]), 0)
                    text = out.getvalue()
                    self.assertIn("steer     aktif", text)
                    pct = float(text.split("aktif ")[1].split("%")[0])
                    self.assertTrue(30.0 < pct < 70.0, text)  # steering ~first half only
                    os.remove(rec.path)
            # a line without "mirrored" (old recording) defaults to True
            path = os.path.join(config.RECORDINGS_DIR, "old.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"t_ms": 1, "hands": {"Left": None, "Right": None}}) + "\n")
            self.assertEqual(replay.load_frames(path)[0][2], True)
        finally:
            import shutil
            shutil.rmtree(config.RECORDINGS_DIR, ignore_errors=True)
            config.RECORDINGS_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
