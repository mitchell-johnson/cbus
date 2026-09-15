"""Catalogue selection and offline-guard tests; native evidence lives in the report."""
import importlib.util
import json
import sys
from unittest import mock
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "research/verify_catalog.py"
spec = importlib.util.spec_from_file_location("verify_catalog", SCRIPT)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class VerifyCatalogTests(unittest.TestCase):
    def write_catalog(self, directory):
        path = Path(directory) / "catalog.xml"
        path.write_text('''<CBusUnits><Units>
          <Unit><CatalogNumber>A</CatalogNumber><FirmwareRevisions>
            <Revision><UnitType>KEY1</UnitType><MinVersion>1.0</MinVersion><MaxVersion>1.9</MaxVersion><IsDefault>true</IsDefault></Revision>
            <Revision><UnitType>KEY1</UnitType><MinVersion>2.0</MinVersion><MaxVersion>2.0</MaxVersion></Revision>
          </FirmwareRevisions></Unit>
          <Unit><CatalogNumber>A</CatalogNumber><FirmwareRevisions>
            <Revision><UnitType>KEY1</UnitType><MinVersion>1.0</MinVersion><MaxVersion>1.9</MaxVersion><IsDefault>true</IsDefault></Revision>
          </FirmwareRevisions></Unit>
          <Unit><CatalogNumber>B</CatalogNumber><FirmwareRevisions>
            <Revision><UnitType>KEY2</UnitType><MinVersion>3.0</MinVersion><MaxVersion>3.0</MaxVersion></Revision>
          </FirmwareRevisions></Unit>
          </Units></CBusUnits>''')
        return path

    def test_default_deduplication_preserves_source_revisions_and_missing_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            cases, metadata = verify.load_cases(self.write_catalog(directory))
        self.assertEqual(len(cases), 1)
        self.assertEqual(len(cases[0]["sources"]), 2)
        self.assertEqual(cases[0]["firmware"], "1.0")
        self.assertEqual(metadata["unit_entries"], 3)
        self.assertEqual(metadata["revision_entries"], 4)
        self.assertEqual(metadata["unit_entries_without_default"], [{"unit_index": 2, "catalog_number": "B", "revision_count": 1}])

    def test_full_and_boundary_modes_select_explicit_firmware_points(self):
        with tempfile.TemporaryDirectory() as directory:
            cases, metadata = verify.load_cases(self.write_catalog(directory), all_revisions=True, boundaries=True)
        self.assertEqual({(case["unit_type"], case["firmware"], case["catalog_number"]) for case in cases},
                         {("KEY1", "1.0", "A"), ("KEY1", "1.9", "A"), ("KEY1", "2.0", "A"), ("KEY2", "3.0", "B")})
        self.assertEqual(metadata["firmware_selection"], "minimum and maximum boundaries")
        self.assertEqual(len({case["id"] for case in cases}), 4)

    def test_offline_guard_rejects_physical_and_unowned_commands_before_send(self):
        class Client:
            def __init__(self):
                self.sent = []

            def command(self, command):
                self.sent.append(command)
                return None
        client = Client()
        audit = verify.OfflineAuditClient(client)
        for command in ("NET OPEN //CATTEST/254", "ON //CATTEST/254/56/1", "PROJECT USE HOME",
                        "DBSET //HOME/Description changed", "PP SAVE cat_test //CATTEST/254/p/1",
                        "PP LOAD cat_test //CATTEST/254/p/1", "PP LOCK cat_test //HOME/254",
                        "PP START unrelated unrelated_lock"):
            with self.subTest(command=command), self.assertRaises(RuntimeError):
                audit.command(command)
        self.assertEqual(client.sent, [])
        audit.command("PP NEW cat_test KEY1 1.2.67 5031N")
        audit.command("PP RESET_TO_DEFAULTS cat_test")
        self.assertEqual(len(client.sent), 2)

    def test_parallel_network_guards_do_not_allow_other_workers_locks(self):
        class Client:
            def command(self, command):
                return command
        audit = verify.OfflineAuditClient(Client(), network=250)
        self.assertEqual(audit.command("PP LOCK cat_test //CATTEST/250"), "PP LOCK cat_test //CATTEST/250")
        with self.assertRaises(RuntimeError):
            audit.command("PP LOCK cat_test //CATTEST/251")
        with self.assertRaises(ValueError):
            verify.OfflineAuditClient(Client(), network=249)

    def test_checkpoint_does_not_count_unrun_or_rejected_cases_as_pass(self):
        report = {"cases": [{"id": "a", "result": {"status": "pass"}},
                            {"id": "b", "result": {"status": "vendor_catalog_rejected"}},
                            {"id": "c"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.json"
            verify.checkpoint(path, report)
            saved = json.loads(path.read_text())
        self.assertEqual(saved["summary"]["completed"], 2)
        self.assertEqual(saved["summary"]["not_run"], 1)
        self.assertFalse(saved["summary"]["all_selected_cases_passed"])
        self.assertEqual(saved["summary"]["status_counts"]["pass"], 1)

    def test_summary_keeps_failed_alternatives_excluded_and_pending_cases_unrun(self):
        module_spec = importlib.util.spec_from_file_location("summarize_catalog", SCRIPT.with_name("summarize_catalog.py"))
        module = importlib.util.module_from_spec(module_spec)
        with mock.patch.dict(sys.modules, {"verify_catalog": verify}):
            module_spec.loader.exec_module(module)
        catalog = {"sha256": "same-catalogue", "unit_entries": 4, "revision_entries": 4,
                   "declared_default_revisions": 4, "unit_entries_without_default": [], "unit_entries_with_multiple_defaults": []}
        defaults = {"catalog": catalog, "cases": [
            {"id": "pass", "result": {"status": "pass", "parameter_count": 3}},
            {"id": "alternate", "result": {"status": "vendor_catalog_rejected"}},
            {"id": "excluded", "result": {"status": "vendor_catalog_rejected"}}, {"id": "pending"}],
            "summary": {"selected": 4, "completed": 3, "not_run": 1, "status_counts": {"pass": 1, "vendor_catalog_rejected": 2}}}
        diagnostics = {"catalog_sha256": "same-catalogue", "greeting": "201 C-Gate fixture", "cases": [
            {"id": "alternate", "status": "alternative_roundtrip_pass"},
            {"id": "excluded", "status": "alternative_failed", "error": {"message": "Missing specification"}}], "summary": {}}
        result = module.summarize(defaults, diagnostics, None)
        self.assertEqual(result["combined_default_workflows"]["verified_cases"], 2)
        self.assertEqual(result["combined_default_workflows"]["excluded_cases"], 1)
        self.assertEqual(result["combined_default_workflows"]["not_run"], 1)
        self.assertFalse(result["combined_default_workflows"]["all_selected_cases_passed"])
        self.assertEqual(result["excluded_default_cases"][0]["id"], "excluded")
        self.assertEqual(result["default_new_workflow"]["successful_parameter_comparisons"], 3)
        diagnostics["catalog_sha256"] = "different-catalogue"
        with self.assertRaises(ValueError):
            module.summarize(defaults, diagnostics, None)

    def test_diagnostic_guard_rejects_live_load_and_foreign_units(self):
        module_spec = importlib.util.spec_from_file_location("diagnose_catalog", SCRIPT.with_name("diagnose_catalog.py"))
        module = importlib.util.module_from_spec(module_spec)
        with mock.patch.dict(sys.modules, {"verify_catalog": verify}):
            module_spec.loader.exec_module(module)
        class Client:
            def command(self, command):
                return command
        client = module.DiagnosticClient(Client())
        self.assertEqual(client.command("PP LOAD catdiag_test /db//CATDIAG/254/p/240"), "PP LOAD catdiag_test /db//CATDIAG/254/p/240")
        for command in ("PP LOAD catdiag_test //CATDIAG/254/p/240", "PP SAVE catdiag_test /db//CATDIAG/254/p/240",
                        "DBDELETE //CATDIAG/254/p/241", "DBDELETE //HOME/254/p/240", "NET OPEN //CATDIAG/254"):
            with self.subTest(command=command), self.assertRaises(RuntimeError):
                client.command(command)

    def test_entities_and_wrong_catalogue_roots_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.xml"
            for source in ('<!DOCTYPE CBusUnits [<!ENTITY x SYSTEM "file:///etc/passwd">]><CBusUnits/>', '<Units/>'):
                path.write_text(source)
                with self.assertRaises(ValueError):
                    verify.load_cases(path)


if __name__ == "__main__":
    unittest.main()
