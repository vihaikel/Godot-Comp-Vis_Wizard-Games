"""Phase 1 debug loop: webcam -> HandTracker -> overlay window.

MediaPipe API usage lives in tracker.py (docs:
https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python).
This file only uses OpenCV (cv2.imshow / cv2.line / cv2.circle / cv2.putText / cv2.waitKey).

Keys: q/ESC quit, s toggle camera mirror (Left/Right labels auto-corrected),
h toggle manual Left/Right swap (runtime only).
"""
import time
from collections import deque

import cv2

import config
from capture import CameraCapture
from tracker import WRIST, HandTracker, handle_toggle_key, status_text

# Standard 21-point hand skeleton (written by hand; not imported from the legacy MediaPipe solutions API).
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),          # index
    (5, 9), (9, 10), (10, 11), (11, 12),     # middle
    (9, 13), (13, 14), (14, 15), (15, 16),   # ring
    (13, 17), (17, 18), (18, 19), (19, 20),  # pinky
    (0, 17),                                  # palm edge
)


class FpsMeter:
    """Moving average over the last N frame intervals."""

    def __init__(self, window):
        self._t = deque(maxlen=window + 1)

    def tick(self, now):
        self._t.append(now)

    def fps(self):
        if len(self._t) < 2:
            return 0.0
        dt = self._t[-1] - self._t[0]
        return (len(self._t) - 1) / dt if dt > 0 else 0.0


def draw_hand(img, sample, label):
    h, w = img.shape[:2]
    pts = [(int(x * w), int(y * h)) for x, y, _ in sample.landmarks]
    for a, b in HAND_CONNECTIONS:
        cv2.line(img, pts[a], pts[b], config.BONE_COLOR_BGR, config.BONE_THICKNESS_PX)
    for p in pts:
        cv2.circle(img, p, config.LANDMARK_RADIUS_PX, config.LANDMARK_COLOR_BGR, -1)
    wx, wy = pts[WRIST]
    cv2.putText(
        img, label,
        (wx + config.LABEL_OFFSET_PX[0], wy + config.LABEL_OFFSET_PX[1]),
        cv2.FONT_HERSHEY_SIMPLEX, config.TEXT_SCALE,
        config.LABEL_COLOR_BGR, config.TEXT_THICKNESS,
    )


def main():
    cam = CameraCapture()
    tracker = HandTracker(swap_handedness=config.SWAP_HANDEDNESS)  # runtime copy only
    cam_fps = FpsMeter(config.FPS_AVG_WINDOW)
    det_fps = FpsMeter(config.FPS_AVG_WINDOW)
    last_id = 0
    last_results = 0
    last_console = time.perf_counter()
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

                n = tracker.results_count
                if n != last_results:
                    last_results = n
                    det_fps.tick(now)

                if config.DEBUG_WINDOW:
                    img = frame.copy()
                    visible = 0
                    for label in ("Left", "Right"):
                        s = tracker.get_latest(label)
                        if s is not None and ts_ms - s.timestamp_ms <= config.HAND_STALE_MS:
                            draw_hand(img, s, label)
                            visible += 1
                    lines = [
                        f"cam FPS: {cam_fps.fps():.1f}  det FPS: {det_fps.fps():.1f}",
                        f"hands: {visible}  {status_text(tracker)}",
                    ]
                    for i, t in enumerate(lines):
                        cv2.putText(img, t, (10, 22 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX,
                                    config.TEXT_SCALE, config.TEXT_COLOR_BGR,
                                    config.TEXT_THICKNESS)
                    cv2.imshow(config.WINDOW_TITLE, img)
                elif now - last_console >= config.CONSOLE_FPS_INTERVAL_S:
                    last_console = now
                    print(f"cam FPS {cam_fps.fps():.1f} | det FPS {det_fps.fps():.1f}")
            else:
                time.sleep(config.MAIN_IDLE_SLEEP_S)

            if config.DEBUG_WINDOW:
                key = cv2.waitKey(1) & 0xFF
                if key in config.QUIT_KEYS:
                    break
                handle_toggle_key(key, cam, tracker)  # s = mirror, h = manual swap
    except KeyboardInterrupt:
        pass
    finally:
        tracker.close()
        cam.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
