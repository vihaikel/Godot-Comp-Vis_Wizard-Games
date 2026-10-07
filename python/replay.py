"""Replay a gesture recording through GestureEngine + SteerController (no camera / mediapipe needed).

    python replay.py recordings/rec_YYYYmmdd_HHMMSS.jsonl

Each line: {"t_ms": int, "hands": {"Left": sample|null, "Right": sample|null},
"mirrored": bool (optional, default true)} with sample = {"timestamp_ms",
"landmarks", "world", "score"}. A list of samples per hand is also accepted.
Samples are appended to a per-hand deque(HISTORY_LEN) exactly like HandTracker
does, then GestureEngine.update() and SteerController.update() run per line.
"""
import json
import sys
from collections import Counter, deque

import config
from features import HandSample
from gestures import LABELS, GestureEngine
from steering import SteerController


def sample_from_dict(d):
    return HandSample(
        timestamp_ms=int(d["timestamp_ms"]),
        landmarks=[tuple(p) for p in d["landmarks"]],
        score=float(d.get("score", 1.0)),
        world=[tuple(p) for p in (d.get("world") or [])],
    )


def sample_to_dict(s):
    return {
        "timestamp_ms": int(s.timestamp_ms),
        "landmarks": [list(map(float, p)) for p in s.landmarks],
        "world": [list(map(float, p)) for p in (s.world or [])],
        "score": float(s.score),
    }


def load_frames(path):
    """-> list of (t_ms, {'Left': [HandSample...], 'Right': [...]}, mirrored) (new samples
    per line; mirrored defaults to True for recordings made before the field existed)."""
    frames = []
    with open(path, "r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"line {n}: skipped ({e})", file=sys.stderr)
                continue
            new = {}
            for label in LABELS:
                v = (rec.get("hands") or {}).get(label)
                if v is None:
                    new[label] = []
                elif isinstance(v, list):
                    new[label] = [sample_from_dict(d) for d in v if d]
                else:
                    new[label] = [sample_from_dict(v)]
            frames.append((int(rec["t_ms"]), new, bool(rec.get("mirrored", True))))
    return frames


def run_frames(frames, engine=None, cfg=config, on_event=None, steer=None, on_update=None):
    """Feed frames [(t_ms, {label: HandSample | list | None}[, mirrored])] through an engine.

    Optional steer (SteerController) runs after the engine on every frame with that
    frame's events; mirrored defaults to True. on_update(t_ms, events, steer_value)
    is called per frame (steer_value None without a controller).
    Returns the list of all GestureEvents. Used by replay and by the tests.
    """
    engine = engine or GestureEngine(cfg)
    hist = {l: deque(maxlen=cfg.HISTORY_LEN) for l in LABELS}
    events = []
    for fr in frames:
        t_ms, new = fr[0], fr[1]
        mirrored = bool(fr[2]) if len(fr) > 2 else True
        for label in LABELS:
            v = new.get(label)
            if v is None:
                continue
            for s in (v if isinstance(v, list) else [v]):
                hist[label].append(s)
        hands = {l: list(hist[l]) for l in LABELS}
        evs = engine.update(t_ms, hands)
        value = None
        if steer is not None:
            value = steer.update(t_ms, hands, mirrored=mirrored, events=evs)
        if on_update:
            on_update(t_ms, evs, value)
        for e in evs:
            if on_event:
                on_event(e)
        events.extend(evs)
    return events


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    frames = load_frames(argv[1])
    if not frames:
        print("no frames")
        return 1
    t0 = frames[0][0]
    steer = SteerController()
    stats = SteerStats()
    events = run_frames(
        frames,
        on_event=lambda e: print(f"[{e.t_ms - t0:7d} ms] {e.skill:<9} conf={e.conf:.2f}"),
        steer=steer,
        on_update=lambda t, evs, v: stats.add(t, v, steer.debug_state()["reason"]),
    )
    dur = (frames[-1][0] - t0) / 1000.0
    counts = Counter(e.skill for e in events)
    print(f"--- {len(frames)} updates, {dur:.1f} s, {len(events)} events")
    for skill in ("fire", "water", "lightning", "earth"):
        print(f"{skill:<9} {counts.get(skill, 0)}")
    print(stats.summary())
    return 0


class SteerStats:
    """Time-weighted steer summary: each update's value holds until the next update."""

    def __init__(self):
        self.prev = None  # (t_ms, value)
        self.total_ms = 0
        self.active_ms = 0
        self.abs_ms = 0.0  # integral of |value| dt
        self.reasons = Counter()

    def add(self, t_ms, value, reason):
        self.reasons[reason] += 1
        if self.prev is not None:
            pt, pv = self.prev
            dt = max(0, t_ms - pt)
            self.total_ms += dt
            if pv:
                self.active_ms += dt
                self.abs_ms += abs(pv) * dt
        self.prev = (t_ms, value or 0.0)

    def summary(self):
        pct = 100.0 * self.active_ms / self.total_ms if self.total_ms else 0.0
        mean_all = self.abs_ms / self.total_ms if self.total_ms else 0.0
        mean_act = self.abs_ms / self.active_ms if self.active_ms else 0.0
        reasons = ", ".join(f"{k}={v}" for k, v in self.reasons.most_common())
        return (f"steer     aktif {pct:.1f}% waktu, rata-rata |value| {mean_all:.3f} "
                f"(saat aktif {mean_act:.3f})\nsteer reason (update): {reasons or '-'}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
