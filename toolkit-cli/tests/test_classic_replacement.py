from dataclasses import replace
import os
from pathlib import Path
import struct
import unittest
from uuid import uuid4
from xml.dom import minidom

from cbus_toolkit.classic_replacement import (
    ClassicReplacement, LearnedHistory, ReplacementError, learned_flag,
    _canonical, _document, _field, _set, _digest,
)
from cbus_toolkit.unitspec import UnitSpecStore
from cbus_toolkit.offline_conversion import COPY_PARAMETERS


class PolicyTests(unittest.TestCase):
    def test_frontend_current_original_truth_table(self):
        # Vendor copies when current=False AND original=True. Default target=1,
        # source=0 makes every branch distinguishable.
        for current, original, expected in ((False, False, 1), (False, True, 0),
                                            (True, False, 1), (True, True, 1)):
            with self.subTest(current=current, original=original):
                self.assertEqual(learned_flag("frontend", 0, 1, LearnedHistory(current, original)), expected)

    def test_alternative_policies_are_explicit(self):
        self.assertEqual(learned_flag("preserve_source", 0, 1), 0)
        self.assertEqual(learned_flag("target_default", 0, 1), 1)
        for policy, history in (("frontend", None), ("guessed", None), ("target_default", LearnedHistory(False, True))):
            with self.assertRaises(ValueError): learned_flag(policy, 0, 1, history)
        with self.assertRaises(ValueError): LearnedHistory(0, True)
        with self.assertRaises(ValueError): learned_flag("preserve_source", 2, 1)

    def test_unknown_xml_comments_namespaces_attributes_and_order_are_retained(self):
        source = '<Unit xmlns:x="urn:private" x:extension="v"><OID>old</OID><Description>A &amp; B</Description><!--keep--><x:Opaque p="a"><x:First>1</x:First><x:Second>2</x:Second></x:Opaque></Unit>'
        document = _document(source)
        _set(document, "OID", "new")
        _set(document, "UnitType", "KEY1")
        self.assertEqual(_canonical(source, ("OID", "UnitType")), _canonical(document.toxml(), ("OID", "UnitType")))
        self.assertNotEqual(_digest(source), _digest(document.toxml()))
        lost = source.replace(' x:extension="v"', '')
        self.assertNotEqual(_canonical(source), _canonical(lost))
        reordered = source.replace('<x:First>1</x:First><x:Second>2</x:Second>', '<x:Second>2</x:Second><x:First>1</x:First>')
        self.assertNotEqual(_canonical(source), _canonical(reordered))

    def test_xml_validation_rejects_entities_wrong_root_duplicate_scalar(self):
        for value in ('<!DOCTYPE Unit [<!ENTITY secret SYSTEM "file:///nope">]><Unit/>', '<Network/>'):
            with self.assertRaises(ValueError): _document(value)
        with self.assertRaises(ValueError): _field(_document('<Unit><OID>a</OID><OID>b</OID></Unit>'), "OID")


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_EXE"), "Set CBUS_TOOLKIT_EXE for learned-state source verification")
class LearnedSourceTests(unittest.TestCase):
    def test_original_branch_sequence(self):
        data = Path(os.environ["CBUS_TOOLKIT_EXE"]).read_bytes()
        u16 = lambda n: struct.unpack_from("<H", data, n)[0]
        u32 = lambda n: struct.unpack_from("<I", data, n)[0]
        pe = u32(60); optional = pe + 24; sections = optional + u16(pe + 20); base = u32(optional + 28)
        def at(address, length):
            rva = address - base
            for i in range(u16(pe + 6)):
                offset = sections + i * 40; begin = u32(offset + 12)
                if begin <= rva < begin + max(u32(offset + 8), u32(offset + 16)):
                    raw = u32(offset + 20) + rva - begin
                    return data[raw:raw + length]
            self.fail("Address outside PE sections")
        self.assertEqual(at(0xCC5FD8, 4), bytes.fromhex("84c07511"))  # current true skips copying
        self.assertEqual(at(0xCC5FE9, 4), bytes.fromhex("3c017404"))  # original equals true selects copying
        self.assertEqual(at(0xCC5FED, 6), bytes.fromhex("33c0eb02b001"))
        self.assertEqual(at(0xC9E07C, 12).decode("utf-16le"), "1.2.63")


