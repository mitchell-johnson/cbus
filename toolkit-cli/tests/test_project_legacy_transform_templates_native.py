"""Owned original C-Gate acceptance for the Unit-conditioned migration templates.

One generated project carries PC/PCI, DLT, Neo, wireless and key units. Each
case adds synthetic PP tokens or cis:Unit wrappers, stages the result at an
earlier DBVersion and compares native TRANSFORM PROJECT bytes with the
portable conversion before native LOAD and DBGETXML. Only a loopback CNI
address is stored; NET OPEN is never sent.
"""
from __future__ import annotations

from collections import Counter
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
from tests.test_project_legacy_transform_neo_native import VENDOR_STYLESHEETS


ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "research/fixtures/project-legacy-transform-template-census.json"
CIS = b'xmlns:cis="http://www.clipsal.com/cis/schema/2001/cbus.xsd"'
UNITS = (
    (20, "PC_CTA", "4.00"), (21, "PCINT4", "4.0.00"), (22, "PCLOCAL4", "4.0.00"),
    (23, "PC_CBTI", "4.0.00.7"), (24, "PC_PGA", "4.0.00"), (25, "PC_IRT2", "4.0.00"),
    (26, "PC_WHAM", "4.0.00"), (27, "PC_PGA", "4.0.0"), (28, "KEYBL5", "1.0"),
    (29, "KEYML5", "1.0"), (30, "KEYM8", "1.6.2"), (31, "KEYA1", "1.7"),
    (32, "WRB4D1", "2.0.0"), (33, "WRM8R2", "2.0.0"), (34, "KEYA3", "1.5"),
)
RENAMES = ("v21tov22#18-8e846bdd", "v21tov22#19-c309fdfb")
FOUR = ("KeyDisableGroupInvert", "CorridorLinkEnable", "NightlightColour", "DisableIRNEC")


def pp(name: str, value: str = "1") -> bytes:
    return f'<PP Name="{name}" Value="{value}"/>'.encode()


def add(data: bytes, address: int, extra: bytes) -> bytes:
    marker = data.index(f"<Address>{address}</Address>".encode())
    end = data.index(b"</Unit>", marker)
    return data[:end] + extra + data[end:]


def namespaced(data: bytes, address: int) -> bytes:
    marker = data.index(f"<Address>{address}</Address>".encode())
    start = data.rindex(b"<Unit>", 0, marker)
    end = data.index(b"</Unit>", marker)
    return (data[:start] + b"<cis:Unit " + CIS + b">" + data[start + 6:end] + b"</cis:Unit>"
            + data[end + 7:])


def firmware(data: bytes) -> bytes:
    return add(data, 20, pp("Keep") + pp("Remote3Identity", "0xff"))


def dlt(data: bytes) -> bytes:
    data = add(data, 28, pp("CorridorLinkEnable", "0") + pp("Other", "2"))
    return add(data, 29, pp("Application", "0x38") + pp("CorridorLinkEnable", "0"))


def neo(data: bytes) -> bytes:
    four = b"".join(pp(name) for name in FOUR)
    return add(add(data, 30, four + pp("Keep")), 31, four)


def cis(data: bytes) -> bytes:
    data = add(data, 30, pp("Application", "0x38") + pp("FeatureSet", "0x1"))
    return namespaced(namespaced(data, 30), 28)


def wireless(data: bytes) -> bytes:
    data = add(data, 32, pp("Application", "0x38") + pp("Remote3Identity", "0x1") + pp("Keep"))
    return add(data, 33, pp("Keep"))


def expansion(data: bytes) -> bytes:
    data = add(data, 34, pp("KeyMaskAllowed", "0x1") + pp("KeyExtraLongPressDuration", "0x40")
               + pp("EnableNightlightPCx", "0x2"))
    # Stage-one expansion output precedes the stage-two wireless additions.
    return add(data, 32, pp("Application", "0x38") + pp("KeyExtraLongPressDuration", "0x41"))


CASES = (
    ("FW21", "2.1", firmware, RENAMES),
    ("FW2", "2", firmware, RENAMES),
    ("FW22", "2.2", firmware, ()),
    ("DLT21", "2.1", dlt, ("v21tov22#03-98a206ab", *RENAMES)),
    ("DLT2", "2", dlt, ("v21tov22#03-98a206ab", *RENAMES)),
    ("NEO21", "2.1", neo, ("v21tov22#04-36fd2be7", *RENAMES)),
    ("NS2", "2", cis, ("v2tov21#57-1338c52b", *RENAMES)),
    ("NS21", "2.1", cis, RENAMES),
    ("WL21", "2.1", wireless, ("v21tov22#17-efb660bf", *RENAMES)),
    ("WL2", "2", wireless, ("v21tov22#17-efb660bf", *RENAMES)),
    ("EXP2", "2", expansion, ("v2tov21#55-9e87eeb9", "v2tov21#56-fd9c07b5",
                               "v21tov22#17-efb660bf", *RENAMES)),
)


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def unit_map(xml: bytes) -> dict:
    """Address -> (UnitType, FirmwareVersion, PP name counts), ignoring namespaces."""
    units = {}
    for element in ET.fromstring(xml).iter():
        if element.tag.rsplit("}", 1)[-1] == "Unit":
            units[element.findtext("Address")] = (
                element.findtext("UnitType"), element.findtext("FirmwareVersion"),
                Counter(child.get("Name") for child in element.findall("PP")))
    return units


