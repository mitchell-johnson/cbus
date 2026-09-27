"""Toolkit XML template CLI and preserved destination identity."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from cbus_toolkit import cli
from cbus_toolkit.template_transaction import UnitTemplateTransactionError


class UnitTemplateCLITests(unittest.TestCase):
    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    @unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"),
                         "Set native C-Gate and specifications for classic template CLI profiles")
    def test_explicit_classic_profiles_and_mismatched_type_guard(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        project = "TP" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        base = ("cgate", "--host", host, "--port", port, "unit", "--lock-address", network)
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            folder = Path(folder)
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            projects.operation("save", project)
            try:
                database.create_network(project, 254, "Profiles", "Cni", "127.0.0.1:29999")
                for number in (1, 2):
                    name, catalog = "KEY" + str(number), "503" + str(number) + "N"
                    database.create_unit(network, number, name, name, "1.2.67", catalog_number=catalog)
                    args = (*base, "--source", "/db" + network + "/p/" + str(number))
                    snapshot, template = folder / (name + ".json"), folder / (name + ".xml")
                    result = self.cli(*args, "template-export", template, "--profile", name)
                    self.assertEqual((result["unit_type"], result["tested_catalog_number"]), (name, catalog))
                    self.cli(*args, "export", snapshot)
                    offline = folder / (name + "-offline.xml")
                    self.cli("unit-templates", "export", snapshot, offline, "--profile", name)
                    self.assertEqual(offline.read_bytes(), template.read_bytes())
                    applied = self.cli(*args, "template-import", template, "--profile", name)
                    self.assertTrue(applied["saved"])
                    self.assertFalse(applied["changed_parameters"])
                target = (*base, "--source", "/db" + network + "/p/2")
                original = self.cli(*target, "show")
                error = self.cli(*target, "template-import", folder / "KEY1.xml", "--profile", "KEY2", status=1)
                self.assertIn("type", error["error"].lower())
                self.assertEqual(self.cli(*target, "show"), original)
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)

    @unittest.skipUnless(os.environ.get("CBUS_CGATE_TEST_HOST") and os.environ.get("CBUS_UNITSPEC_DIR"),
                         "Set native C-Gate and specifications for template CLI acceptance")
    def test_template_xml_export_offline_agreement_import_preview_save_reload_and_crc_rejection(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer
        project = "TC" + uuid4().hex[:6].upper()
        network = "//" + project + "/254"
        host, port = os.environ["CBUS_CGATE_TEST_HOST"], int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        base = ("cgate", "--host", host, "--port", port, "unit", "--lock-address", network)
        source = (*base, "--source", "/db" + network + "/p/20")
        target = (*base, "--source", "/db" + network + "/p/21")
        with tempfile.TemporaryDirectory() as folder, CGateClient(host, port, timeout=30) as client:
            folder = Path(folder)
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation("new", project)
            projects.operation("save", project)
            try:
                database.create_network(project, 254, "Template_CLI", "Cni", "127.0.0.1:29999")
                for address in (20, 21):
                    database.create_unit(network, address, "Key" + str(address), "KEY4", "1.2.67", catalog_number="5034N")
                with Programmer(client).load(network, "/db" + network + "/p/20") as session:
                    session.set("UnitName", "SCENE_A")
                    session.set("GroupAddress", "12 24 25 27 255 255 255 255")
                    session.set("LightLevelStore1", "64 127 200 255")
                    session.save_to_source()
                original = self.cli(*target, "show")
                native_xml, offline_xml, snapshot = folder / "native.xml", folder / "offline.xml", folder / "source.json"
                exported = self.cli(*source, "template-export", native_xml, "--description", "Key template")
                self.assertEqual(exported["unit_type"], "KEY4")
                self.cli(*source, "export", snapshot)
                self.cli("unit-templates", "export", snapshot, offline_xml, "--description", "Key template")
                self.assertEqual(offline_xml.read_bytes(), native_xml.read_bytes())
                self.assertIn(b"\r\n", native_xml.read_bytes())
                inspected = self.cli("unit-templates", "inspect", native_xml)
                self.assertEqual(inspected["crc"], exported["crc"])
                self.assertEqual(inspected["attributes"]["GroupAddress"], "12 24 25 27 255 255 255 255")
                before_file = native_xml.read_bytes()
                self.cli(*source, "template-export", native_xml, status=1)
                self.assertEqual(native_xml.read_bytes(), before_file)
                preview = self.cli(*target, "--dry-run", "template-import", native_xml)
                self.assertFalse(preview["saved"])
                self.assertTrue(preview["verified"])
                self.assertEqual(self.cli(*target, "show"), original)
                saved = self.cli(*target, "template-import", native_xml)
                self.assertTrue(saved["saved"])
                self.assertEqual(saved["parameters"], preview["parameters"])
                self.assertEqual(saved["parameters"]["UnitName"].rstrip(), "SCENE_A")
                for key in ("UnitAddress", "NetworkAddress", "Project", "PatchEnable", "LearnedFlag"):
                    self.assertEqual(saved["parameters"][key], original[key])
                for operation in ("save", "close", "load"):
                    projects.operation(operation, project)
                self.assertEqual(self.cli(*target, "show"), saved["parameters"])
                broken = folder / "corrupt.xml"
                broken.write_bytes(before_file.replace(b"SCENE_A", b"SCENE_B"))
                error = self.cli(*target, "template-import", broken, status=1)
                self.assertIn("CRC mismatch", error["error"])
                self.assertEqual(self.cli(*target, "show"), saved["parameters"])
                error = self.cli(*target, "--destination", network + "/p/21", "template-import", native_xml, status=1)
                self.assertIn("database destinations only", error["error"])
            finally:
                projects.operation("close", project)
                projects.operation("delete", project)


class UnitTemplateTransactionCLITests(unittest.TestCase):
    def arguments(self, *tail):
        return cli.build_parser().parse_args(
            [
                "cgate",
                "unit",
                "--lock-address",
                "//TEST/254",
                "--source",
                "/db//TEST/254/p/20",
                *tail,
            ]
        )

    def test_copy_and_default_commands_dispatch_complete_native_transactions(self):
        calls = []

        class Transaction:
            def __init__(self, programmer, templates, lock):
                calls.append(("init", programmer, templates, lock))

            def copy(self, source, destination, **options):
                calls.append(("copy", source, destination, options))
                return {"operation": "copy", "complete": True}

            def reset_template_defaults(self, destination, **options):
                calls.append(("reset", destination, options))
                return {"operation": "reset-template-defaults", "complete": True}

        programmer, templates = object(), object()
        with patch("cbus_toolkit.programming.Programmer", return_value=programmer), patch(
            "cbus_toolkit.cli._unit_templates", return_value=templates
        ), patch(
            "cbus_toolkit.template_transaction.NativeTemplateTransaction", Transaction
        ):
            copied = cli._programming(
                self.arguments(
                    "--destination",
                    "/db//TEST/254/p/21",
                    "--dry-run",
                    "template-copy",
                    "--profile",
                    "KEY2",
                ),
                object(),
            )
            reset = cli._programming(
                self.arguments("template-reset-defaults", "--profile", "KEY1"),
                object(),
            )
        self.assertTrue(copied["complete"])
        self.assertTrue(reset["complete"])
        self.assertEqual(
            calls[1],
            (
                "copy",
                "/db//TEST/254/p/20",
                "/db//TEST/254/p/21",
                {"dry_run": True},
            ),
        )
        self.assertEqual(
            calls[3],
            ("reset", "/db//TEST/254/p/20", {"dry_run": False}),
        )

    def test_transaction_surface_guards_fail_before_profile_or_programming_io(self):
        cases = (
            self.arguments("template-copy"),
            self.arguments(
                "--destination",
                "/db//TEST/254/p/21",
                "template-reset-defaults",
            ),
        )
        for arguments in cases:
            with self.subTest(action=arguments.remote_action), patch(
                "cbus_toolkit.programming.Programmer"
            ) as programmer, patch("cbus_toolkit.cli._unit_templates") as templates:
                with self.assertRaises(ValueError):
                    cli._programming(arguments, object())
                programmer.assert_called_once()
                templates.assert_not_called()

    def test_failure_and_interruption_emit_uncertain_transaction_evidence(self):
        evidence = {
            "format": "cbus-native-unit-template-transaction-v1",
            "state": "saving_destination",
            "save_attempted": True,
            "save_confirmed": False,
            "save_outcome_uncertain": True,
            "complete": False,
        }
        arguments = [
            "cgate",
            "unit",
            "--lock-address",
            "//TEST/254",
            "--source",
            "/db//TEST/254/p/20",
            "--destination",
            "/db//TEST/254/p/21",
            "template-copy",
        ]
        error = UnitTemplateTransactionError("lost save reply", evidence)
        for failure, status in ((error, 1), (KeyboardInterrupt(), 130)):
            if isinstance(failure, KeyboardInterrupt):
                failure.unit_template_transaction_evidence = evidence
            with self.subTest(status=status), patch(
                "cbus_toolkit.cgate.CGateClient", return_value=nullcontext(object())
            ), patch("cbus_toolkit.cli._programming", side_effect=failure), redirect_stdout(
                io.StringIO()
            ), redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(cli.main(arguments), status)
                result = json.loads(errors.getvalue())
                self.assertEqual(result["unit_template_transaction_evidence"], evidence)


if __name__ == "__main__":
    unittest.main()
