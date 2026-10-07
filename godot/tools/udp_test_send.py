"""Send manual test packets to Godot (Phase 3) without a webcam.

Follows python/PROTOCOL.md. Stdlib only; independent of python/ (no debounce here,
so the Godot cooldown can be tested directly).

Examples:
  python udp_test_send.py fire                      # one fire cast
  python udp_test_send.py fire --count 2 --interval 0.2   # 2nd must be REJECTED (cooldown 1 s)
  python udp_test_send.py water --count 5 --interval 1 --hb   # heartbeats keep the link up
  python udp_test_send.py hb --count 10 --interval 0.5        # heartbeats only
  python udp_test_send.py fire --dup --junk         # also send duplicates + invalid packets
  python udp_test_send.py steer 1 --duration 1      # turn right at full speed for 1 s (30 Hz), then one 0
  python udp_test_send.py steer -0.5 --duration 2 --hz 30   # turn left at half speed
  python udp_test_send.py steer 0.8 --junk          # also send invalid steer packets first
"""
import argparse
import json
import math
import secrets
import socket
import time

SKILLS = ("fire", "water", "lightning", "earth")


def main():
    p = argparse.ArgumentParser(description="Send protocol-v1 test packets to Godot.")
    p.add_argument("skill", choices=SKILLS + ("hb", "steer"),
                   help="skill to cast, 'hb' for heartbeats only, or 'steer' (needs a value)")
    p.add_argument("value", nargs="?", type=float,
                   help="steer only: -1..1 (negative = left, positive = right)")
    p.add_argument("--duration", type=float, default=1.0, help="steer only: seconds to keep sending (default 1)")
    p.add_argument("--hz", type=float, default=30.0, help="steer only: packets per second (default 30)")
    p.add_argument("--count", type=int, default=1, help="number of packets (default 1)")
    p.add_argument("--interval", type=float, default=0.5, help="seconds between packets (default 0.5)")
    p.add_argument("--conf", type=float, default=0.9)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=4242)
    p.add_argument("--hb", action="store_true", help="also send a heartbeat before each cast")
    p.add_argument("--dup", action="store_true", help="send every packet twice (Godot must drop the copy)")
    p.add_argument("--junk", action="store_true",
                   help="first send invalid packets (bad JSON, wrong v, unknown type/skill, bad seq)")
    args = p.parse_args()
    if args.skill == "steer":
        if args.value is None or not math.isfinite(args.value):
            p.error("steer needs a finite value, e.g. 'steer 1' or 'steer -0.5'")
        if args.hz <= 0 or args.duration < 0:
            p.error("--hz must be > 0 and --duration >= 0")
    elif args.value is not None:
        p.error("a value is only allowed with 'steer'")

    sid = secrets.token_hex(4)
    seq = 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (args.host, args.port)

    def send_raw(data, note):
        sock.sendto(data, dest)
        if note is not None:  # None = quiet (steer stream: only first/last are printed)
            print(f"-> {note:<10} {data.decode('utf-8', 'replace')}  unix={time.time():.3f}")

    def send(body, note):
        nonlocal seq
        seq += 1
        msg = {"v": 1, "type": body.pop("type"), "sid": sid, "seq": seq, **body}
        data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
        send_raw(data, note)
        if args.dup:
            send_raw(data, "dup" if note is not None else None)

    try:
        print(f"target {args.host}:{args.port} sid={sid}")
        if args.junk:
            send_raw(b"{not json", "junk")
            send_raw(b"[1,2,3]", "junk")
            send_raw(json.dumps({"v": 2, "type": "hb", "sid": sid, "seq": 1}).encode(), "junk")
            send_raw(json.dumps({"v": 1, "type": "zap", "sid": sid, "seq": 1}).encode(), "junk")
            send_raw(json.dumps({"v": 1, "type": "cast", "sid": sid, "seq": 1,
                                 "skill": "ice", "conf": 1}).encode(), "junk")
            send_raw(json.dumps({"v": 1, "type": "hb", "sid": "", "seq": 1.5}).encode(), "junk")
            if args.skill == "steer":
                send_raw(json.dumps({"v": 1, "type": "steer", "sid": sid, "seq": 1, "value": "left"}).encode(), "junk")
                send_raw(b'{"v":1,"type":"steer","sid":"%s","seq":1,"value":NaN}' % sid.encode(), "junk")
                send_raw(json.dumps({"v": 1, "type": "steer", "sid": sid, "seq": 1}).encode(), "junk")
        if args.skill == "steer":
            # ~hz packets for `duration` seconds, then exactly one 0 (like python/main.py).
            n = max(1, round(args.duration * args.hz))
            t0 = time.monotonic()
            for i in range(n):
                target = t0 + i / args.hz
                delay = target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                send({"type": "steer", "value": round(args.value, 3)}, "steer" if i in (0, n - 1) else None)
            delay = t0 + n / args.hz - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            send({"type": "steer", "value": 0}, "steer")
            print(f"sent {n} steer packets of {args.value:+.3f} over {time.monotonic() - t0:.2f} s, then 0")
            return
        for i in range(args.count):
            if i:
                time.sleep(args.interval)
            if args.skill == "hb":
                send({"type": "hb"}, "hb")
                continue
            if args.hb:
                send({"type": "hb"}, "hb")
            send({"type": "cast", "skill": args.skill, "conf": args.conf}, "cast")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
