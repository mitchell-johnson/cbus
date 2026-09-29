import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.cgate import CGateClient, CGateResponse
from cbus_toolkit.cgl import NativeCGL, parse_document, summary
from cbus_toolkit.native import NativeDatabase, NativeProjects
from research import native_cgl_routes as routes


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

    def test_native_binding_rules_unknown_fields_absent_networks_and_names(self):
        # Native Jackson binding rejects unknown properties at every level.
        for change in (lambda d: d.update(numberOfExportedObjects=3),
                       lambda d: d["networks"][0].update(extra=True),
                       lambda d: d["networks"][0]["applications"][0].update(extra=1),
                       lambda d: d["networks"][0]["applications"][0]["groups"][0]["levels"][0].update(extra=1)):
            document = copy.deepcopy(DOCUMENT)
            change(document)
            with self.assertRaises(ValueError):
                parse_document(json.dumps(document))
        self.assertEqual(summary(parse_document('{"cglVersion":"1.1","localNetwork":254}'))["networks"], 0)
        nameless = copy.deepcopy(DOCUMENT)
        nameless["networks"][0]["applications"][0]["groups"][0]["levels"][0].pop("name")
        self.assertEqual(parse_document(json.dumps(nameless)), nameless)
        fake = FakeClient()
        with self.assertRaises(ValueError):
            NativeCGL(fake).import_document("TEST", json.dumps(nameless))
        self.assertEqual(fake.commands, [])

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


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_cgl_routes.json"
VECTORS = ROOT / "rust/testdata/vectors/cgate_cgl_routes.jsonl"
NATIVE = bool(os.environ.get("CBUS_LOCAL_CGATE_VENDOR") and os.environ.get("CBUS_CGATE_JAVA"))


def fixture():
    return json.loads(FIXTURE.read_text())


def replies(name):
    scenario = next(item for item in fixture()["scenarios"] if item["name"] == name)
    return [(step["command"], step.get("document"), step.get("reply")) for step in scenario["steps"]
            if not step.get("setup")]


class CommittedNativeCaptureTests(unittest.TestCase):
    """Offline checks that the committed native transcript supports each recorded fact."""

    def test_fixture_is_current_sanitized_and_vectors_are_derived_from_it(self):
        committed = fixture()
        self.assertEqual(committed["format"], routes.FORMAT)
        self.assertEqual(committed["capture_script_sha256"],
                         hashlib.sha256(Path(routes.__file__).read_bytes()).hexdigest())
        self.assertEqual(committed["oracle"]["jar_sha256"],
                         "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630")
        self.assertTrue(committed["oracle"]["cleanup_complete"])
        self.assertEqual(committed["native_facts"], routes.NATIVE_FACTS)
        text = FIXTURE.read_text()
        for private in ("127.0.0.1", "/Users/", "/Volumes/", "/private/"):
            self.assertNotIn(private, text)
        rows = [json.loads(line) for line in VECTORS.read_text().splitlines()]
        self.assertEqual(rows, routes.vectors(committed))

    def test_routes_follow_bridge_units_up_to_six_hops_and_last_selected_network_is_local(self):
        exports = {command: reply for command, _, reply in replies("export_routes")}
        chain = json.loads(exports["CGL EXPORT CGLP 254"][1][4:])
        self.assertEqual(chain["localNetwork"], 254)
        self.assertEqual([network.get("route", []) for network in chain["networks"]],
                         [[], [253], [253, 252], [253, 252, 251], [253, 252, 251, 250],
                          [253, 252, 251, 250, 249], [253, 252, 251, 250, 249, 248]])
        self.assertEqual(json.loads(exports["CGL EXPORT CGLP"][1][4:])["localNetwork"], 240)
        self.assertEqual(json.loads(exports["CGL EXPORT CGLP 253,254"][1][4:])["localNetwork"], 253)
        self.assertEqual(exports["CGL EXPORT CGLP ,"][-1], "408 Operation failed: CGL export failed: Export failed.  "
                         "Exception: com.clipsal.cgate.cgl.CglException: Local address is missing.")
        topology = {command: json.loads(reply[1][4:]) for command, _, reply in replies("topology")
                    if command.startswith("CGL EXPORT")}
        routes_254 = {network["address"]: network.get("route") for network in topology["CGL EXPORT CGLT 254"]["networks"]}
        # BRIDGEX and PCGATEWAY/XGATEY count; lowercase bridge, relays and
        # dangling units do not; the first-created of two equal paths wins.
        self.assertEqual(routes_254, {254: None, 10: [10], 20: [20], 30: [20, 30], 60: [60]})
        self.assertEqual(topology["CGL EXPORT CGLT 40"]["networks"], [{"address": 40, "name": "D"}])

    def test_import_ignores_supplied_routes_and_reports_skips_as_incomplete(self):
        (_, _, reply), *_ = replies("import_routes")
        self.assertIn("380-Importing Network 252", reply)  # wrong route [9, 9]
        self.assertIn("380-Importing Network 248", reply)  # empty route
        self.assertIn("380-          254 - 253 - 252 - 251 - 250 - 249 - 248 - 247", reply)
        self.assertIn("380-SKIPPED - Network 99 does not exist. Please create it and try the import again.", reply)
        self.assertEqual(reply[-1], "380 CGL import not completed: Skipped 3 network(s). ")
        scenario = next(item for item in fixture()["scenarios"] if item["name"] == "import_routes")
        self.assertEqual(scenario["pci_inbound_records_during_import_and_export"], 0)
        self.assertGreater(fixture()["pci"]["total_wire_records"], 0)

    def test_conflicts_preserve_names_and_runtime_layer_reports_again_after_reload(self):
        (_, _, first), (_, _, repeat), (_, _, export) = replies("conflicts")
        self.assertIn("380-  Created new application 251/56 ('Different')", first)
        self.assertNotIn("Duplicate", " ".join(first))
        self.assertEqual(repeat[-2:], ["380-Imported 0 object(s) of 1 network(s): 0 application(s), "
                                       "0 group(s), 0 level(s) ", "200 OK."])
        exported = json.loads(export[1][4:])
        hop3 = next(network for network in exported["networks"] if network["address"] == 251)
        self.assertEqual(hop3["applications"][0]["name"], "ExistingLighting")
        self.assertEqual(hop3["applications"][0]["groups"][0]["name"], "ExistingGroup")
        runtime = [reply for command, _, reply in replies("runtime_layer") if command.startswith("CGL IMPORT")]
        self.assertEqual([len(reply) for reply in runtime], [5, 4, 6, 4])

    def test_validation_and_nameless_hazard(self):
        answers = {document: reply for command, document, reply in replies("validation") if document is not None}
        self.assertEqual(answers['{"cglVersion":"1.1","networks":[]}'],
                         ["408 Operation failed: CGL import failed: Import failed.  Exception: java.lang.NullPointerException"])
        self.assertTrue(answers["not json"][0].startswith("400 Syntax Error: CGL validation failed: Import Failed: "))
        metadata = {document: reply for _, document, reply in replies("metadata")}
        self.assertTrue(all(reply[-1] == "200 OK." for document, reply in metadata.items()
                            if "yesterday" not in document and "Objects" not in document
                            and "extra" not in document and "bogus" not in document))
        nameless = {command: reply for command, _, reply in replies("nameless")}
        self.assertIn("380-      Created new level 254/56/1/7 ('null')", nameless["CGL IMPORT CGLN"])
        self.assertIn("NOT NULL constraint failed", nameless["PROJECT SAVE CGLN"][-1])
        with self.assertRaises(ValueError):
            parse_document(json.dumps({**DOCUMENT, "networks": [{"address": 254, "applications": [
                {"address": 56}]}]}), require_names=True)


