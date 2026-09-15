"""eDLT CLI offline/native preview agreement and database persistence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


class EdltCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_offline_profile_guard_requires_exact_firmware(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wrong.json"
            path.write_text(json.dumps({"format": "cbus-cli-parameters-v1", "unit_type": "KEYGL5",
                "catalog_number": "5055EDL", "firmware": "5.4.00", "parameters": {}}))
            result = self.cli("edlt", "lighting-plan", path, "--page", 1, "--position", 1,
                              "--group", 42, "--mode", "off-on", status=1)
            self.assertIn("identity differs", result["error"])

    @unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"),
                         "Set native C-Gate and unit specifications for eDLT CLI acceptance")
    def test_offline_and_native_plans_match_save_reload_and_rejected_edit_preserves_source(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = "EC" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        args = ("cgate", "--host", host, "--port", port, "--timeout", "20", "unit",
                "--lock-address", network, "--source", "/db" + network + "/p/20")
        options = ("--page", 1, "--position", 1, "--group", 42, "--mode", "off-on", "--label-text", "Lamp", "--status-type", "percent")
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            try:
                database.create_network(project, 254, "eDLT_CLI", "Cni", "127.0.0.1:29999")
                database.create_unit(network, 20, "eDLT", "KEYGL5", "5.5.00", catalog_number="5055EDL")
                projects.operation("save", project)
                original = self.cli(*args, "show")
                snapshot = Path(folder) / "edlt.json"
                self.cli(*args, "export", snapshot)
                plan = self.cli("edlt", "lighting-plan", snapshot, *options)
                preview = self.cli(*args, "--dry-run", "edlt-lighting", *options)
                self.assertFalse(preview["saved"])
                self.assertFalse(preview["physical_device_verified"])
                self.assertTrue(preview["verified"])
                self.assertEqual(preview["changes"], plan["changes"])
                self.assertEqual(preview["record_hex"], plan["record_hex"])
                self.assertEqual(self.cli(*args, "show"), original)
                result = self.cli(*args, "edlt-lighting", *options)
                self.assertTrue(result["saved"])
                self.assertEqual(result["parameters"], preview["parameters"])
                projects.operation("save", project)
                projects.operation("close", project)
                projects.operation("load", project)
                self.assertEqual(self.cli(*args, "show"), result["parameters"])
                error = self.cli(*args, "edlt-lighting", "--page", 1, "--position", 1,
                                 "--group", 43, "--mode", "dimmer", status=1)
                self.assertIn("restore_level", error["error"])
                self.assertEqual(self.cli(*args, "show"), result["parameters"])
                error = self.cli(*args, "--destination", network + "/p/20", "edlt-lighting", *options, status=1)
                self.assertIn("database destinations only", error["error"])
                labels = ("--page", 1, "--position", 1, "--group", 42, "--mode", "off-on",
                          "--label-text", "Māori Lounge", "--status-text", "Māori Lounge")
                label_snapshot = Path(folder) / "before-labels.json"
                self.cli(*args, "export", label_snapshot)
                label_plan = self.cli("edlt", "lighting-plan", label_snapshot, *labels)
                labelled = self.cli(*args, "edlt-lighting", *labels)
                self.assertEqual(labelled["changes"], label_plan["changes"])
                self.assertEqual(labelled["static_allocation"]["index"], labelled["status_allocation"]["index"])
                self.assertFalse(labelled["static_allocation"]["reused"])
                self.assertTrue(labelled["status_allocation"]["reused"])
                text_parameter = "StaticTextString" + str(labelled["static_allocation"]["index"])
                encoded = bytes(int(value, 0) for value in labelled["parameters"][text_parameter].split())
                self.assertEqual(encoded, "Māori Lounge".encode() + bytes(64 - len("Māori Lounge".encode())))
                projects.operation("save", project)
                projects.operation("close", project)
                projects.operation("load", project)
                self.assertEqual(self.cli(*args, "show"), labelled["parameters"])
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)


if __name__ == "__main__":
    unittest.main()
