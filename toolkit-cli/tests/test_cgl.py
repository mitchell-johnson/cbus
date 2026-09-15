import copy
import json
import os
import unittest
import uuid

from cbus_toolkit.cgate import CGateClient, CGateResponse
from cbus_toolkit.cgl import NativeCGL, parse_document, summary
from cbus_toolkit.native import NativeDatabase, NativeProjects


DOCUMENT = {"cglVersion": "1.1", "localNetwork": 254, "networks": [
    {"address": 254, "name": "Local", "applications": [
        {"address": 56, "type": 56, "name": "Lighting", "groups": [
            {"address": 1, "name": "Lounge", "levels": [{"address": 255, "name": "On"}]}]}]}]}


class FakeClient:
    def __init__(self, response=None):
        self.commands = []
        self.response = response or CGateResponse(("200 OK.",), "200 OK.", 200)

    def command(self, command):
        self.commands.append(command)
        return self.response

    def command_document(self, command, document):
        self.commands.append((command, json.loads(document)))
        return self.response


class CGLTests(unittest.TestCase):
    def test_parse_counts_and_preserve_optional_metadata(self):
        document = copy.deepcopy(DOCUMENT)
        document["createdBy"] = "Test"
        self.assertEqual(parse_document(json.dumps(document)), document)
        self.assertEqual(summary(document), {"version": "1.1", "local_network": 254,
                                             "networks": 1, "applications": 1, "groups": 1, "levels": 1})

    def test_reject_bad_version_shape_and_duplicate_json_fields(self):
        for text in ('{}', '[]', '{"cglVersion":"1.1","cglVersion":"1.1"}',
                     json.dumps({**DOCUMENT, "cglVersion": "2.0"}),
                     json.dumps({**DOCUMENT, "localNetwork": True}),
                     json.dumps({**DOCUMENT, "networks": None}),
                     json.dumps({**DOCUMENT, "networks": [None]})):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_document(text)

    def test_reject_bad_nested_addresses_names_routes_and_duplicates(self):
        for change in (lambda d: d["networks"].append(d["networks"][0]),
                       lambda d: d["networks"][0].update(route=[256]),
                       lambda d: d["networks"][0].update(route="254"),
                       lambda d: d["networks"][0].update(name=42),
                       lambda d: d["networks"][0]["applications"][0]["groups"][0].update(address=-1),
                       lambda d: d["networks"][0]["applications"][0].update(groups={})):
            document = copy.deepcopy(DOCUMENT)
            change(document)
            with self.assertRaises(ValueError):
                parse_document(json.dumps(document))

    def test_selection_and_native_payload_extraction(self):
        lines = ("343-Begin CGL snippet", "347-" + json.dumps(DOCUMENT), "344 End CGL snippet")
        fake = FakeClient(CGateResponse(lines, lines[-1], 344))
        self.assertEqual(NativeCGL(fake).export("TEST", networks=[254, 1], applications=[56]), DOCUMENT)
        self.assertEqual(fake.commands, ["CGL EXPORT TEST 254,1 56"])
        for networks in ([], [-1], [True]):
            with self.assertRaises(ValueError):
                NativeCGL(fake).export("TEST", networks=networks)
        self.assertEqual(len(fake.commands), 1)

    def test_import_preflight_and_backup_before_native_mutation(self):
        fake = FakeClient()
        cgl = NativeCGL(fake)
        for text, backup in (("{}", "BACKUP"), (json.dumps(DOCUMENT), "test")):
            with self.assertRaises(ValueError):
                cgl.import_document("TEST", text, backup_project=backup)
        self.assertEqual(fake.commands, [])
        result = cgl.import_document("TEST", json.dumps(DOCUMENT), backup_project="BACKUP")
        self.assertTrue(result["complete"])
        self.assertEqual(fake.commands, ["PROJECT SAVE TEST", "PROJECT COPY TEST BACKUP",
                                          ("CGL IMPORT TEST", DOCUMENT)])

    def test_skipped_network_is_incomplete_even_with_3xx_response(self):
        reply = CGateResponse(("380-SKIPPED - Network 253", "380 CGL import not completed"),
                              "380 CGL import not completed", 380)
        result = NativeCGL(FakeClient(reply)).import_document("TEST", json.dumps(DOCUMENT))
        self.assertFalse(result["complete"])


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST"), "set CBUS_CGATE_TEST_HOST for real CGL acceptance")
class NativeCGLTests(unittest.TestCase):
    def test_import_export_filter_backup_and_partial_import(self):
        name = "G" + uuid.uuid4().hex[:7].upper()
        backup = "B" + uuid.uuid4().hex[:7].upper()
        with CGateClient(os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))) as client:
            projects, db, cgl = NativeProjects(client), NativeDatabase(client), NativeCGL(client)
            projects.operation("new", name)
            saved = backup_created = backup_loaded = False
            try:
                db.create_network(name, 254, "Local", "Cni", "127.0.0.1:29999")
                self.assertTrue(cgl.import_document(name, json.dumps(DOCUMENT))["complete"])
                exported = cgl.export(name, networks=[254], applications=[56])
                self.assertEqual(exported["networks"], DOCUMENT["networks"])
                self.assertEqual(summary(cgl.export(name, networks=[254], applications=[57]))["groups"], 0)
                changed = copy.deepcopy(DOCUMENT)
                changed["networks"][0]["applications"][0]["groups"][0]["name"] = "Living Room"
                changed["networks"][0]["applications"][0]["groups"].append({"address": 2, "name": "Hall"})
                projects.operation("save", name)
                saved = True
                result = cgl.import_document(name, json.dumps(changed), backup_project=backup)
                backup_created = True
                self.assertTrue(result["complete"])
                # The actual 3.4 importer adds missing objects and preserves
                # existing names, despite the command help saying "replaces".
                self.assertIn("Lounge", " ".join(db.get(f"//{name}/254/56/1/TagName").lines))
                self.assertIn("Hall", " ".join(db.get(f"//{name}/254/56/2/TagName").lines))
                projects.operation("load", backup)
                backup_loaded = True
                self.assertEqual(cgl.export(backup, networks=[254])["networks"], DOCUMENT["networks"])
                changed["networks"][0]["address"] = 253
                self.assertFalse(cgl.import_document(name, json.dumps(changed))["complete"])
                self.assertEqual(client.command("NOOP").code, 200)
            finally:
                projects.operation("close", name)
                if saved:
                    projects.operation("delete", name)
                if backup_created:
                    if backup_loaded:
                        projects.operation("close", backup)
                    projects.operation("delete", backup)


if __name__ == "__main__":
    unittest.main()
