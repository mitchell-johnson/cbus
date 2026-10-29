"""Typed CLI workflows for Toolkit command families missing before #162.

Every command sends Toolkit's own recovered command text and classifies replies
exactly as far as `research/toolkit-client/inventory.json` records them.
Not-yet-recorded replies fail closed and never replay a command.
"""

import json
import subprocess
import sys
import unittest

from tests.test_cgate import peer


class ToolkitSurfaceCLITests(unittest.TestCase):
    def cli(self, host, port, *arguments, status=0):
        process = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "cgate",
             "--host", host, "--port", str(port), *map(str, arguments)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(process.returncode, status, process.stderr + process.stdout)
        return json.loads(process.stdout if process.stdout else process.stderr)

    def cli_failure(self, host, port, *arguments):
        process = subprocess.run(
            [sys.executable, "-m", "cbus_toolkit", "cgate",
             "--host", host, "--port", str(port), *map(str, arguments)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(process.returncode, 1, process.stderr + process.stdout)
        return json.loads(process.stderr)

    # -- apiver -----------------------------------------------------------------

    def test_apiver_records_protocol_version_recovered_check(self):
        with peer([[b"[1] 138 x=1.4.8.0\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "apiver")
        self.assertEqual(sent, [b"[1] apiver\r\n"])
        self.assertEqual(result["operation"], "apiver")
        self.assertEqual(result["protocol_reply"], "x=1.4.8.0")
        self.assertTrue(result["accepted"])
        self.assertFalse(result["device_effects_verified"])

    def test_apiver_refuses_the_recovered_400yntax_error_class(self):
        with peer([[b"[1] 400 Syntax Error.\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "apiver")
        self.assertEqual(sent, [b"[1] apiver\r\n"])
        self.assertTrue(failure["sent"])
        self.assertFalse(failure["accepted"])
        self.assertFalse(failure["automatic_replay"])

    def test_apiver_non_138_reply_fails_closed_as_unmodeled(self):
        with peer([[b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "apiver")
        self.assertEqual(sent, [b"[1] apiver\r\n"])
        self.assertFalse(failure["accepted"])
        self.assertIn("unmodeled", json.dumps(failure))
        self.assertFalse(failure["automatic_replay"])

    # -- network flush / delete -------------------------------------------------

    def test_network_flush_sends_native_text_and_requires_recovered_reply(self):
        with peer([[b"[1] 200 ok\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "network", "flush", "//TEST/254")
        self.assertEqual(sent, [b"[1] NET FLUSH //TEST/254\r\n"])
        self.assertEqual(result["operation"], "net-flush")
        self.assertTrue(result["cgate_accepted"])
        self.assertFalse(result["device_effects_verified"])
        self.assertFalse(result["automatic_replay"])

    def test_network_flush_refuses_sync_in_progress_and_unmodeled(self):
        cases = (
            ([b"[1] 459 flush failed, sync in progress\r\n"], "recorded"),
            ([b"[1] 200 OK.\r\n"], "unmodeled"),
        )
        for reply, classification in cases:
            with self.subTest(reply=reply), peer([reply]) as ((host, port), sent):
                failure = self.cli_failure(host, port, "network", "flush", "//TEST/254")
            self.assertEqual(sent, [b"[1] NET FLUSH //TEST/254\r\n"])
            self.assertFalse(failure["cgate_accepted"])
            self.assertEqual(failure["reply_classification"], classification)
            self.assertTrue(failure["sent"])
            self.assertFalse(failure["automatic_replay"])

    def test_flush_statusless_fragment_fails_without_claiming_success(self):
        with peer([[b"[1] flush failed, sync in progress\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "network", "flush", "//TEST/254")
        self.assertEqual(sent, [b"[1] NET FLUSH //TEST/254\r\n"])
        self.assertFalse(failure["cgate_accepted"])
        # The transport drops the row before the recorded fragment could be
        # matched, so the receipt names the row statusless instead.
        self.assertEqual(failure["reply_classification"], "statusless_row")
        self.assertTrue(failure["sent"])
        self.assertFalse(failure["automatic_replay"])

    def test_network_delete_sends_native_text_and_records_one_exact_send(self):
        with peer([[b"[1] 200 ok\r\n"]]) as ((host, port), sent):
            result = self.cli(host, port, "network", "delete", "//TEST/254")
        self.assertEqual(sent, [b"[1] NET DELETE //TEST/254\r\n"])
        self.assertEqual(result["operation"], "net-delete")
        self.assertTrue(result["cgate_accepted"])
        self.assertFalse(result["device_effects_verified"])
        self.assertFalse(result["persistence_verified"])
        self.assertFalse(result["automatic_replay"])
        self.assertFalse(result["project_save_verified"])

    def test_network_delete_unmodeled_reply_fails_closed_without_replay(self):
        with peer([[b"[1] 200 OK.\r\n"]]) as ((host, port), sent):
            failure = self.cli_failure(host, port, "network", "delete", "//TEST/254")
        self.assertEqual(sent, [b"[1] NET DELETE //TEST/254\r\n"])
        self.assertIn("unmodeled", json.dumps(failure))
        self.assertFalse(failure["automatic_replay"])
        self.assertTrue(failure["sent"])


if __name__ == "__main__":
    unittest.main()
