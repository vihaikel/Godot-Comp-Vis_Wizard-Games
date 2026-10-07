"""Real loopback tests for sender.UdpSender (stdlib unittest only).

Run from python/:  python3 -m unittest discover -s tests_net -v
"""
import json
import os
import re
import socket
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from sender import VALID_SKILLS, UdpSender  # noqa: E402

DEBOUNCE_S = getattr(config, "SEND_DEBOUNCE_MS", 100) / 1000.0
HB_S = getattr(config, "HEARTBEAT_INTERVAL_S", 0.5)
VERSION = getattr(config, "PROTOCOL_VERSION", 1)
RECV_TIMEOUT_S = 1.0


class LoopbackTestCase(unittest.TestCase):
    def setUp(self):
        self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx.bind(("127.0.0.1", 0))  # ephemeral port
        self.rx.settimeout(RECV_TIMEOUT_S)
        self.port = self.rx.getsockname()[1]
        self.tx = UdpSender(host="127.0.0.1", port=self.port)

    def tearDown(self):
        self.tx.close()
        self.rx.close()

    def recv(self):
        data, _ = self.rx.recvfrom(65536)
        return data, json.loads(data.decode("utf-8"))

    def assert_nothing_pending(self):
        self.rx.settimeout(0.05)
        try:
            data, _ = self.rx.recvfrom(65536)
            self.fail(f"unexpected extra packet: {data!r}")
        except socket.timeout:
            pass
        finally:
            self.rx.settimeout(RECV_TIMEOUT_S)


class TestFormat(LoopbackTestCase):
    def test_cast_packet_matches_protocol(self):
        self.assertTrue(self.tx.send_cast("fire", 0.8712, now_s=10.0))
        raw, msg = self.recv()
        self.assertEqual(list(msg.keys()), ["v", "type", "sid", "seq", "skill", "conf"])
        self.assertEqual(msg["v"], VERSION)
        self.assertEqual(msg["type"], "cast")
        self.assertRegex(msg["sid"], r"^[0-9a-f]{8}$")
        self.assertIsInstance(msg["seq"], int)
        self.assertEqual(msg["skill"], "fire")
        self.assertAlmostEqual(msg["conf"], 0.871)
        self.assertNotIn(b" ", raw)  # compact separators
        self.assertTrue(raw.startswith(b'{"v":'))

    def test_heartbeat_packet_matches_protocol(self):
        self.assertTrue(self.tx.maybe_heartbeat(now_s=1.0))
        _, msg = self.recv()
        self.assertEqual(list(msg.keys()), ["v", "type", "sid", "seq"])
        self.assertEqual(msg["type"], "hb")
        self.assertEqual(msg["sid"], self.tx.sid)

    def test_conf_is_clamped(self):
        self.tx.send_cast("water", 1.7, now_s=0.0)
        self.tx.send_cast("earth", -0.2, now_s=0.0)
        self.assertEqual(self.recv()[1]["conf"], 1.0)
        self.assertEqual(self.recv()[1]["conf"], 0.0)

    def test_sid_is_random_per_sender(self):
        other = UdpSender(host="127.0.0.1", port=self.port)
        try:
            self.assertNotEqual(self.tx.sid, other.sid)
            self.assertTrue(re.fullmatch(r"[0-9a-f]{8}", other.sid))
        finally:
            other.close()


class TestSeq(LoopbackTestCase):
    def test_seq_monotonic_and_shared_with_heartbeat(self):
        t = 100.0
        self.tx.maybe_heartbeat(now_s=t)          # hb
        self.tx.send_cast("fire", 0.9, now_s=t)   # cast
        self.tx.send_cast("water", 0.9, now_s=t)  # cast
        self.tx.maybe_heartbeat(now_s=t + HB_S)   # hb
        self.tx.send_cast("fire", 0.9, now_s=t + 1.0)
        msgs = [self.recv()[1] for _ in range(5)]
        self.assertEqual([m["type"] for m in msgs], ["hb", "cast", "cast", "hb", "cast"])
        seqs = [m["seq"] for m in msgs]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), 5)
        self.assertEqual(seqs, list(range(seqs[0], seqs[0] + 5)))  # one shared counter
        self.assertEqual({m["sid"] for m in msgs}, {self.tx.sid})


