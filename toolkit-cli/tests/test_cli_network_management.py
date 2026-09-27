"""Typed CLI coverage for the evidence-bounded physical network commands."""

import json
import subprocess
import sys
import unittest

from tests.test_cgate import peer


class NetworkManagementCLITests(unittest.TestCase):
    def cli(self, host, port, *arguments, status=0):
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "cbus_toolkit",
                "cgate",
                "--host",
                host,
                "--port",
                str(port),
                "network",
                *map(str, arguments),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(process.returncode, status, process.stderr + process.stdout)
        return json.loads(process.stdout if process.stdout else process.stderr)

    def test_learn_cli_emits_exact_native_high_grade_and_honest_receipt(self):
        with peer([[b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
            result = self.cli(
                host, port, "learn", "//TEST/254", 56, "cancel", 1,
            )
        self.assertEqual(sent, [b"[1] NET LEARN //TEST/254 56 $80 1\r\n"])
        self.assertEqual(result["operation"], "net-learn")
        self.assertEqual(result["target"]["grade_value"], 128)
        self.assertTrue(result["interface_delivery_confirmed"])
        self.assertFalse(result["device_action_verified"])
        self.assertFalse(result["physical_state_readback"])
        self.assertFalse(result["persistence_verified"])
        self.assertFalse(result["automatic_replay"])

    def test_locate_cli_covers_every_selector_and_exact_wire_command(self):
        cases = (
            (("unit", 1, "ON"), b"NETWORK LOCATE //TEST/254/208 UNIT 1 ON", {"unit": 1}),
            (("app", 56, 2), b"NETWORK LOCATE //TEST/254/208 APP 56 2", {"application": 56}),
            (
                ("group", 56, 1, "OFF"),
                b"NETWORK LOCATE //TEST/254/208 GROUP 56 1 OFF",
                {"application": 56, "group": 1},
            ),
            (
                ("serial", 1, "12345.67", 255),
                b"NETWORK LOCATE //TEST/254/208 SERIAL 1 12345.67 255",
                {"manufacturer": 1, "serial": "12345.67"},
            ),
        )
        for arguments, command, target in cases:
            with self.subTest(selector=arguments[0]), peer(
                [[b"[1] 200 OK.\r\n"]]
            ) as ((host, port), sent):
                result = self.cli(
                    host, port, "locate", "//TEST/254/208", *arguments,
                )
            self.assertEqual(sent, [b"[1] " + command + b"\r\n"])
            self.assertEqual(result["selector"], arguments[0])
            self.assertEqual(result["target"], target)
            self.assertEqual(result["carrier_application"], 208)
            self.assertTrue(result["cgate_accepted"])
            self.assertTrue(result["interface_delivery_confirmed"])
            self.assertFalse(result["device_action_verified"])

    def test_invalid_typed_inputs_fail_in_argument_parsing_before_connect(self):
        cases = (
            ("learn", "//TEST/254", 56, 3, 1),
            ("locate", "//TEST/254/56", "unit", 1, "ON"),
            ("locate", "//TEST/254/208", "group", 56, 255, "ON"),
            ("locate", "//TEST/254/208", "serial", 1, "1048576.0", "ON"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
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
                        "network",
                        *map(str, arguments),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(process.returncode, 2, process.stderr)
                self.assertIn("error:", process.stderr)
                self.assertNotIn("Unable to establish", process.stderr)

    def test_rejection_and_lost_reply_never_emit_a_success_receipt_or_replay(self):
        replies = (
            ([b"[1] 408 Network closed\r\n"], "C-Gate error"),
            ([], "outcome may be unknown"),
        )
        for response, message in replies:
            with self.subTest(response=response), peer([response]) as (
                (host, port), sent,
            ):
                result = self.cli(
                    host,
                    port,
                    "locate",
                    "//TEST/254/208",
                    "unit",
                    1,
                    "ON",
                    status=1,
                )
            self.assertIn(message, result["error"])
            self.assertNotIn("cgate_accepted", result)
            self.assertEqual(
                sent,
                [b"[1] NETWORK LOCATE //TEST/254/208 UNIT 1 ON\r\n"],
            )


if __name__ == "__main__":
    unittest.main()
