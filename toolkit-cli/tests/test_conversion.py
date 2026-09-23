import os
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.conversion import ConversionError, NativeConversions


class RecordingClient:
    def __init__(self, allowed=True):
        self.commands = []
        self.allowed = allowed

    def command(self, command):
        self.commands.append(command)
        code = 301 if command.startswith("CONVERTUNIT CHECK") and not self.allowed else 200
        line = f"{code} " + ("yes" if code == 200 else "no")
        return CGateResponse((line,), line, code)


class ConversionTests(unittest.TestCase):
    def test_check_selects_project_and_uses_native_mode(self):
        client = RecordingClient()
        result = NativeConversions(client).check_catalog("//TEST/254/p/20", "DIMDU4", "L5504D2U")
        self.assertTrue(result["allowed"])
        self.assertFalse(result["removes_source"])
        self.assertEqual(client.commands, ["PROJECT USE TEST", "CONVERTUNIT CHECK 1 //TEST/254/p/20 DIMDU4 L5504D2U"])
        result = NativeConversions(client).check_move("//TEST/254/p/20", "//TEST/254/p/21")
        self.assertTrue(result["removes_source"])
        self.assertEqual(client.commands[-1], "CONVERTUNIT CHECK 2 //TEST/254/p/20 //TEST/254/p/21")

    def test_rejected_conversion_does_not_mutate_or_create_backup(self):
        client = RecordingClient(allowed=False)
        converter = NativeConversions(client)
        self.assertFalse(converter.check_catalog("//TEST/254/p/20", "KEY2", "5032N")["allowed"])
        with self.assertRaises(ConversionError):
            converter.convert_catalog("//TEST/254/p/20", "KEY2", "5032N", backup_project="BACKUP")
        self.assertFalse(any("CONVERTUNIT CONVERT" in command or "PROJECT SAVE" in command for command in client.commands))

    def test_invalid_paths_targets_and_backups_fail_before_io(self):
        client = RecordingClient()
        converter = NativeConversions(client)
        for path in ("254/p/20", "//TEST/*/p/20", "//TEST/254/p/256", "//TEST/254/p/20\nNOOP", None):
            with self.subTest(path=path), self.assertRaises(ValueError):
                converter.check_catalog(path, "DIMDU4", "L5504D2U")
        for target in ("//OTHER/254/p/20", "//TEST/254/p/20"):
            with self.assertRaises(ValueError):
                converter.check_move("//TEST/254/p/20", target)
        with self.assertRaises(ValueError):
            converter.convert_catalog("//TEST/254/p/20", "DIMDU4", "L5504D2U", backup_project="TEST")
        with self.assertRaises(ValueError):
            converter.check_catalog("//TEST/254/p/20", "DIMDU4", "L5504D2U\r\nSHUTDOWN")
        self.assertEqual(client.commands, [])


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "set CBUS_CGATE_TEST_HOST for native conversion acceptance")
class NativeConversionTests(unittest.TestCase):
    def setUp(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        self.client = CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023")), timeout=20).connect()
        self.addCleanup(self.client.close)
        self.project = "V" + uuid4().hex[:7].upper()
        self.projects = NativeProjects(self.client)
        self.projects.operation("new", self.project)
        self.saved = False
        self.backups = []
        self.addCleanup(self.cleanup_projects)
        self.db = NativeDatabase(self.client)
        self.network = f"//{self.project}/254"
        self.path = self.network + "/p/20"
        self.db.create_network(self.project, 254, "Offline", "Cni", "127.0.0.1:29999")
        self.db.create_unit(self.network, 20, "Old dimmer", "DIMDN4", "2.7.00", catalog_number="L5504D2A")
        self.converter = NativeConversions(self.client)
        from cbus_toolkit.programming import Programmer
        self.programmer = Programmer(self.client)
        with self.programmer.load(self.network, "/db" + self.path) as session:
            session.set("GroupAddress", "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16")
            session.save_to_source()

    def cleanup_projects(self):
        self.projects.operation("close", self.project)
        if self.saved:
            self.projects.operation("delete", self.project)
        for name in self.backups:
            self.projects.operation("close", name)
            self.projects.operation("delete", name)

    def test_catalog_conversion_backup_parameter_retention_and_persistence(self):
        backup = "B" + uuid4().hex[:7].upper()
        result = self.converter.convert_catalog(self.path, "DIMDU4", "L5504D2U", backup_project=backup)
        self.saved = True
        self.backups.append(backup)
        self.assertTrue(result["converted"])
        self.assertFalse(result["source_removed"])
        self.assertTrue(result["parameter_address_matches_database"])
        self.assertEqual(result["after"]["unit_type"], "DIMDU4")
        self.assertEqual(result["before"]["parameters"]["GroupAddress"], result["after"]["parameters"]["GroupAddress"])
        self.projects.operation("load", backup)
        before = self.converter._snapshot(f"//{backup}/254/p/20")
        self.assertEqual(before["unit_type"], "DIMDN4")
        self.assertEqual(before["parameters"], result["before"]["parameters"])
        self.projects.operation("save", self.project)
        self.projects.operation("close", self.project)
        self.projects.operation("load", self.project)
        self.assertEqual(self.converter._snapshot(self.path), result["after"])

    def test_move_preserves_destination_metadata_removes_source_and_exposes_address_mismatch(self):
        from cbus_toolkit.cgate import CGateError
        destination = self.network + "/p/21"
        self.db.create_unit(self.network, 21, "Replacement", "DIMDU4", "2.7.00", catalog_number="L5504D2U")
        self.db.set(destination + "/SerialNumber", "01234567.0001")
        result = self.converter.move(self.path, destination)
        self.assertTrue(result["source_removed"])
        self.assertFalse(result["parameter_address_matches_database"])
        self.assertEqual(result["after"]["parameters"]["UnitAddress"], "0x14")
        self.assertEqual(result["after"]["parameters"]["GroupAddress"], result["before"]["parameters"]["GroupAddress"])
        self.assertIn("Replacement", self.db.get(destination + "/TagName").final)
        self.assertIn("01234567.0001", self.db.get(destination + "/SerialNumber").final)
        with self.assertRaises(CGateError):
            self.db.get(self.path)
        self.assertEqual(self.client.command("NOOP").code, 200)

    def test_unsupported_conversion_and_unchanged_identity_have_no_mutation(self):
        before = self.converter._snapshot(self.path)
        # Native CHECK and CONVERT disagree for an unchanged DIMDN4 identity:
        # CHECK returns yes, but CONVERT returns 301 no. Do not trust CHECK alone.
        for kind, catalog, allowed in (("KEY4", "5034N", False), ("DIMDN4", "L5504D2A", True)):
            with self.subTest(kind=kind):
                self.assertEqual(self.converter.check_catalog(self.path, kind, catalog)["allowed"], allowed)
                with self.assertRaises(ConversionError):
                    self.converter.convert_catalog(self.path, kind, catalog)
                self.assertEqual(self.converter._snapshot(self.path), before)


if __name__ == "__main__":
    unittest.main()
