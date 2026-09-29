"""Reconcile verified selected-serial journals with offline and native databases."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from cbus_toolkit import cli
from cbus_toolkit.project import ProjectDocument
from cbus_toolkit.serial_reconcile import (
    ProjectFileDatabase, ReconcileError, ReconcileRecord, default_record_path, reconcile, verify_journal,
)
from cbus_toolkit.simulator_duplicate_addressing import SerialAddressFault
from tests.test_pci_selected_serial import manager
from tests.test_simulator_duplicate_addressing import A, B, fixture


OID = "0c0e0f10-1111-4222-8333-944455556666"
OTHER = "1c0e0f10-1111-4222-8333-944455556667"
PROJECT = f"""<?xml version="1.0" encoding="utf-8"?>
<Installation><OID>7c0e0f10-1111-4222-8333-944455556600</OID><Project><OID>7c0e0f10-1111-4222-8333-944455556601</OID><TagName>SYNTH</TagName><Address>SYNTH</Address>
<Network><OID>7c0e0f10-1111-4222-8333-944455556602</OID><TagName>Main</TagName><Address>254</Address><NetworkNumber>254</NetworkNumber>
<Interface><OID>7c0e0f10-1111-4222-8333-944455556603</OID><InterfaceType>Cni</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>
<Unit><OID>{OID}</OID><TagName>Mover</TagName><Address>255</Address><UnitType>KEYE1</UnitType><UnitName>KEYE1</UnitName><SerialNumber>101136.1558</SerialNumber><FirmwareVersion>2.5.00</FirmwareVersion><Description>Keep A &amp; B</Description><vendor:Opaque xmlns:vendor="urn:synthetic">kept</vendor:Opaque><PP Name="UnitAddress" Value="0xff"/><PP Name="GroupAddress" Value="0x1 0xff"/></Unit>
<Unit><OID>{OTHER}</OID><TagName>Keeper</TagName><Address>20</Address><UnitType>KEYE1</UnitType><SerialNumber>101136.9</SerialNumber><FirmwareVersion>2.5.00</FirmwareVersion><Partner>{OID}</Partner><PP Name="UnitAddress" Value="20"/></Unit>
</Network></Project></Installation>
"""


def write_project(directory, text=PROJECT, name="site.xml", cbz=False):
    path = Path(directory) / (name if not cbz else "site.cbz")
    if cbz:
        with ZipFile(path, "w") as archive:
            archive.writestr("project.xml", text)
            archive.writestr("attachments/notes.txt", "opaque member")
    else:
        path.write_text(text, encoding="utf-8")
    return path


def run_move(directory, *, fault=None):
    """Drive the existing simulator fixture through serial-address plan/apply."""
    sim = fixture(state_path=Path(directory) / "fixture.json", faults={A: fault} if fault else {})
    journal = Path(directory) / "journal.json"
    with sim.running() as endpoint:
        subject = manager(endpoint)
        result = subject.apply(subject.plan(A, 6), recovery_path=journal)
    return journal, result, sim


class Journals:
    directory = None

    @classmethod
    def get(cls):
        if cls.directory is None:
            cls.directory = tempfile.mkdtemp(prefix="reconcile-journals-")
            (Path(cls.directory) / "moved").mkdir(); (Path(cls.directory) / "unchanged").mkdir()
            cls.moved, result, _ = run_move(Path(cls.directory) / "moved")
            assert result.outcome == "observed_expected_change", result.outcome
            cls.unchanged, result, _ = run_move(Path(cls.directory) / "unchanged", fault=SerialAddressFault(move=False))
            assert result.outcome == "observed_unchanged", result.outcome
        return cls


def tearDownModule():
    if Journals.directory:
        shutil.rmtree(Journals.directory, ignore_errors=True)


def mutated_journal(directory, change):
    value = json.loads(Journals.get().moved.read_text())
    change(value)
    path = Path(directory) / "copy.json"
    path.write_text(json.dumps(value))
    return path


class OfflineReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.journals = Journals.get()
        # Each test owns a copy of the verified journal, so its default record is private.
        self.journal = self.tmp / "journal.json"
        shutil.copyfile(self.journals.moved, self.journal)

    def run_reconcile(self, project, **options):
        return reconcile(self.journal, ProjectFileDatabase(project), **options)

    def assert_moved(self, project, original_text):
        document = ProjectDocument.load(project)
        unit = document.resolve("oid:" + OID)
        self.assertEqual(document.path_of(unit), "/network/254/unit/6")
        self.assertEqual(document.parameters("/network/254/unit/6"),
                         {"UnitAddress": "0x6", "GroupAddress": "0x1 0xff"})
        self.assertEqual(document.get_field("/network/254/unit/20", "Partner"), OID)
        self.assertIn('<vendor:Opaque xmlns:vendor="urn:synthetic">kept</vendor:Opaque>', document.raw_xml())
        # Only the Address field and the PP UnitAddress value differ.
        restored = document.raw_xml().replace("<Address>6</Address>", "<Address>255</Address>").replace(
            'Value="0x6"', 'Value="0xff"')
        self.assertEqual(restored, ProjectDocument.from_bytes(original_text.encode()).raw_xml())

    def test_dry_run_plans_without_writing_then_apply_moves_and_rerun_is_noop(self):
        project = write_project(self.tmp)
        before = project.read_bytes()
        plan = self.run_reconcile(project)
        self.assertEqual(plan["outcome"], "planned")
        self.assertEqual(plan["plan"]["unit_address_after"], "0x6")
        self.assertEqual(plan["plan"]["oid_references"], ["/network/254/unit/20/Partner"])
        self.assertFalse(plan["bus_io_performed"])
        self.assertEqual(project.read_bytes(), before)
        self.assertFalse(default_record_path(self.journal).exists())
        result = self.run_reconcile(project, apply=True)
        self.assertEqual((result["outcome"], result["database_changed"]), ("reconciled", True))
        self.assert_moved(project, PROJECT)
        record = json.loads(default_record_path(self.journal).read_text())
        self.assertEqual(record["phase"], "db_done")
        self.assertEqual([h.get("phase") or h.get("event") for h in record["history"]],
                         ["physical_done", "db_pending", "database_write_attempted", "db_done"])
        self.assertEqual(Path(record["backup"]).read_bytes(), before)
        after = project.read_bytes()
        again = self.run_reconcile(project, apply=True)
        self.assertEqual(again["outcome"], "already_reconciled")
        self.assertTrue(again["current_database_matches_record"])
        self.assertEqual(project.read_bytes(), after)

    def test_cbz_members_are_preserved(self):
        project = write_project(self.tmp, cbz=True)
        self.assertEqual(self.run_reconcile(project, apply=True)["outcome"], "reconciled")
        with ZipFile(project) as archive:
            self.assertEqual(archive.read("attachments/notes.txt"), b"opaque member")
        self.assert_moved(project, PROJECT)

    def test_serial_not_found_ambiguous_and_destination_occupied_refuse_without_record(self):
        cases = {
            "not recorded": PROJECT.replace("101136.1558", "101136.1557"),
            "ambiguous": PROJECT.replace("101136.9", "0101136.1558"),
            "occupied": PROJECT.replace("<Address>20</Address>", "<Address>6</Address>").replace(
                'Value="20"', 'Value="6"'),
            "neither the journal source": PROJECT.replace("<Address>255</Address>", "<Address>7</Address>"),
            "type": PROJECT,
        }
        for message, text in cases.items():
            with self.subTest(message=message):
                project = write_project(self.tmp, text, name=message.replace(" ", "_") + ".xml")
                before = project.read_bytes()
                options = {"unit_type": "KEY4"} if message == "type" else {}
                with self.assertRaisesRegex(ReconcileError, message):
                    self.run_reconcile(project, apply=True, **options)
                self.assertEqual(project.read_bytes(), before)
                self.assertFalse(default_record_path(self.journal).exists())

    def test_database_already_at_destination_is_recorded_without_change(self):
        text = PROJECT.replace("<Address>255</Address>", "<Address>6</Address>").replace('Value="0xff"', 'Value="0x6"')
        project = write_project(self.tmp, text)
        before = project.read_bytes()
        self.assertEqual(self.run_reconcile(project)["outcome"], "database_already_matches")
        result = self.run_reconcile(project, apply=True)
        self.assertEqual((result["outcome"], result["database_changed"]), ("database_already_matches", False))
        self.assertEqual(project.read_bytes(), before)
        self.assertEqual(self.run_reconcile(project, apply=True)["outcome"], "already_reconciled")

    def test_only_observed_expected_change_journals_are_admitted(self):
        project = write_project(self.tmp)
        before = project.read_bytes()
        def tampered_after(value):
            value["after"]["serial_observations"][0]["received_hex"] = value["before"]["serial_observations"][0]["received_hex"]
        cases = {
            "observed_unchanged": lambda v: v.update(json.loads(self.journals.unchanged.read_text())),
            "in progress": lambda v: v.update(state="receipt_collected", after=None, outcome="uncertain"),
            "'uncertain' is not": lambda v: v.update(outcome="uncertain"),
            "observed_unexpected_change": lambda v: v.update(outcome="observed_unexpected_change"),
            "unexpected_changes is inconsistent": lambda v: v.update(unexpected_changes=[{"address": 7}]),
            "tampered or inconsistent": tampered_after,
            "plan is invalid or tampered": lambda v: v["plan"].update(destination=7),
            "unbound": lambda v: v.pop("attempt_identity"),
            "different journal": lambda v: v["journal"].update(path="/elsewhere.json"),
        }
        for message, change in cases.items():
            with self.subTest(message=message):
                journal = mutated_journal(self.tmp, change)
                with self.assertRaisesRegex(ReconcileError, message):
                    reconcile(journal, ProjectFileDatabase(project), apply=True)
                self.assertFalse(default_record_path(journal).exists())
        with self.assertRaisesRegex(ReconcileError, "attempt marker records only"):
            verify_journal(json.loads(self.journals.moved.read_text())["attempt_identity"])
        self.assertEqual(project.read_bytes(), before)

    def test_deleted_attempt_marker_makes_the_journal_stale(self):
        directory = self.tmp / "own"; directory.mkdir()
        journal, result, _ = run_move(directory)
        self.assertEqual(result.outcome, "observed_expected_change")
        Path(result.as_dict()["attempt_identity"]).unlink()
        with self.assertRaisesRegex(ReconcileError, "stale"):
            verify_journal(journal)

    def test_journal_changed_after_reconciliation_started_is_refused(self):
        project = write_project(self.tmp)
        self.run_reconcile(project, apply=True)
        value = json.loads(self.journal.read_text())
        self.journal.write_text(json.dumps(value, indent=1))
        with self.assertRaisesRegex(ReconcileError, "Journal changed after reconciliation started"):
            self.run_reconcile(project, apply=True)

    def test_interrupted_between_save_and_record_resumes_to_db_done(self):
        project = write_project(self.tmp)
        original = ReconcileRecord.advance
        def interrupt(record, phase, **fields):
            if phase == "db_done": raise KeyboardInterrupt
            return original(record, phase, **fields)
        with patch.object(ReconcileRecord, "advance", interrupt), self.assertRaises(KeyboardInterrupt):
            self.run_reconcile(project, apply=True)
        self.assertEqual(json.loads(default_record_path(self.journal).read_text())["phase"], "db_pending")
        saved = project.read_bytes()
        self.assertEqual(self.run_reconcile(project)["outcome"], "resume_pending")
        result = self.run_reconcile(project, apply=True)
        self.assertEqual(result["outcome"], "resumed_complete")
        self.assertEqual(result["record"]["phase"], "db_done")
        self.assertEqual(project.read_bytes(), saved)
        self.assert_moved(project, PROJECT)
        self.assertEqual(self.run_reconcile(project, apply=True)["outcome"], "already_reconciled")

    def test_interrupted_before_save_repeats_the_unstarted_move(self):
        project = write_project(self.tmp)
        with patch.object(ProjectDocument, "save", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.run_reconcile(project, apply=True)
        self.assertEqual(json.loads(default_record_path(self.journal).read_text())["phase"], "db_pending")
        self.assertEqual(self.run_reconcile(project, apply=True)["outcome"], "reconciled")
        self.assert_moved(project, PROJECT)

    def test_pending_record_with_a_changed_database_reports_conflict(self):
        project = write_project(self.tmp)
        with patch.object(ProjectDocument, "save", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.run_reconcile(project, apply=True)
        project.write_text(PROJECT.replace("Keep A &amp; B", "Edited elsewhere"), encoding="utf-8")
        with self.assertRaisesRegex(ReconcileError, "changed while reconciliation was pending"):
            self.run_reconcile(project, apply=True)
        self.assertIn("Edited elsewhere", project.read_text())

    def test_record_for_another_database_is_refused(self):
        first, second = write_project(self.tmp, name="a.xml"), write_project(self.tmp, name="b.xml")
        self.run_reconcile(first, apply=True)
        with self.assertRaisesRegex(ReconcileError, "different database"):
            self.run_reconcile(second, apply=True)


class EndToEndTests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            actual = cli.main(list(map(str, args)))
        self.assertEqual(actual, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def test_simulator_apply_journal_then_cli_reconcile_synthetic_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal, result, sim = run_move(Path(tmp))
            self.assertEqual(result.outcome, "observed_expected_change")
            self.assertEqual((sim.nodes[A].address, sim.nodes[B].address), (6, 255))
            project = write_project(tmp)
            base = ["serial-address", "reconcile", "--journal", journal, "--project", project,
                    "--unit-type", "KEYE1", "--firmware", "2.5.00", "--network", "254"]
            self.assertEqual(self.invoke(base)["outcome"], "planned")
            applied = self.invoke(base + ["--apply"])
            self.assertEqual((applied["outcome"], applied["record"]["phase"]), ("reconciled", "db_done"))
            self.assertEqual(ProjectDocument.load(project).path_of(ProjectDocument.load(project).resolve("oid:" + OID)),
                             "/network/254/unit/6")
            self.assertEqual(self.invoke(base + ["--apply"])["outcome"], "already_reconciled")
            failure = self.invoke(["serial-address", "reconcile", "--journal", journal, "--cgate", "127.0.0.1:1"], 1)
            self.assertIn("--project-name", failure["error"])


@unittest.skipUnless(all(os.environ.get(name) for name in ("CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR")),
                     "Select pinned Java11/vendor for owned original C-Gate reconciliation acceptance")
class NativeReconcileTests(unittest.TestCase):
    def test_native_move_preserves_oid_reference_and_programming_through_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.classic_replacement import _canonical, _document, _field
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer, xml_text
        from cbus_toolkit.serial_reconcile import CGateDatabase
        from research.local_cgate import LocalCGate
        service = LocalCGate(Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"]))
        try:
            projects = service.work / "reconcile-projects"; projects.mkdir()
            config = service.work / "config/C-GateConfig.txt"
            config.write_text(config.read_text() + f"project.default.dir={projects}\n")
            (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
        except BaseException as error:
            service._cleanup_preserving(error)
            raise
        with tempfile.TemporaryDirectory() as tmp, service:
            journal = Path(tmp) / "journal.json"
            shutil.copyfile(Journals.get().moved, journal)
            with CGateClient("127.0.0.1", service.port, timeout=30, max_line_bytes=16 * 1024 * 1024) as client:
                db = NativeDatabase(client)
                client.command("PROJECT NEW RECON"); client.command("PROJECT USE RECON")
                db.create_network("RECON", 254, "Owned", "Cni", "127.0.0.1:1")
                db.create_unit("//RECON/254", 255, "Mover", "KEYE1", "2.5.00", catalog_number="5031NMML")
                db.create_unit("//RECON/254", 20, "Keeper", "KEYE1", "2.5.00", catalog_number="5031NMML")
                db.set("//RECON/254/p/255/SerialNumber", A)
                db.set("//RECON/254/p/255/Description", "Keep A & B")
                oid = _field(_document(xml_text(db.get("//RECON/254/p/255", xml=True))), "OID")
                db.set("//RECON/254/p/20/Description", oid)  # An OID reference from another unit.
                client.command("PROJECT SAVE RECON")
                # Reload first: native loading adds normalized fields such as DeviceName.
                client.command("PROJECT CLOSE RECON"); client.command("PROJECT LOAD RECON")
                client.command("PROJECT USE RECON")
                original = xml_text(db.get("//RECON/254/p/255", xml=True))
                with Programmer(client).load("//RECON/254", "/db//RECON/254/p/255") as session:
                    values = session.values()
                database = CGateDatabase(client, "RECON", endpoint="local")
                self.assertEqual(reconcile(journal, database)["outcome"], "planned")
                result = reconcile(journal, database, apply=True)
                self.assertEqual((result["outcome"], result["record"]["phase"]), ("reconciled", "db_done"))
                backup = result["record"]["backup"]
                client.command("PROJECT CLOSE RECON"); client.command("PROJECT LOAD RECON")
                client.command("PROJECT USE RECON")
            with CGateClient("127.0.0.1", service.port, timeout=30, max_line_bytes=16 * 1024 * 1024) as fresh:
                db = NativeDatabase(fresh)
                moved = xml_text(db.get("//RECON/254/p/6", xml=True))
                self.assertEqual(_field(_document(moved), "OID"), oid)
                self.assertEqual(_canonical(moved, exclude=("Address", "PP")), _canonical(original, exclude=("Address", "PP")))
                self.assertEqual(_field(_document(xml_text(db.get("//RECON/254/p/20", xml=True))), "Description"), oid)
                with Programmer(fresh).load("//RECON/254", "/db//RECON/254/p/6") as session:
                    after = session.values()
                self.assertEqual(int(after["UnitAddress"], 0), 6)
                self.assertEqual({k: v for k, v in after.items() if k != "UnitAddress"},
                                 {k: v for k, v in values.items() if k != "UnitAddress"})
                self.assertIsNotNone(backup)
                again = reconcile(journal, CGateDatabase(fresh, "RECON", endpoint="local"), apply=True)
                self.assertEqual(again["outcome"], "already_reconciled")
                self.assertTrue(again["current_database_matches_record"])


if __name__ == "__main__":
    unittest.main()
