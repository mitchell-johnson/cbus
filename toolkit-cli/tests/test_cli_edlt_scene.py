"""eDLT Scene CLI preview/save agreement and preserved existing scene records."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


class EdltSceneCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    @unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"),
                         "Set native C-Gate and unit specifications for eDLT scene CLI acceptance")
    def test_existing_scene_offline_preview_save_reload_and_invalid_reference(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer
        project = "ES" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        args = ("cgate", "--host", host, "--port", port, "--timeout", "20", "unit",
                "--lock-address", network, "--source", "/db" + network + "/p/20")
        options = ("--page", 1, "--position", 1, "--scene", 2, "--label-type", "scene", "--status-text", "Scene ready")
        # Output of the original Toolkit DLL SaveScenes: one local lighting
        # scene followed by a trigger-only scene. No editor builds this fixture.
        bucket = bytes.fromhex("02012a4d0114097f02002a5801") + b"\xff" * 219
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            try:
                database.create_network(project, 254, "Scene_CLI", "Cni", "127.0.0.1:29999")
                database.create_unit(network, 20, "eDLT", "KEYGL5", "5.5.00", catalog_number="5055EDL")
                with Programmer(client).load(network, "/db" + network + "/p/20") as session:
                    session.set("SceneBucket", " ".join(map(str, bucket)))
                    session.set("SceneCount", "2")
                    for scene in range(1, 9):
                        session.set(f"Scene{scene}StartAddress", str({1: 0, 2: 8}.get(scene, 255)))
                    session.set("StaticTextString1", " ".join(map(str, b"Evening".ljust(64, b"\0"))))
                    session.save_to_source()
                original = self.cli(*args, "show")
                snapshot = Path(folder) / "edlt.json"
                self.cli(*args, "export", snapshot)
                plan = self.cli("edlt", "scene-plan", snapshot, *options)
                preview = self.cli(*args, "--dry-run", "edlt-scene", *options)
                self.assertEqual(preview["changes"], plan["changes"])
                self.assertEqual(preview["scene_reference"]["action_selector"], 88)
                self.assertEqual(preview["scene_reference"]["item_count"], 0)
                self.assertFalse(preview["saved"])
                self.assertEqual(self.cli(*args, "show"), original)
                saved = self.cli(*args, "edlt-scene", *options)
                self.assertTrue(saved["saved"])
                self.assertFalse(saved["physical_device_verified"])
                self.assertEqual(saved["record_hex"], "063526250000011a1b0000003fff000000000000000000000000000000000000")
                self.assertEqual(saved["parameters"], preview["parameters"])
                for name in original:
                    if name.startswith("Scene") and name != "ScenesCheckSum":
                        self.assertEqual(saved["parameters"][name], original[name])
                for operation in ("save", "close", "load"):
                    projects.operation(operation, project)
                self.assertEqual(self.cli(*args, "show"), saved["parameters"])
                error = self.cli(*args, "edlt-scene", "--page", 1, "--position", 2, "--scene", 3, status=1)
                self.assertIn("not configured", error["error"])
                self.assertEqual(self.cli(*args, "show"), saved["parameters"])
                error = self.cli(*args, "--destination", network + "/p/20", "edlt-scene", *options, status=1)
                self.assertIn("database destinations only", error["error"])
                for mode, settings, macros in (
                        ("ramp", ("--scene", 1, "--ramp-seconds", 30), (28, 29)),
                        ("nudge", ("--scene", 1, "--offset", 42), (32, 33)),
                        ("cycle", ("--cycle-scene", 2, "--cycle-scene", 1, "--cycle-scene", 2,
                                   "--cycle-variant", "select"), (30, 31))):
                    with self.subTest(mode=mode):
                        before = Path(folder) / (mode + ".json")
                        self.cli(*args, "export", before)
                        settings = ("--page", 1, "--position", 1, "--mode", mode, *settings)
                        offline = self.cli("edlt", "scene-plan", before, *settings)
                        configured = self.cli(*args, "edlt-scene", *settings)
                        self.assertEqual(configured["changes"], offline["changes"])
                        record = bytes.fromhex(configured["record_hex"])
                        self.assertEqual(tuple(record[7:9]), macros)
                        if mode == "ramp":
                            self.assertEqual(record[9], 5)
                        elif mode == "nudge":
                            self.assertEqual(record[10], 42)
                        else:
                            self.assertEqual(record[13:22], bytes((1, 0, 1, 255, 255, 255, 255, 255, 255)))
                            self.assertEqual(record[1] & 128, 128)
                            self.assertEqual([ref["scene"] for ref in configured["cycle_references"]], [2, 1, 2])
                            self.assertIsNone(configured["scene_reference"])
                        for operation in ("save", "close", "load"):
                            projects.operation(operation, project)
                        self.assertEqual(self.cli(*args, "show"), configured["parameters"])
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)


if __name__ == "__main__":
    unittest.main()
