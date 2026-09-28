"""Owned original C-Gate migration of unitless repaired DBVersion 2/2.1 XML."""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.native import NativeProjects
from cbus_toolkit.project_legacy_transform import transform_repaired_legacy_project
from cbus_toolkit.repositories import parse_repository_list
from research.local_cgate import JAR_SHA256, LocalCGate
from tests.test_project_legacy_transform import NATIVE_OUTPUT_SHA, candidates, digest
from tests.test_project_legacy_transform_native import JAVA_SHA256


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = (("FRENC", "ENC"), ("FRDTD", "DTD"), ("FRXML11", "X11"))


@unittest.skipUnless(all(os.environ.get(key) for key in ("CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR")),
                     "Select pinned Java11 and original C-Gate for isolated legacy versions")
class LegacyVersionsNativeTests(unittest.TestCase):
    def test_native_2_and_2_1_migration_load_and_unsupported_boundaries(self):
        java = Path(os.environ["CBUS_CGATE_JAVA"])
        vendor = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"])
        self.assertEqual(digest(java.read_bytes()), JAVA_SHA256)
        stylesheet_hashes = {name: digest((vendor / "transform" / name).read_bytes())
                             for name in ("v2tov21.xslt", "v21tov22.xslt", "v22tov23.xslt",
                                          "projectversions.xml")}
        base = {name: data for name, _, data in candidates()}
        service = LocalCGate(vendor, java=java)
        projects = service.work / "legacy-projects"
        supplied = {}
        try:
            projects.mkdir()
            config = service.work / "config/C-GateConfig.txt"
            config.write_text(config.read_text() + f"project.default.dir={projects}\n")
            (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
            for original, label in SAMPLES:
                for version, prefix in (("2", "V2"), ("2.1", "V21")):
                    name = prefix + label
                    source = base[original].replace(
                        b"<DBVersion>2.2</DBVersion>", f"<DBVersion>{version}</DBVersion>".encode())
                    self.assertNotEqual(source, base[original])
                    self.assertEqual(transform_repaired_legacy_project(source).source_db_version, version)
                    (projects / f"{name}.xml").write_bytes(source)
                    supplied[name] = (source, version, original)
            for name, version in (("VBAD1", "1"), ("VBAD24", "2.4")):
                source = base["FRDTD"].replace(
                    b"<DBVersion>2.2</DBVersion>", f"<DBVersion>{version}</DBVersion>".encode())
                (projects / f"{name}.xml").write_bytes(source)
                supplied[name] = (source, version, "FRDTD")
            custom_source = base["FRDTD"]
            (projects / "VCUSTOM.xml").write_bytes(custom_source)
            (projects / "VINLINE.xml").write_bytes(custom_source)
            custom_output = projects / "VOUT.xml"
            custom_output.write_bytes(b"owned-output-sentinel")
        except BaseException as error:
            service._cleanup_preserving(error)
            raise

        findings = []
        custom_finding = None
        with service:
            with CGateClient("127.0.0.1", service.port, timeout=10) as client:
                def request(command, code):
                    try:
                        reply = client.command(command)
                    except CGateError as error:
                        reply = error.response
                    self.assertEqual(reply.code, code, (command, reply.lines))
                    return reply

                listing = parse_repository_list(request("REPOSITORY LIST", 123))
                file_repo, = [repo for repo in listing.repositories if repo.type == "file"]
                self.assertEqual(Path(file_repo.path).resolve(), projects.resolve())
                request(f"REPOSITORY USE {file_repo.index}", 200)

                for name in sorted(supplied):
                    source, version, original = supplied[name]
                    backup = projects / f"{name}.xml.0"
                    staged = projects / f"{name}.xml"
                    with self.subTest(name=name):
                        self.assertFalse(backup.exists())
                        if version in ("2", "2.1"):
                            rejected = request(f"PROJECT LOAD {name}", 408)
                            self.assertIn(f"DBVersion is {version} and must be 2.3", rejected.final)
                            self.assertFalse(backup.exists())
                            preview = request(f"TRANSFORM PROJECT --test {name}", 200)
                            self.assertEqual(preview.lines[0], f"199-current DBVersion is: {version}")
                            self.assertEqual(preview.lines[1], "199-wanted DBVersion is: 2.3")
                            self.assertIn("199-Transform from 2.2 to 2.3 XSLT file: v22tov23.xslt",
                                          preview.lines)
                            if version == "2":
                                self.assertIn("199-Transform from 2 to 2.1 XSLT file: v2tov21.xslt",
                                              preview.lines)
                            self.assertEqual(staged.read_bytes(), source)
                            self.assertEqual(backup.read_bytes(), source)
                            transformed = request(f"TRANSFORM PROJECT {name}", 200)
                            output = staged.read_bytes()
                            portable = transform_repaired_legacy_project(source)
                            self.assertEqual(output, portable.transformed_xml)
                            self.assertEqual(digest(output), NATIVE_OUTPUT_SHA[original])
                            self.assertEqual(backup.read_bytes(), source)
                            request(f"PROJECT LOAD {name}", 200)
                            snippet = request(f"DBGETXML //{name}", 344)
                            root = ET.fromstring("\n".join(
                                line[4:] for line in snippet.lines[1:-1]).encode("utf-8"))
                            self.assertEqual(root.findtext("DBVersion"), "2.3")
                            self.assertEqual(root.findtext("Project/Address"), name)
                            self.assertEqual(root.findtext("Project/TagName"), name)
                            request(f"PROJECT CLOSE {name}", 200)
                            findings.append({"name": name, "source_version": version,
                                "source_sha256": digest(source), "output_sha256": digest(output),
                                "backup_sha256": digest(backup.read_bytes()),
                                "preview": list(preview.lines), "transform": transformed.final,
                                "load_before": rejected.final, "load_after": "200 OK.",
                                "readback_db_version": root.findtext("DBVersion"),
                                "readback_project_address": root.findtext("Project/Address")})
                        else:
                            preview = request(f"TRANSFORM PROJECT --test {name}", 408)
                            self.assertEqual(preview.lines[-1],
                                             "408 Operation failed: Transform failed: No suitable transforms")
                            self.assertEqual(backup.read_bytes(), source)
                            rejected = request(f"TRANSFORM PROJECT {name}", 408)
                            self.assertEqual(rejected.final,
                                             "408 Operation failed: Transform failed: No suitable transforms")
                            self.assertEqual(staged.read_bytes(), source)
                            findings.append({"name": name, "source_version": version,
                                "source_sha256": digest(source), "backup_sha256": digest(backup.read_bytes()),
                                "preview": list(preview.lines), "transform": rejected.final,
                                "source_unchanged": True})

                typed = NativeProjects(client)
                custom_backup = projects / "VCUSTOM.xml.0"
                self.assertFalse(custom_backup.exists())
                preview = typed.operation("transform", "VCUSTOM", test=True,
                    xslt_file="transform/v22tov23.xslt", output_file=str(custom_output))
                self.assertEqual(preview.lines,
                    ("199-Calculated transform list:",
                     "199-Transform with XSLT file: v22tov23.xslt", "200 OK."))
                self.assertEqual((projects / "VCUSTOM.xml").read_bytes(), custom_source)
                self.assertEqual(custom_output.read_bytes(), b"owned-output-sentinel")
                self.assertFalse(custom_backup.exists())
                converted = typed.operation("transform", "VCUSTOM",
                    xslt_file="transform/v22tov23.xslt", output_file=str(custom_output))
                self.assertEqual(converted.lines, ("200 OK.",))
                expected = transform_repaired_legacy_project(custom_source).transformed_xml
                self.assertEqual(custom_output.read_bytes(), expected)
                self.assertEqual((projects / "VCUSTOM.xml").read_bytes(), custom_source)
                self.assertFalse(custom_backup.exists())
                loaded = request("PROJECT LOAD VOUT", 200)
                snippet = request("DBGETXML //VOUT", 344)
                root = ET.fromstring("\n".join(
                    line[4:] for line in snippet.lines[1:-1]).encode("utf-8"))
                self.assertEqual(root.findtext("DBVersion"), "2.3")
                self.assertEqual(root.findtext("Project/Address"), "VOUT")
                request("PROJECT CLOSE VOUT", 200)
                custom_finding = {"source_sha256": digest(custom_source),
                    "preview": list(preview.lines), "preview_source_unchanged": True,
                    "preview_output_unchanged": True,
                    "source_backup_created": False,
                    "output_sha256": digest(custom_output.read_bytes()),
                    "source_unchanged_after_transform": True,
                    "load_after": loaded.final,
                    "readback_db_version": root.findtext("DBVersion"),
                    "readback_project_address": root.findtext("Project/Address")}

                inline = typed.operation("transform", "VINLINE",
                    xslt_file="transform/v22tov23.xslt")
                self.assertEqual(inline.lines, ("200 OK.",))
                self.assertEqual((projects / "VINLINE.xml").read_bytes(), expected)
                self.assertEqual((projects / "VINLINE.xml.0").read_bytes(), custom_source)
                request("PROJECT LOAD VINLINE", 200)
                snippet = request("DBGETXML //VINLINE", 344)
                root = ET.fromstring("\n".join(
                    line[4:] for line in snippet.lines[1:-1]).encode("utf-8"))
                self.assertEqual(root.findtext("DBVersion"), "2.3")
                self.assertEqual(root.findtext("Project/Address"), "VINLINE")
                request("PROJECT CLOSE VINLINE", 200)
                custom_finding["in_place"] = {"output_sha256": digest(expected),
                    "backup_sha256": digest(custom_source), "load_after": "200 OK.",
                    "readback_db_version": root.findtext("DBVersion"),
                    "readback_project_address": root.findtext("Project/Address")}
        self.assertTrue(service.report["listener_ownership_verified"])
        self.assertTrue(service.report["cleanup_complete"])
        self.assertFalse(service.work.exists())

        report_path = os.environ.get("CBUS_PROJECT_LEGACY_VERSIONS_REPORT")
        if report_path:
            report = {"format": "cbus-project-legacy-transform-versions-native-v1",
                "target": "original C-Gate 3.4.0 build 2001, owned XML repository and loopback only",
                "sources": {"java_sha256": JAVA_SHA256, "vendor_jar_sha256": JAR_SHA256,
                    "transform_sha256": stylesheet_hashes,
                    "native_test_sha256": digest(Path(__file__).read_bytes()),
                    "portable_module_sha256": digest((ROOT / "src/cbus_toolkit/project_legacy_transform.py").read_bytes()),
                    "native_module_sha256": digest((ROOT / "src/cbus_toolkit/native.py").read_bytes()),
                    "cli_dispatch_sha256": digest((ROOT / "src/cbus_toolkit/cli.py").read_bytes()),
                    "portable_test_sha256": digest((ROOT / "tests/test_project_legacy_transform.py").read_bytes()),
                    "owned_service_harness_sha256": digest((ROOT / "research/local_cgate.py").read_bytes())},
                "cases": findings,
                "custom_stylesheet_output": custom_finding,
                "service": {"listener_ownership_verified": True, "listener_count": 6,
                    "process_exit_confirmed": service.report["process_exit_confirmed"],
                    "work_removed": service.report["work_removed"],
                    "cleanup_complete": service.report["cleanup_complete"]},
                "physical_networks_opened": False,
                "scope": "Unitless repaired XML 2 and 2.1 via default native migration; no arbitrary unit XSLT parity"}
            Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
