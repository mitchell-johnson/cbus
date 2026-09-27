import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest

from cbus_toolkit.cni_discovery import (
    DISCOVERY_QUERY,
    decode_discovery_reply,
    discover_cni,
    scan_cni,
)


VECTORS = Path(__file__).parents[2] / "rust" / "testdata" / "vectors" / "cni_discovery.jsonl"
CNI2 = bytes.fromhex("cb81000020e8f5528101000101810b00022711811d000101800100028c26")
HIDDEN = bytes.fromhex("cb810000000000028101000102810b00022711811d000100800100020000")


class CniDiscoveryCodecTests(unittest.TestCase):
    def test_shared_rust_vectors_pin_python_codec(self):
        cases = [json.loads(line) for line in VECTORS.read_text().splitlines() if line]
        cases = [case for case in cases
                 if case["kind"] in {"query", "reply", "reply_error"}]
        self.assertEqual(len(cases), 8)
        for case in cases:
            with self.subTest(case=case["id"]):
                if case["kind"] == "query":
                    self.assertEqual(DISCOVERY_QUERY.hex(), case["expect_hex"])
                elif case["kind"] == "reply":
                    self.assertEqual(decode_discovery_reply(bytes.fromhex(case["wire_hex"])).as_dict(),
                                     case["expect"])
                else:
                    with self.assertRaisesRegex(ValueError, case["expect_error"]):
                        decode_discovery_reply(bytes.fromhex(case["wire_hex"]))

    def test_decoder_requires_bytes_and_preserves_unknown_values(self):
        with self.assertRaisesRegex(TypeError, "must be bytes"):
            decode_discovery_reply(bytearray(CNI2))
        unknown = decode_discovery_reply(bytes.fromhex(
            "cb8100000102030481010001fe810b0002ffff811d0001aa800100021234"))
        self.assertEqual(unknown.product, "unknown")
        self.assertEqual(unknown.unknown1, b"\x01\x02\x03\x04")
        self.assertEqual(unknown.service_port, 65535)
        self.assertEqual(unknown.status, 170)
        self.assertEqual(unknown.trailer, b"\x12\x34")


def responder(payloads):
    peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    peer.bind(("127.0.0.1", 0))
    peer.settimeout(2)
    address = peer.getsockname()
    errors = []

    def run():
        try:
            query, source = peer.recvfrom(64)
            if query != DISCOVERY_QUERY:
                raise AssertionError(query.hex())
            for payload in payloads:
                peer.sendto(payload, source)
        except BaseException as error:
            errors.append(error)
        finally:
            peer.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return address, thread, errors


