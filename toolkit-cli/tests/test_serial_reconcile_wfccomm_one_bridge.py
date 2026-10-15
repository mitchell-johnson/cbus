"""WFCOMM one-bridge routed serial-reconcile (issues #32 known-serial + #28 seam).

Software-only slice 1: the exact one-bridge shape from the acceptance contract —
root network 254, one evidenced bridge to 252 (bridge address 252, which is not
the consecutive 253 covered by the existing one-bridge cases), selected serial
101136.1558, local PCI unit 16/serial 100966.1187, empty target 6 — proved
through a synthetic PCI peer and, with an owned cmqttd service, a loaded
WFCOMM project.

Covers: topology-derived (non-consecutive) route and plan, exactly one address
request on the peer transcript, movement derived from the fresh after-inventory
rather than the ACK, offline backup->mutate->reload preservation diff, loaded
backup->mutate->CLOSE/LOAD diff, loaded target-SAVE failure with database-only
retry and no address replay, repeat no-op, and fault refusals before any
database write. No vendor process, real bridge, or hardware persistence claim.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cbus_toolkit import cli
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeProjects
from cbus_toolkit.pci_selected_serial import (
    SelectedSerialPlan, route_from_project,
)
from cbus_toolkit.programming import xml_text
from cbus_toolkit.project import ProjectDocument
from cbus_toolkit.serial_reconcile import (
    CGateDatabase, ReconcileError, _project_digest, default_record_path,
    reconcile, verify_journal,
)
from research.cgate_dbsetxml_unit_differential import owned_server
from tests.test_pci_selected_serial_routed import (
    A, C, after_responses, before_requests, before_responses, far_requests,
    manager, peer, receipt, routed_co,
)
from tests.test_serial_reconcile_routed import KEEPER, OID, unit

BIN = __import__("os").environ.get("CBUS_CMQTTD_BIN")

PROJECT = "WFCOMM"
SOURCE = 254
TARGET = 252
ROUTE = [252]
DEST = 6


def wfccomm_offline_bytes():
    """Legacy project file: 254/CNI with BRIDGE2N at 252, 252 bridged to 254."""
    root = (
        "<Network><TagName>N254</TagName><Address>254</Address>"
        "<Interface><InterfaceType>CNI</InterfaceType>"
        "<InterfaceAddress>127.0.0.1:10001</InterfaceAddress></Interface>"
        "<Unit><Address>252</Address><UnitType>BRIDGE2N</UnitType></Unit>"
        + unit(KEEPER, 20, A) + "</Network>"
    )
    far = (
        "<Network><TagName>N252</TagName><Address>252</Address>"
        "<Interface><InterfaceType>Bridge</InterfaceType>"
        "<InterfaceAddress>254/p/252</InterfaceAddress></Interface>"
        + unit(OID, 255, A)
        + "<Unit><Address>21</Address><UnitType>KEYE1</UnitType>"
        f"<Partner>{OID}</Partner></Unit></Network>"
    )
    return (
        f"<Installation><Project><TagName>{PROJECT}</TagName>"
        + root + far + "</Project></Installation>"
    ).encode()


def physical(directory, snapshot):
    """Plan/apply/verify over a synthetic peer; return (journal, plan, state)."""
    derived, digest = route_from_project(
        snapshot, source_network=SOURCE, target_network=TARGET)
    assert derived == ROUTE, derived
    with peer(before_responses(ROUTE)) as (endpoint, _):
        plan = manager(endpoint).plan(A, DEST, route=derived, project_sha256=digest)
    assert plan.as_dict()["request_hex"] == routed_co(ROUTE, A, DEST).hex()
    assert plan.as_dict()["expected_after"]["identities"] == [
        {"address": 6, "serials": [A]},
        {"address": 16, "serials": [C]},
        {"address": 255, "serials": ["101136.1559"]},
    ]
    journal = directory / "wfccomm-apply.json"
    responses = (before_responses(ROUTE) + [b"g." + receipt(ROUTE, DEST, A)]
                 + after_responses(ROUTE))
    with peer(responses) as (endpoint, state):
        document = plan.as_dict()
        document["endpoint"] = {"host": endpoint[0], "port": endpoint[1]}
        document["before"] = dict(document["before"], endpoint=document["endpoint"])
        plan = SelectedSerialPlan.from_dict(document)
        result = manager(endpoint).apply(
            plan, recovery_path=journal, project=snapshot,
            source_network=SOURCE, target_network=TARGET)
    assert result.outcome == "observed_expected_change", result.outcome
    assert result.as_dict()["receipt_matches_request"] is True
    with peer(after_responses(ROUTE), port=endpoint[1]):
        observed = manager(endpoint).verify(
            plan, project=snapshot, source_network=SOURCE, target_network=TARGET)
    assert observed.outcome == "observed_expected_change", observed.outcome
    assert observed.as_dict()["send_attempted"] is False
    return journal, plan, state


def assert_offline_preserved(project, before):
    document = ProjectDocument.load(project)
    target = f"/network/{TARGET}/unit/{DEST}"
    assert document.path_of(document.resolve("oid:" + OID)) == target
    assert document.parameters(target) == {
        "UnitAddress": "0x6", "GroupAddress": "0x1 0xff"}
    assert document.get_field(f"/network/{TARGET}/unit/21", "Partner") == OID
    document.update(target, {"Address": "255"})
    document.set_parameter(f"/network/{TARGET}/unit/255", "UnitAddress", "0xff")
    assert (document.raw_xml()
            == ProjectDocument.from_snapshot(before).raw_xml())


class WfccommOneBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_route_and_plan_derive_nonconsecutive_bridge_from_topology(self):
        snapshot = self.dir / "commissioning.xml"
        snapshot.write_bytes(wfccomm_offline_bytes())
        derived, _ = route_from_project(
            snapshot, source_network=SOURCE, target_network=TARGET)
        self.assertEqual(derived, ROUTE)

    def test_apply_sends_one_address_request_with_fresh_inventory_movement(self):
        snapshot = self.dir / "commissioning.xml"
        snapshot.write_bytes(wfccomm_offline_bytes())
        journal, plan, state = physical(self.dir, snapshot)
        self.assertEqual(state["errors"], [])
        self.assertEqual(state["requests"],
                         before_requests(ROUTE) + [routed_co(ROUTE, A, DEST)]
                         + far_requests(ROUTE, {6: 2, 16: 1, 255: 2}))
        self.assertEqual(
            sum(b"FF0F00" in row for row in state["requests"]), 1)
        self.assertTrue(verify_journal(journal).receipt_matches_request)

    def test_offline_backup_mutate_reload_noop_and_faults(self):
        from cbus_toolkit.serial_reconcile import ProjectFileDatabase
        project = self.dir / "commissioning.xml"
        project.write_bytes(wfccomm_offline_bytes())
        before = project.read_bytes()
        journal, _, _ = physical(self.dir, snapshot=project)
        planned = reconcile(journal, ProjectFileDatabase(project))
        self.assertEqual(planned["outcome"], "planned")
        self.assertEqual(planned["unit"]["network"], TARGET)
        self.assertEqual(project.read_bytes(), before)
        self.assertFalse(default_record_path(journal).exists())
        with self.subTest(fault="stale-project-before-apply"):
            project.write_bytes(before + b" ")
            with patch.object(ProjectDocument, "save",
                               side_effect=AssertionError("stale wrote")):
                with self.assertRaises(ReconcileError):
                    reconcile(journal, ProjectFileDatabase(project), apply=True)
            self.assertFalse(default_record_path(journal).exists())
            project.write_bytes(before)
        result = reconcile(journal, ProjectFileDatabase(project), apply=True)
        self.assertEqual(result["outcome"], "reconciled")
        self.assertFalse(result["bus_io_performed"])
        record = json.loads(default_record_path(journal).read_text())
        self.assertEqual(Path(record["backup"]).read_bytes(), before)
        assert_offline_preserved(project, before)
        saved = project.read_bytes()
        with patch.object(ProjectDocument, "save",
                           side_effect=AssertionError("db_done wrote")):
            repeated = reconcile(journal, ProjectFileDatabase(project), apply=True)
        self.assertEqual(repeated["outcome"], "already_reconciled")
        self.assertTrue(repeated["current_database_matches_record"])
        self.assertEqual(project.read_bytes(), saved)
        pristine = journal.read_bytes()
        try:
            with self.subTest(fault="wrong-network"):
                with self.assertRaises(ReconcileError):
                    reconcile(journal, ProjectFileDatabase(project),
                              apply=True, network=SOURCE)
            with self.subTest(fault="db-done-later-edit-reports-without-writes"):
                project.write_bytes(saved + b"<!-- later edit -->")
                with patch.object(ProjectDocument, "save",
                                   side_effect=AssertionError("db_done wrote")):
                    later = reconcile(journal, ProjectFileDatabase(project), apply=True)
                self.assertEqual(later["outcome"], "already_reconciled")
                self.assertFalse(later["current_database_matches_record"])
                project.write_bytes(saved)
            with self.subTest(fault="tampered-journal"):
                value = json.loads(pristine)
                value["receipt_matches_request"] = False
                journal.write_text(json.dumps(value))
                with patch.object(ProjectDocument, "save",
                                   side_effect=AssertionError("tampered wrote")):
                    with self.assertRaises(ReconcileError):
                        reconcile(journal, ProjectFileDatabase(project), apply=True)
        finally:
            journal.write_bytes(pristine)
        self.assertEqual(project.read_bytes(), saved)


@unittest.skipUnless(BIN, "Select CBUS_CMQTTD_BIN for owned loaded WFCOMM reconciliation")
class LoadedWfccommOneBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wfccomm-one-bridge-")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.server = owned_server("cmqttd", Path(BIN))
        self.port = self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.client = CGateClient("127.0.0.1", self.port, timeout=15,
                                  max_line_bytes=16 * 1024 * 1024)
        self.client.connect()
        self.addCleanup(self.client.close)

    def seed(self):
        self.client.command(f"PROJECT NEW {PROJECT}")
        self.client.command(f"PROJECT USE {PROJECT}")
        self.client.command(f"DBCREATENET {SOURCE} N{SOURCE} Cni 127.0.0.1:1")
        tree = ET.fromstring(xml_text(
            self.client.command(f"DBGETXML //{PROJECT}/{SOURCE}")))
        tree.append(ET.fromstring(unit(
            "7c0e0f10-1111-4222-8333-000000252001", TARGET, "101137.252", "BRIDGE2N")))
        tree.append(ET.fromstring(unit(KEEPER, 20, A)))
        for entry in tree.findall("Unit"):
            if entry.find("UnitName") is None:
                ET.SubElement(entry, "UnitName").text = entry.findtext("UnitType")
        self.client.command_document(
            f"DBSETXML //{PROJECT}/{SOURCE}", ET.tostring(tree, encoding="unicode"))
        self.client.command(
            f"DBCREATENET {TARGET} N{TARGET} Bridge {SOURCE}/p/{TARGET}")
        tree = ET.fromstring(xml_text(
            self.client.command(f"DBGETXML //{PROJECT}/{TARGET}")))
        moved = ET.fromstring(unit(OID, 255, A))
        ET.SubElement(moved, "UnitName").text = "KEYE1"
        tree.append(moved)
        keeper = ET.fromstring(unit(
            "7c0e0f10-1111-4222-8333-944455556603", 21, "101136.9"))
        keeper.find("Description").text = OID
        tree.append(keeper)
        for entry in tree.findall("Unit"):
            if entry.find("UnitName") is None:
                ET.SubElement(entry, "UnitName").text = entry.findtext("UnitType")
        self.client.command_document(
            f"DBSETXML //{PROJECT}/{TARGET}", ET.tostring(tree, encoding="unicode"))
        for action in ("SAVE", "CLOSE", "LOAD", "USE"):
            self.client.command(f"PROJECT {action} {PROJECT}")
        snapshot = self.directory / f"{PROJECT}.xml"
        snapshot.write_text(
            xml_text(self.client.command("DBGETXML //" + PROJECT)), encoding="utf-8")
        return snapshot

    def run_cli(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = cli.main(arguments)
        return code, output.getvalue() + error.getvalue()

    def reconcile_args(self, journal, snapshot):
        return ["serial-address", "reconcile", "--journal", str(journal),
                "--cgate", f"127.0.0.1:{self.port}", "--project-name", PROJECT,
                "--route-project", str(snapshot), "--exclusive-project"]

    def database(self, snapshot):
        return CGateDatabase(self.client, PROJECT, endpoint=f"127.0.0.1:{self.port}",
                             route_project=snapshot, exclusive_project=True)

    def test_cli_plan_apply_close_load_readback_noop(self):
        snapshot = self.seed()
        original = ProjectDocument.load(snapshot)
        journal, _, state = physical(self.directory, snapshot)
        self.assertEqual(
            sum(b"FF0F00" in row for row in state["requests"]), 1)
        old_journal = journal.read_bytes()
        marker = Path(json.loads(old_journal)["attempt_identity"])
        old_marker = marker.read_bytes()
        arguments = self.reconcile_args(journal, snapshot)
        code, text = self.run_cli(arguments)
        self.assertEqual(code, 0, text)
        self.assertEqual(json.loads(text)["outcome"], "planned")
        self.assertFalse(default_record_path(journal).exists())
        code, text = self.run_cli(arguments + ["--apply"])
        self.assertEqual(code, 0, text)
        result = json.loads(text)
        self.assertEqual(result["outcome"], "reconciled")
        self.assertFalse(result["bus_io_performed"])
        self.assertEqual(journal.read_bytes(), old_journal)
        self.assertEqual(marker.read_bytes(), old_marker)
        for action in ("close", "load"):
            code, text = self.run_cli(
                ["cgate", "--host", "127.0.0.1", "--port", str(self.port),
                 "project", action, PROJECT])
            self.assertEqual(code, 0, text)
        reopened = self.directory / "reopened.xml"
        code, text = self.run_cli(
            ["cgate", "--host", "127.0.0.1", "--port", str(self.port),
             "database", "get-xml", f"//{PROJECT}", "--project", PROJECT,
             "--output", str(reopened)])
        self.assertEqual(code, 0, text)
        current = ProjectDocument.load(reopened)
        target = f"/network/{TARGET}/unit/{DEST}"
        self.assertEqual(current.path_of(current.resolve("oid:" + OID)), target)
        current.update(target, {"Address": "255"})
        current.set_parameter(f"/network/{TARGET}/unit/255", "UnitAddress",
                              original.parameters(f"/network/{TARGET}/unit/255")["UnitAddress"])
        self.assertEqual(_project_digest(current), _project_digest(original))
        record_before = default_record_path(journal).read_bytes()
        calls = []
        original_operation = NativeProjects.operation

        def recording(self, action, *args, **kwargs):
            calls.append(action)
            return original_operation(self, action, *args, **kwargs)

        with patch.object(NativeProjects, "operation", recording):
            code, text = self.run_cli(arguments + ["--apply"])
        self.assertEqual(code, 0, text)
        again = json.loads(text)
        self.assertEqual(again["outcome"], "already_reconciled")
        self.assertTrue(again["current_database_matches_record"])
        self.assertFalse(any(action in ("save", "close", "load", "copy")
                             for action in calls))
        self.assertEqual(default_record_path(journal).read_bytes(), record_before)

    def test_target_save_failure_retries_database_only_without_readdress(self):
        snapshot = self.seed()
        original = ProjectDocument.load(snapshot)
        journal, _, state = physical(self.directory, snapshot)
        self.assertEqual(sum(b"FF0F00" in row for row in state["requests"]), 1)
        requests_before = list(state["requests"])
        old_journal = journal.read_bytes()
        marker = Path(json.loads(old_journal)["attempt_identity"])
        old_marker = marker.read_bytes()
        self.assertEqual(reconcile(journal, self.database(snapshot))["outcome"], "planned")
        self.assertFalse(default_record_path(journal).exists())
        operation = NativeProjects.operation
        saves = 0

        def interrupt(projects, action, name, *args, **kwargs):
            nonlocal saves
            if action == "save" and name == PROJECT:
                saves += 1
                if saves == 2:
                    raise TimeoutError("target SAVE not sent")
            return operation(projects, action, name, *args, **kwargs)

        with patch.object(NativeProjects, "operation", interrupt):
            with self.assertRaises(ReconcileError):
                reconcile(journal, self.database(snapshot), apply=True)
        record_path = default_record_path(journal)
        self.assertEqual(json.loads(record_path.read_text())["phase"], "db_pending")
        self.assertEqual(saves, 2)
        self.assertEqual((journal.read_bytes(), marker.read_bytes()), (old_journal, old_marker))
        with self.assertRaisesRegex(ReconcileError, "Saved project remains the original"):
            reconcile(journal, self.database(snapshot), apply=True)
        result = reconcile(journal, self.database(snapshot), apply=True, retry_database=True)
        self.assertEqual(result["outcome"], "reconciled")
        self.assertFalse(result["bus_io_performed"])
        self.assertEqual(list(state["requests"]), requests_before)
        self.assertEqual((journal.read_bytes(), marker.read_bytes()), (old_journal, old_marker))
        record = json.loads(record_path.read_text())
        self.assertEqual(record["phase"], "db_done")
        self.assertTrue(record["cgate"]["backup_confirmed"])
        self.assertTrue(record["cgate"]["saved_readback_verified"])
        current, _ = self.database(snapshot).snapshot()
        target = f"/network/{TARGET}/unit/{DEST}"
        self.assertEqual(current.path_of(current.resolve("oid:" + OID)), target)
        self.assertEqual(int(current.parameters(target)["UnitAddress"], 0), DEST)
        self.assertEqual(current.parameters(target)["GroupAddress"], "0x1 0xff")
        self.assertEqual(current.get_field(f"/network/{TARGET}/unit/21", "Description"), OID)
        self.assertEqual(current.get_field(f"/network/{SOURCE}/unit/{TARGET}", "UnitType"), "BRIDGE2N")
        current.update(target, {"Address": "255"})
        current.set_parameter(f"/network/{TARGET}/unit/255", "UnitAddress",
                              original.parameters(f"/network/{TARGET}/unit/255")["UnitAddress"])
        self.assertEqual(_project_digest(current), _project_digest(original))
        for action in ("CLOSE", "LOAD", "USE"):
            self.client.command(f"PROJECT {action} {PROJECT}")
        reopened, _ = self.database(snapshot).snapshot()
        self.assertEqual(_project_digest(reopened), record["cgate"]["expected_project_sha256"])
        self.assertEqual(reopened.path_of(reopened.resolve("oid:" + OID)), target)
        database = self.database(snapshot)
        before = record_path.read_bytes()
        with patch.object(NativeProjects, "operation",
                           wraps=database.addressing.projects.operation) as calls, \
                patch.object(self.client, "command_document",
                             side_effect=AssertionError("repeat wrote")):
            again = reconcile(journal, database, apply=True)
        self.assertEqual(again["outcome"], "already_reconciled")
        self.assertTrue(again["current_database_matches_record"])
        self.assertFalse(any(call.args[0] in ("save", "close", "load", "copy")
                             for call in calls.call_args_list))
        self.assertEqual(record_path.read_bytes(), before)

    def test_cli_admission_and_tamper_refuse_before_write(self):
        snapshot = self.seed()
        journal, _, _ = physical(self.directory, snapshot)
        arguments = ["serial-address", "reconcile", "--journal", str(journal),
                     "--cgate", "127.0.0.1:1", "--project-name", PROJECT, "--apply"]
        for extra, expected in (
                ([], "route-project"),
                (["--route-project", str(snapshot)], "exclusive-project")):
            with self.subTest(extra=extra):
                with patch("cbus_toolkit.cgate.CGateClient",
                            side_effect=AssertionError("connected")) as client:
                    code, text = self.run_cli(arguments + extra)
                self.assertEqual(code, 1)
                client.assert_not_called()
                self.assertIn(expected, text.lower())
                self.assertFalse(default_record_path(journal).exists())
        pristine = journal.read_bytes()
        try:
            with self.subTest(fault="tampered-journal"):
                value = json.loads(pristine)
                value["receipt_matches_request"] = False
                journal.write_text(json.dumps(value))
                with patch("cbus_toolkit.cgate.CGateClient",
                            side_effect=AssertionError("connected")) as client, \
                     patch.object(self.client, "command_document",
                                  side_effect=AssertionError("tampered wrote")):
                    code, text = self.run_cli(self.reconcile_args(journal, snapshot)
                                              + ["--apply"])
                self.assertEqual(code, 1, text)
                client.assert_not_called()
            with self.subTest(fault="stale-route-snapshot"):
                snapshot.write_bytes(snapshot.read_bytes() + b"<!--stale-->")
                with patch("cbus_toolkit.cgate.CGateClient",
                            side_effect=AssertionError("connected")) as client:
                    code, text = self.run_cli(self.reconcile_args(journal, snapshot)
                                              + ["--apply"])
                self.assertEqual(code, 1, text)
                client.assert_not_called()
        finally:
            journal.write_bytes(pristine)


if __name__ == "__main__":
    unittest.main()
