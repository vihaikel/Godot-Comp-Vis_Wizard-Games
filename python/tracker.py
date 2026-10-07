"""HandTracker: wrapper around MediaPipe Hand Landmarker in LIVE_STREAM mode.

API source (verified):
https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python

Handedness: per the official Hand Landmarker docs, handedness is determined
assuming the input image is mirrored (front/selfie camera, flipped horizontally).
So with a mirrored frame the physical right hand is labelled 'Right'; with a raw
(non-mirrored) frame it is labelled 'Left'. The tracker corrects this
automatically: effective_swap = swap_handedness XOR (not mirror), where
swap_handedness is only a manual override on top.

Mirror toggle race: a frame submitted with the OLD mirror state can return from
MediaPipe after the toggle. submit() records the mirror state per timestamp
(ts -> mirrored) and the callback uses the state of THAT frame for the label,
then converts the coordinates into the CURRENT mirror space (x -> 1 - x,
world x -> -x) if they differ, so history never mixes the two spaces.
"""
import os
import threading
from collections import deque
from contextlib import ExitStack
import cv2
import mediapipe as mp

import config
from features import HandSample  # re-exported: `from tracker import HandSample` keeps working

# Aliases exactly as in the official docs (see URL above).
BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
HandLandmarkerResult = mp.tasks.vision.HandLandmarkerResult
VisionRunningMode = mp.tasks.vision.RunningMode

# Landmark indices (from the same docs page).
WRIST = 0
INDEX_FINGER_PIP = 6
INDEX_FINGER_TIP = 8
MIDDLE_FINGER_MCP = 9
MIDDLE_FINGER_PIP = 10
MIDDLE_FINGER_TIP = 12
RING_FINGER_TIP = 16
PINKY_TIP = 20

LABELS = ("Left", "Right")
_TS_MIRROR_MAX = 256  # safety cap on pending ts -> mirrored entries


def effective_swap(swap_handedness, mirrored):
    """True if MediaPipe's Left/Right label must be swapped.

    MediaPipe assumes a mirrored (selfie) image, so a raw frame needs a swap;
    the manual override swap_handedness flips that once more (XOR).
    """
    return bool(swap_handedness) != (not bool(mirrored))


def flip_label(label):
    return "Left" if label == "Right" else "Right" if label == "Left" else label


