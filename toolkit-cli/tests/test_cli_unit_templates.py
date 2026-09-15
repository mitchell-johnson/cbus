"""Toolkit XML template CLI and preserved destination identity."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4


class UnitTemplateCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    @unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"),
                         "Set native C-Gate and specifications for classic template CLI profiles")
    def test_explicit_classic_profiles_and_mismatched_type_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = "TP" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        base = ("cgate", "--host", host, "--port", port, "unit", "--lock-address", network)
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            folder = Path(folder)
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            projects.operation("save", project)
            try:
                database.create_network(project, 254, "Profiles", "Cni", "127.0.0.1:29999")
                for number in (1, 2):
                    name, catalog = "KEY" + str(number), "503" + str(number) + "N"
                    database.create_unit(network, number, name, name, "1.2.67", catalog_number=catalog)
                    args = (*base, "--source", "/db" + network + "/p/" + str(number))
                    snapshot, template = folder / (name + ".json"), folder / (name + ".xml")
                    result = self.cli(*args, "template-export", template, "--profile", name)
                    self.assertEqual((result["unit_type"], result["tested_catalog_number"]), (name, catalog))
                    self.cli(*args, "export", snapshot)
                    offline = folder / (name + "-offline.xml")
                    self.cli("unit-templates", "export", snapshot, offline, "--profile", name)
                    self.assertEqual(offline.read_bytes(), template.read_bytes())
                    applied = self.cli(*args, "template-import", template, "--profile", name)
                    self.assertTrue(applied["saved"])
                    self.assertFalse(applied["changed_parameters"])
                target = (*base, "--source", "/db" + network + "/p/2")
                original = self.cli(*target, "show")
                error = self.cli(*target, "template-import", folder / "KEY1.xml", "--profile", "KEY2", status=1)
                self.assertIn("type", error["error"].lower())
                self.assertEqual(self.cli(*target, "show"), original)
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)

    @unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"),
                         "Set native C-Gate and specifications for template CLI acceptance")
    def test_template_xml_export_offline_agreement_import_preview_save_reload_and_crc_rejection(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer
        project = "TC" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        base = ("cgate", "--host", host, "--port", port, "unit", "--lock-address", network)
        source = (*base, "--source", "/db" + network + "/p/20")
        target = (*base, "--source", "/db" + network + "/p/21")
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            folder = Path(folder)
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            projects.operation("save", project)
            try:
                database.create_network(project, 254, "Template_CLI", "Cni", "127.0.0.1:29999")
                for address in (20, 21):
                    database.create_unit(network, address, "Key" + str(address), "KEY4", "1.2.67", catalog_number="5034N")
                with Programmer(client).load(network, "/db" + network + "/p/20") as session:
                    session.set("UnitName", "SCENE_A")
                    session.set("GroupAddress", "12 24 25 27 255 255 255 255")
                    session.set("LightLevelStore1", "64 127 200 255")
                    session.save_to_source()
                original = self.cli(*target, "show")
                native_xml, offline_xml, snapshot = folder / "native.xml", folder / "offline.xml", folder / "source.json"
                exported = self.cli(*source, "template-export", native_xml, "--description", "Key template")
                self.assertEqual(exported["unit_type"], "KEY4")
                self.cli(*source, "export", snapshot)
                self.cli("unit-templates", "export", snapshot, offline_xml, "--description", "Key template")
                self.assertEqual(offline_xml.read_bytes(), native_xml.read_bytes())
                self.assertIn(b"\r\n", native_xml.read_bytes())
                inspected = self.cli("unit-templates", "inspect", native_xml)
                self.assertEqual(inspected["crc"], exported["crc"])
                self.assertEqual(inspected["attributes"]["GroupAddress"], "12 24 25 27 255 255 255 255")
                before_file = native_xml.read_bytes()
                self.cli(*source, "template-export", native_xml, status=1)
                self.assertEqual(native_xml.read_bytes(), before_file)
                preview = self.cli(*target, "--dry-run", "template-import", native_xml)
                self.assertFalse(preview["saved"])
                self.assertTrue(preview["verified"])
                self.assertEqual(self.cli(*target, "show"), original)
                saved = self.cli(*target, "template-import", native_xml)
                self.assertTrue(saved["saved"])
                self.assertEqual(saved["parameters"], preview["parameters"])
                self.assertEqual(saved["parameters"]["UnitName"].rstrip(), "SCENE_A")
                for key in ("UnitAddress", "NetworkAddress", "Project", "PatchEnable", "LearnedFlag"):
                    self.assertEqual(saved["parameters"][key], original[key])
                for operation in ("save", "close", "load"):
                    projects.operation(operation, project)
                self.assertEqual(self.cli(*target, "show"), saved["parameters"])
                broken = folder / "corrupt.xml"
                broken.write_bytes(before_file.replace(b"SCENE_A", b"SCENE_B"))
                error = self.cli(*target, "template-import", broken, status=1)
                self.assertIn("CRC mismatch", error["error"])
                self.assertEqual(self.cli(*target, "show"), saved["parameters"])
                error = self.cli(*target, "--destination", network + "/p/21", "template-import", native_xml, status=1)
                self.assertIn("database destinations only", error["error"])
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)


if __name__ == "__main__":
    unittest.main()