class TestDebounce(LoopbackTestCase):
    def test_same_skill_debounced_within_window(self):
        t = 50.0
        self.assertTrue(self.tx.send_cast("fire", 0.9, now_s=t))
        self.assertFalse(self.tx.send_cast("fire", 0.9, now_s=t + DEBOUNCE_S * 0.5))
        self.assertFalse(self.tx.send_cast("fire", 0.9, now_s=t + DEBOUNCE_S - 0.001))
        self.assertTrue(self.tx.send_cast("fire", 0.9, now_s=t + DEBOUNCE_S))
        a, b = self.recv()[1], self.recv()[1]
        self.assertEqual(b["seq"], a["seq"] + 1)  # debounced casts consume no seq
        self.assert_nothing_pending()

    def test_other_skill_not_debounced(self):
        t = 50.0
        for skill in ("fire", "water", "lightning", "earth"):
            self.assertTrue(self.tx.send_cast(skill, 0.9, now_s=t))
        got = [self.recv()[1]["skill"] for _ in range(4)]
        self.assertEqual(got, ["fire", "water", "lightning", "earth"])
        self.assertFalse(self.tx.send_cast("water", 0.9, now_s=t + 0.01))
        self.assert_nothing_pending()

    def test_debounce_with_real_clock(self):
        self.assertTrue(self.tx.send_cast("lightning", 0.9))
        self.assertFalse(self.tx.send_cast("lightning", 0.9))
        time.sleep(DEBOUNCE_S + 0.02)
        self.assertTrue(self.tx.send_cast("lightning", 0.9))
        self.recv()
        self.recv()


class TestValidation(LoopbackTestCase):
    def test_unknown_skill_rejected(self):
        for bad in ("ice", "", "FIRE", None, "hb"):
            with self.assertRaises(ValueError):
                self.tx.send_cast(bad, 0.9, now_s=0.0)
        self.assert_nothing_pending()

    def test_non_finite_conf_rejected(self):
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.tx.send_cast("fire", bad, now_s=0.0)
        self.assert_nothing_pending()

    def test_valid_skill_set(self):
        self.assertEqual(VALID_SKILLS, {"fire", "water", "lightning", "earth"})


class TestHeartbeat(LoopbackTestCase):
    def test_heartbeat_only_after_interval(self):
        t = 200.0
        self.assertTrue(self.tx.maybe_heartbeat(now_s=t))  # first call sends
        self.assertFalse(self.tx.maybe_heartbeat(now_s=t))
        self.assertFalse(self.tx.maybe_heartbeat(now_s=t + HB_S * 0.9))
        self.assertTrue(self.tx.maybe_heartbeat(now_s=t + HB_S))
        self.assertFalse(self.tx.maybe_heartbeat(now_s=t + HB_S * 1.5))
        self.assertTrue(self.tx.maybe_heartbeat(now_s=t + HB_S * 2.0))
        types = [self.recv()[1]["type"] for _ in range(3)]
        self.assertEqual(types, ["hb", "hb", "hb"])
        self.assert_nothing_pending()

    def test_cast_does_not_reset_heartbeat_timer(self):
        t = 300.0
        self.tx.maybe_heartbeat(now_s=t)
        self.tx.send_cast("earth", 0.5, now_s=t + HB_S * 0.5)
        self.assertTrue(self.tx.maybe_heartbeat(now_s=t + HB_S))
        self.assertEqual([self.recv()[1]["type"] for _ in range(3)], ["hb", "cast", "hb"])


STEER_DT = 1.0 / getattr(config, "STEER_SEND_HZ", 30)
STEER_EPS = getattr(config, "STEER_SEND_EPS", 0.02)
STEER_KA = getattr(config, "STEER_KEEPALIVE_S", 0.1)


