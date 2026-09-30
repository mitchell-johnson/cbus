"""Loaded routed reconciliation against an owned real cmqttd service.

The addressing peer retains literal Reply Network frames and the native project
snapshot is exported before the physical plan. These are software integration
cases, with no vendor process, real bridge or hardware persistence claim.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from cbus_toolkit import cli
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeProjects
from cbus_toolkit.pci_selected_serial import (
    SelectedSerialPlan, SelectedSerialUncertain, export_verification, recovery_binding, route_from_project,
)
from cbus_toolkit.programming import xml_text
from cbus_toolkit.project import ProjectDocument
from cbus_toolkit.serial_reconcile import (
    CGateDatabase, ReconcileError, ReconcileRecord, _project_digest, default_record_path, reconcile, verify_journal,
)
from research.cgate_dbsetxml_unit_differential import owned_server
from tests.test_pci_selected_serial_routed import (
    A, ONE, SIX, after_responses, before_responses, manager, peer, receipt,
)
from tests.test_serial_reconcile_routed import OID, KEEPER, unit
from tests.test_commissioning_route import line

BIN = os.environ.get("CBUS_CMQTTD_BIN")
TOOLS_BIN = os.environ.get("CBUS_TOOLS_BIN")


class NativeRouteSnapshotTests(unittest.TestCase):
    def test_native_address_identity_routes_without_changing_the_raw_snapshot(self):
        from cbus_toolkit.commissioning_route import plan_commissioning_route, project_sha256
        raw = line(1)[0].replace(b"<TagName>HOUSE</TagName>", b"<Address>HOUSE</Address>")
        project = ProjectDocument.from_bytes(raw)
        before = project.raw_xml()
        result = plan_commissioning_route(project, project_digest=project_sha256(raw), source_network=254,
                                         target_network=253, target_unit=5, local_unit=16,
                                         expected_project_name="HOUSE")
        self.assertEqual(result.project_name, "HOUSE")
        self.assertEqual(result.bridges, (253,))
        self.assertEqual(project.raw_xml(), before)

    def test_empty_legacy_tagname_and_missing_or_duplicate_native_identity_refuse(self):
        from cbus_toolkit.commissioning_route import resolve_network_route
        raw = line(1)[0]
        for identity in (b"<TagName></TagName><Address>HOUSE</Address>", b"", b"<Address></Address>",
                         b"<Address>HOUSE</Address><Address>OTHER</Address>"):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                resolve_network_route(ProjectDocument.from_bytes(raw.replace(b"<TagName>HOUSE</TagName>", identity)),
                                      source_network=254, target_network=253)


@unittest.skipUnless(BIN, "Select CBUS_CMQTTD_BIN for owned loaded routed reconciliation")
class LoadedRoutedReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="loaded-routed-reconcile-")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.server = owned_server("cmqttd", Path(BIN))
        self.port = self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.client = CGateClient("127.0.0.1", self.port, timeout=15,
                                  max_line_bytes=16 * 1024 * 1024)
        self.client.connect()
        self.addCleanup(self.client.close)

    def seed(self, depth=1, name="HOUSE"):
        self.client.command("PROJECT NEW " + name)
        self.client.command("PROJECT USE " + name)
        for offset in range(depth + 1):
            network = 254 - offset
            interface = "Cni 127.0.0.1:1" if offset == 0 else f"Bridge {network + 1}/p/{network}"
            self.client.command(f"DBCREATENET {network} N{network} {interface}")
            tree = ET.fromstring(xml_text(self.client.command(f"DBGETXML //{name}/{network}")))
            if offset < depth:
                bridge = ET.fromstring(unit(f"7c0e0f10-1111-4222-8333-{network:012d}", network - 1,
                                          f"101137.{offset}", "BRIDGE2N"))
                tree.append(bridge)
            if offset == 0:
                tree.append(ET.fromstring(unit(KEEPER, 20, A)))
            if offset == depth:
                moved = ET.fromstring(unit(OID, 255, A))
                ET.SubElement(moved, "UnitName").text = "KEYE1"
                tree.append(moved)
                keeper = ET.fromstring(unit("7c0e0f10-1111-4222-8333-944455556603", 21, "101136.9"))
                keeper.find("Description").text = OID
                tree.append(keeper)
            for entry in tree.findall("Unit"):
                if entry.find("UnitName") is None:
                    ET.SubElement(entry, "UnitName").text = entry.findtext("UnitType")
            self.client.command_document(f"DBSETXML //{name}/{network}", ET.tostring(tree, encoding="unicode"))
        for action in ("SAVE", "CLOSE", "LOAD", "USE"):
            self.client.command(f"PROJECT {action} {name}")
        snapshot = self.directory / f"{name}.xml"
        snapshot.write_text(xml_text(self.client.command("DBGETXML //" + name)), encoding="utf-8")
        return snapshot

    def physical(self, snapshot, depth=1, *, uncertain=False):
        route = ONE if depth == 1 else SIX
        derived, digest = route_from_project(snapshot, source_network=254, target_network=254 - depth)
        self.assertEqual(derived, route)
        with peer(before_responses(route)) as (endpoint, _):
            plan = manager(endpoint).plan(A, 6, route=route, project_sha256=digest)
        journal = self.directory / (snapshot.stem + "-apply.json")
        responses = before_responses(route) + [b"g." + receipt(route, 6, A) + (b"XX\r\n" if uncertain else b"")]
        if not uncertain:
            responses += after_responses(route)
        with peer(responses) as (endpoint, state):
            value = plan.as_dict()
            value["endpoint"] = dict(host=endpoint[0], port=endpoint[1])
            value["before"]["endpoint"] = dict(value["endpoint"])
            plan = SelectedSerialPlan.from_dict(value)
            subject = manager(endpoint)
            binding = dict(project=snapshot, source_network=254, target_network=254 - depth)
            if uncertain:
                with self.assertRaises(SelectedSerialUncertain):
                    subject.apply(plan, recovery_path=journal, **binding)
            else:
                self.assertEqual(subject.apply(plan, recovery_path=journal, **binding).outcome,
                                 "observed_expected_change")
        self.assertEqual(sum(b"FF0F00" in row for row in state["requests"]), 1)
        if not uncertain:
            return journal
        old_journal = journal.read_bytes()
        marker = Path(json.loads(old_journal)["attempt_identity"])
        old_marker = marker.read_bytes()
        original = recovery_binding(journal)
        verified = self.directory / (snapshot.stem + "-verified.json")
        with peer(after_responses(route), port=endpoint[1]):
            result = manager(endpoint).verify(plan, **binding)
            export_verification(verified, original, result)
        self.assertEqual(journal.read_bytes(), old_journal)
        self.assertEqual(marker.read_bytes(), old_marker)
        self.assertFalse(verify_journal(verified).receipt_matches_request)
        self.assertTrue(json.loads(verified.read_text())["verification"]["route_binding"]["topology_fresh_at_handoff"])
        return verified

    def database(self, snapshot, *, exclusive=True):
        return CGateDatabase(self.client, snapshot.stem, endpoint=f"127.0.0.1:{self.port}",
                             route_project=snapshot, exclusive_project=exclusive)

    def test_one_and_six_bridge_loaded_save_reload_backup_and_noop_preserve_whole_project(self):
        for depth in (1, 6):
            with self.subTest(depth=depth):
                snapshot = self.seed(depth, "HOUSE" + str(depth))
                original = ProjectDocument.load(snapshot)
                journal = self.physical(snapshot, depth)
                database = self.database(snapshot)
                plan = reconcile(journal, database)
                self.assertEqual(plan["outcome"], "planned")
                self.assertEqual(plan["unit"]["network"], 254 - depth)
                self.assertFalse(default_record_path(journal).exists())
                result = reconcile(journal, database, apply=True)
                self.assertEqual(result["outcome"], "reconciled")
                self.assertFalse(result["bus_io_performed"])
                current, _ = database.snapshot()
                target = f"/network/{254 - depth}/unit/6"
                self.assertEqual(current.path_of(current.resolve("oid:" + OID)), target)
                current.update(target, {"Address": "255"})
                current.set_parameter(f"/network/{254 - depth}/unit/255", "UnitAddress",
                                      original.parameters(f"/network/{254 - depth}/unit/255")["UnitAddress"])
                self.assertEqual(_project_digest(current), _project_digest(original))
                record = json.loads(default_record_path(journal).read_text())
                self.assertTrue(record["cgate"]["backup_confirmed"])
                self.assertTrue(record["cgate"]["saved_readback_verified"])
                before = default_record_path(journal).read_bytes()
                with patch.object(NativeProjects, "operation", wraps=database.addressing.projects.operation) as operation:
                    again = reconcile(journal, self.database(snapshot), apply=True)
                self.assertEqual(again["outcome"], "already_reconciled")
                self.assertTrue(again["current_database_matches_record"])
                self.assertFalse(any(call.args[0] in ("save", "close", "load", "copy")
                                     for call in operation.call_args_list))
                self.assertEqual(default_record_path(journal).read_bytes(), before)

    def test_routed_uncertain_apply_fresh_handoff_reconciles_without_address_replay(self):
        snapshot = self.seed()
        journal = self.physical(snapshot, uncertain=True)
        self.assertEqual(reconcile(journal, self.database(snapshot), apply=True)["outcome"], "reconciled")

    @unittest.skipUnless(TOOLS_BIN, "Select CBUS_TOOLS_BIN for complete Rust apply-v2 handoff")
    def test_complete_rust_apply_v2_public_cli_reconciles_same_loaded_routed_project(self):
        from tests.test_rust_serial_reconcile import rust_peer, expected_requests
        snapshot = self.seed()
        route, digest = route_from_project(snapshot, source_network=254, target_network=253)
        with peer(before_responses(route)) as (endpoint, _):
            plan = manager(endpoint).plan(A, 6, route=route, project_sha256=digest)
        journal = self.directory / "rust-apply.json"
        with rust_peer(route, False) as (endpoint, state):
            value = plan.as_dict()
            value["endpoint"] = dict(host=endpoint[0], port=endpoint[1])
            value["before"]["endpoint"] = dict(value["endpoint"])
            plan_file = self.directory / "rust-plan.json"
            plan_file.write_text(json.dumps(SelectedSerialPlan.from_dict(value).as_dict()))
            command = [str(Path(TOOLS_BIN).resolve()), "serial-apply", "--pci", f"{endpoint[0]}:{endpoint[1]}",
                       "--plan", str(plan_file), "--project", str(snapshot), "--source-network", "254",
                       "--target-network", "253", "--journal", str(journal), "--timeout", "60"]
            process = subprocess.run(command, capture_output=True, text=True, timeout=90)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(state["errors"], [])
        self.assertEqual(state["moves"], 1)
        self.assertEqual(state["requests"].count(expected_requests(route, False)[2]), 1)
        old_journal = journal.read_bytes()
        marker = Path(json.loads(old_journal)["attempt_identity"])
        old_marker = marker.read_bytes()
        self.assertEqual(json.loads(old_journal)["format"], "cbus-selected-serial-apply-v2")
        self.assertTrue(verify_journal(journal).receipt_matches_request)
        arguments = ["serial-address", "reconcile", "--journal", str(journal), "--cgate",
                     f"127.0.0.1:{self.port}", "--project-name", "HOUSE", "--route-project", str(snapshot),
                     "--exclusive-project"]
        for extra, expected in (([], "planned"), (["--apply"], "reconciled"), (["--apply"], "already_reconciled")):
            output, error = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                code = cli.main(arguments + extra)
            self.assertEqual(code, 0, output.getvalue() + error.getvalue())
            result = json.loads(output.getvalue())
            self.assertEqual(result["outcome"], expected)
            self.assertFalse(result["bus_io_performed"])
        self.assertEqual(journal.read_bytes(), old_journal)
        self.assertEqual(marker.read_bytes(), old_marker)

    def test_pending_unsaved_candidate_requires_explicit_database_only_retry(self):
        snapshot = self.seed()
        journal = self.physical(snapshot)
        database = self.database(snapshot)
        operation = NativeProjects.operation
        saves = 0
        def interrupt(projects, action, name, *args, **kwargs):
            nonlocal saves
            if action == "save" and name == "HOUSE":
                saves += 1
                if saves == 2:
                    raise TimeoutError("target SAVE not sent")
            return operation(projects, action, name, *args, **kwargs)
        with patch.object(NativeProjects, "operation", interrupt), self.assertRaises(ReconcileError):
            reconcile(journal, database, apply=True)
        record = default_record_path(journal)
        self.assertEqual(json.loads(record.read_text())["phase"], "db_pending")
        with self.assertRaisesRegex(ReconcileError, "Saved project remains the original"):
            reconcile(journal, self.database(snapshot), apply=True)
        self.assertEqual(reconcile(journal, self.database(snapshot), apply=True, retry_database=True)["outcome"],
                         "reconciled")

    def test_pending_saved_candidate_recovers_read_only_after_lost_save_reply(self):
        snapshot = self.seed()
        journal = self.physical(snapshot)
        database = self.database(snapshot)
        operation = NativeProjects.operation
        saves = 0
        def interrupt(projects, action, name, *args, **kwargs):
            nonlocal saves
            result = operation(projects, action, name, *args, **kwargs)
            if action == "save" and name == "HOUSE":
                saves += 1
                if saves == 2:
                    raise TimeoutError("target SAVE reply lost")
            return result
        with patch.object(NativeProjects, "operation", interrupt), self.assertRaises(ReconcileError):
            reconcile(journal, database, apply=True)
        def refuse_save(projects, action, name, *args, **kwargs):
            self.assertNotIn(action, ("save", "copy"))
            return operation(projects, action, name, *args, **kwargs)
        with patch.object(NativeProjects, "operation", refuse_save), \
                patch.object(self.client, "command_document", side_effect=AssertionError("DB write replayed")):
            self.assertEqual(reconcile(journal, self.database(snapshot), apply=True)["outcome"], "resumed_complete")

    def test_foreign_loaded_project_pins_and_ownership_refuse_before_write(self):
        snapshot = self.seed()
        journal = self.physical(snapshot)
        for options in ({"network": 254}, {"unit_type": "KEY4"}, {"firmware": "1.0.00"}):
            with self.subTest(options=options), self.assertRaises(ReconcileError):
                reconcile(journal, self.database(snapshot), apply=True, **options)
        with self.assertRaises(ReconcileError):
            reconcile(journal, self.database(snapshot, exclusive=False), apply=True)
        self.client.command("DBSET //HOUSE/253/p/255/Description foreign")
        with patch.object(self.client, "command_document", side_effect=AssertionError("foreign edit overwritten")), \
                self.assertRaises(ReconcileError):
            reconcile(journal, self.database(snapshot), apply=True)
        self.assertFalse(default_record_path(journal).exists())

    def test_record_original_candidate_and_target_bindings_refuse_before_recovery_mutations(self):
        snapshot = self.seed()
        journal = self.physical(snapshot)
        advance = ReconcileRecord.advance
        def interrupt(record, phase, **fields):
            if phase == "db_done":
                raise KeyboardInterrupt
            return advance(record, phase, **fields)
        with patch.object(ReconcileRecord, "advance", interrupt), self.assertRaises(KeyboardInterrupt):
            reconcile(journal, self.database(snapshot), apply=True)
        record_path = default_record_path(journal)
        old_record = record_path.read_bytes()
        mutations = (
            lambda value: value["move"].update(target_network=254),
            lambda value: value["unit"].update(oid=KEEPER),
            lambda value: value["unit"].update(destination_path="//HOUSE/254/p/6"),
            lambda value: value.update(expected_sha256="0" * 64),
            lambda value: value["cgate"].update(before_xml=value["cgate"]["before_xml"].replace("Keep A &amp; B", "foreign")),
            lambda value: value["cgate"].update(expected_project_sha256="0" * 64),
            lambda value: value["cgate"].update(unit_address_after="7"),
            lambda value: value["cgate"].update(backup_readback_sha256="0" * 64),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value = json.loads(old_record)
                mutation(value)
                record_path.write_text(json.dumps(value))
                with patch.object(self.client, "command", wraps=self.client.command) as command, \
                        patch.object(self.client, "command_document", side_effect=AssertionError("tampered record wrote")), \
                        self.assertRaises(ReconcileError):
                    reconcile(journal, self.database(snapshot), apply=True)
                self.assertFalse(any(call.args[0].startswith(("PROJECT SAVE ", "PROJECT CLOSE ", "PROJECT COPY "))
                                     for call in command.call_args_list))
        record_path.write_bytes(old_record)

    def test_completed_python_marker_envelope_rejects_contradictory_values_before_connection(self):
        snapshot = self.seed()
        journal = self.physical(snapshot)
        marker = Path(json.loads(journal.read_text())["attempt_identity"])
        original = marker.read_bytes()
        mutations = (("operation", "verify"), ("send_may_have_occurred", False),
                     ("send_may_have_occurred", 1), ("read_only_recovery_only", False),
                     ("read_only_recovery_only", 1), ("scope", "unknown"),
                     ("scope", "operator_selected_attempt_store"))
        arguments = ["serial-address", "reconcile", "--journal", str(journal), "--cgate", "127.0.0.1:1",
                     "--project-name", "HOUSE", "--route-project", str(snapshot), "--exclusive-project", "--apply"]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                state = json.loads(original)
                state[key] = value
                marker.write_text(json.dumps(state))
                with self.assertRaises(ReconcileError):
                    verify_journal(journal)
                with self.assertRaises(ValueError):
                    recovery_binding(journal)
                output, error = io.StringIO(), io.StringIO()
                with patch("cbus_toolkit.cgate.CGateClient", side_effect=AssertionError("connected")) as client, \
                        redirect_stdout(output), redirect_stderr(error):
                    self.assertEqual(cli.main(arguments), 1)
                client.assert_not_called()
                self.assertFalse(default_record_path(journal).exists())
        marker.write_bytes(original)
        self.assertTrue(verify_journal(journal).receipt_matches_request)

    def test_route_snapshot_changed_after_backup_stops_before_database_write(self):
        snapshot = self.seed()
        journal = self.physical(snapshot)
        database = self.database(snapshot)
        mark = ReconcileRecord.mark_attempted
        def change(record):
            mark(record)
            snapshot.write_bytes(snapshot.read_bytes() + b"<!--changed-->")
        with patch.object(ReconcileRecord, "mark_attempted", change), \
                patch.object(self.client, "command_document", side_effect=AssertionError("changed route written")), \
                self.assertRaises(ReconcileError):
            reconcile(journal, database, apply=True)

    def test_cli_routed_admission_requires_snapshot_and_exclusive_before_connection(self):
        snapshot = self.seed()
        journal = self.physical(snapshot)
        arguments = ["serial-address", "reconcile", "--journal", str(journal),
                     "--cgate", "127.0.0.1:1", "--project-name", "HOUSE", "--apply"]
        for extra, expected in (([], "route-project"), (["--route-project", str(snapshot)], "exclusive-project")):
            output, error = io.StringIO(), io.StringIO()
            with patch("cbus_toolkit.cgate.CGateClient", side_effect=AssertionError("connected")) as client, \
                    redirect_stdout(output), redirect_stderr(error):
                status = cli.main(arguments + extra)
            self.assertEqual(status, 1)
            client.assert_not_called()
            self.assertIn(expected, output.getvalue() + error.getvalue())


if __name__ == "__main__":
    unittest.main()
