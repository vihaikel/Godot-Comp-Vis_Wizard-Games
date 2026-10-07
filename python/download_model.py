"""Download the MediaPipe Hand Landmarker model to models/hand_landmarker.task.

Model URL (from the official docs):
https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python
"""
import os
import sys
import urllib.request

import config


def main():
    dest = config.MODEL_PATH
    if os.path.isfile(dest):
        print(f"Model already exists, skipping: {dest}")
        return 0
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    last = {"pct": -1}

    def hook(blocks, block_size, total):
        if total > 0:
            pct = min(100, int(blocks * block_size * 100 / total))
            if pct != last["pct"] and pct % 10 == 0:
                last["pct"] = pct
                print(f"  {pct}%")

    print(f"Downloading {config.MODEL_URL}")
    try:
        urllib.request.urlretrieve(config.MODEL_URL, tmp, hook)
        os.replace(tmp, dest)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"Download failed: {e}", file=sys.stderr)
        return 1
    print(f"Saved to {dest} ({os.path.getsize(dest)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