@unittest.skipUnless(NATIVE, "owned native C-Gate is not configured")
class NativeCGLTests(unittest.TestCase):
    """Owned loopback C-Gate 3.4.0.2001: the typed client and the full route capture."""

    def test_capture_matches_committed_fixture(self):
        with tempfile.TemporaryDirectory(prefix="cbus-cgl-native-") as directory:
            report = routes.capture(output_dir=directory)
        self.assertTrue(report["local_service"]["cleanup_complete"])
        self.assertEqual(report["scenarios"], fixture()["scenarios"])

    def test_import_export_filter_backup_and_partial_import(self):
        from research.local_cgate import LocalCGate
        service = LocalCGate(os.environ["CBUS_LOCAL_CGATE_VENDOR"], java=os.environ["CBUS_CGATE_JAVA"])
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
        name, backup = "GCGL", "BCGL"
        with service, CGateClient("127.0.0.1", service.port) as client:
            projects, db, cgl = NativeProjects(client), NativeDatabase(client), NativeCGL(client)
            projects.operation("new", name)
            db.create_network(name, 254, "Local", "Cni", "127.0.0.2:29999")
            self.assertTrue(cgl.import_document(name, json.dumps(DOCUMENT))["complete"])
            exported = cgl.export(name, networks=[254], applications=[56])
            self.assertEqual(exported["networks"], DOCUMENT["networks"])
            self.assertEqual(summary(cgl.export(name, networks=[254], applications=[57]))["groups"], 0)
            changed = copy.deepcopy(DOCUMENT)
            changed["networks"][0]["applications"][0]["groups"][0]["name"] = "Living Room"
            changed["networks"][0]["applications"][0]["groups"].append({"address": 2, "name": "Hall"})
            projects.operation("save", name)
            result = cgl.import_document(name, json.dumps(changed), backup_project=backup)
            self.assertTrue(result["complete"])
            # The actual 3.4 importer adds missing objects and preserves
            # existing names, despite the command help saying "replaces".
            self.assertIn("Lounge", " ".join(db.get(f"//{name}/254/56/1/TagName").lines))
            self.assertIn("Hall", " ".join(db.get(f"//{name}/254/56/2/TagName").lines))
            projects.operation("load", backup)
            self.assertEqual(cgl.export(backup, networks=[254])["networks"][0]["applications"],
                             DOCUMENT["networks"][0]["applications"])
            changed["networks"][0]["address"] = 253
            self.assertFalse(cgl.import_document(name, json.dumps(changed))["complete"])
            self.assertEqual(client.command("NOOP").code, 200)
        self.assertTrue(service.report["cleanup_complete"])


if __name__ == "__main__":
    unittest.main()
