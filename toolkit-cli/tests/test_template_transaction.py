"""Native UnitTemplate copy/default transactions and failure boundaries."""
import copy
import unittest
import xml.etree.ElementTree as ET

from cbus_toolkit.template_transaction import (
    NativeTemplateTransaction,
    PRESERVED_PARAMETERS,
    UnitTemplateTransactionError,
)
from cbus_toolkit.unit_templates import PARAMETERS, PROFILES, UnitTemplates
from test_unit_templates import fixture


class Reply:
    def __init__(self, text):
        self.lines = ("347-" + text, "344 End XML")


class Session:
    def __init__(self, programmer, path):
        self.programmer = programmer
        self.path = path
        record = programmer.records[path]
        self.spec = record["spec"]
        self.unit_type = record["unit_type"]
        self.firmware = record["firmware"]
        self.catalog_number = record["catalog_number"]
        self.current = copy.deepcopy(record["values"])
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        return False

    def values(self):
        return copy.deepcopy(self.current)

    def info(self, _name):
        root = ET.Element("Parameters")
        for parameter in self.spec.parameters.values():
            node = ET.SubElement(root, "Param")
            for key, value in parameter.fields.items():
                ET.SubElement(node, key).text = value
        return Reply(ET.tostring(root, encoding="unicode"))

    def set(self, name, value):
        self.current[name] = value
        if self.programmer.change_identity_during_stage:
            self.current["UnitAddress"] = "99"

    def save_to_source(self):
        self.programmer.save_attempts += 1
        failure = self.programmer.save_failure
        if failure is not None and self.programmer.persist_before_failure:
            self.programmer.records[self.path]["values"] = copy.deepcopy(self.current)
        if failure is not None:
            raise failure
        self.programmer.records[self.path]["values"] = copy.deepcopy(self.current)
        return object()


class Programmer:
    def __init__(self, records):
        self.records = records
        self.loads = []
        self.save_attempts = 0
        self.save_failure = None
        self.persist_before_failure = False
        self.change_identity_during_stage = False

    def load(self, lock, path):
        self.loads.append((lock, path))
        return Session(self, path)


def record(spec, values, *, unit_type="KEY4", catalog_number="5034N"):
    return {
        "spec": spec,
        "unit_type": unit_type,
        "firmware": "1.2.67",
        "catalog_number": catalog_number,
        "values": copy.deepcopy(values),
    }


class NativeTemplateTransactionTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.templates = UnitTemplates(self.spec)
        self.source = "/db//TEST/254/p/20"
        self.destination = "/db//TEST/254/p/21"
        identities = {
            "CUSTYPE": "71",
            "EEPROMChecksumActive": "1",
            "EEPROMLevelRecall": "0",
            "LearnedFlag": "1",
            "NetworkAddress": "254",
            "PatchEnable": "0 0",
            "Project": "TEST",
            "SerialNo": "TARGET-SERIAL",
            "State": "ok",
            "UnitAddress": "21",
        }
        source = dict(
            self.spec.defaults(),
            UnitName="SOURCE",
            GroupAddress="1 2 3 4 5 6 7 8",
            JPCommand="13 15 11 0",
        )
        target = dict(
            self.spec.defaults(),
            UnitName="TARGET",
            GroupAddress="8 7 6 5 4 3 2 1",
            JPCommand="0 0 0 0",
            **identities,
        )
        self.programmer = Programmer(
            {
                self.source: record(self.spec, source),
                self.destination: record(self.spec, target),
            }
        )
        self.transaction = NativeTemplateTransaction(
            self.programmer, self.templates, "//TEST/254"
        )
        self.identities = identities

    def test_copy_stages_saves_once_reloads_and_preserves_every_declared_value(self):
        result = self.transaction.copy(self.source, self.destination)
        self.assertEqual(result["state"], "verified_saved")
        self.assertTrue(result["complete"])
        self.assertTrue(result["staged_verified"])
        self.assertTrue(result["save_confirmed"])
        self.assertTrue(result["reload_verified"])
        self.assertFalse(result["save_outcome_uncertain"])
        self.assertFalse(result["physical_hardware_verified"])
        self.assertFalse(result["project_file_saved"])
        self.assertEqual(result["template_parameter_count"], 26)
        self.assertEqual(result["preserved_parameters"], list(PRESERVED_PARAMETERS))
        self.assertEqual(self.programmer.save_attempts, 1)
        self.assertEqual(
            self.programmer.loads,
            [
                ("//TEST/254", self.source),
                ("//TEST/254", self.destination),
                ("//TEST/254", self.destination),
            ],
        )
        actual = self.programmer.records[self.destination]["values"]
        expected = self.programmer.records[self.source]["values"]
        for name in PARAMETERS:
            self.assertEqual(actual[name], expected[name], name)
        for name, value in self.identities.items():
            self.assertEqual(actual[name], value, name)

    def test_copy_preview_discards_staging_and_performs_no_save_or_reload(self):
        before = copy.deepcopy(self.programmer.records[self.destination]["values"])
        result = self.transaction.copy(
            self.source, self.destination, dry_run=True
        )
        self.assertEqual(result["state"], "previewed")
        self.assertTrue(result["complete"])
        self.assertTrue(result["staged_verified"])
        self.assertFalse(result["save_attempted"])
        self.assertFalse(result["reload_attempted"])
        self.assertEqual(self.programmer.save_attempts, 0)
        self.assertEqual(self.programmer.records[self.destination]["values"], before)

    def test_template_defaults_reset_only_selected_fields_and_verifies_reload(self):
        result = self.transaction.reset_template_defaults(self.destination)
        self.assertEqual(result["operation"], "reset-template-defaults")
        self.assertTrue(result["reload_verified"])
        actual = self.programmer.records[self.destination]["values"]
        defaults = self.spec.defaults()
        for name in PARAMETERS:
            self.assertEqual(actual[name], defaults[name], name)
        for name, value in self.identities.items():
            self.assertEqual(actual[name], value, name)

    def test_all_three_profiles_have_the_same_bounded_transaction_shape(self):
        for unit_type, profile in PROFILES.items():
            with self.subTest(unit_type=unit_type):
                spec = fixture(unit_type)
                templates = UnitTemplates(spec)
                source = dict(spec.defaults(), UnitName="SOURCE")
                target = dict(spec.defaults(), UnitName="TARGET", UnitAddress="21")
                programmer = Programmer(
                    {
                        self.source: record(
                            spec, source, unit_type=unit_type, catalog_number=profile[2]
                        ),
                        self.destination: record(
                            spec, target, unit_type=unit_type, catalog_number=profile[2]
                        ),
                    }
                )
                result = NativeTemplateTransaction(
                    programmer, templates, "//TEST/254"
                ).copy(self.source, self.destination)
                self.assertTrue(result["complete"])
                self.assertEqual(result["profile"]["unit_type"], unit_type)
                self.assertEqual(
                    programmer.records[self.destination]["values"]["UnitName"],
                    "SOURCE",
                )

    def test_profile_failure_and_preservation_failure_stop_before_save(self):
        self.programmer.records[self.source]["unit_type"] = "KEY2"
        with self.assertRaises(UnitTemplateTransactionError) as mismatch:
            self.transaction.copy(self.source, self.destination)
        self.assertEqual(mismatch.exception.evidence["state"], "reading_source")
        self.assertEqual(self.programmer.save_attempts, 0)

        self.programmer.records[self.source]["unit_type"] = "KEY4"
        self.programmer.change_identity_during_stage = True
        with self.assertRaises(UnitTemplateTransactionError) as changed:
            self.transaction.copy(self.source, self.destination)
        self.assertEqual(changed.exception.evidence["state"], "staging_destination")
        self.assertFalse(changed.exception.evidence["save_attempted"])
        self.assertEqual(self.programmer.save_attempts, 0)

    def test_uncertain_save_is_never_retried_or_reloaded(self):
        self.programmer.save_failure = OSError("lost save reply")
        self.programmer.persist_before_failure = True
        with self.assertRaises(UnitTemplateTransactionError) as raised:
            self.transaction.copy(self.source, self.destination)
        evidence = raised.exception.evidence
        self.assertEqual(evidence["state"], "saving_destination")
        self.assertTrue(evidence["save_attempted"])
        self.assertFalse(evidence["save_confirmed"])
        self.assertTrue(evidence["save_outcome_uncertain"])
        self.assertFalse(evidence["reload_attempted"])
        self.assertEqual(self.programmer.save_attempts, 1)
        self.assertEqual(len(self.programmer.loads), 2)

    def test_interruption_identity_and_evidence_are_preserved(self):
        interruption = KeyboardInterrupt()
        self.programmer.save_failure = interruption
        with self.assertRaises(KeyboardInterrupt) as raised:
            self.transaction.copy(self.source, self.destination)
        self.assertIs(raised.exception, interruption)
        evidence = raised.exception.unit_template_transaction_evidence
        self.assertTrue(evidence["save_outcome_uncertain"])
        self.assertEqual(self.programmer.save_attempts, 1)

    def test_paths_lock_and_source_destination_are_rejected_before_io(self):
        cases = (
            ("not-a-db-path", self.destination, "//TEST/254"),
            (self.source, "/db//TEST/300/p/1", "//TEST/254"),
            (self.source, "/db//OTHER/254/p/21", "//TEST/254"),
            (self.source, self.source, "//TEST/254"),
            (self.source, self.source.replace("/db/", "/DB/"), "//TEST/254"),
        )
        for source, destination, lock in cases:
            with self.subTest(source=source, destination=destination):
                programmer = Programmer(self.programmer.records)
                transaction = NativeTemplateTransaction(
                    programmer, self.templates, lock
                )
                with self.assertRaises(ValueError):
                    transaction.copy(source, destination)
                self.assertEqual(programmer.loads, [])


if __name__ == "__main__":
    unittest.main()
