"""Original build-2001 conversion of generated, Python-repaired legacy XML.

The opt-in test owns the child and six loopback listeners. It never opens a
network or adopts a running server or project directory.
"""
from hashlib import sha256
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
from tests.test_project_legacy_transform import FIXTURE_SHA, NATIVE_OUTPUT_SHA, candidates, digest


ROOT = Path(__file__).resolve().parents[1]
JAVA_SHA256 = "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
STYLESHEET_SHA256 = "5674534824826a2db5e3b762c207ce0e566298e54703f628d16f9b3d2d47dab2"
TEST_PREVIEW_LINES = (
    "199-current DBVersion is: 2.2",
    "199-wanted DBVersion is: 2.3",
    "199-Calculated transform list:",
    "199-Transform from 2.2 to 2.3 XSLT file: v22tov23.xslt",
    "200 OK.",
)


@unittest.skipUnless(all(os.environ.get(key) for key in ("CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR")),
                     "Select pinned Java11 and original C-Gate for isolated transform")
class LegacyTransformNativeTests(unittest.TestCase):
    def test_original_transform_load_and_readback(self):
        java = Path(os.environ["CBUS_CGATE_JAVA"])
        vendor = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"])
        self.assertEqual(digest(java.read_bytes()), JAVA_SHA256)
        stylesheet = vendor / "transform/v22tov23.xslt"
        self.assertEqual(digest(stylesheet.read_bytes()), STYLESHEET_SHA256)
        samples = list(candidates())
        self.assertEqual([name for name, _, _ in samples], list(NATIVE_OUTPUT_SHA))
        service = LocalCGate(vendor, java=java)
        projects = service.work / "legacy-projects"
        try:
            projects.mkdir()
            config = service.work / "config/C-GateConfig.txt"
            config.write_text(config.read_text() + f"project.default.dir={projects}\n")
            (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
            for name, _, source in samples:
                (projects / f"{name}.xml").write_bytes(source)
        except BaseException as error:
            service._cleanup_preserving(error)
            raise

        findings = []
        with service:
            with CGateClient("127.0.0.1", service.port, timeout=10) as client:
                typed = NativeProjects(client)
                def request(command, code):
                    try:
                        reply = client.command(command)
                    except CGateError as error:
                        reply = error.response
                    self.assertEqual(reply.code, code, (command, reply.lines))
                    return reply

                help_lines = request("HELP TRANSFORM PROJECT", 101).lines
                self.assertIn("TRANSFORM PROJECT [--test] <project-name>", help_lines[0])
                listing = parse_repository_list(request("REPOSITORY LIST", 123))
                file_repo, = [repo for repo in listing.repositories if repo.type == "file"]
                self.assertEqual(Path(file_repo.path).resolve(), projects.resolve())
                self.assertEqual(request("PROJECT LIST", 124).lines, ("124 no projects found",))
                request(f"REPOSITORY USE {file_repo.index}", 200)
                for name, case_id, source in samples:
                    with self.subTest(name=name):
                        staged = projects / f"{name}.xml"
                        backup = projects / f"{name}.xml.0"
                        before = request(f"PROJECT LOAD {name}", 408)
                        self.assertEqual(before.final,
                            "408 Operation failed: Project load failed: Incompatible project: DBVersion is 2.2 and must be 2.3 - perform a TRANSFORM PROJECT command to fix this")
                        if name == "RPMAL":
                            preview = typed.operation("transform", name, test=True)
                            self.assertEqual(preview.lines, TEST_PREVIEW_LINES)
                            self.assertEqual(staged.read_bytes(), source)
                            self.assertEqual(backup.read_bytes(), source)
                        converted = typed.operation("transform", name)
                        self.assertEqual(converted.lines, ("200 OK.",))
                        self.assertEqual(backup.read_bytes(), source)
                        native_output = staged.read_bytes()
                        portable = transform_repaired_legacy_project(source)
                        self.assertEqual(native_output, portable.transformed_xml)
                        self.assertEqual(digest(native_output), NATIVE_OUTPUT_SHA[name])
                        loaded = request(f"PROJECT LOAD {name}", 200)
                        self.assertEqual(loaded.lines, ("200 OK.",))
                        reply = request(f"DBGETXML //{name}", 344)
                        self.assertEqual(reply.lines[0], "343-Begin XML snippet")
                        self.assertEqual(reply.lines[-1], "344 End XML snippet")
                        self.assertTrue(all(line.startswith("347-") for line in reply.lines[1:-1]))
                        readback = "\n".join(line[4:] for line in reply.lines[1:-1]).encode("utf-8")
                        root = ET.fromstring(readback)
                        self.assertEqual(root.findtext("DBVersion"), "2.3")
                        self.assertEqual(root.findtext("Project/Address"), name)
                        self.assertEqual(root.findtext("Project/TagName"), name)
                        groups = [(group.findtext("Address"), group.findtext("TagName"))
                                  for group in root.findall("Project/Network/Application/Group")]
                        if name == "RPMAL":
                            self.assertEqual(root.findtext("Project/Network/Address"), "254")
                            self.assertEqual(groups, [("1", "First"), ("255", "<Unused>")])
                        else:
                            self.assertEqual(groups, [])
                        oids = [node.text for node in root.findall(".//OID")]
                        self.assertTrue(oids)
                        self.assertEqual(len(oids), len(set(oids)))
                        self.assertEqual(staged.read_bytes(), native_output)
                        request(f"PROJECT CLOSE {name}", 200)
                        self.assertEqual(request("PROJECT LIST", 124).lines, ("124 no projects found",))
                        findings.append({
                            "name": name, "source_case": case_id,
                            "source_sha256": digest(source), "native_output_sha256": digest(native_output),
                            "backup_sha256": digest(backup.read_bytes()),
                            "load_before": before.final, "transform_response": converted.final,
                            "load_after": loaded.final, "readback_code": reply.code,
                            "readback_db_version": root.findtext("DBVersion"),
                            "readback_project_address": root.findtext("Project/Address"),
                            "readback_project_tag": root.findtext("Project/TagName"),
                            "readback_groups": groups, "readback_oid_count": len(oids),
                        })
                self.assertEqual({path.name for path in projects.iterdir()},
                                 {f"{name}.xml{suffix}" for name, _, _ in samples for suffix in ("", ".0")})
        self.assertTrue(service.report["listener_ownership_verified"])
        self.assertTrue(service.report["cleanup_complete"])
        self.assertFalse(service.work.exists())

        report_path = os.environ.get("CBUS_PROJECT_LEGACY_TRANSFORM_REPORT")
        if report_path:
            summary = {
                "format": "cbus-project-legacy-transform-native-v1",
                "target": "original C-Gate 3.4.0 build 2001, owned XML repository and loopback only",
                "sources": {"java_sha256": JAVA_SHA256, "vendor_jar_sha256": JAR_SHA256,
                            "v22tov23_xslt_sha256": STYLESHEET_SHA256,
                            "fixture_sha256": {name: value[1] for name, value in FIXTURE_SHA.items()},
                            "test_sha256": digest(Path(__file__).read_bytes()),
                            "portable_test_sha256": digest((ROOT / "tests/test_project_legacy_transform.py").read_bytes()),
                            "portable_module_sha256": digest((ROOT / "src/cbus_toolkit/project_legacy_transform.py").read_bytes()),
                            "cli_module_sha256": digest((ROOT / "src/cbus_toolkit/project_legacy_transform_cli.py").read_bytes()),
                            "native_module_sha256": digest((ROOT / "src/cbus_toolkit/native.py").read_bytes()),
                            "cli_dispatch_sha256": digest((ROOT / "src/cbus_toolkit/cli.py").read_bytes()),
                            "owned_service_harness_sha256": digest((ROOT / "research/local_cgate.py").read_bytes())},
                "help": help_lines, "preview": {"response": TEST_PREVIEW_LINES,
                    "creates_backup_without_changing_xml": True},
                "cases": findings,
                "service": {"listener_ownership_verified": True, "listener_count": 6,
                            "process_exit_confirmed": service.report["process_exit_confirmed"],
                            "work_removed": service.report["work_removed"],
                            "cleanup_complete": service.report["cleanup_complete"]},
                "physical_networks_opened": False,
                "scope": "Four generated repaired inputs; no arbitrary-project or Toolkit GUI parity claim",
            }
            Path(report_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
