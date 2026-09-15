import os
import unittest
import uuid

from cbus_toolkit.native import NativeDatabase, NativeProjects


class CaptureClient:
    def __init__(self):
        self.commands = []

    def command(self, command):
        self.commands.append(command)
        return command


class NativeGrammarTests(unittest.TestCase):
    def setUp(self):
        self.client = CaptureClient()

    def test_parameter_values_are_remainder_not_shell_quoted(self):
        db = NativeDatabase(self.client)
        db.set("//TEST/254/56/1/TagName", 'Living room "north"')
        self.assertEqual(self.client.commands, ['DBSETSAFE //TEST/254/56/1/TagName Living room "north"'])

    def test_rejects_command_injection_before_any_io(self):
        db = NativeDatabase(self.client)
        for value in ("text\r\nSHUTDOWN", "bad\x00value"):
            with self.assertRaises(ValueError):
                db.set("//TEST/254/TagName", value)
        with self.assertRaises(ValueError):
            db.get("//TEST/254\nNOOP")
        self.assertEqual(self.client.commands, [])

    def test_address_and_project_name_validation(self):
        projects = NativeProjects(self.client)
        for name in ("NINECHARS", "../../x", "name two", ""):
            with self.assertRaises(ValueError):
                projects.operation("new", name)
        with self.assertRaises(ValueError):
            projects.operation("copy", "TEST")
        db = NativeDatabase(self.client)
        for address in (-1, 256, True, "1"):
            with self.assertRaises(ValueError):
                db.add("//TEST", "network", address, "Local")
        self.assertEqual(self.client.commands, [])

    def test_database_network_rename_uses_selected_project_and_decimal_addresses(self):
        db = NativeDatabase(self.client)
        db.rename_network("//TEST/254", 253)
        self.assertEqual(self.client.commands, ["PROJECT USE TEST", "DBRENAMENETSAFE 254 253"])
        self.client.commands.clear()
        for source, target in (("254", 253), ("//TEST/256", 253), ("//TEST/254", 256), ("//TEST/254", 254), ("//TEST/254\nNOOP", 253)):
            with self.assertRaises(ValueError):
                db.rename_network(source, target)
        self.assertEqual(self.client.commands, [])

    def test_native_confirmation_stops_dependent_writes_and_backup_workflows(self):
        from cbus_toolkit.cgate import CGateResponse
        class Confirmation(CaptureClient):
            def command(self, command):
                self.commands.append(command)
                return CGateResponse(("600 Confirmation required",), "600 Confirmation required", 600)
        client = Confirmation()
        with self.assertRaisesRegex(RuntimeError, "did not complete"):
            NativeDatabase(client).create_network("TEST", 254, "Offline", "Cni", "127.0.0.1:1")
        self.assertEqual(client.commands, ["PROJECT USE TEST"])
        client.commands.clear()
        with self.assertRaisesRegex(RuntimeError, "did not complete"):
            NativeProjects(client).operation("copy", "TEST", "BACKUP")
        self.assertEqual(client.commands, ["PROJECT COPY TEST BACKUP"])
        with self.assertRaisesRegex(RuntimeError, "did not complete"):
            NativeDatabase(client).set("//TEST/254/TagName", "Example")


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "set CBUS_CGATE_TEST_HOST for disposable real-server acceptance")
class NativeOracleTests(unittest.TestCase):
    def test_database_network_rename_and_reload_do_not_claim_runtime_rename(self):
        from cbus_toolkit.cgate import CGateClient, CGateError
        name = "N" + uuid.uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", name)
            saved = False
            try:
                db.create_network(name, 254, "Offline", "Cni", "127.0.0.1:29999")
                self.assertEqual(db.rename_network(f"//{name}/254", 253).code, 200)
                self.assertTrue(db.get(f"//{name}/253/Address").final.endswith("=253"))
                self.assertTrue(db.get(f"//{name}/253/NetworkNumber").final.endswith("=253"))
                self.assertIn("InterfaceState=closed", client.command(f"GET //{name}/254 InterfaceState").final)
                with self.assertRaises(CGateError):
                    client.command(f"GET //{name}/253 state")
                projects.operation("save", name)
                saved = True
                projects.operation("close", name)
                projects.operation("load", name)
                self.assertIn("InterfaceState=closed", client.command(f"GET //{name}/253 InterfaceState").final)
            finally:
                projects.operation("close", name)
                if saved:
                    projects.operation("delete", name)

    def test_named_level_creation_and_copy_save_and_reload(self):
        from cbus_toolkit.cgate import CGateClient, CGateError
        project = "L" + uuid.uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            saved = False
            try:
                network, group = f"//{project}/254", f"//{project}/254/56/1"
                db.create_network(project, 254, "Offline", "Cni", "127.0.0.1:29999")
                db.add(network, "application", 56, "Lighting")
                db.add(network + "/56", "group", 1, "Hall")
                db.add(group, "level", 123, "Evening")
                db.copy(group + "/123", group, 124, "Reading")
                db.add(network, "application", 202, "Trigger")
                db.add(network + "/202", "netvar", 1, "Scene")
                level = db.add(network + "/202/1", "level", 42, "Dinner")
                level_oid = "!" + level.final.split("=", 1)[1]
                copied = db.copy(level_oid, network + "/202/1", 43, "Breakfast")
                copied_oid = "!" + copied.final.split("=", 1)[1]
                self.assertTrue(db.get(level_oid + "/Value").final.endswith("=42"))
                self.assertTrue(db.get(copied_oid + "/Value").final.endswith("=43"))
                self.assertTrue(db.get(group + "/123/Value").final.endswith("=123"))
                self.assertTrue(db.get(group + "/124/Value").final.endswith("=124"))
                self.assertIn("Breakfast", db.get(copied_oid + "/TagName").final)
                with self.assertRaises(CGateError):
                    db.add(group, "level", 123, "Duplicate")
                self.assertIn("Evening", db.get(group + "/123/TagName").final)
                projects.operation("save", project)
                saved = True
                projects.operation("close", project)
                projects.operation("load", project)
                self.assertIn("Reading", db.get(group + "/124/TagName").final)
                self.assertTrue(db.get(group + "/124/Value").final.endswith("=124"))
            finally:
                projects.operation("close", project)
                if saved:
                    projects.operation("delete", project)

    def test_create_units_initializes_large_memory_and_rolls_back_failures(self):
        from cbus_toolkit.cgate import CGateClient, CGateError
        from cbus_toolkit.programming import Programmer
        name = "J" + uuid.uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", name)
            saved = False
            try:
                network = f"//{name}/254"
                db.create_network(name, 254, "Local", "Cni", "127.0.0.1:1")
                for address, kind, firmware, catalog, minimum in (
                        (20, "KEY4", "1.2.67", None, 30),
                        (21, "KEYGL5", "5.5.00", "5055EDL", 800),
                        (22, "DMXDO12", "1.0.00", "5500DMX", 60),
                        (23, "DIMAR3", "1.0.00", "L5103D5UA*", 390)):
                    with self.subTest(kind=kind):
                        result = db.create_unit(network, address, "Fixture " + kind, kind, firmware, catalog_number=catalog)
                        self.assertGreaterEqual(result["parameter_count"], minimum)
                        with Programmer(client).load(network, f"/db{network}/p/{address}") as session:
                            self.assertEqual(int(session.values("UnitAddress")["UnitAddress"], 16), address)
                            self.assertEqual(session.values("Project")["Project"].strip(), name)
                with self.assertRaises(RuntimeError):
                    db.create_unit(network, 24, "Invalid fixture", "NO_SUCH_UNIT", "1.0")
                with self.assertRaises(CGateError):
                    db.get(network + "/p/24")
                # A duplicate ADD must never delete or alter an existing unit.
                with self.assertRaises(CGateError):
                    db.create_unit(network, 20, "Duplicate", "KEY4", "1.2.67")
                self.assertIn("Fixture KEY4", str(db.get(network + "/p/20/TagName")))
                projects.operation("save", name)
                saved = True
                projects.operation("close", name)
                projects.operation("load", name)
                with Programmer(client).load(network, f"/db{network}/p/21") as session:
                    self.assertGreaterEqual(len(session.values()), 800)
            finally:
                projects.operation("close", name)
                if saved:
                    projects.operation("delete", name)

    def test_native_sqlite_project_lifecycle(self):
        from cbus_toolkit.cgate import CGateClient
        name = "T" + uuid.uuid4().hex[:7].upper()
        copy = "T" + uuid.uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as c:
            p, db = NativeProjects(c), NativeDatabase(c)
            created = []
            saved = set()
            try:
                p.operation("new", name)
                created.append(name)
                p.operation("use", name)
                db.create_network(name, 254, "Local", "Cni", "127.0.0.1:29999")
                db.add(f"//{name}/254", "application", 56, "Lighting")
                db.add(f"//{name}/254/56", "group", 1, "Lounge")
                db.set(f"//{name}/254/56/1/TagName", "Living room")
                self.assertIn("Living room", str(db.get(f"//{name}/254/56/1/TagName")))
                db.copy(f"//{name}/254/56/1", f"//{name}/254/56", 2, "Hall")
                self.assertIn("Hall", str(db.get(f"//{name}/254/56/2/TagName")))
                db.delete(f"//{name}/254/56/2")
                p.operation("save", name)
                saved.add(name)
                p.operation("close", name)
                p.operation("load", name)
                self.assertIn("Living room", str(db.get(f"//{name}/254/56/1/TagName")))
                p.operation("copy", name, copy)
                created.append(copy)
                saved.add(copy)
                p.operation("load", copy)
                self.assertIn("Living room", str(db.get(f"//{copy}/254/56/1/TagName")))
            finally:
                for project in created:
                    try:
                        p.operation("close", project)
                    finally:
                        if project in saved:
                            p.operation("delete", project)


if __name__ == "__main__":
    unittest.main()
