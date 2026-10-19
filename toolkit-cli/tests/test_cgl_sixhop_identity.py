"""Focused six-hop one-way CGL identity interchange tests (P2.03, issue #25).

Offline only: a fake client replays the committed six-hop identity vectors in
``rust/testdata/vectors/cgate_cgl_sixhop_identity.jsonl``. CGL moves only a
project's network/application/group/level labels; no PCI traffic or
controller programming is claimed.
"""
import copy
import json
import unittest
from pathlib import Path

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.cgl import NativeCGL, parse_document, summary

ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "rust/testdata/vectors/cgate_cgl_sixhop_identity.jsonl"
# createdBy names cmqttd (dispositioned in rust cgl_deviation_tests.rs);
# cmqttd does not impersonate the native C-Gate build string.
CREATOR = "cmqttd"


def rows():
    return [json.loads(line) for line in VECTORS.read_text().splitlines()]


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


class SixHopIdentityTests(unittest.TestCase):
    def test_head_export_document_names_cmqttd_creator_and_sixhop_routes(self):
        row = rows()[0]
        self.assertEqual(row["command"], "CGL EXPORT CGLI 254")
        document = row["expect_export"]["document"]
        self.assertEqual(document["createdBy"], CREATOR)
        parsed = parse_document(json.dumps(document))
        self.assertEqual(parsed["createdBy"], CREATOR)
        self.assertEqual(
            [network.get("route", []) for network in parsed["networks"]],
            [[], [253], [253, 252], [253, 252, 251], [253, 252, 251, 250],
             [253, 252, 251, 250, 249], [253, 252, 251, 250, 249, 248]])
        self.assertEqual(
            summary(parsed),
            {"version": "1.1", "local_network": 254, "networks": 7,
             "applications": 1, "groups": 1, "levels": 1})

    def test_tail_exports_only_itself_with_cmqttd_creator(self):
        row = rows()[1]
        self.assertEqual(row["command"], "CGL EXPORT CGLI 247")
        document = parse_document(json.dumps(row["expect_export"]["document"]))
        self.assertEqual(document["createdBy"], CREATOR)
        self.assertEqual(document["localNetwork"], 247)
        self.assertEqual(document["networks"], [{"address": 247, "name": "Hop7"}])

    def test_export_command_parses_343_347_344_envelope(self):
        row = rows()[0]
        body = copy.deepcopy(row["expect_export"]["document"])
        body["createdTime"] = "2026-10-17T00:00:00.000+00:00"
        lines = (row["expect_export"]["first"], "347-" + json.dumps(body),
                 row["expect_export"]["final"])
        fake = FakeClient(CGateResponse(lines, lines[-1], 344))
        self.assertEqual(NativeCGL(fake).export("CGLI", networks=[254]), body)
        self.assertEqual(fake.commands, ["CGL EXPORT CGLI 254 *"])
        self.assertEqual(body["createdBy"], CREATOR)

    def test_far_end_import_with_wrong_route_is_complete(self):
        row = rows()[2]
        document = json.loads(row["document"])
        self.assertEqual(document["networks"][1]["route"], [9, 9])
        lines = tuple(row["expect"])
        fake = FakeClient(CGateResponse(lines, lines[-1], 200))
        result = NativeCGL(fake).import_document(
            "CGLI", row["document"], backup_project="BACKUP")
        self.assertTrue(result["complete"])
        self.assertEqual(result["document"]["applications"], 1)
        self.assertEqual(fake.commands, ["PROJECT SAVE CGLI", "PROJECT COPY CGLI BACKUP",
                                          ("CGL IMPORT CGLI", document)])

    def test_skipped_tail_network_is_incomplete(self):
        row = rows()[0]
        reply = CGateResponse(("380-SKIPPED - Network 247 is not routable",
                               "380 CGL import not completed: Skipped 1 network(s). "),
                              "380 CGL import not completed: Skipped 1 network(s). ", 380)
        result = NativeCGL(FakeClient(reply)).import_document(
            "CGLI", json.dumps(row["expect_export"]["document"]))
        self.assertFalse(result["complete"])

    def test_nameless_preflight_still_refuses_before_any_command(self):
        row = rows()[2]
        nameless = copy.deepcopy(json.loads(row["document"]))
        del nameless["networks"][1]["applications"][0]["groups"][0]["name"]
        fake = FakeClient()
        with self.assertRaises(ValueError):
            NativeCGL(fake).import_document("CGLI", json.dumps(nameless))
        self.assertEqual(fake.commands, [])


if __name__ == "__main__":
    unittest.main()