class TestSteer(LoopbackTestCase):
    def drain(self):
        out = []
        self.rx.settimeout(0.05)
        try:
            while True:
                out.append(json.loads(self.rx.recvfrom(65536)[0].decode("utf-8")))
        except socket.timeout:
            pass
        finally:
            self.rx.settimeout(RECV_TIMEOUT_S)
        return out

    def test_steer_packet_exact_format(self):
        self.assertTrue(self.tx.send_steer(-0.6234, now_s=10.0))
        raw, msg = self.recv()
        self.assertEqual(list(msg.keys()), ["v", "type", "sid", "seq", "value"])
        self.assertEqual(raw.decode("utf-8"),
                         '{"v":%d,"type":"steer","sid":"%s","seq":%d,"value":-0.623}'
                         % (VERSION, self.tx.sid, msg["seq"]))
        self.assertIsInstance(msg["value"], float)

    def test_seq_shared_with_cast_and_hb(self):
        t = 100.0
        self.tx.maybe_heartbeat(now_s=t)
        self.tx.send_steer(0.5, now_s=t)
        self.tx.send_cast("water", 0.9, now_s=t)
        self.tx.send_steer(0.8, now_s=t + 1.0)
        msgs = [self.recv()[1] for _ in range(4)]
        self.assertEqual([m["type"] for m in msgs], ["hb", "steer", "cast", "steer"])
        seqs = [m["seq"] for m in msgs]
        self.assertEqual(seqs, list(range(seqs[0], seqs[0] + 4)))

    def test_rate_limit_30hz(self):
        t0 = 500.0
        sent = 0
        for i in range(1000):  # 1 kHz for 1 s, value changes every call
            v = 0.3 if i % 2 else 0.6
            sent += self.tx.send_steer(v, now_s=t0 + i * 0.001)
        self.assertLessEqual(sent, getattr(config, "STEER_SEND_HZ", 30))
        self.assertGreaterEqual(sent, 25)
        self.assertEqual(len(self.drain()), sent)
        # boundary: exactly one interval later is allowed, just before is not
        tx = UdpSender(host="127.0.0.1", port=self.port)
        try:
            self.assertTrue(tx.send_steer(0.2, now_s=0.0))
            self.assertFalse(tx.send_steer(0.9, now_s=STEER_DT * 0.99))
            self.assertTrue(tx.send_steer(0.9, now_s=STEER_DT))
        finally:
            tx.close()
        self.drain()

    def test_eps_and_keepalive(self):
        t = 50.0
        self.assertTrue(self.tx.send_steer(0.5, now_s=t))
        # change <= EPS after the rate interval: not sent (no keep-alive due yet)
        self.assertFalse(self.tx.send_steer(0.5 + STEER_EPS * 0.5, now_s=t + 0.05))
        # change > EPS: sent
        self.assertTrue(self.tx.send_steer(0.5 + STEER_EPS * 1.5, now_s=t + 0.06))
        v = 0.5 + STEER_EPS * 1.5
        self.assertFalse(self.tx.send_steer(v, now_s=t + 0.06 + STEER_KA * 0.5))
        # unchanged non-zero value is re-sent as a keep-alive
        self.assertTrue(self.tx.send_steer(v, now_s=t + 0.06 + STEER_KA))
        self.assertTrue(self.tx.send_steer(v, now_s=t + 0.06 + 2 * STEER_KA))
        vals = [m["value"] for m in self.drain()]
        self.assertEqual(vals, [0.5, round(v, 3), round(v, 3), round(v, 3)])
        self.assertLess(STEER_KA, 0.3)  # must beat Godot's 0.3 s steer timeout

    def test_zero_sent_exactly_once(self):
        t = 10.0
        self.assertFalse(self.tx.send_steer(0.0, now_s=t))  # nothing to stop yet
        self.assertFalse(self.tx.send_steer(-0.0, now_s=t))
        self.assertTrue(self.tx.send_steer(0.5, now_s=t + 1.0))
        self.assertTrue(self.tx.send_steer(0.0, now_s=t + 1.1))
        for i in range(5):
            self.assertFalse(self.tx.send_steer(0.0, now_s=t + 1.2 + i))
        self.assertTrue(self.tx.send_steer(-0.4, now_s=t + 7.0))
        # zero within the rate interval is postponed, not lost
        self.assertFalse(self.tx.send_steer(0.0, now_s=t + 7.0 + STEER_DT * 0.5))
        self.assertTrue(self.tx.send_steer(0.0, now_s=t + 7.0 + STEER_DT))
        self.assertFalse(self.tx.send_steer(0.0, now_s=t + 8.0))
        msgs = self.drain()
        self.assertEqual([m["value"] for m in msgs], [0.5, 0.0, -0.4, 0.0])
        self.assertTrue(all(m["type"] == "steer" for m in msgs))

    def test_value_clamped_and_rounded(self):
        self.tx.send_steer(1.7, now_s=0.0)
        self.tx.send_steer(-3.0, now_s=1.0)
        self.tx.send_steer(0.12345, now_s=2.0)
        self.assertEqual([m["value"] for m in self.drain()], [1.0, -1.0, 0.123])

    def test_non_finite_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                self.tx.send_steer(bad, now_s=0.0)
        self.assert_nothing_pending()

    def test_steer_does_not_touch_cast_or_heartbeat_timers(self):
        t = 300.0
        self.tx.maybe_heartbeat(now_s=t)
        self.tx.send_cast("fire", 0.9, now_s=t)
        self.tx.send_steer(0.7, now_s=t + 0.01)
        self.assertFalse(self.tx.send_cast("fire", 0.9, now_s=t + DEBOUNCE_S * 0.5))
        self.assertTrue(self.tx.send_cast("fire", 0.9, now_s=t + DEBOUNCE_S))
        self.assertTrue(self.tx.maybe_heartbeat(now_s=t + HB_S))
        self.assertEqual([m["type"] for m in self.drain()], ["hb", "cast", "steer", "cast", "hb"])


class TestErrors(unittest.TestCase):
    def test_send_to_closed_port_does_not_raise(self):
        # Grab a free port, then close it so nothing listens there.
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        tx = UdpSender(host="127.0.0.1", port=port)
        try:
            with self.assertNoLogs("sender", level="ERROR"):
                for i in range(5):
                    tx.send_cast("fire", 0.9, now_s=float(i))  # must not raise
                    tx.maybe_heartbeat(now_s=float(i))
        finally:
            tx.close()

    def test_send_after_close_raises(self):
        tx = UdpSender(host="127.0.0.1", port=9)
        tx.close()
        tx.close()  # idempotent
        with self.assertRaises(RuntimeError):
            tx.maybe_heartbeat(now_s=0.0)


if __name__ == "__main__":
    unittest.main()