class CniDiscoveryTransportTests(unittest.TestCase):
    def test_bounded_collection_deduplicates_and_retains_rejections(self):
        address, thread, errors = responder((CNI2, CNI2, HIDDEN, b"noise"))
        report = discover_cni(bind="127.0.0.1", listen_port=0,
                              destination=address[0], discovery_port=address[1],
                              timeout=0.2, max_datagrams=16)
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(report["collection_complete"])
        self.assertEqual(report["datagrams_received"], 4)
        self.assertEqual(report["duplicates_ignored"], 1)
        self.assertEqual(report["hidden_ignored"], 1)
        self.assertEqual(len(report["devices"]), 1)
        self.assertEqual(report["devices"][0]["endpoint"], "127.0.0.1:10001")
        self.assertEqual(report["devices"][0]["product"], "cni2")
        self.assertEqual(report["devices"][0]["unknown1_hex"], "20e8f552")
        self.assertNotIn("device_id_hex", report["devices"][0])
        self.assertEqual(len(report["malformed"]), 1)
        self.assertTrue(report["query_sent_once"])
        self.assertFalse(report["tcp_connection_opened"])
        self.assertFalse(report["absence_proven"])

    def test_hidden_policy_and_datagram_cap_are_explicit(self):
        address, thread, errors = responder((HIDDEN,))
        report = discover_cni(bind="127.0.0.1", listen_port=0,
                              destination=address[0], discovery_port=address[1],
                              timeout=1, max_datagrams=1, include_hidden=True)
        thread.join(2)
        self.assertEqual(errors, [])
        self.assertFalse(report["collection_complete"])
        self.assertEqual(report["collection_ended"], "datagram_limit")
        self.assertEqual(report["hidden_ignored"], 0)
        self.assertEqual(report["devices"][0]["product"], "hidden")
        self.assertFalse(report["devices"][0]["visible_by_default"])

    def test_large_malformed_replies_are_bounded_and_deduplicated(self):
        address, thread, errors = responder((b"x" * 4096, b"x" * 4096))
        report = discover_cni(bind="127.0.0.1", listen_port=0,
                              destination=address[0], discovery_port=address[1],
                              timeout=0.1)
        thread.join(2)
        self.assertEqual(errors, [])
        self.assertEqual(report["datagrams_received"], 2)
        self.assertEqual(report["duplicates_ignored"], 1)
        self.assertEqual(len(report["malformed"]), 1)
        self.assertEqual(report["malformed"][0]["raw_length"], 4096)
        self.assertTrue(report["malformed"][0]["raw_truncated"])
        self.assertEqual(report["malformed"][0]["raw_hex"], b"x".hex() * 64)

    def test_invalid_inputs_fail_before_socket_creation(self):
        def forbidden(*_args):
            raise AssertionError("socket must not be created")

        cases = (
            {"bind": "localhost"}, {"destination": "::1"}, {"listen_port": -1},
            {"discovery_port": 0}, {"timeout": 0}, {"timeout": float("nan")},
            {"max_datagrams": 0}, {"max_datagrams": 4097}, {"include_hidden": 1},
        )
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                discover_cni(socket_factory=forbidden, **options)

    def test_explicit_multi_adapter_routes_preserve_independent_observations(self):
        found, found_thread, found_errors = responder((CNI2,))
        report = scan_cni([
            f"127.0.0.1@{found[0]}",
            f"0.0.0.0@{found[0]}",
        ], listen_port=0, discovery_port=found[1], timeout=0.1)
        # The routes deliberately use different local binds. The one-shot
        # responder closes after the first query, so the second gets no reply.
        found_thread.join(2)
        self.assertEqual(found_errors, [])
        self.assertEqual(report["format"], "cbus-cni-multi-discovery-v1")
        self.assertEqual(report["probe_count"], 2)
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["probes"][0]["outcome"], "devices_observed")
        self.assertEqual(report["probes"][0]["observation"]["devices"][0]["product"], "cni2")
        self.assertEqual(report["probes"][1]["outcome"], "no_reply_by_deadline")
        self.assertEqual(report["probes"][1]["observation"]["devices"], [])
        self.assertFalse(report["absence_proven"])
        self.assertFalse(report["ownership_checked"])
        self.assertFalse(report["tcp_connection_opened"])

    def test_multi_probe_transport_failure_does_not_erase_later_probe(self):
        called = []

        def discover(**options):
            called.append(options["bind"])
            if options["bind"] == "127.0.0.2":
                raise OSError("local adapter unavailable")
            return {"collection_complete": True, "devices": [], "malformed": [],
                    "hidden_ignored": 0}

        report = scan_cni([
            "127.0.0.2@192.0.2.1", "127.0.0.1@192.0.2.2",
        ], discover=discover)
        self.assertEqual(called, ["127.0.0.2", "127.0.0.1"])
        self.assertFalse(report["scan_complete"])
        self.assertEqual(report["probes"][0]["outcome"], "transport_error")
        self.assertIsNone(report["probes"][0]["query_sent_once"])
        self.assertIsNone(report["probes"][0]["observation"])
        self.assertIn("local adapter unavailable", report["probes"][0]["error"])
        self.assertEqual(report["probes"][1]["outcome"], "no_reply_by_deadline")

    def test_multi_probe_distinguishes_cap_from_malformed_only(self):
        cap, cap_thread, cap_errors = responder((CNI2, CNI2))
        cap_report = scan_cni(["127.0.0.1@127.0.0.1"], listen_port=0,
                              discovery_port=cap[1], timeout=0.2, max_datagrams=1)
        cap_thread.join(2)
        self.assertEqual(cap_errors, [])
        self.assertFalse(cap_report["scan_complete"])
        self.assertEqual(cap_report["probes"][0]["outcome"], "datagram_limit")
        self.assertEqual(len(cap_report["probes"][0]["observation"]["devices"]), 1)

        bad, bad_thread, bad_errors = responder((b"noise",))
        bad_report = scan_cni(["127.0.0.1@127.0.0.1"], listen_port=0,
                              discovery_port=bad[1], timeout=0.1)
        bad_thread.join(2)
        self.assertEqual(bad_errors, [])
        self.assertTrue(bad_report["scan_complete"])
        self.assertEqual(bad_report["probes"][0]["outcome"], "no_valid_reply_by_deadline")
        self.assertEqual(len(bad_report["probes"][0]["observation"]["malformed"]), 1)

        hidden, hidden_thread, hidden_errors = responder((HIDDEN,))
        hidden_report = scan_cni(["127.0.0.1@127.0.0.1"], listen_port=0,
                                 discovery_port=hidden[1], timeout=0.1)
        hidden_thread.join(2)
        self.assertEqual(hidden_errors, [])
        self.assertTrue(hidden_report["scan_complete"])
        self.assertEqual(hidden_report["probes"][0]["outcome"], "hidden_replies_by_deadline")
        self.assertEqual(hidden_report["probes"][0]["observation"]["hidden_ignored"], 1)

        mixed, mixed_thread, mixed_errors = responder((HIDDEN, b"noise"))
        mixed_report = scan_cni(["127.0.0.1@127.0.0.1"], listen_port=0,
                                discovery_port=mixed[1], timeout=0.1)
        mixed_thread.join(2)
        self.assertEqual(mixed_errors, [])
        self.assertEqual(mixed_report["probes"][0]["outcome"], "filtered_replies_by_deadline")

        shown, shown_thread, shown_errors = responder((HIDDEN,))
        shown_report = scan_cni(["127.0.0.1@127.0.0.1"], listen_port=0,
                                discovery_port=shown[1], timeout=0.1,
                                include_hidden=True)
        shown_thread.join(2)
        self.assertEqual(shown_errors, [])
        self.assertEqual(shown_report["probes"][0]["outcome"], "devices_observed")

    def test_multi_probe_validates_every_route_before_first_socket(self):
        def forbidden(**_options):
            raise AssertionError("discovery must not start")

        cases = (
            [], ["127.0.0.1@127.0.0.1"] * 17,
            ["127.0.0.1@127.0.0.2", "127.0.0.1@host"],
            ["127.0.0.1@127.0.0.2", "127.0.0.1@127.0.0.2"],
            ["127.0.0.1@127.0.0.2", "127.0.0.1"],
        )
        for probes in cases:
            with self.subTest(probes=probes), self.assertRaises(ValueError):
                scan_cni(probes, discover=forbidden)
        for option in ({"timeout": float("inf")}, {"max_datagrams": 4097},
                       {"listen_port": -1}, {"discovery_port": 0},
                       {"include_hidden": 1}):
            with self.subTest(option=option), self.assertRaises(ValueError):
                scan_cni(["127.0.0.1@127.0.0.1"], discover=forbidden, **option)
        with self.assertRaisesRegex(ValueError, "scan window"):
            scan_cni(["127.0.0.1@127.0.0.1", "127.0.0.2@127.0.0.2"],
                     timeout=151, discover=forbidden)


