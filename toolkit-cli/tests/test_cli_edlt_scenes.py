"""Complete eDLT scene-table CLI with reference-preserving subsequent edits."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"),
                     "Set native C-Gate and unit specifications for scene-table CLI acceptance")
class EdltSceneTableCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_full_table_offline_preview_read_save_and_reference_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = "ET" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        args = ("cgate", "--host", host, "--port", port, "unit", "--lock-address", network,
                "--source", "/db" + network + "/p/20")
        scenes = [{"application": "primary", "trigger_group": 42, "action_selector": 77, "name_text": "Evening",
                   "items": [{"group": 9, "level": 127, "ramp_seconds": 20}]},
                  {"application": "primary", "trigger_group": 42, "action_selector": 88, "name_text": "Evening"}]
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            folder = Path(folder)
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            projects.operation("save", project)
            try:
                database.create_network(project, 254, "Table_CLI", "Cni", "127.0.0.1:29999")
                database.create_unit(network, 20, "eDLT", "KEYGL5", "5.5.00", catalog_number="5055EDL")
                original = self.cli(*args, "show")
                snapshot, definitions = folder / "initial.json", folder / "scenes.json"
                self.cli(*args, "export", snapshot)
                self.assertEqual(self.cli("edlt", "scenes-inspect", snapshot), [])
                definitions.write_text(json.dumps(scenes))
                plan = self.cli("edlt", "scenes-plan", snapshot, "--scenes", definitions)
                preview = self.cli(*args, "--dry-run", "edlt-scenes", "--scenes", definitions)
                self.assertEqual(preview["changes"], plan["changes"])
                self.assertFalse(preview["saved"])
                self.assertEqual(self.cli(*args, "show"), original)
                result = self.cli(*args, "edlt-scenes", "--scenes", definitions)
                self.assertTrue(result["saved"])
                self.assertFalse(result["physical_device_verified"])
                self.assertEqual(result["parameters"], preview["parameters"])
                self.assertEqual(result["pointers"], [0, 8, 255, 255, 255, 255, 255, 255])
                self.assertEqual(result["bucket_hex"], "02012a4d3f14097f02002a583f" + "ff" * 219)
                self.assertEqual([row["reused"] for row in result["name_allocations"]], [False, True])
                for operation in ("save", "close", "load"):
                    projects.operation(operation, project)
                self.assertEqual(self.cli(*args, "show"), result["parameters"])
                configured = folder / "configured.json"
                self.cli(*args, "export", configured)
                inspected = self.cli("edlt", "scenes-inspect", configured)
                self.assertEqual(len(inspected), 2)
                self.assertEqual(inspected[0]["items"][0]["ramp_seconds"], 20)
                roundtrip = folder / "roundtrip.json"
                roundtrip.write_text(json.dumps(inspected))
                again = self.cli("edlt", "scenes-plan", configured, "--scenes", roundtrip)
                self.assertFalse(again["changes"])
                self.cli(*args, "edlt-scene", "--page", 1, "--position", 1, "--scene", 2, "--label-type", "scene")
                with_widget = self.cli(*args, "show")
                definitions.write_text(json.dumps(scenes[::-1]))
                error = self.cli(*args, "edlt-scenes", "--scenes", definitions, status=1)
                self.assertIn("Referenced scene slot 2", error["error"])
                self.assertEqual(self.cli(*args, "show"), with_widget)
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)


if __name__ == "__main__":
    unittest.main()
