"""Command-line contract for the live KEYGL5 WidgetGroups cache reader."""
import json
import subprocess
import sys
import unittest

from test_cgate import peer


ADDRESS = "//TEST/254/p/5"
NETWORK = "//TEST/254"
VALUES = [(index * 53) % 256 for index in range(44)]
PAYLOAD = ",".join(map(str, VALUES))


class EdltWidgetGroupsCliTests(unittest.TestCase):
    def run_cli(self, host, port, *, address=ADDRESS):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "cbus_toolkit",
                "cgate",
                "--host",
                host,
                "--port",
                str(port),
                "edlt-widget-groups",
                address,
            ],
            text=True,
            capture_output=True,
        )

    def test_cli_synchronizes_then_prints_honest_structured_json(self):
        responses = [
            [b"[1] 200 OK\r\n"],
            [f"[2] 300 {ADDRESS}: WidgetGroups={PAYLOAD}\r\n".encode()],
        ]
        with peer(responses) as ((host, port), sent):
            process = self.run_cli(host, port)

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        result = json.loads(process.stdout)
        self.assertTrue(result["complete"])
        self.assertEqual(result["widget_groups"], VALUES)
        self.assertEqual(result["native_decimal_csv"], PAYLOAD)
        self.assertTrue(result["opaque"])
        self.assertEqual(result["source"], "physical-synchronized-cache")
        self.assertTrue(result["widget_groups_device_readback"])
        self.assertEqual(result["network_sync"]["scope"], "entire-network")
        self.assertTrue(result["network_sync"]["read_only"])
        self.assertFalse(result["dynamic_label_cache_readback"])
        self.assertFalse(result["rendering_verified"])
        self.assertFalse(result["persistence_verified"])
        self.assertFalse(result["network_snapshot_atomic"])
        self.assertEqual(
            sent,
            [
                f"[1] NET SYNC {NETWORK}\r\n".encode(),
                f"[2] GET {ADDRESS} WidgetGroups\r\n".encode(),
            ],
        )

    def test_cli_emits_no_success_document_after_sync_or_envelope_failure(self):
        cases = (
            ([[b"[1] 408 Physical synchronization failed\r\n"]], 1),
            (
                [
                    [b"[1] 200 OK\r\n"],
                    [f"[2] 300 //OTHER/254/p/5: WidgetGroups={PAYLOAD}\r\n".encode()],
                ],
                2,
            ),
            (
                [
                    [b"[1] 200 OK\r\n"],
                    [f"[2] 300 {ADDRESS}: WidgetGroups=".encode()
                     + ",".join(map(str, VALUES[:-1])).encode() + b"\r\n"],
                ],
                2,
            ),
            (
                [
                    [b"[1] 200 OK\r\n"],
                    [f"[2] 300 {ADDRESS}: WidgetGroups=".encode()
                     + ",".join(map(str, [*VALUES[:-1], 256])).encode() + b"\r\n"],
                ],
                2,
            ),
            ([[b"[1] 200 OK\r\n"], [b"[2] 404 Parameter not found\r\n"]], 2),
        )
        for responses, command_count in cases:
            with self.subTest(responses=responses), peer(responses) as ((host, port), sent):
                process = self.run_cli(host, port)
            self.assertEqual(process.returncode, 1)
            self.assertEqual(process.stdout, "")
            self.assertIn("error", json.loads(process.stderr))
            self.assertEqual(len(sent), command_count)

    def test_cli_rejects_non_unit_path_before_connecting(self):
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbus_toolkit",
                "cgate",
                "--host",
                "127.0.0.1",
                "--port",
                "1",
                "edlt-widget-groups",
                "//TEST/254/56/5",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")
        self.assertIn("invalid unit_path value", process.stderr)
        self.assertNotIn("Unable to establish", process.stderr)


if __name__ == "__main__":
    unittest.main()
