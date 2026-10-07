"""Phase 3: UDP sender, Python -> Godot. Wire format: see PROTOCOL.md.

One datagram = one UTF-8 JSON object. Python only debounces per skill;
the AUTHORITATIVE cooldown lives in Godot (player.gd). Types: cast, hb, steer.
"""
import json
import logging
import math
import secrets
import socket
import time

import config

log = logging.getLogger(__name__)

VALID_SKILLS = frozenset({"fire", "water", "lightning", "earth"})


class UdpSender:
    def __init__(self, host=None, port=None):
        self.host = host if host is not None else getattr(config, "UDP_HOST", "127.0.0.1")
        self.port = int(port if port is not None else getattr(config, "UDP_PORT", 4242))
        self.version = getattr(config, "PROTOCOL_VERSION", 1)
        self.debounce_s = getattr(config, "SEND_DEBOUNCE_MS", 100) / 1000.0
        self.heartbeat_interval_s = getattr(config, "HEARTBEAT_INTERVAL_S", 0.5)

        self.sid = secrets.token_hex(4)  # 8 hex chars, new per process/session
        self._seq = 0  # one counter shared by every packet type
        self._last_cast_s = {}  # skill -> monotonic time of the last SENT cast
        self._last_hb_s = None
        self._error_logged = False
        # steer (see send_steer)
        hz = float(getattr(config, "STEER_SEND_HZ", 30))
        self.steer_min_interval_s = 1.0 / hz if hz > 0 else 0.0
        self.steer_eps = float(getattr(config, "STEER_SEND_EPS", 0.02))
        self.steer_keepalive_s = float(getattr(config, "STEER_KEEPALIVE_S", 0.1))
        self._steer_last_value = None  # last SENT steer value (None = never sent)
        self._steer_last_s = None  # monotonic time of the last SENT steer packet

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # UDP sendto practically never blocks; non-blocking guarantees it never
        # stalls the camera loop (a full buffer raises BlockingIOError instead).
        self._sock.setblocking(False)

    # ------------------------------------------------------------------ API
    def send_cast(self, skill, conf, now_s=None):
        """Send a cast packet. Returns False if debounced (or the send failed).

        Raises ValueError for an unknown skill or a non-finite conf.
        """
        if skill not in VALID_SKILLS:
            raise ValueError(f"unknown skill {skill!r}; expected one of {sorted(VALID_SKILLS)}")
        conf = float(conf)
        if not math.isfinite(conf):
            raise ValueError(f"conf must be finite, got {conf!r}")
        now = time.monotonic() if now_s is None else now_s
        last = self._last_cast_s.get(skill)
        if last is not None and now - last < self.debounce_s:
            return False
        self._last_cast_s[skill] = now
        conf = round(min(1.0, max(0.0, conf)), 3)
        return self._send({"type": "cast", "skill": skill, "conf": conf})

    def maybe_heartbeat(self, now_s=None):
        """Send a heartbeat if HEARTBEAT_INTERVAL_S has passed. Returns True if sent."""
        now = time.monotonic() if now_s is None else now_s
        if self._last_hb_s is not None and now - self._last_hb_s < self.heartbeat_interval_s:
            return False
        self._last_hb_s = now
        return self._send({"type": "hb"})

    def send_steer(self, value, now_s=None):
        """Send a steer packet if due. Returns True if a packet was sent.

        value is clamped to [-1, 1] and rounded to 3 decimals; ValueError if not finite.
        All steer packets (zero included) are limited to STEER_SEND_HZ per second.
        Compared with the last SENT steer value:
        - value == 0: sent exactly once when coming back from a non-zero value, then
          nothing while it stays 0. If that call is rate-limited the zero stays
          pending and goes out on the next call that is allowed. Never sent if no
          non-zero value was ever sent.
        - value != 0: sent when it differs from the last sent value by more than
          STEER_SEND_EPS (or the last sent value was 0 / nothing), otherwise as a
          keep-alive once STEER_KEEPALIVE_S has passed since the last steer packet.
        Callers just pass the current value on every update.
        """
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"steer value must be finite, got {value!r}")
        value = round(min(1.0, max(-1.0, value)), 3)
        if value == 0.0:
            value = 0.0  # normalise -0.0
        last_v, last_s = self._steer_last_value, self._steer_last_s
        if value == 0.0 and not last_v:  # never sent, or 0 already sent
            return False
        now = time.monotonic() if now_s is None else now_s
        if last_s is not None and now - last_s < self.steer_min_interval_s:
            return False
        if value != 0.0:
            changed = not last_v or abs(value - last_v) > self.steer_eps
            keepalive = last_s is None or now - last_s >= self.steer_keepalive_s
            if not (changed or keepalive):
                return False
        self._steer_last_value = value
        self._steer_last_s = now
        return self._send({"type": "steer", "value": value})

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------- internal
    def _send(self, body):
        if self._sock is None:
            raise RuntimeError("UdpSender is closed")
        self._seq += 1
        msg = {"v": self.version, "type": body["type"], "sid": self.sid, "seq": self._seq}
        msg.update(body)
        data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
        try:
            self._sock.sendto(data, (self.host, self.port))
            return True
        except OSError as e:
            # e.g. BlockingIOError (buffer full) or, on Windows, ConnectionResetError
            # after an ICMP "port unreachable" when Godot is not listening yet.
            if not self._error_logged:
                log.warning("UDP send to %s:%s failed (%s); further errors are silenced",
                            self.host, self.port, e)
                self._error_logged = True
            return False
