"""Owned original C-Gate acceptance for KEYB2/KEYB4 1.6 legacy migration.

The source project and PP snapshot are generated inside the disposable child.
Only a loopback CNI address is stored; NET OPEN is never sent.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.project_legacy_transform import transform_repaired_legacy_project
from cbus_toolkit.repositories import parse_repository_list
from research.local_cgate import JAR_SHA256, LocalCGate
from tests.test_project_legacy_transform_native import JAVA_SHA256


ROOT = Path(__file__).resolve().parents[1]
VENDOR_STYLESHEETS = {
    "v2tov21.xslt": "8346eab4259b957d53fc2b5c14ee1e058196124eabe4a7e3fb45b145f74735a8",
    "v21tov22.xslt": "e2090621171b5febf4903eaa964dd7a855b3d3cea827678da3758376dceab875",
    "v22tov23.xslt": "5674534824826a2db5e3b762c207ce0e566298e54703f628d16f9b3d2d47dab2",
    "projectversions.xml": "f9b2e0a83753321e311dee1ac7e1817b28dd984a792a2fd2923efa1cac85aaf8",
}
CONDITIONAL_PP = frozenset({
    "KeyDisableGroupInvert", "CorridorLinkEnable", "NightlightColour", "DisableIRNEC",
})
PROFILES = (("KEYB2", "5032NL", "BASE2", "B2"),
            ("KEYB4", "5034NL", "BASE4", "B4"))
CASES = (("A21", "2.1", True), ("N21", "2.1", False),
         ("A2", "2", True), ("N2", "2", False))


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


@unittest.skipUnless(all(os.environ.get(name) for name in ("CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR")),
                     "Select pinned Java11/vendor for owned original C-Gate migration acceptance")
class LegacyNeoNativeTests(unittest.TestCase):
    def test_neo_application_gate_exact_native_bytes_load_and_readback(self):
        java = Path(os.environ["CBUS_CGATE_JAVA"])
        vendor = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"])
        self.assertEqual(digest(java.read_bytes()), JAVA_SHA256)
        for name, expected in VENDOR_STYLESHEETS.items():
            self.assertEqual(digest((vendor / "transform" / name).read_bytes()), expected)
        service = LocalCGate(vendor, java=java)
        projects = service.work / "legacy-projects"
        try:
            projects.mkdir()
            config = service.work / "config/C-GateConfig.txt"
            config.write_text(config.read_text() + f"project.default.dir={projects}\n")
            (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
        except BaseException as error:
            service._cleanup_preserving(error)
            raise

        findings = []
        with service:
            with CGateClient("127.0.0.1", service.port, timeout=15) as client:
                def request(command: str, code: int):
                    try:
                        reply = client.command(command)
                    except CGateError as error:
                        reply = error.response
                    self.assertEqual(reply.code, code, (command, reply.lines[-3:]))
                    return reply

                repositories = parse_repository_list(request("REPOSITORY LIST", 123))
                file_repo, = [repo for repo in repositories.repositories if repo.type == "file"]
                self.assertEqual(Path(file_repo.path).resolve(), projects.resolve())
                request(f"REPOSITORY USE {file_repo.index}", 200)
                for unit_type, catalog, base_name, prefix in PROFILES:
                    request(f"PROJECT NEW {base_name}", 200)
                    request(f"PROJECT USE {base_name}", 200)
                    request("DBCREATENET 254 Owned Cni 127.0.0.1:1", 301)
                    request("NET LOAD DB", 200)
                    request(f"DBADDSAFE //{base_name}/254 Unit 20 OwnedUnit", 301)
                    for field, value in (("UnitType", unit_type), ("UnitName", "NativeUnit"),
                                         ("FirmwareVersion", "1.6"), ("CatalogNumber", catalog),
                                         ("SerialNumber", "1.2.3")):
                        request(f"DBSETSAFE //{base_name}/254/p/20/{field} {value}", 200)
                    request(f"PP LOCK OWNLOCK //{base_name}/254", 200)
                    request("PP START OWNSESSION OWNLOCK", 200)
                    request(f"PP LOAD OWNSESSION /db//{base_name}/254/p/20", 200)
                    request("PP RESET_TO_DEFAULTS OWNSESSION", 200)
                    request("PP SAVE_TO_SOURCE OWNSESSION", 200)
                    request("PP END OWNSESSION", 200)
                    request("PP UNLOCK OWNLOCK", 200)
                    request(f"PROJECT SAVE {base_name}", 200)
                    request(f"PROJECT CLOSE {base_name}", 200)
                    base = (projects / f"{base_name}.xml").read_bytes()
                    base_unit = ET.fromstring(base).find("Project/Network/Unit")
                    self.assertIsNotNone(base_unit)
                    base_pp = [pp.get("Name") for pp in base_unit.findall("PP")]
                    self.assertGreater(len(base_pp), 50)
                    self.assertIn("Application", base_pp)
                    self.assertIn("EEPROM Checksum", base_pp)
                    self.assertTrue(CONDITIONAL_PP.issubset(base_pp))
                    self.assertNotIn("KeyExtraLongPressDuration", base_pp)
                    self.assertNotIn("EnableNightlightPCx", base_pp)
                    self.assertEqual(base.count(b'<Value></Value>'), 1)

                    for suffix, version, has_application in CASES:
                        name = prefix + suffix
                        with self.subTest(name=name):
                            source = base.replace(b"<DBVersion>2.3</DBVersion>",
                                                  f"<DBVersion>{version}</DBVersion>".encode(), 1)
                            source = source.replace(b'?>\n<Installation>', b'?><Installation>', 1)
                            source = source.replace(b'<Value></Value>', b'<Value/>') + b'\n'
                            if not has_application:
                                source, count = re.subn(rb'<PP Name="Application" Value="[^"<>]*"/>',
                                                        b'', source, count=1)
                                self.assertEqual(count, 1)
                            # Global stylesheet removals accompany the unit-specific gate.
                            extra = b'<PP Name="Remote3Identity" Value="0xff 0xff 0xff 0xff"/>'
                            if version == "2":
                                extra += b'<PP Name="FeatureSet" Value="0x1"/>'
                            source = source.replace(b'</Unit>', extra + b'</Unit>', 1)
                            staged = projects / f"{name}.xml"
                            backup = projects / f"{name}.xml.0"
                            staged.write_bytes(source)
                            before = request(f"PROJECT LOAD {name}", 408)
                            self.assertIn(f"DBVersion is {version} and must be 2.3", before.final)
                            request(f"TRANSFORM PROJECT {name}", 200)
                            output = staged.read_bytes()
                            portable = transform_repaired_legacy_project(source)
                            self.assertEqual(output, portable.transformed_xml)
                            self.assertEqual(backup.read_bytes(), source)
                            source_unit = ET.fromstring(source).find("Project/Network/Unit")
                            source_pp = [pp.get("Name") for pp in source_unit.findall("PP")]
                            expected_removed = {"Remote3Identity"}
                            if version == "2":
                                expected_removed.add("FeatureSet")
                            if not has_application:
                                expected_removed.update(CONDITIONAL_PP)
                            self.assertEqual(portable.removed_programming_parameters,
                                             tuple(pp for pp in source_pp if pp in expected_removed))
                            loaded = request(f"PROJECT LOAD {name}", 200)
                            readback = request(f"DBGETXML //{name}", 344)
                            body = '\n'.join(line[4:] for line in readback.lines[1:-1]).encode()
                            model = ET.fromstring(body)
                            unit = model.find("Project/Network/Unit")
                            self.assertIsNotNone(unit)
                            self.assertEqual(unit.findtext("UnitType"), unit_type)
                            self.assertEqual(unit.findtext("FirmwareVersion"), "1.6")
                            self.assertEqual(model.findtext("DBVersion"), "2.3")
                            readback_pp = {pp.get("Name") for pp in unit.findall("PP")}
                            self.assertEqual("Application" in readback_pp, has_application)
                            self.assertEqual(CONDITIONAL_PP.issubset(readback_pp), has_application)
                            self.assertFalse(expected_removed.intersection(readback_pp))
                            self.assertIn("UnitAddress", readback_pp)
                            request(f"PROJECT CLOSE {name}", 200)
                            findings.append({"case": name, "unit_type": unit_type,
                                             "source_db_version": version,
                                             "application_present": has_application,
                                             "source_pp_count": len(source_pp),
                                             "readback_pp_count": len(readback_pp),
                                             "source_sha256": digest(source),
                                             "output_sha256": digest(output),
                                             "backup_sha256": digest(backup.read_bytes()),
                                             "readback_sha256": digest(body),
                                             "removed_pp": list(portable.removed_programming_parameters),
                                             "load_before": before.code, "transform": 200,
                                             "load_after": loaded.code, "readback": readback.code,
                                             "native_bytes_equal_portable": True})
        self.assertTrue(service.report["listener_ownership_verified"])
        self.assertTrue(service.report["cleanup_complete"])
        self.assertFalse(service.work.exists())
        report_path = os.environ.get("CBUS_PROJECT_LEGACY_NEO_REPORT")
        if report_path:
            report = {"format": "cbus-project-legacy-transform-neo-native-v1",
                      "target": "original C-Gate 3.4.0 build 2001, owned XML repository and loopback only",
                      "sources": {"java_sha256": JAVA_SHA256, "vendor_jar_sha256": JAR_SHA256,
                                  "transform_sha256": VENDOR_STYLESHEETS,
                                  "native_test_sha256": digest(Path(__file__).read_bytes()),
                                  "portable_module_sha256": digest((ROOT / "src/cbus_toolkit/project_legacy_transform.py").read_bytes()),
                                  "portable_test_sha256": digest((ROOT / "tests/test_project_legacy_transform.py").read_bytes()),
                                  "owned_service_harness_sha256": digest((ROOT / "research/local_cgate.py").read_bytes())},
                      "cases": findings,
                      "service": {"listener_ownership_verified": True,
                                  "process_exit_confirmed": service.report["process_exit_confirmed"],
                                  "work_removed": service.report["work_removed"],
                                  "cleanup_complete": service.report["cleanup_complete"]},
                      "physical_networks_opened": False,
                      "scope": "KEYB2/KEYB4 1.6 Application-gated and global PP removals, versions 2/2.1"}
            Path(report_path).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
