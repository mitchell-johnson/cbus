"""Opt-in native acceptance for bounded UnitTemplate transactions."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from cbus_toolkit.template_transaction import (
    NativeTemplateTransaction,
    PRESERVED_PARAMETERS,
)
from cbus_toolkit.unit_templates import PROFILES, UnitTemplates
from cbus_toolkit.unitspec import UnitSpecStore


@unittest.skipUnless(
    os.environ.get("CBUS_TEMPLATE_TRANSACTION_TEST_HOST")
    and os.environ.get("CBUS_UNITSPEC_DIR"),
    "Set an owned C-Gate service and specifications for native template transaction acceptance",
)
class UnitTemplateTransactionNativeTest(unittest.TestCase):
    def test_copy_and_template_default_transactions_save_reload_and_preserve(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer

        host = os.environ["CBUS_TEMPLATE_TRANSACTION_TEST_HOST"]
        port = int(os.environ.get("CBUS_TEMPLATE_TRANSACTION_TEST_PORT", "20023"))
        report = {
            "format": "cbus-native-unit-template-transaction-acceptance-v1",
            "scope": "Owned C-Gate-compatible service, closed temporary database units, one PP SAVE and fresh reload per operation; no project-file or physical-device save",
            "profiles": [],
            "passed": False,
            "physical_hardware_verified": False,
            "original_gui_process_verified": False,
        }
        try:
            with CGateClient(host, port, timeout=30) as client:
                report["greeting"] = client.greeting
                for index, (unit_type, firmware, catalog, spec_name) in enumerate(
                    PROFILES.values()
                ):
                    row = {
                        "profile": {
                            "unit_type": unit_type,
                            "firmware": firmware,
                            "catalog_number": catalog,
                            "spec": spec_name,
                        },
                        "copy_save_reload_cases": 0,
                        "defaults_save_reload_cases": 0,
                        "preserved_parameters": [],
                        "passed": False,
                    }
                    report["profiles"].append(row)
                    project = "TT" + uuid4().hex[:6].upper()
                    network = f"//{project}/254"
                    source = network + "/p/" + str(220 + index * 2)
                    target = network + "/p/" + str(221 + index * 2)
                    client.command("PROJECT NEW " + project)
                    try:
                        client.command("PROJECT USE " + project)
                        # Keep the dummy CNI closed. The transaction operates on
                        # database PP state and does not contact a physical bus.
                        client.command(
                            "DBCREATENET 254 Template_Transaction Cni 127.0.0.1:29999"
                        )
                        database = NativeDatabase(client)
                        database.create_unit(
                            network,
                            220 + index * 2,
                            "Template_Source",
                            unit_type,
                            firmware,
                            catalog_number=catalog,
                        )
                        database.create_unit(
                            network,
                            221 + index * 2,
                            "Template_Target",
                            unit_type,
                            firmware,
                            catalog_number=catalog,
                        )
                        programmer = Programmer(client)
                        with programmer.load(network, "/db" + source) as session:
                            session.set("UnitName", "SOURCE")
                            session.set(
                                "GroupAddress", "12 24 25 27 255 255 255 255"
                            )
                            session.save_to_source()
                        with programmer.load(network, "/db" + target) as session:
                            before = session.values()
                            preserved = {
                                name: before[name]
                                for name in PRESERVED_PARAMETERS
                                if name in before
                            }
                        templates = UnitTemplates(
                            UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"]).load(
                                spec_name
                            )
                        )
                        transaction = NativeTemplateTransaction(
                            programmer, templates, network
                        )
                        copied = transaction.copy("/db" + source, "/db" + target)
                        self.assertTrue(copied["reload_verified"])
                        row["copy_save_reload_cases"] = 1
                        with programmer.load(network, "/db" + target) as session:
                            session.set("UnitName", "RESETME")
                            session.save_to_source()
                        reset = transaction.reset_template_defaults("/db" + target)
                        self.assertTrue(reset["reload_verified"])
                        row["defaults_save_reload_cases"] = 1
                        with programmer.load(network, "/db" + target) as session:
                            actual = session.values()
                            self.assertEqual(
                                templates.export(session).attributes,
                                templates.from_values(
                                    templates.spec.defaults()
                                ).attributes,
                            )
                            self.assertEqual(
                                {name: actual[name] for name in preserved}, preserved
                            )
                        row["preserved_parameters"] = sorted(preserved)
                        row["passed"] = True
                    finally:
                        client.command("PROJECT CLOSE " + project)
                        client.command("PROJECT DELETE " + project)
            report["passed"] = all(row["passed"] for row in report["profiles"])
        finally:
            report["copy_save_reload_cases"] = sum(
                row["copy_save_reload_cases"] for row in report["profiles"]
            )
            report["defaults_save_reload_cases"] = sum(
                row["defaults_save_reload_cases"] for row in report["profiles"]
            )
            root = Path(__file__).resolve().parents[1]
            files = (
                "src/cbus_toolkit/template_transaction.py",
                "src/cbus_toolkit/unit_templates.py",
                "src/cbus_toolkit/cli.py",
                "tests/test_template_transaction.py",
                "tests/test_template_transaction_native.py",
                "tests/test_cli_unit_templates.py",
            )
            report["source_hashes"] = {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in files
            }
            if os.environ.get("CBUS_TEMPLATE_TRANSACTION_REPORT"):
                Path(os.environ["CBUS_TEMPLATE_TRANSACTION_REPORT"]).write_text(
                    json.dumps(report, indent=2) + "\n"
                )


if __name__ == "__main__":
    unittest.main()
