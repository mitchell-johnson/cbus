"""Opt-in owned-loopback native acceptance for bounded IOPE editors.

All units and group metadata are synthetic. PP sources use /db addresses and
networks remain closed; these tests establish no physical-unit acceptance.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.pp_editor import PPEditError
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitSpecStore
from test_macros import closed_network_project

ROOT = Path(__file__).resolve().parents[1]
PROFILES = (("IOPE1R1", "5752PP/1R"), ("IOPE2R2", "5752PP/2R"),
            ("IOPE2C4", "5752PP/2R/2D"))
FIRMWARE = ("1.0.00", "1.1.00", "1.2.00")
IMPLEMENTATION_FILES = ("src/cbus_toolkit/iope_environment.py", "src/cbus_toolkit/iope_output_settings.py",
                        "src/cbus_toolkit/iope_workflow_cli.py", "tests/test_iope_workflow_native.py")
NATIVE = (os.environ.get("CBUS_NATIVE_SERVICE_BACKEND") == "local" and
          all(os.environ.get(name) for name in
              ("CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR", "CBUS_UNITSPEC_DIR")))
REASON = "Requires explicitly owned local native C-Gate, Java11 and decoded UnitSpecs"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def implementation_hashes():
    # Hash modules actually executed, so an installed-wheel run cannot borrow
    # evidence from a different source checkout. The receipt check separately
    # requires those bytes to equal the submitted source files.
    result = {}
    for name in IMPLEMENTATION_FILES:
        path = ROOT / name
        if name.startswith("src/"):
            module = importlib.import_module(name.removeprefix("src/").removesuffix(".py").replace("/", "."))
            path = Path(module.__file__)
        result[name] = sha256(path)
    return result


def raw_byte(pp, address):
    return int(pp.get_raw_data(address, 1).lines[-1].split("RawData=", 1)[1], 16)


def group_cache():
    return {"format": "cbus-iope-environment-groups-v1",
            "source": "owned native synthetic project application/group objects",
            "applications": [{"address": 56, "groups": list(range(10, 31))}]}


@unittest.skipUnless(NATIVE, REASON)
class IopeWorkflowNativeTest(unittest.TestCase):
    """One private service, one closed project and eighteen editor/profile cases."""

    def check(self, pp, editor, row, label, *, raw=(), **options):
        before = pp.values()
        result = editor.configure(pp, **options)
        self.assertTrue(result["verified"], label)
        after = pp.values()
        untouched = set(before) - set(result["changes"])
        self.assertEqual({name: after[name] for name in untouched},
                         {name: before[name] for name in untouched}, label)
        for address, mask, expected in raw:
            actual = raw_byte(pp, address)
            self.assertEqual(actual & mask, expected, (label, hex(address), hex(actual)))
            row["raw_byte_assertions"].append({"address": address, "mask": mask,
                                               "expected": expected, "actual": actual})
        row["positive"].append({"case": label, "changed_fields": sorted(result["changes"]),
                                 "unchanged_parameters_verified": len(untouched)})
        return result

    def refuse(self, pp, editor, row, label, **options):
        before = pp.values()
        with self.assertRaises(PPEditError, msg=label):
            editor.configure(pp, **options)
        self.assertEqual(pp.values(), before, label)
        row["refused_without_changes"].append(label)

    def outputs(self, pp, row):
        from cbus_toolkit.iope_output_settings import IopeOutputSettings
        editor = IopeOutputSettings(self.store.load(pp.unit_type + ".xml"))
        for name in ("LogicGA13Associations", "LogicGA14Associations", "LogicGA15Associations",
                     "LogicGA16Associations", "LogicFunction"):
            pp.set(name, "1 0 1 0")
        self.check(pp, editor, row, "output-relay-threshold-restrike-delay-max",
                   channels={1: {"min_percent": 50, "restrike": True}}, restrike_delay=254,
                   raw=((0x78, 255, 127), (0x70, 207, 207), (0x6F, 255, 254)))
        self.check(pp, editor, row, "output-minimum-and-delay-lower-bound",
                   channels={1: {"min_percent": 0}}, restrike_delay=1,
                   raw=((0x78, 255, 0), (0x6F, 255, 1), (0x70, 207, 207)))
        self.refuse(pp, editor, row, "output-minimum-below-domain", channels={1: {"min_percent": -1}})
        self.refuse(pp, editor, row, "output-maximum-on-relay", channels={1: {"max_percent": 50}})
        self.refuse(pp, editor, row, "output-delay-below-domain", restrike_delay=0)
        self.refuse(pp, editor, row, "output-delay-above-domain", restrike_delay=255)
        count = {"IOPE1R1": 1, "IOPE2R2": 2, "IOPE2C4": 4}[pp.unit_type]
        self.refuse(pp, editor, row, "output-channel-outside-profile",
                    channels={count + 1: {"min_percent": 50}})
        if pp.unit_type == "IOPE2C4":
            self.check(pp, editor, row, "dimmer-crossing-minimum-then-maximum",
                       channels={3: {"min_percent": 80, "max_percent": 20}},
                       raw=((0x7A, 255, 48), (0x7C, 255, 51)))
            self.check(pp, editor, row, "dimmer-maximum-endpoint-pair",
                       channels={3: {"min_percent": 100}},
                       raw=((0x7A, 255, 255), (0x7C, 255, 255)))
            self.check(pp, editor, row, "dimmer-zero-endpoint-pair",
                       channels={4: {"max_percent": 0}},
                       raw=((0x7B, 255, 0), (0x7D, 255, 0)))
            self.refuse(pp, editor, row, "dimmer-restrike-is-relay-only", channels={3: {"restrike": True}})
        self.check(pp, editor, row, "relay-restrike-disabled-preserves-logic",
                   channels={1: {"restrike": False}}, raw=((0x70, 207, 143),))
        self.refuse(pp, editor, row, "restrike-delay-requires-enabled-relay", restrike_delay=20)
        row["workflows"].append("output")

    def environment(self, pp, row):
        from cbus_toolkit.iope_environment import IopeEnvironment
        editor = IopeEnvironment(self.store.load(pp.unit_type + ".xml"))
        # Source event normalization moves reserved indices to the original
        # corridor/office defaults. Other shared-byte fields stay selected.
        for name, value in (("InputGroupAddress", "10 11 12 13 14 15 16 17"),
                            ("CorridorGroupBlock", "0"), ("FirstCorridorOfficeGroupBlock", "1"),
                            ("SecondCorridorOfficeGroupBlock", "2"),
                            ("SensorOccupancyDebounce", "6"), ("LightStateMachine", "1")):
            pp.set(name, value)
        cache = group_cache()
        self.check(pp, editor, row, "corridor-enable-hidden-block-relocation",
                   enabled=True, group_cache=cache,
                   raw=((0x6B, 191, 147), (0x6C, 255, 228)))
        self.check(pp, editor, row, "corridor-two-offices-master-group",
                   master_group=20, second_office_enabled=True, group_cache=cache,
                   raw=((0x60, 255, 20), (0x6B, 191, 147), (0x6C, 255, 236)))
        self.check(pp, editor, row, "corridor-explicit-independent-blocks",
                   corridor_block=8, first_office_block=7, second_office_block=6, group_cache=cache,
                   raw=((0x6B, 191, 190), (0x6C, 255, 237)))
        self.refuse(pp, editor, row, "corridor-block-below-domain", corridor_block=0, group_cache=cache)
        self.refuse(pp, editor, row, "corridor-block-above-domain", first_office_block=9, group_cache=cache)
        self.refuse(pp, editor, row, "corridor-master-below-domain", master_group=-1, group_cache=cache)
        self.refuse(pp, editor, row, "corridor-duplicate-office-block", first_office_block=8, group_cache=cache)
        self.refuse(pp, editor, row, "corridor-unresolved-master-group", master_group=31, group_cache=cache)
        self.check(pp, editor, row, "corridor-disable-clears-dependent-office-enable",
                   enabled=False, group_cache=cache,
                   raw=((0x6B, 191, 62), (0x6C, 255, 229)))
        row["workflows"].append("environment")

    def exercise(self, client, network, address, unit_type, catalog, firmware, report):
        database = NativeDatabase(client)
        database.create_unit(network, address, "Synthetic" + str(address), unit_type, firmware,
                             catalog_number=catalog)
        source = f"/db{network}/p/{address}"
        row = {"unit_type": unit_type, "catalog_number": catalog, "firmware": firmware,
               "workflows": [], "positive": [], "refused_without_changes": [], "raw_byte_assertions": []}
        with Programmer(client).load(network, source) as pp:
            self.assertEqual((pp.unit_type, pp.firmware, pp.catalog_number), (unit_type, firmware, catalog))
            self.outputs(pp, row)
            self.environment(pp, row)
            after = pp.values()
            pp.save_to_source()
        project = network.split("/")[2]
        for operation in ("SAVE", "CLOSE", "LOAD", "USE"):
            self.assertEqual(client.command(f"PROJECT {operation} {project}").code, 200)
        with Programmer(client).load(network, source) as pp:
            self.assertEqual(pp.values(), after)
        row.update(save_reload_passed=True, project_close_load_passed=True, reloaded_parameter_count=len(after))
        report["profiles"].append(row)

    def cli(self, *args, status=0):
        result = subprocess.run([sys.executable, "-B", "-m", "cbus_toolkit.iope_workflow_cli",
                                 *map(str, args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def cli_workflows(self, client, host, port, network, report):
        cases, persisted = [], []
        for offset, family in enumerate(("output", "environment")):
            address = 50 + offset
            NativeDatabase(client).create_unit(network, address, "SyntheticCli" + str(address),
                                               "IOPE2C4", "1.2.00", catalog_number="5752PP/2R/2D")
            source = f"/db{network}/p/{address}"
            prefix = ("--spec-dir", os.environ["CBUS_UNITSPEC_DIR"], family)
            database = (*prefix, "database", "--host", host, "--port", port,
                        "--lock-address", network, "--source", source)
            original = self.cli(*database, "--export")
            initial_view = self.cli(*database, "--show")
            edits = ({"channels": {"3": {"min_percent": 80, "max_percent": 20},
                                    "1": {"restrike": True}}, "restrike_delay": 40}
                     if family == "output" else
                     {"enabled": True, "master_group": 20, "group_cache": group_cache()})
            with tempfile.TemporaryDirectory(prefix="iope-cli-") as folder:
                snapshot, edits_file, plan_file = [Path(folder) / name for name in
                                                    ("snapshot.json", "edits.json", "plan.json")]
                snapshot.write_text(json.dumps(original))
                edits_file.write_text(json.dumps(edits))
                self.assertEqual(self.cli(*prefix, "show", snapshot), initial_view)
                plan = self.cli(*prefix, "plan", snapshot, "--edits", edits_file)
                plan_file.write_text(json.dumps(plan))
                preview = self.cli(*database, "--plan", plan_file, "--dry-run", "--exclusive-project")
                self.assertFalse(preview["saved"])
                self.assertFalse(preview["pp_save_attempted"])
                self.assertEqual(preview["changes"], plan["changes"])
                self.assertEqual(self.cli(*database, "--export"), original)
                applied = self.cli(*database, "--plan", plan_file, "--exclusive-project")
                for field in ("saved", "pp_save_attempted", "pp_save_completed", "project_save_attempted",
                              "project_save_completed", "fresh_reload_verified"):
                    self.assertTrue(applied[field], (family, field))
                self.assertFalse(applied["physical_hardware_verified"])
                after = self.cli(*database, "--export")
                self.assertEqual({k: v for k, v in after["parameters"].items() if k not in plan["changes"]},
                                 {k: v for k, v in original["parameters"].items() if k not in plan["changes"]})
                stale = self.cli(*database, "--plan", plan_file, "--exclusive-project", status=1)
                self.assertIn("changed since", stale["error"])
                self.assertEqual(self.cli(*database, "--export"), after)
                case = {"family": family, "unit_type": "IOPE2C4", "firmware": "1.2.00",
                        "offline_plan_matches_dry_run": True, "dry_run_preserved_database": True,
                        "save_and_fresh_reload_passed": True, "stale_plan_refused_without_changes": True,
                        "unrelated_parameters_preserved": applied["unrelated_parameters_preserved"]}
                if family == "environment":
                    # The caller cache must not claim positive objects that
                    # the fresh native database does not contain.
                    bad_cache = group_cache()
                    bad_cache["applications"][0]["groups"].append(31)
                    snapshot.write_text(json.dumps(after))
                    edits_file.write_text(json.dumps({"master_group": 21, "group_cache": bad_cache}))
                    bad_plan = self.cli(*prefix, "plan", snapshot, "--edits", edits_file)
                    plan_file.write_text(json.dumps(bad_plan))
                    error = self.cli(*database, "--plan", plan_file, "--exclusive-project", status=1)
                    self.assertIn("current native database groups", error["error"])
                    self.assertEqual(self.cli(*database, "--export"), after)
                    case["unsupported_native_group_cache_refused_without_changes"] = True
                cases.append(case)
                persisted.append((database, after))
        project = network.split("/")[2]
        for operation in ("CLOSE", "LOAD", "USE"):
            self.assertEqual(client.command(f"PROJECT {operation} {project}").code, 200)
        for (database, after), case in zip(persisted, cases):
            self.assertEqual(self.cli(*database, "--export"), after)
            case["project_close_load_passed"] = True
        report["cli"] = cases

    def refused_profile(self, client, network, report):
        from cbus_toolkit.iope_environment import IopeEnvironment
        from cbus_toolkit.iope_output_settings import IopeOutputSettings
        NativeDatabase(client).create_unit(network, 40, "SyntheticOld", "IOPE1R1", "0.9.99",
                                           catalog_number="5752PP/1R")
        cases = []
        with Programmer(client).load(network, f"/db{network}/p/40") as pp:
            for cls, options in ((IopeOutputSettings, {"channels": {1: {"min_percent": 20}}}),
                                 (IopeEnvironment, {"enabled": True, "group_cache": group_cache()})):
                before = pp.values()
                with self.assertRaises(PPEditError):
                    cls(self.store.load("IOPE1R1.xml")).configure(pp, **options)
                self.assertEqual(pp.values(), before)
                cases.append(cls.__name__)
        report["profile_refusals"] = [{"unit_type": "IOPE1R1", "firmware": "0.9.99",
                                        "editors": cases, "unchanged": True}]

    def test_profile_matrix_preservation_boundaries_and_save_reload(self):
        from research.local_cgate import LocalCGate
        self.store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        vendor = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"])
        specs = Path(os.environ["CBUS_UNITSPEC_DIR"])
        report = {"format": "cbus-iope-workflow-native-acceptance-v1", "backend": "owned-local-native",
                  "scope": "Bounded output thresholds/restrike and corridor controls on closed synthetic database units",
                  "physical_hardware_verified": False, "original_toolkit_form_executed": False,
                  "source_sha256": {"cgate.jar": sha256(vendor / "cgate.jar"),
                                    "cbusunits.xml": sha256(vendor / "unitspec/cbusunits.xml"),
                                    **{name: sha256(specs / name) for name in
                                       ("I_IOPE.xml", "IOPE1R1.xml", "IOPE2R2.xml", "IOPE2C4.xml")}},
                  "implementation_sha256": implementation_hashes(),
                  "profiles": [], "passed": False}
        service = LocalCGate(vendor, java=os.environ["CBUS_CGATE_JAVA"])
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
        with service, CGateClient("127.0.0.1", service.port, timeout=30) as client, \
                closed_network_project(client, "IW") as project:
            network = f"//{project}/254"
            database = NativeDatabase(client)
            database.add(network, "application", 56, "SyntheticLighting")
            for address in range(10, 31):
                database.add(network + "/56", "group", address, "SyntheticGroup" + str(address))
            client.command("PROJECT SAVE " + project)
            for index, (unit_type, catalog) in enumerate(PROFILES):
                for revision, firmware in enumerate(FIRMWARE):
                    with self.subTest(unit_type=unit_type, firmware=firmware):
                        self.exercise(client, network, 20 + index * 3 + revision,
                                      unit_type, catalog, firmware, report)
            self.refused_profile(client, network, report)
            self.cli_workflows(client, "127.0.0.1", service.port, network, report)
        report["native_service"] = {key: service.report[key] for key in
                                    ("vendor_jar_sha256", "java_version", "java_sha256",
                                     "listener_ownership_verified", "projects_adopted", "cleanup_complete",
                                     "process_exit_confirmed", "work_removed", "reserved_sockets_closed")}
        report["passed"] = (len(report["profiles"]) == 9 and report["native_service"]["cleanup_complete"])
        self.assertTrue(report["passed"])
        if path := os.environ.get("CBUS_IOPE_WORKFLOW_REPORT"):
            Path(path).write_text(json.dumps(report, indent=2) + "\n")


class IopeWorkflowNativeReceiptTest(unittest.TestCase):
    def test_committed_receipt_has_exact_profile_matrix_and_scoped_evidence(self):
        receipt = ROOT / "research/fixtures/iope-workflow-native-acceptance.json"
        text = receipt.read_text()
        report = json.loads(text)
        self.assertEqual(report["format"], "cbus-iope-workflow-native-acceptance-v1")
        self.assertTrue(report["passed"])
        self.assertEqual(report["implementation_sha256"],
                         {name: sha256(ROOT / name) for name in IMPLEMENTATION_FILES})
        self.assertFalse(report["physical_hardware_verified"])
        self.assertFalse(report["original_toolkit_form_executed"])
        expected = {(unit_type, catalog, firmware) for unit_type, catalog in PROFILES for firmware in FIRMWARE}
        self.assertEqual({(row["unit_type"], row["catalog_number"], row["firmware"])
                          for row in report["profiles"]}, expected)
        self.assertEqual(len(report["profiles"]), len(expected))
        for row in report["profiles"]:
            self.assertEqual(set(row["workflows"]), {"output", "environment"})
            self.assertTrue(row["save_reload_passed"])
            self.assertTrue(row["project_close_load_passed"])
            self.assertGreater(row["reloaded_parameter_count"], 100)
            self.assertGreater(len(row["positive"]), 5)
            self.assertGreater(len(row["refused_without_changes"]), 5)
            for observed in row["raw_byte_assertions"]:
                self.assertEqual(observed["actual"] & observed["mask"], observed["expected"])
        self.assertEqual({row["family"] for row in report["cli"]}, {"output", "environment"})
        for row in report["cli"]:
            for key in ("offline_plan_matches_dry_run", "dry_run_preserved_database",
                        "save_and_fresh_reload_passed", "stale_plan_refused_without_changes",
                        "project_close_load_passed"):
                self.assertTrue(row[key])
        self.assertTrue(next(row for row in report["cli"] if row["family"] == "environment")
                        ["unsupported_native_group_cache_refused_without_changes"])
        self.assertEqual(report["profile_refusals"], [{"unit_type": "IOPE1R1", "firmware": "0.9.99",
            "editors": ["IopeOutputSettings", "IopeEnvironment"], "unchanged": True}])
        service = report["native_service"]
        for key in ("listener_ownership_verified", "cleanup_complete", "process_exit_confirmed",
                    "work_removed", "reserved_sockets_closed"):
            self.assertTrue(service[key])
        self.assertFalse(service["projects_adopted"])
        self.assertEqual(service["vendor_jar_sha256"], report["source_sha256"]["cgate.jar"])
        for private_marker in ("/Users/", "/Volumes/", "Clipsal", "PRIVATE KEY", "127.0.0.1"):
            self.assertNotIn(private_marker, text)


if __name__ == "__main__":
    unittest.main()
