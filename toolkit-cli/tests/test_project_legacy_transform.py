"""Focused portable conversion for four pinned repaired legacy documents."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cbus_toolkit.cli import build_parser, main
from cbus_toolkit.native import NativeProjects
from cbus_toolkit.project_legacy_transform import (
    LegacyProjectTransformError, transform_repaired_legacy_project,
)
from cbus_toolkit.project_legacy_transform_cli import (
    LegacyProjectTransformFileError, LegacyProjectTransformFileOperation,
)
from cbus_toolkit.project_repair import repair_project_xml, transform_project_repair_xml


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SHA = {
    "native": ("project-repair-native-vectors.json", "4249fba21a15c4018b3c3c4d8b4c126697a9c990382c3bf23cec0cc51b3c98da"),
    "encoding": ("project-repair-encoding-vectors.json", "d9512bfdf248f203f7b2e5558eb736eeedd00b1ec208ec2c6230f29b3d533d3c"),
    "dtd": ("project-repair-dtd-vectors.json", "35e2c58d4f08ec2306b914210fa3603407f971daa76d1edbe000f21e0f48c4c7"),
    "xml11": ("project-repair-xml11-vectors.json", "ac0ce71275e85dec2b6f14a075d1e25b3b4142971e91239ad261f1918bcfe75f"),
}
NATIVE_OUTPUT_SHA = {
    "RPMAL": "eb1f52f1020f920cce0417aa517e29fce7d5cb5e827fb057782e7cff5b326b15",
    "FRENC": "013d8f4dffe845a564bd9de2f56231c36f2048ad906f00f519d2a53909cfb5ee",
    "FRDTD": "0bd9a252ab42edc1738349f916f3287fc4ca1fc8373eeb260c33173f8716b853",
    "FRXML11": "eafeea84196d28fb3832f3863b446bf42244c21484f30b52e56837e41e7df224",
}


def digest(data):
    return sha256(data).hexdigest()


def row(kind, case_id):
    file, expected = FIXTURE_SHA[kind]
    raw = (ROOT / "research/fixtures" / file).read_bytes()
    assert digest(raw) == expected
    matching = [entry for entry in json.loads(raw)["rows"] if entry["id"] == case_id]
    assert len(matching) == 1
    return matching[0]


def candidates():
    modern = row("native", "RPMAL")
    assert digest(modern["source_utf8"].encode()) == modern["source_sha256"]
    yield "RPMAL", "RPMAL", repair_project_xml(modern["source_utf8"].encode()).repaired_xml
    for name, kind, case_id in (
        ("FRENC", "encoding", "windows1252-utf8-full"),
        ("FRDTD", "dtd", "one-text-repair"),
        ("FRXML11", "xml11", "c1-text-full"),
    ):
        captured = row(kind, case_id)
        source = bytes.fromhex(captured["input_hex"])
        output = (repair_project_xml(source).repaired_xml if captured["operation"] == "full"
                  else transform_project_repair_xml(source, stage=captured["operation"]))
        assert output == bytes.fromhex(captured["output_hex"])
        yield name, case_id, output


class LegacyTransformTests(unittest.TestCase):
    def test_typed_remote_transform_forwards_observed_default_and_custom_forms(self):
        class RecordingClient:
            def __init__(self):
                self.commands = []

            def command(self, command):
                self.commands.append(command)
                return SimpleNamespace(code=200, final="200 OK.")

        client = RecordingClient()
        project = NativeProjects(client)
        project.operation("transform", "RPMAL", test=True)
        project.operation("transform", "RPMAL")
        project.operation("transform", "RPMAL", test=True,
                          xslt_file="transform/v22tov23.xslt", output_file="/srv/cgate/RPMAL_OUT.xml")
        project.operation("transform", "RPMAL", xslt_file="transform/v22tov23.xslt")
        self.assertEqual(client.commands,
                         ["TRANSFORM PROJECT --test RPMAL", "TRANSFORM PROJECT RPMAL",
                          "TRANSFORM PROJECT --test RPMAL transform/v22tov23.xslt /srv/cgate/RPMAL_OUT.xml",
                          "TRANSFORM PROJECT RPMAL transform/v22tov23.xslt"])
        with self.assertRaises(ValueError):
            project.operation("transform", "bad name")
        with self.assertRaises(ValueError):
            project.operation("repair", "RPMAL", test=True)
        with self.assertRaises(ValueError):
            project.operation("transform", "RPMAL", output_file="/srv/cgate/OUT.xml")
        with self.assertRaises(ValueError):
            project.operation("transform", "RPMAL", xslt_file="evil\nPROJECT DELETE RPMAL")
        with self.assertRaises(ValueError):
            project.operation("repair", "RPMAL", xslt_file="transform/v22tov23.xslt")
        parsed = build_parser().parse_args(["cgate", "project", "transform", "RPMAL", "--test"])
        self.assertEqual((parsed.remote_action, parsed.name, parsed.test), ("transform", "RPMAL", True))
        parsed = build_parser().parse_args(["cgate", "project", "transform", "RPMAL",
                                            "--xslt-file", "transform/v22tov23.xslt",
                                            "--output-file", "/srv/cgate/RPMAL_OUT.xml"])
        self.assertEqual((parsed.xslt_file, parsed.output_file),
                         ("transform/v22tov23.xslt", "/srv/cgate/RPMAL_OUT.xml"))

    def test_four_source_bound_outputs_match_original_bytes(self):
        for name, _, source in candidates():
            with self.subTest(name=name):
                result = transform_repaired_legacy_project(source)
                self.assertEqual(result.as_dict()["source_sha256"], digest(source))
                self.assertEqual(result.as_dict()["output_sha256"], NATIVE_OUTPUT_SHA[name])
                self.assertEqual(result.transformed_xml,
                                 source.replace(b"<DBVersion>2.2</DBVersion>", b"<DBVersion>2.3</DBVersion>")[:-1])
                self.assertEqual(result.project_address, "RPMAL" if name == "RPMAL" else None)
                self.assertFalse(result.as_dict()["native_load_verified"])

    def test_earlier_unitless_versions_have_exact_bounded_conversion(self):
        for original, _, repaired in candidates():
            for version in ("2", "2.1"):
                with self.subTest(original=original, version=version):
                    source = repaired.replace(
                        b"<DBVersion>2.2</DBVersion>", f"<DBVersion>{version}</DBVersion>".encode())
                    converted = transform_repaired_legacy_project(source)
                    self.assertEqual(converted.source_db_version, version)
                    self.assertEqual(converted.as_dict()["source_db_version"], version)
                    self.assertEqual(converted.as_dict()["output_sha256"], NATIVE_OUTPUT_SHA[original])
                    self.assertEqual(converted.transformed_xml,
                                     source.replace(f"<DBVersion>{version}</DBVersion>".encode(),
                                                    b"<DBVersion>2.3</DBVersion>")[:-1])

    def test_earlier_versions_reject_unit_and_programming_elements(self):
        _, _, repaired = next(candidates())
        for version in ("2", "2.1"):
            source = repaired.replace(b"<DBVersion>2.2</DBVersion>",
                                      f"<DBVersion>{version}</DBVersion>".encode())
            for insert in (b"<Unit><UnitType>KEYBL5</UnitType></Unit>",
                           b'<PP Name="Remote3Identity" Value="0xff"/>',
                           b'<cis:Unit xmlns:cis="urn:example"/>'):
                with self.subTest(version=version, insert=insert):
                    candidate = source.replace(b"<Project>", b"<Project>" + insert, 1)
                    with self.assertRaisesRegex(LegacyProjectTransformError, "native XSLT conversion"):
                        transform_repaired_legacy_project(candidate)

    def test_earlier_version_cli_is_exclusive_and_preserves_source(self):
        _, _, repaired = next(candidates())
        source = repaired.replace(b"<DBVersion>2.2</DBVersion>", b"<DBVersion>2.1</DBVersion>")
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "repaired.xml"
            output = Path(directory) / "converted.xml"
            original.write_bytes(source)
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["project", "transform-legacy", str(original), "--output", str(output)])
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(json.loads(stdout.getvalue())["transform"]["source_db_version"], "2.1")
            self.assertEqual(output.read_bytes(), transform_repaired_legacy_project(source).transformed_xml)
            self.assertEqual(original.read_bytes(), source)

    def test_cli_dry_run_and_exclusive_output_preserve_source(self):
        _, _, source = next(candidates())
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "repaired.xml"
            output = Path(directory) / "RPMAL.xml"
            original.write_bytes(source)

            def command(*argv):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main(["project", "transform-legacy", str(original), *map(str, argv)])
                return code, json.loads((stdout if code == 0 else stderr).getvalue())

            code, preview = command("--dry-run")
            self.assertEqual(code, 0)
            self.assertTrue(preview["complete"] and preview["dry_run"])
            self.assertFalse(output.exists())
            code, written = command("--output", output)
            self.assertEqual(code, 0)
            self.assertEqual(output.read_bytes(), transform_repaired_legacy_project(source).transformed_xml)
            self.assertEqual(written["output_bytes_confirmed"], len(output.read_bytes()))
            self.assertEqual(original.read_bytes(), source)
            code, error = command("--output", output)
            self.assertEqual(code, 1)
            self.assertEqual(error["project_legacy_transform_evidence"]["error"]["type"], "FileExistsError")
            self.assertEqual(output.read_bytes(), transform_repaired_legacy_project(source).transformed_xml)
            code, error = command("--output", original)
            self.assertEqual(code, 1)
            self.assertEqual(error["project_legacy_transform_evidence"]["error"]["type"], "FileExistsError")
            self.assertEqual(original.read_bytes(), source)

    def test_unsupported_input_is_rejected_before_output_creation(self):
        _, _, source = next(candidates())
        invalid = (
            source.replace(b"<DBVersion>2.2</DBVersion>", b"<DBVersion>2.3</DBVersion>"),
            source.replace(b"<DBVersion>2.2</DBVersion>", b"<DBVersion> 2.2 </DBVersion>"),
            source.replace(b"<Project>", b"<Project><Address>SECOND</Address>", 1),
            source.replace(b"<Project>", b"<Project><Address>bad name</Address>", 1),
            source.replace(b"<Project>", b"<!DOCTYPE Installation><Project>", 1),
            source[:-1],
        )
        for candidate in invalid:
            with self.subTest(digest=digest(candidate)):
                with self.assertRaises(LegacyProjectTransformError):
                    transform_repaired_legacy_project(candidate)

    def test_open_error_after_exclusive_create_records_uncertain_output(self):
        _, _, source = next(candidates())
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "repaired.xml"
            output = Path(directory) / "RPMAL.xml"
            original.write_bytes(source)
            actual_open = os.open
            attempts = []

            def uncertain_open(path, flags, mode=0o777):
                if Path(path) == output:
                    attempts.append(path)
                    descriptor = actual_open(path, flags, mode)
                    os.close(descriptor)
                    raise OSError("open failed after exclusive create")
                return actual_open(path, flags, mode)

            operation = LegacyProjectTransformFileOperation()
            with patch("cbus_toolkit.project_legacy_transform_cli.os.open", side_effect=uncertain_open):
                with self.assertRaises(LegacyProjectTransformFileError) as caught:
                    operation.run(original, output=output)
            evidence = caught.exception.details
            self.assertEqual(len(attempts), 1)
            self.assertEqual(evidence["stage"], "output_create")
            self.assertTrue(evidence["output_create_attempted"])
            self.assertTrue(evidence["output_may_exist"])
            self.assertFalse(evidence["output_created"])
            self.assertTrue(evidence["output_may_be_partial"])
            self.assertEqual(evidence["output_bytes_confirmed"], 0)
            self.assertEqual(output.read_bytes(), b"")
            self.assertEqual(original.read_bytes(), source)


if __name__ == "__main__":
    unittest.main()
