"""Phase 2 debug loop: webcam -> HandTracker -> GestureEngine -> overlay window.

Keys: q/ESC quit, s toggle camera mirror (Left/Right labels auto-corrected),
h toggle manual Left/Right swap (runtime only), r start/stop recording
to recordings/rec_YYYYmmdd_HHMMSS.jsonl (replay with `python replay.py <file>`).
Detected events are also printed to the console. The steering controller
(steering.py) runs too: bar at the bottom (center = 0) + reason, thin vertical
lines at the frame center and at the deadzone edges.
"""
import json
import os
import time

import cv2

import config
from capture import CameraCapture
from gestures import GestureEngine
from main_debug import FpsMeter, draw_hand  # reuse Phase 1 drawing helpers
from replay import sample_to_dict
from steering import SteerController
from tracker import WRIST, HandTracker, handle_toggle_key, status_text

LABELS = ("Left", "Right")


def _fmt(v, nd=2):
    return "-" if v is None else f"{v:.{nd}f}"


class Recorder:
    """One JSON line per engine update with every NEW sample per hand (list, or null)."""

    def __init__(self):
        self._f = None
        self._last_ts = {l: None for l in LABELS}
        self.path = None

    @property
    def active(self):
        return self._f is not None

    def toggle(self):
        if self._f is not None:
            self._f.close()
            self._f = None
            print(f"[rec] stopped: {self.path}")
            return
        os.makedirs(config.RECORDINGS_DIR, exist_ok=True)
        self.path = os.path.join(
            config.RECORDINGS_DIR, time.strftime("rec_%Y%m%d_%H%M%S.jsonl"))
        self._f = open(self.path, "w", encoding="utf-8")
        self._last_ts = {l: None for l in LABELS}
        print(f"[rec] recording to {self.path}")

    def write(self, t_ms, hists, mirrored=None):
        """mirrored: coordinate space of the samples (tracker.mirror); stored as the
        "mirrored" field so replay.py steers in the right direction (omitted if None)."""
        if self._f is None:
            return
        hands = {}
        for l in LABELS:
            last = self._last_ts[l]
            # ALL samples newer than the last written one (several detection results
            # can land between two engine updates); replay.py accepts a list.
            new = [s for s in (hists.get(l) or []) if last is None or s.timestamp_ms > last]
            if new:
                self._last_ts[l] = new[-1].timestamp_ms
                hands[l] = [sample_to_dict(s) for s in new]
            else:
                hands[l] = None  # no new sample for this hand in this result
        rec = {"t_ms": int(t_ms), "hands": hands}
        if mirrored is not None:
            rec["mirrored"] = bool(mirrored)
        self._f.write(json.dumps(rec) + "\n")

    def close(self):
        if self._f is not None:
            self.toggle()


def _put(img, text, org, color=None, scale=None, thick=None):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX,
                scale or config.TEXT_SCALE, color or config.TEXT_COLOR_BGR,
                thick or config.TEXT_THICKNESS)


def draw_earth_zone(img):
    """Thin rectangle showing where the left palm center must be for Earth."""
    h, w = img.shape[:2]
    zx = config.EARTH_ZONE_X
    zy = config.EARTH_ZONE_MAX_Y
    if zx is None and zy is None:
        return
    x0, x1 = (zx if zx is not None else (0.0, 1.0))
    y1 = zy if zy is not None else 1.0
    cv2.rectangle(img, (int(x0 * w), 0), (int(x1 * w) - 1, int(y1 * h) - 1),
                  config.EVENT_COLORS_BGR["earth"], 1)


def draw_steer_guides(img):
    """Thin vertical lines: frame center and the deadzone edges (in image space).
    The deadzone is symmetric, so mirroring does not move the lines."""
    h, w = img.shape[:2]
    cx = w // 2
    cv2.line(img, (cx, 0), (cx, h - 1), (200, 200, 200), 1)
    dz = int(round(config.STEER_DEADZONE * w))
    for x in (cx - dz, cx + dz):
        cv2.line(img, (x, 0), (x, h - 1), (120, 120, 120), 1)