class HandTracker:
    def __init__(self, swap_handedness=None, mirror=None):
        self._lock = threading.Lock()
        self._swap = bool(
            config.SWAP_HANDEDNESS if swap_handedness is None else swap_handedness
        )
        # Mirror state of the frames being submitted (coordinate space of history).
        self._mirror = bool(config.MIRROR if mirror is None else mirror)
        self._ts_mirror = {}  # submitted ts -> mirrored (insertion order == ts order)
        self._history = {l: deque(maxlen=config.HISTORY_LEN) for l in LABELS}
        self._last_ts = -1
        self._results_count = 0
        self._last_result_ms = -1
        self._stack = ExitStack()
        self._landmarker = None

    def start(self):
        if self._landmarker is not None:
            return
        if not os.path.isfile(config.MODEL_PATH):
            raise FileNotFoundError(
                f"Model file not found: {config.MODEL_PATH}\n"
                "Run `python download_model.py` first."
            )
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=config.MODEL_PATH),
            running_mode=VisionRunningMode.LIVE_STREAM,
            num_hands=config.NUM_HANDS,
            min_hand_detection_confidence=config.MIN_HAND_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=config.MIN_HAND_PRESENCE_CONFIDENCE,
            min_tracking_confidence=config.MIN_TRACKING_CONFIDENCE,
            result_callback=self._on_result,
        )
        # The docs use `with HandLandmarker.create_from_options(options)`;
        # ExitStack gives the same context-manager lifecycle across start()/close().
        self._landmarker = self._stack.enter_context(
            HandLandmarker.create_from_options(options)
        )

    # Called by MediaPipe on its own thread:
    # fn(result: HandLandmarkerResult, output_image: mp.Image, timestamp_ms: int)
    def _on_result(self, result, output_image, timestamp_ms):
        ts = int(timestamp_ms)
        worlds = result.hand_world_landmarks or []
        raw = []  # (mediapipe label, score, landmarks, world)
        for i, lms in enumerate(result.hand_landmarks or []):
            cat = result.handedness[i][0]
            raw.append((
                cat.category_name,  # 'Left' / 'Right'
                cat.score,
                [(lm.x, lm.y, lm.z) for lm in lms],
                [(w.x, w.y, w.z) for w in worlds[i]] if i < len(worlds) else [],
            ))
        with self._lock:
            frame_mirrored = self._pop_frame_mirror(ts)
            swap = effective_swap(self._swap, frame_mirrored)  # state of THIS frame
            to_current = frame_mirrored != self._mirror  # stale pre-toggle frame
            best = {}  # label -> HandSample (highest score if a label repeats)
            for label, score, lms, world in raw:
                if swap:
                    label = flip_label(label)
                if label not in self._history:
                    continue
                if to_current:
                    lms = [(1.0 - x, y, z) for x, y, z in lms]
                    world = [(-x, y, z) for x, y, z in world]
                if label not in best or score > best[label].score:
                    best[label] = HandSample(
                        timestamp_ms=ts, landmarks=lms, score=score, world=world
                    )
            self._results_count += 1
            self._last_result_ms = ts
            for label, sample in best.items():
                self._history[label].append(sample)

    def _pop_frame_mirror(self, ts):
        """(lock held) Mirror state recorded for ts; older entries are dropped (MediaPipe
        returns results in timestamp order, so they were skipped frames)."""
        m = self._ts_mirror.pop(ts, None)
        while self._ts_mirror:
            k = next(iter(self._ts_mirror))
            if k >= ts:
                break
            del self._ts_mirror[k]
        return self._mirror if m is None else m

    def _register_frame(self, timestamp_ms, mirrored=None):
        """Allocate a strictly increasing ts and remember the frame's mirror state."""
        with self._lock:
            ts = max(int(timestamp_ms), self._last_ts + 1)  # strictly increasing
            self._last_ts = ts
            self._ts_mirror[ts] = self._mirror if mirrored is None else bool(mirrored)
            while len(self._ts_mirror) > _TS_MIRROR_MAX:
                del self._ts_mirror[next(iter(self._ts_mirror))]
        return ts

    def submit(self, frame_bgr, timestamp_ms, mirrored=None):
        """Non-blocking; frames are dropped by MediaPipe while the model is busy.

        mirrored: flip state the frame was produced with (CameraCapture.read_latest_tagged);
        None = assume the tracker's current `mirror`.
        """
        if self._landmarker is None:
            raise RuntimeError("HandTracker.start() must be called before submit().")
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts = self._register_frame(timestamp_ms, mirrored)  # before detect_async
        self._landmarker.detect_async(mp_image, ts)

    # --- runtime mirror / manual swap ---------------------------------------
    @property
    def mirror(self):
        with self._lock:
            return self._mirror

    @mirror.setter
    def mirror(self, value):
        with self._lock:
            self._mirror = bool(value)

    @property
    def swap_handedness(self):
        with self._lock:
            return self._swap

    @swap_handedness.setter
    def swap_handedness(self, value):
        with self._lock:
            self._swap = bool(value)

    def set_mirror(self, value):
        """Atomically set mirror and clear history (old samples have flipped x)."""
        with self._lock:
            self._mirror = bool(value)
            for h in self._history.values():
                h.clear()

    def set_swap(self, value):
        """Atomically set the manual override and clear history (old labelling)."""
        with self._lock:
            self._swap = bool(value)
            for h in self._history.values():
                h.clear()

    def get_history(self, label):
        with self._lock:
            return list(self._history[label])

    def get_latest(self, label):
        with self._lock:
            h = self._history[label]
            return h[-1] if h else None

    def clear_history(self):
        with self._lock:
            for h in self._history.values():
                h.clear()

    @property
    def results_count(self):
        """Number of callback results received (for detection-FPS display)."""
        with self._lock:
            return self._results_count

    @property
    def last_result_ms(self):
        """MediaPipe timestamp (ms, same clock as submit()) of the newest result; -1 if none."""
        with self._lock:
            return self._last_result_ms

    def snapshot(self):
        """Atomic (results_count, last_result_ms, {'Left': [..], 'Right': [..]}) copy."""
        with self._lock:
            return (
                self._results_count,
                self._last_result_ms,
                {l: list(h) for l, h in self._history.items()},
            )

    def close(self):
        self._stack.close()
        self._landmarker = None


# --- shared runtime-toggle helpers (main_debug / main_gestures / main) ---------
def set_mirror(cam, tracker, value, engine=None):
    """Mirror camera + tracker together, clear history, reset engine state."""
    if cam is not None:
        cam.mirror = value
    tracker.set_mirror(value)
    if engine is not None:
        engine.reset()


def set_swap(tracker, value, engine=None):
    """Manual Left/Right override on top of the automatic mirror correction."""
    tracker.set_swap(value)
    if engine is not None:
        engine.reset()


def handle_toggle_key(key, cam, tracker, engine=None):
    """'s' (MIRROR_KEY) toggles mirror, 'h' (SWAP_KEY) toggles manual swap.
    Returns True if the key was handled."""
    if key == config.MIRROR_KEY:
        set_mirror(cam, tracker, not tracker.mirror, engine)
        print(f"[keys] {status_text(tracker)}")
        return True
    if key == config.SWAP_KEY:
        set_swap(tracker, not tracker.swap_handedness, engine)
        print(f"[keys] {status_text(tracker)}")
        return True
    return False


def status_text(tracker):
    return (f"mirror: {'ON' if tracker.mirror else 'OFF'}  "
            f"swap: {'ON' if tracker.swap_handedness else 'OFF'}")