@unittest.skipUnless(all(os.environ.get(name) for name in ("CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR")),
                     "Select pinned Java11/vendor for owned original C-Gate migration acceptance")
class LegacyTemplateNativeTests(unittest.TestCase):
    def test_unit_template_branches_match_native_bytes_load_and_readback(self):
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
                request("PROJECT NEW BASE", 200)
                request("PROJECT USE BASE", 200)
                request("DBCREATENET 254 Owned Cni 127.0.0.1:1", 301)
                request("NET LOAD DB", 200)
                for address, unit_type, version in UNITS:
                    request(f"DBADDSAFE //BASE/254 Unit {address} U{address}", 301)
                    for field, value in (("UnitType", unit_type), ("UnitName", f"N{address}"),
                                         ("FirmwareVersion", version), ("CatalogNumber", "5500X"),
                                         ("SerialNumber", "1.2.3")):
                        request(f"DBSETSAFE //BASE/254/p/{address}/{field} {value}", 200)
                request("PROJECT SAVE BASE", 200)
                request("PROJECT CLOSE BASE", 200)
                base = (projects / "BASE.xml").read_bytes()
                self.assertEqual(len(unit_map(base)), len(UNITS))
                base = base.replace(b'?>\n<Installation>', b'?><Installation>', 1)
                base = base.replace(b'<Value></Value>', b'<Value/>') + b'\n'

                for name, version, edit, templates in CASES:
                    with self.subTest(name=name):
                        source = edit(base).replace(
                            b"<DBVersion>2.3</DBVersion>", f"<DBVersion>{version}</DBVersion>".encode(), 1)
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
                        loaded = request(f"PROJECT LOAD {name}", 200)
                        readback = request(f"DBGETXML //{name}", 344)
                        body = '\n'.join(line[4:] for line in readback.lines[1:-1]).encode()
                        self.assertEqual(ET.fromstring(body).findtext("DBVersion"), "2.3")
                        # Readback returns every cis:Unit as a plain Unit with
                        # the migrated firmware and PP multiset.
                        self.assertEqual(unit_map(body), unit_map(output))
                        request(f"PROJECT CLOSE {name}", 200)
                        findings.append({
                            "case": name, "source_db_version": version, "templates": list(templates),
                            "source_sha256": digest(source), "output_sha256": digest(output),
                            "backup_sha256": digest(backup.read_bytes()),
                            "readback_sha256": digest(body),
                            "removed_pp": list(portable.removed_programming_parameters),
                            "added_pp_count": len(portable.added_programming_parameters),
                            "renamed_pp": [list(pair) for pair in portable.renamed_programming_parameters],
                            "firmware_changes": len(portable.firmware_version_changes),
                            "cis_units": source.count(b"<cis:Unit"),
                            "load_before": before.code, "transform": 200,
                            "load_after": loaded.code, "readback": readback.code,
                            "readback_units_equal_portable": True,
                            "native_bytes_equal_portable": True})
        self.assertTrue(service.report["listener_ownership_verified"])
        self.assertTrue(service.report["cleanup_complete"])
        self.assertFalse(service.work.exists())
        report_path = os.environ.get("CBUS_PROJECT_LEGACY_TEMPLATES_REPORT")
        if report_path:
            report = {"format": "cbus-project-legacy-transform-templates-native-v1",
                      "target": "original C-Gate 3.4.0 build 2001, owned XML repository and loopback only",
                      "sources": {"java_sha256": JAVA_SHA256, "vendor_jar_sha256": JAR_SHA256,
                                  "transform_sha256": VENDOR_STYLESHEETS,
                                  "census_sha256": digest(CENSUS.read_bytes()),
                                  "native_test_sha256": digest(Path(__file__).read_bytes()),
                                  "portable_module_sha256": digest((ROOT / "src/cbus_toolkit/project_legacy_transform.py").read_bytes()),
                                  "portable_test_sha256": digest((ROOT / "tests/test_project_legacy_transform_templates.py").read_bytes()),
                                  "owned_service_harness_sha256": digest((ROOT / "research/local_cgate.py").read_bytes())},
                      "cases": findings,
                      "service": {"listener_ownership_verified": True,
                                  "process_exit_confirmed": service.report["process_exit_confirmed"],
                                  "work_removed": service.report["work_removed"],
                                  "cleanup_complete": service.report["cleanup_complete"]},
                      "physical_networks_opened": False,
                      "scope": "PC/PCI firmware renames, DLT and Neo Application gates, cis:Unit additions, "
                               "wireless additions and version-2 PP expansion/rename"}
            Path(report_path).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