def draw_steer_bar(img, sdbg):
    """Bar at the bottom: center = 0, fill toward -1 (left) / +1 (right) + reason."""
    h, w = img.shape[:2]
    bw, bh = min(300, w - 20), 14
    x, y = (w - bw) // 2, h - 30
    value = float(sdbg.get("value") or 0.0)
    cv2.rectangle(img, (x, y), (x + bw, y + bh), (200, 200, 200), 1)
    mid = x + bw // 2
    end = mid + int(round(max(-1.0, min(1.0, value)) * (bw // 2)))
    if end != mid:
        cv2.rectangle(img, (min(mid, end), y + 1), (max(mid, end), y + bh - 1),
                      config.STEER_BAR_COLOR_BGR, -1)
    cv2.line(img, (mid, y - 3), (mid, y + bh + 3), (255, 255, 255), 1)
    gl, gr = sdbg.get("growth_L"), sdbg.get("growth_R")
    text = (f"steer {value:+.2f} raw {_fmt(sdbg.get('raw'))} off {_fmt(sdbg.get('offset'))}"
            f"  {sdbg.get('reason')}  g {_fmt(gl)}/{_fmt(gr)}")
    _put(img, text, (10, y - 8),
         color=config.STEER_BAR_COLOR_BGR if sdbg.get("active") else config.TEXT_COLOR_BGR)


def draw_overlay(img, dbg, hists, ts_ms, cam_fps, det_fps, status, recording, flash,
                 steer_dbg=None):
    h, w = img.shape[:2]
    draw_earth_zone(img)
    if steer_dbg is not None:
        draw_steer_guides(img)
        draw_steer_bar(img, steer_dbg)
    poses = dbg.get("poses", {})
    visible = 0
    for label in LABELS:
        hist = hists.get(label) or []
        s = hist[-1] if hist else None
        if s is not None and ts_ms - s.timestamp_ms <= config.HAND_STALE_MS:
            visible += 1
            draw_hand(img, s, label)
            wx, wy = s.landmarks[WRIST][0] * w, s.landmarks[WRIST][1] * h
            _put(img, poses.get(label) or "-", (int(wx) + 10, int(wy) + 20),
                 color=(255, 255, 0))

    fire, water = dbg.get("fire", {}), dbg.get("water", {})
    light, earth = dbg.get("lightning", {}), dbg.get("earth", {})
    lines = [
        f"cam FPS: {cam_fps:.1f}  det FPS: {det_fps:.1f}  hands: {visible}  {status}",
        f"L: {poses.get('Left') or '-'}   R: {poses.get('Right') or '-'}"
        f"   lock: {dbg.get('lock_remaining_ms', 0)} ms",
        f"fire  growth {_fmt(fire.get('growth'))}/{config.FIRE_GROWTH_MIN}"
        f"  chest {fire.get('chest_ok')}  {'armed' if fire.get('armed') else 'wait'}",
        f"water gL {_fmt(water.get('growth_L'))} gR {_fmt(water.get('growth_R'))}"
        f"/{config.WATER_GROWTH_MIN}  {'armed' if water.get('armed') else 'wait'}",
        f"light down {_fmt(light.get('vel'))}/{config.LIGHTNING_MIN_VEL} size/s"
        f"  travel {_fmt(light.get('travel'))}/{config.LIGHTNING_MIN_TRAVEL}",
        f"earth drift {_fmt(earth.get('drift'))} dscale {_fmt(earth.get('scale_change'))}"
        f"  zone {earth.get('in_zone')}  {'armed' if earth.get('armed') else 'release pose'}",
    ]
    for i, t in enumerate(lines):
        _put(img, t, (10, 22 + 22 * i))

    # Earth hold progress bar.
    y = 22 + 22 * len(lines) - 8
    prog = float(earth.get("progress") or 0.0)
    cv2.rectangle(img, (10, y), (210, y + 12), (200, 200, 200), 1)
    cv2.rectangle(img, (10, y), (10 + int(200 * prog), y + 12),
                  config.EVENT_COLORS_BGR["earth"], -1)

    if recording:
        cv2.circle(img, (w - 20, 20), 8, (0, 0, 255), -1)
        _put(img, "REC", (w - 75, 27), color=(0, 0, 255))

    if flash is not None:
        skill, conf, age_ms = flash
        if (age_ms // config.EVENT_FLASH_PERIOD_MS) % 2 == 0:  # blink
            text = f"{skill.upper()} {conf:.2f}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX,
                                          config.EVENT_TEXT_SCALE, config.EVENT_TEXT_THICKNESS)
            _put(img, text, ((w - tw) // 2, (h + th) // 2),
                 color=config.EVENT_COLORS_BGR.get(skill, (255, 255, 255)),
                 scale=config.EVENT_TEXT_SCALE, thick=config.EVENT_TEXT_THICKNESS)


def main():
    cam = CameraCapture()
    tracker = HandTracker(swap_handedness=config.SWAP_HANDEDNESS)  # runtime copy only
    engine = GestureEngine(config)
    steer_ctl = SteerController(config)
    recorder = Recorder()
    cam_fps = FpsMeter(config.FPS_AVG_WINDOW)
    det_fps = FpsMeter(config.FPS_AVG_WINDOW)
    last_id = 0
    last_results = 0
    last_console = time.perf_counter()
    flash_event, flash_wall = None, 0.0
    hists = {l: [] for l in LABELS}
    try:
        cam.start()
        tracker.start()
        while True:
            frame, fid, mirrored = cam.read_latest_tagged()
            if frame is not None and fid != last_id:
                last_id = fid
                now = time.perf_counter()
                cam_fps.tick(now)
                ts_ms = int(now * 1000)
                tracker.submit(frame, ts_ms, mirrored=mirrored)

                n, result_ms, hists = tracker.snapshot()
                if n != last_results:  # one engine update per new detection result
                    last_results = n
                    det_fps.tick(now)
                    t_ms = result_ms if result_ms >= 0 else ts_ms
                    events = engine.update(t_ms, hists)
                    steer_ctl.update(t_ms, hists, mirrored=tracker.mirror, events=events)
                    for e in events:
                        print(f"[event] {e.skill:<9} conf={e.conf:.2f} t_ms={e.t_ms}")
                        flash_event, flash_wall = e, now
                    recorder.write(t_ms, hists, mirrored=tracker.mirror)

                if config.DEBUG_WINDOW:
                    img = frame.copy()
                    flash = None
                    if flash_event is not None:
                        age_ms = int((now - flash_wall) * 1000)
                        if age_ms < config.EVENT_FLASH_MS:
                            flash = (flash_event.skill, flash_event.conf, age_ms)
                    draw_overlay(img, engine.debug_state(), hists, ts_ms,
                                 cam_fps.fps(), det_fps.fps(), status_text(tracker),
                                 recorder.active, flash, steer_ctl.debug_state())
                    cv2.imshow(config.GESTURE_WINDOW_TITLE, img)
                elif now - last_console >= config.CONSOLE_FPS_INTERVAL_S:
                    last_console = now
                    print(f"cam FPS {cam_fps.fps():.1f} | det FPS {det_fps.fps():.1f}")
            else:
                time.sleep(config.MAIN_IDLE_SLEEP_S)

            if config.DEBUG_WINDOW:
                key = cv2.waitKey(1) & 0xFF
                if key in config.QUIT_KEYS:
                    break
                # s = mirror, h = manual swap; both clear history + reset the engine
                if handle_toggle_key(key, cam, tracker, engine):
                    steer_ctl.reset()
                if key == config.RECORD_KEY:
                    recorder.toggle()
    except KeyboardInterrupt:
        pass
    finally:
        recorder.close()
        tracker.close()
        cam.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
