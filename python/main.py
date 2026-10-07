"""Game runtime (Phase 1+2+3): webcam -> HandTracker -> GestureEngine + SteerController -> UDP -> Godot.

Usage:  python main.py [--no-window] [--host 127.0.0.1] [--port 4242]
Keys (preview window only): q/ESC quit, s toggle camera mirror (labels
auto-corrected), h toggle manual Left/Right swap.
Steering: both open palms slid left/right of the frame center (see steering.py).
Protocol: see PROTOCOL.md. Godot must be running to receive; sending without a
listener is harmless (UDP is fire-and-forget).
"""
import argparse
import time

import cv2

import config
from capture import CameraCapture
from gestures import GestureEngine
from main_debug import draw_hand
from sender import UdpSender
from steering import SteerController
from tracker import LABELS, HandTracker, handle_toggle_key, status_text

PREVIEW_SCALE = 0.5  # "small" preview window
PREVIEW_TITLE = "Comp Vis Game - gesture sender"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--no-window", action="store_true",
                   help="force headless mode (no preview window)")
    p.add_argument("--host", default=None,
                   help="destination host (default: config.UDP_HOST)")
    p.add_argument("--port", type=int, default=None,
                   help="destination port (default: config.UDP_PORT)")
    return p.parse_args()


def draw_steer_bar(img, value, x, y, w=120, h=10):
    """Small horizontal bar: center tick = 0, fill toward -1 (left) / +1 (right)."""
    cv2.rectangle(img, (x, y), (x + w, y + h), (200, 200, 200), 1)
    mid = x + w // 2
    end = mid + int(round(max(-1.0, min(1.0, value)) * (w // 2)))
    if end != mid:
        cv2.rectangle(img, (min(mid, end), y + 1), (max(mid, end), y + h - 1),
                      config.STEER_BAR_COLOR_BGR, -1)
    cv2.line(img, (mid, y - 2), (mid, y + h + 2), (255, 255, 255), 1)


def draw_preview(frame, tracker, ts_ms, last_cast, steer=0.0):
    img = frame.copy()
    for label in LABELS:
        s = tracker.get_latest(label)
        if s is not None and ts_ms - s.timestamp_ms <= config.HAND_STALE_MS:
            draw_hand(img, s, label)
    img = cv2.resize(img, None, fx=PREVIEW_SCALE, fy=PREVIEW_SCALE)
    lines = (f"last: {last_cast}", status_text(tracker), f"steer: {steer:+.2f}")
    for i, text in enumerate(lines):
        cv2.putText(img, text, (8, 20 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    config.TEXT_SCALE, config.TEXT_COLOR_BGR, config.TEXT_THICKNESS)
    draw_steer_bar(img, steer, 8, 20 + 20 * len(lines) - 8)
    return img


def main():
    args = parse_args()
    show_window = config.DEBUG_WINDOW and not args.no_window

    cam = CameraCapture()
    tracker = HandTracker(swap_handedness=config.SWAP_HANDEDNESS)
    engine = GestureEngine()
    steer_ctl = SteerController()
    sender = UdpSender(host=args.host, port=args.port)
    print(f"[net] sending to {sender.host}:{sender.port} sid={sender.sid}")

    last_id = 0
    last_results = 0
    last_cast = "-"
    steer = 0.0
    last_frame_s = float("-inf")
    try:
        cam.start()
        tracker.start()
        while True:
            now_s = time.perf_counter()
            # Heartbeat only while the camera is alive, so Godot's "Gestur aktif"
            # indicator means "gestures can actually arrive", not just "Python runs".
            if now_s - last_frame_s <= config.CAMERA_STALE_S:
                sender.maybe_heartbeat(now_s)
            else:
                # Camera stalled: stop turning. send_steer(0) sends the zero exactly
                # once (retried next loop if rate-limited), then is a no-op.
                if steer != 0.0:
                    steer_ctl.reset()
                    steer = 0.0
                sender.send_steer(0.0, now_s)
            frame, fid, mirrored = cam.read_latest_tagged()
            if frame is not None and fid != last_id:
                last_id = fid
                last_frame_s = now_s
                ts_ms = int(time.perf_counter() * 1000)  # same clock base as HandSample
                tracker.submit(frame, ts_ms, mirrored=mirrored)

                # Atomic read; evaluate gestures at the detection result's own
                # timestamp (not the newest frame's), so hold timers aren't
                # shortened by detection latency.
                n, result_ms, hands = tracker.snapshot()
                if n != last_results and result_ms >= 0:
                    last_results = n
                    events = engine.update(result_ms, hands)
                    steer = steer_ctl.update(result_ms, hands, mirrored=tracker.mirror,
                                             events=events)
                    sender.send_steer(steer, now_s)
                    for ev in events:
                        sent = sender.send_cast(ev.skill, ev.conf)
                        status = "sent" if sent else "debounced"
                        # wall-clock stamp so latency can be compared with Godot's log
                        print(f"[cast] {ev.skill} conf={ev.conf:.2f} {status} "
                              f"(unix={time.time():.3f})")
                        if sent:
                            last_cast = f"{ev.skill} {ev.conf:.2f}"

                if show_window:
                    cv2.imshow(PREVIEW_TITLE, draw_preview(frame, tracker, ts_ms, last_cast, steer))
            else:
                time.sleep(config.MAIN_IDLE_SLEEP_S)

            if show_window:
                key = cv2.waitKey(1) & 0xFF
                if key in config.QUIT_KEYS:
                    break
                # s = mirror, h = manual swap; both clear history + reset the engine
                if handle_toggle_key(key, cam, tracker, engine):
                    steer_ctl.reset()  # old samples used the other mirror/label space
                    steer = 0.0
                    sender.send_steer(0.0, time.perf_counter())
    except KeyboardInterrupt:
        pass
    finally:
        sender.close()
        tracker.close()
        cam.stop()
        if show_window:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
