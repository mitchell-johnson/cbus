"""Owned original-C-Gate acceptance for KEYGL5 5.5.00 legacy PP migration.

The source project and PP snapshot are generated inside the disposable child.
Only a loopback CNI address is stored; NET OPEN is never sent.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.project_legacy_transform import transform_repaired_legacy_project
from cbus_toolkit.repositories import parse_repository_list
from research.local_cgate import JAR_SHA256, LocalCGate
from tests.test_project_legacy_transform_native import JAVA_SHA256


ROOT = Path(__file__).resolve().parents[1]
CASES = (("UGEN", "2.1", None), ("UGEN2", "2", None),
         ("UREM", "2.1", "Remote3Identity"), ("UFEATURE", "2", "FeatureSet"))
EXTRA_PP = {
    "Remote3Identity": b'<PP Name="Remote3Identity" Value="0xff 0xff 0xff 0xff"/>',
    "FeatureSet": b'<PP Name="FeatureSet" Value="0x1"/>',
}


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


@unittest.skipUnless(all(os.environ.get(name) for name in ("CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR")),
                     "Select pinned Java11/vendor for owned original C-Gate migration acceptance")
class LegacyUnitsNativeTests(unittest.TestCase):
    def test_keygl5_pp_migration_exact_native_bytes_load_and_readback(self):
        java = Path(os.environ["CBUS_CGATE_JAVA"])
        vendor = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"])
        self.assertEqual(digest(java.read_bytes()), JAVA_SHA256)
        stylesheets = {name: digest((vendor / "transform" / name).read_bytes())
                       for name in ("v2tov21.xslt", "v21tov22.xslt", "v22tov23.xslt",
                                    "projectversions.xml")}
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
                request("PROJECT NEW BASE", 200)
                request("PROJECT USE BASE", 200)
                request("DBCREATENET 254 Owned Cni 127.0.0.1:1", 301)
                request("NET LOAD DB", 200)
                request("DBADDSAFE //BASE/254 Unit 20 OwnedUnit", 301)
                for name, value in (("UnitType", "KEYGL5"), ("UnitName", "NativeUnit"),
                                    ("FirmwareVersion", "5.5.00"), ("CatalogNumber", "5055EDL"),
                                    ("SerialNumber", "1.2.3")):
                    request(f"DBSETSAFE //BASE/254/p/20/{name} {value}", 200)
                request("PP LOCK OWNLOCK //BASE/254", 200)
                request("PP START OWNSESSION OWNLOCK", 200)
                request("PP LOAD OWNSESSION /db//BASE/254/p/20", 200)
                request("PP RESET_TO_DEFAULTS OWNSESSION", 200)
                request("PP SAVE_TO_SOURCE OWNSESSION", 200)
                request("PP END OWNSESSION", 200)
                request("PP UNLOCK OWNLOCK", 200)
                request("PROJECT SAVE BASE", 200)
                request("PROJECT CLOSE BASE", 200)
                base = (projects / "BASE.xml").read_bytes()
                self.assertEqual(base.count(b'?>\n<Installation>'), 1)
                self.assertEqual(base.count(b'<Value></Value>'), 1)
                self.assertIn(b'<Unit><TagName>OwnedUnit</TagName>', base)
                self.assertGreater(base.count(b'<PP Name='), 100)

                for name, version, extra in CASES:
                    with self.subTest(name=name):
                        source = base.replace(b"<DBVersion>2.3</DBVersion>",
                                              f"<DBVersion>{version}</DBVersion>".encode(), 1)
                        source = source.replace(b'?>\n<Installation>', b'?><Installation>', 1)
                        source = source.replace(b'<Value></Value>', b'<Value/>')
                        source += b'\n'
                        if extra:
                            source = source.replace(b'</Unit>', EXTRA_PP[extra] + b'</Unit>', 1)
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
                        self.assertEqual(portable.removed_programming_parameters,
                                         (extra,) if extra else ())
                        loaded = request(f"PROJECT LOAD {name}", 200)
                        readback = request(f"DBGETXML //{name}", 344)
                        body = '\n'.join(line[4:] for line in readback.lines[1:-1]).encode()
                        model = ET.fromstring(body)
                        unit = model.find("Project/Network/Unit")
                        self.assertIsNotNone(unit)
                        self.assertEqual(unit.findtext("UnitType"), "KEYGL5")
                        self.assertEqual(unit.findtext("FirmwareVersion"), "5.5.00")
                        self.assertEqual(model.findtext("DBVersion"), "2.3")
                        if extra:
                            self.assertFalse(any(pp.get("Name") == extra for pp in unit.findall("PP")))
                        request(f"PROJECT CLOSE {name}", 200)
                        findings.append({"case": name, "source_db_version": version,
                                         "source_sha256": digest(source), "output_sha256": digest(output),
                                         "backup_sha256": digest(backup.read_bytes()),
                                         "readback_sha256": digest(body), "removed_pp": list(portable.removed_programming_parameters),
                                         "load_before": before.code, "transform": 200,
                                         "load_after": loaded.code, "readback": readback.code,
                                         "native_bytes_equal_portable": True})
        self.assertTrue(service.report["listener_ownership_verified"])
        self.assertTrue(service.report["cleanup_complete"])
        self.assertFalse(service.work.exists())
        report_path = os.environ.get("CBUS_PROJECT_LEGACY_UNITS_REPORT")
        if report_path:
            report = {"format": "cbus-project-legacy-transform-units-native-v1",
                      "target": "original C-Gate 3.4.0 build 2001, owned XML repository and loopback only",
                      "sources": {"java_sha256": JAVA_SHA256, "vendor_jar_sha256": JAR_SHA256,
                                  "transform_sha256": stylesheets,
                                  "native_test_sha256": digest(Path(__file__).read_bytes()),
                                  "portable_module_sha256": digest((ROOT / "src/cbus_toolkit/project_legacy_transform.py").read_bytes()),
                                  "portable_test_sha256": digest((ROOT / "tests/test_project_legacy_transform.py").read_bytes()),
                                  "owned_service_harness_sha256": digest((ROOT / "research/local_cgate.py").read_bytes())},
                      "cases": findings, "service": {"listener_ownership_verified": True,
                          "process_exit_confirmed": service.report["process_exit_confirmed"],
                          "work_removed": service.report["work_removed"],
                          "cleanup_complete": service.report["cleanup_complete"]},
                      "physical_networks_opened": False,
                      "scope": "KEYGL5 5.5.00 PP-preserving and obsolete-parameter-removal migration, versions 2/2.1"}
            Path(report_path).write_text(json.dumps(report, indent=2) + "\n")