class FaultClient:
    def __init__(self, client, source, failure):
        self.client, self.source, self.failure = client, source, failure
        self.documents = []
        self.save_count = 0
        self.failed = False

    def command(self, command):
        if command.startswith("PROJECT SAVE "):
            self.save_count += 1
            if self.failure == "saved_promotion" and self.save_count == 2 and not self.failed:
                self.client.command(command)
                self.failed = True
                raise OSError("Simulated error after successful project save")
        if self.failure == "staging" and "DBSETSAFE " in command and "/CatalogNumber " in command and not self.failed:
            self.failed = True
            raise OSError("Simulated staged configuration failure")
        return self.client.command(command)

    def command_document(self, command, document):
        self.documents.append((command, document))
        if self.failure == "unrecoverable" and command == "DBSETXML " + self.source and self.failed:
            raise OSError("Simulated restore connection unavailable")
        if self.failure == "metadata" and command != "DBSETXML " + self.source and not self.failed:
            mutated = _document(document)
            _set(mutated, "Description", "Metadata was dropped by an incompatible backend")
            document = mutated.toxml()
            self.failed = True
        result = self.client.command_document(command, document)
        if command == "DBSETXML " + self.source and self.failure in ("promotion", "unrecoverable") and not self.failed:
            self.failed = True
            raise OSError("Simulated uncertain promotion outcome")
        return result


@unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"), "Set native server and specs for replacement acceptance")
class NativeReplacementTests(unittest.TestCase):
    def setUp(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        self.host = os.environ["CBUS_CGATE_TEST_HOST"]
        self.port = int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        self.client = CGateClient(self.host, self.port, timeout=25)
        self.client.connect()
        self.db = NativeDatabase(self.client)
        self.programmer = Programmer(self.client)
        self.store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        self.project = "R" + uuid4().hex[:7].upper()
        self.backups = []
        self.client.command("PROJECT NEW " + self.project)
        self.db.create_network(self.project, 254, "Replacement_Offline", "Cni", "127.0.0.1:29999")
        self.client.command("PROJECT SAVE " + self.project)
        self.network = f"//{self.project}/254"

    def tearDown(self):
        errors = []
        for project in [self.project, *self.backups]:
            try: self.client.command("PROJECT CLOSE " + project)
            except Exception: pass  # Backups may be persisted but never loaded.
            try: self.client.command("PROJECT DELETE " + project)
            except Exception as error: errors.append(str(error))
        self.client.close()
        if errors: self.fail("Disposable project cleanup failed: " + "; ".join(errors))

    def create_source(self, unit="KEY4", catalog="5034N", address=210):
        from cbus_toolkit.programming import xml_text
        self.db.create_unit(self.network, address, "Original_" + str(address), unit, "1.2.67", catalog_number=catalog)
        path = self.network + "/p/" + str(address)
        self.db.set(path + "/Description", 'A & B <opaque xmlns="urn:metadata" key="x">keep</opaque>')
        self.db.set(path + "/SerialNumber", "ORIGINAL_SERIAL")
        self.db.set(path + "/UnitName", "DB_NAME")
        with self.programmer.load(self.network, "/db" + path) as session:
            for name, value in {"UnitName": "PP_NAME", "JPCommand": "13 11 12 15", "SRCommand": "0 7 1 2",
                                "LPCommand": "4 5 2 0", "LRCommand": "14 14 14 15", "LearnedFlag": "0",
                                "TimerHighByte": "1 2 3 4", "TimerLowByte": "10 20 30 40",
                                "GroupAddress": "11 22 33 44 55 66 77 88"}.items():
                session.set(name, value)
            session.save_to_source()
        self.client.command("PROJECT SAVE " + self.project)
        self.client.command("PROJECT CLOSE " + self.project)
        self.client.command("PROJECT LOAD " + self.project)
        return path, xml_text(self.db.get(path, xml=True))

    def converter(self, source="KEY4", target="KEY1", client=None):
        return ClassicReplacement(client or self.client, self.store.load(source + ".xml"), self.store.load(target + ".xml"))

    def _backup(self):
        name = "B" + uuid4().hex[:7].upper()
        self.backups.append(name)
        return name

    def test_all_nine_pairs_metadata_parameters_backup_and_reopen(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer, xml_text
        units = (("KEY1", "5031N"), ("KEY2", "5032N"), ("KEY4", "5034N"))
        for i, (source_type, source_catalog) in enumerate(units):
            for j, (target_type, target_catalog) in enumerate(units):
                with self.subTest(source=source_type, target=target_type):
                    address = 200 + i * 3 + j
                    path, original = self.create_source(source_type, source_catalog, address)
                    converter = self.converter(source_type, target_type)
                    backup = self._backup()
                    result = converter.replace(path, target_firmware="1.2.67", target_catalog=target_catalog,
                                               target_serial="TARGET_SERIAL", learned_policy="frontend",
                                               learned_history=LearnedHistory(False, True), backup_project=backup)
                    self.assertTrue(result["replaced"])
                    self.assertTrue(result["project_saved"])
                    self.assertNotEqual(result["old_oid"], result["new_oid"])
                    after = converter._xml(path)
                    for name in ("TagName", "Description", "UnitName", "Address"):
                        self.assertEqual(_field(_document(after), name), _field(_document(original), name))
                    self.assertEqual(_field(_document(after), "UnitType"), target_type)
                    self.assertEqual(_field(_document(after), "SerialNumber"), "TARGET_SERIAL")
                    self.client.command("PROJECT LOAD " + backup)
                    saved_original = xml_text(self.db.get(f"//{backup}/254/p/{address}", xml=True))
                    # Project COPY assigns fresh OIDs and changes project identity;
                    # source metadata and all PP values must otherwise survive.
                    self.assertEqual(_field(_document(saved_original), "UnitType"), source_type)
                    self.assertEqual(_field(_document(saved_original), "Description"), _field(_document(original), "Description"))
                    self.client.command("PROJECT CLOSE " + backup)
                    self.client.command("PROJECT CLOSE " + self.project)
                    self.client.command("PROJECT LOAD " + self.project)
                    with CGateClient(self.host, self.port, timeout=25) as fresh:
                        db = NativeDatabase(fresh)
                        self.assertEqual(_field(_document(xml_text(db.get(path, xml=True))), "OID"), result["new_oid"])
                        with Programmer(fresh).load(self.network, "/db" + path) as session:
                            values = session.values()
                            self.assertEqual(int(values["UnitAddress"], 0), address)
                            self.assertEqual(values["UnitName"].strip(), "PP_NAME")
                            self.assertEqual(values["LearnedFlag"], "0")
                            original_pp = {node.getAttribute("Name"): node.getAttribute("Value")
                                           for node in _document(original).getElementsByTagName("PP")}
                            for field in COPY_PARAMETERS:
                                self.assertEqual(values[field], original_pp[field], field)
                            self.assertEqual(session.get_raw_data(50, 8).lines[-1].split("RawData=", 1)[1], "d04eb75ec12ef20f")
                    self.assertEqual(converter._free_address(self.network), 255)

    def test_automatic_backup_and_blank_serial_and_default_learned_policy(self):
        path, _ = self.create_source()
        result = self.converter().replace(path, target_firmware="1.2.67", target_catalog="5031N", learned_policy="target_default")
        self.backups.append(result["backup_project"])
        after = self.converter()._xml(path)
        self.assertEqual(_field(_document(after), "SerialNumber"), "")
        with self.programmer.load(self.network, "/db" + path) as session:
            self.assertEqual(session.values()["LearnedFlag"], "1")

    def test_stale_plan_invalid_catalog_and_forged_plan_fail_before_backup(self):
        path, _ = self.create_source()
        converter = self.converter()
        with self.assertRaises(ValueError):
            converter.plan(path, target_firmware="1.2.67", target_catalog="5034N", learned_policy="preserve_source")
        plan = converter.plan(path, target_firmware="1.2.67", target_catalog="5031N", learned_policy="preserve_source")
        with self.assertRaises(ValueError): converter.apply(replace(plan, learned_value=1))
        self.db.set(path + "/Description", "Changed externally")
        with self.assertRaises(ReplacementError): converter.apply(plan)
        self.assertEqual(self.converter()._free_address(self.network), 255)

    def test_unmodeled_pp_and_oid_references_are_rejected_without_replacement(self):
        path, original = self.create_source()
        converter = self.converter()
        document = _document(original)
        parameter = document.createElement("PP")
        parameter.setAttribute("Name", "FutureParameter")
        parameter.setAttribute("Value", "opaque")
        document.documentElement.appendChild(parameter)
        self.client.command_document("DBSETXML " + path, document.toxml())
        self.assertIn("FutureParameter", converter._xml(path))
        with self.assertRaises(ValueError):
            converter.plan(path, target_firmware="1.2.67", target_catalog="5031N", learned_policy="preserve_source")
        self.client.command_document("DBSETXML " + path, original)
        self.db.set(path + "/Description", "Reference " + _field(_document(original), "OID"))
        with self.assertRaises(ValueError):
            converter.plan(path, target_firmware="1.2.67", target_catalog="5031N", learned_policy="preserve_source")
        self.assertEqual(converter._free_address(self.network), 255)

    def test_failed_staging_keeps_original_and_removes_stage(self):
        self._fault_case("staging")

    def test_metadata_loss_is_detected_before_source_promotion(self):
        self._fault_case("metadata")

    def test_unrecoverable_rollback_reports_backup_and_retains_recovery_details(self):
        path, original = self.create_source()
        backup = self._backup()
        fault = FaultClient(self.client, path, "unrecoverable")
        with self.assertRaises(ReplacementError) as ctx:
            self.converter(client=fault).replace(path, target_firmware="1.2.67", target_catalog="5031N",
                                                learned_policy="preserve_source", backup_project=backup)
        self.assertEqual(ctx.exception.details["backup_project"], backup)
        self.assertTrue(ctx.exception.details["rollback_errors"])
        # Independently restore this disposable fixture after the simulated
        # connection becomes available again, including its original identity.
        self.client.command_document("DBSETXML " + path, original)
        self.client.command("PROJECT SAVE " + self.project)
        self.assertEqual(_canonical(self.converter()._xml(path)), _canonical(original))

    def test_uncertain_promotion_rolls_back_exact_original_oid_xml_and_parameters(self):
        self._fault_case("promotion")

    def test_failure_after_project_save_restores_and_persists_original(self):
        self._fault_case("saved_promotion")

    def _fault_case(self, failure):
        path, original = self.create_source()
        fault = FaultClient(self.client, path, failure)
        backup = self._backup()
        with self.assertRaises(ReplacementError) as ctx:
            self.converter(client=fault).replace(path, target_firmware="1.2.67", target_catalog="5031N",
                                                learned_policy="preserve_source", backup_project=backup)
        self.assertEqual(ctx.exception.details["backup_project"], backup)
        self.assertFalse(ctx.exception.details["rollback_errors"], ctx.exception.details)
        self.assertTrue(fault.failed)
        self.client.command("PROJECT CLOSE " + self.project)
        self.client.command("PROJECT LOAD " + self.project)
        self.assertEqual(_canonical(self.converter()._xml(path)), _canonical(original))
        self.assertEqual(self.converter()._free_address(self.network), 255)
        if failure in ("staging", "metadata"):
            self.assertFalse(any(command == "DBSETXML " + path for command, _ in fault.documents))


if __name__ == "__main__": unittest.main()
