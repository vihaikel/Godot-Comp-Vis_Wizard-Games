"""Threaded webcam capture that keeps only the newest frame (OpenCV)."""
import sys
import threading
import time

import cv2

import config


class CameraCapture:
    def __init__(self):
        self._cap = None
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._frame = None
        self._frame_id = 0
        self._frame_mirrored = bool(config.MIRROR)
        self._mirror = bool(config.MIRROR)  # runtime value, read per frame

    @property
    def mirror(self):
        """Runtime horizontal flip. Thread-safe; takes effect on the next frame read.
        Use tracker.set_mirror(cam, tracker, value) so the tracker stays in sync."""
        with self._lock:
            return self._mirror

    @mirror.setter
    def mirror(self, value):
        with self._lock:
            self._mirror = bool(value)

    def start(self):
        if self._thread is not None:
            return
        if config.CAMERA_BACKEND == "dshow" and sys.platform == "win32":
            cap = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(config.CAMERA_INDEX)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(
                f"Cannot open camera (index={config.CAMERA_INDEX}, "
                f"backend='{config.CAMERA_BACKEND}'). Try changing CAMERA_INDEX "
                "(0, 1, 2...) or CAMERA_BACKEND ('dshow' <-> 'default') in "
                "config.py, and make sure no other app is using the webcam."
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, config.TARGET_FPS)
        self._cap = cap
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="CameraCaptureThread", daemon=True
        )
        self._thread.start()

    def _run(self):
        while not self._stop_event.is_set():
            ok, frame = self._cap.read()
            if not ok or frame is None:
                time.sleep(config.CAPTURE_RETRY_SLEEP_S)
                continue
            with self._lock:
                mirrored = self._mirror  # sampled once per frame
            if mirrored:
                frame = cv2.flip(frame, 1)
            with self._lock:
                self._frame = frame  # replace, never mutate -> safe to share
                self._frame_mirrored = mirrored  # tag: how THIS frame was produced
                self._frame_id += 1

    def read_latest(self):
        """Return (frame_bgr or None, frame_id). frame_id increases per new frame."""
        with self._lock:
            return self._frame, self._frame_id

    def read_latest_tagged(self):
        """Return (frame_bgr or None, frame_id, mirrored): `mirrored` is the flip state
        the frame was actually produced with (may lag a just-toggled `mirror`).
        Pass it to HandTracker.submit(..., mirrored=...)."""
        with self._lock:
            return self._frame, self._frame_id, self._frame_mirrored

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=config.CAPTURE_JOIN_TIMEOUT_S)
            if self._thread.is_alive():
                # cap.read() is still blocking; releasing now could crash the driver.
                # The thread is a daemon and exits with the process.
                print("[capture] warning: camera thread did not stop in time; "
                      "skipping release")
                return
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