class CniDiscoveryCliTests(unittest.TestCase):
    def test_cli_emits_machine_readable_endpoint_without_opening_tcp(self):
        address, thread, errors = responder((CNI2,))
        process = subprocess.run([
            sys.executable, "-m", "cbus_toolkit", "interface", "discover-cni",
            "--bind", "127.0.0.1", "--listen-port", "0",
            "--destination", address[0], "--discovery-port", str(address[1]),
            "--timeout", "0.2",
        ], text=True, capture_output=True)
        thread.join(2)
        self.assertEqual(errors, [])
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["format"], "cbus-cni-discovery-v1")
        self.assertEqual(report["devices"][0]["endpoint"], "127.0.0.1:10001")
        self.assertEqual(report["devices"][0]["unknown1_hex"], "20e8f552")
        self.assertTrue(report["read_only"])
        self.assertFalse(report["tcp_connection_opened"])

    def test_cli_rejects_invalid_bounds_as_json(self):
        process = subprocess.run([
            sys.executable, "-m", "cbus_toolkit", "interface", "discover-cni",
            "--timeout", "301",
        ], text=True, capture_output=True)
        self.assertEqual(process.returncode, 1)
        self.assertIn("CNI discovery timeout", json.loads(process.stderr)["error"])

    def test_cli_scans_explicit_routes_without_selecting_a_device(self):
        address, thread, errors = responder((CNI2,))
        process = subprocess.run([
            sys.executable, "-m", "cbus_toolkit", "interface", "scan-cni",
            "--probe", "127.0.0.1@127.0.0.1",
            "--listen-port", "0", "--discovery-port", str(address[1]),
            "--timeout", "0.1",
        ], text=True, capture_output=True)
        thread.join(2)
        self.assertEqual(errors, [])
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["probe_count"], 1)
        self.assertEqual(report["probes"][0]["outcome"], "devices_observed")
        self.assertEqual(report["probes"][0]["observation"]["devices"][0]["endpoint"],
                         "127.0.0.1:10001")
        self.assertFalse(report["ownership_checked"])


if __name__ == "__main__":
    unittest.main()
