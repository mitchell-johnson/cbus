"""Owned-loopback Join group acceptance; synthetic closed database units only."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.pp_editor import PPEditError, parse_values
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitSpecStore
from test_macros import closed_network_project
import test_iope_workflow_native as prior
from test_iope_workflow_native import FIRMWARE, NATIVE, PROFILES, REASON, ROOT, sha256, raw_byte

IMPLEMENTATION_FILES = ("src/cbus_toolkit/iope_join_groups.py", "src/cbus_toolkit/iope_scene_selectors.py", "src/cbus_toolkit/iope_environment.py",
                        "src/cbus_toolkit/iope_workflow_cli.py", "tests/test_iope_join_groups_native.py",
                        "tests/test_iope_workflow_native.py")
GROUP_FIELDS = ("FirstJoinPrimaryApplication", "SecondJoinPrimaryApplication",
                "FirstJoinEnableControlApplication", "SecondJoinEnableControlApplication")


def implementation_hashes():
    result = {}
    for name in IMPLEMENTATION_FILES:
        path = ROOT / name
        if name.startswith("src/"):
            module = importlib.import_module(name.removeprefix("src/").removesuffix(".py").replace("/", "."))
            path = Path(module.__file__)
        result[name] = sha256(path)
    return result


def group_cache():
    return {"format": "cbus-iope-environment-groups-v1",
            "source": "owned native synthetic application/group objects",
            "applications": [{"address": app, "groups": list(range(0, 41)) + [254]}
                             for app in (56, 57, 203)]}


def seed(pp, branch="primary"):
    values = ((20, 21, 255, 255) if branch == "primary" else (255, 255, 20, 21))
    for name, value in zip(GROUP_FIELDS, values):
        pp.set(name, str(value))
    for name, value in {"Application": "56 57", "InputGroupAddress": "10 11 12 13 14 15 16 17",
                        "SecondApplicationBlocks": "0", "AreaGroupAddress": "18",
                        "FirstCorridorLinkEnable": "1", "SecondCorridorLinkEnable": "1",
                        "CorridorGroupBlock": "2", "FirstCorridorOfficeGroupBlock": "3",
                        "SecondCorridorOfficeGroupBlock": "4", "CorridorMasterGroup": "19"}.items():
        pp.set(name, value)




def scene_cache():
    cache = group_cache()
    cache["format"] = "cbus-iope-scene-selector-groups-v1"
    cache["applications"].append({"address": 202, "groups": [7]})
    cache["action_selectors"] = [{"application": 202, "group": 7,
                                  "addresses": [10, 11, 12, 13, 20, 21, 22, 23, 30, 31, 254]}]
    return cache


def seed_scenes(pp):
    for name, value in {"SceneTriggerGroup": "7", "SceneIndex": "0 1 2 3",
                        "SceneCommandRampRate": "0 1 2 3", "ActionSelector": "10 11 12 13",
                        "ActionSelectorAllOff": "20 21 22 23",
                        "SceneTablePointer": "178 194 210 226",
                        "SceneTable": " ".join(str(v) for g in range(1, 33) for v in (g, 128))}.items():
        pp.set(name, value)


@unittest.skipUnless(NATIVE, REASON)
class IopeJoinGroupsNativeTest(unittest.TestCase):
    refuse = prior.IopeWorkflowNativeTest.refuse
    cli = prior.IopeWorkflowNativeTest.cli

    def check(self, pp, editor, row, label, expected, **options):
        neighbors = {address: raw_byte(pp, address) for address in (0x62, 0x67, 0x68, 0x69)}
        result = prior.IopeWorkflowNativeTest.check(
            self, pp, editor, row, label,
            raw=tuple((address, 255, value) for address, value in zip(range(0x63, 0x67), expected)),
            group_cache=group_cache(), **options)
        for address, value in neighbors.items():
            self.assertEqual(raw_byte(pp, address), value, (label, address))
            row["raw_byte_assertions"].append({"address": address, "mask": 255,
                                               "expected": value, "actual": value})
        self.assertEqual([parse_values(pp.values()[name])[0] for name in GROUP_FIELDS], list(expected))
        return result

    def exercise(self, client, network, address, unit_type, catalog, firmware, report):
        from cbus_toolkit.iope_join_groups import IopeJoinGroups, plan_from_dict
        NativeDatabase(client).create_unit(network, address, "SyntheticJoin" + str(address),
                                           unit_type, firmware, catalog_number=catalog)
        source = f"/db{network}/p/{address}"
        row = {"unit_type": unit_type, "catalog_number": catalog, "firmware": firmware,
               "positive": [], "refused_without_changes": [], "raw_byte_assertions": []}
        with Programmer(client).load(network, source) as pp:
            editor = IopeJoinGroups(self.store.load(unit_type + ".xml"))
            for branch in ("primary", "enable-control"):
                seed(pp, branch)
                def expected(first, second):
                    return (first, second, 255, 255) if branch == "primary" else (255, 255, first, second)
                self.check(pp, editor, row, branch + "-first-then-second", expected(22, 23),
                           first_group=22, second_group=23)
                self.check(pp, editor, row, branch + "-same-address", expected(22, 23), first_group=22)
                self.check(pp, editor, row, branch + "-ordered-release-first", expected(24, 22),
                           first_group=24, second_group=22)
                self.check(pp, editor, row, branch + "-restore-second", expected(25, 23),
                           first_group=25, second_group=23)
                self.check(pp, editor, row, branch + "-restore-first", expected(22, 23), first_group=22)
                self.check(pp, editor, row, branch + "-second-unused", expected(22, 255), second_group=255)
                self.check(pp, editor, row, branch + "-byte-boundaries", expected(0, 254),
                           first_group=0, second_group=254)
                self.refuse(pp, editor, row, branch + "-first-unused-refused", first_group=255,
                            group_cache=group_cache())
                seed(pp, branch)
                for label, options in (("negative", {"first_group": -1}), ("overflow", {"second_group": 256}),
                                       ("boolean", {"first_group": True}), ("missing-positive-object", {"first_group": 41}),
                                       ("same-opposite-object", {"first_group": 21})):
                    self.refuse(pp, editor, row, branch + "-" + label, group_cache=group_cache(), **options)
            seed(pp)
            for index in range(8):
                self.refuse(pp, editor, row, "input-block-" + str(index + 1),
                            first_group=10 + index, group_cache=group_cache())
            for label, address in (("primary-area", 18), ("active-corridor", 12)):
                self.refuse(pp, editor, row, label, first_group=address, group_cache=group_cache())
            seed(pp)
            pp.set("SecondApplicationBlocks", "255")
            self.check(pp, editor, row, "same-address-other-application-allowed", (10, 21, 255, 255), first_group=10)
            seed(pp)
            for label, change in (("dual-first", {"FirstJoinEnableControlApplication": "20"}),
                                  ("mixed-second", {"SecondJoinPrimaryApplication": "255", "SecondJoinEnableControlApplication": "21"}),
                                  ("no-existing-first", {"FirstJoinPrimaryApplication": "255"}),
                                  ("canonical-environment-delta", {"FirstCorridorOfficeGroupBlock": "2"})):
                seed(pp)
                for name, value in change.items():
                    pp.set(name, value)
                self.refuse(pp, editor, row, label, first_group=22, group_cache=group_cache())
            seed(pp)
            for name, value in (("AreaGroupAddress", "24"), ("InputGroupAddress", "24 11 12 13 14 15 16 17"),
                                ("Application", "56 56"), ("CorridorMasterGroup", "24"),
                                ("FirstJoinPrimaryApplication", "24")):
                seed(pp)
                plan = editor.plan(pp.values(), identity=(unit_type, firmware, catalog),
                                   first_group=22, group_cache=group_cache())
                pp.set(name, value)
                before = pp.values()
                with self.assertRaises(PPEditError):
                    editor.apply(pp, plan)
                self.assertEqual(pp.values(), before)
                row["refused_without_changes"].append("stale-" + name)
            seed(pp)
            plan = editor.plan(pp.values(), identity=(unit_type, firmware, catalog),
                               first_group=22, group_cache=group_cache())
            for label, forged in (("forged-changes", replace(plan, changes={GROUP_FIELDS[0]: (24,)})),
                                  ("forged-firmware", replace(plan, details={**plan.details, "firmware": "1.9.00"})),
                                  ("forged-schema", replace(plan, spec_filename="IOPE1R1-forged.xml"))):
                before = pp.values()
                with self.assertRaises(PPEditError):
                    editor.apply(pp, forged)
                self.assertEqual(pp.values(), before)
                row["refused_without_changes"].append(label)
            malformed = plan.as_dict()
            malformed["unexpected"] = True
            with self.assertRaises(PPEditError):
                plan_from_dict(malformed)
            row["refused_without_changes"].append("forged-plan-fields")
            self.check(pp, editor, row, "final-save-projection", (22, 23, 255, 255), first_group=22, second_group=23)
            self.scenes(pp, row)
            after = pp.values()
            pp.save_to_source()
        project = network.split("/")[2]
        for operation in ("SAVE", "CLOSE", "LOAD", "USE"):
            self.assertEqual(client.command(f"PROJECT {operation} {project}").code, 200)
        with Programmer(client).load(network, source) as pp:
            self.assertEqual(pp.values(), after)
        row.update(save_reload_passed=True, project_close_load_passed=True, reloaded_parameter_count=len(after))
        report["profiles"].append(row)


    def scenes(self, pp, row):
        from cbus_toolkit.iope_scene_selectors import IopeSceneSelectors
        seed(pp)
        seed_scenes(pp)
        editor = IopeSceneSelectors(self.store.load(pp.unit_type + ".xml"))
        for scene in range(1, 5):
            seed_scenes(pp)
            prior.IopeWorkflowNativeTest.check(self, pp, editor, row, "scene-normal-" + str(scene),
                scene=scene, normal_selector=30, group_cache=scene_cache(),
                raw=((0xA6 + scene - 1, 255, 30), (0xAA + scene - 1, 255, 19 + scene)))
            prior.IopeWorkflowNativeTest.check(self, pp, editor, row, "scene-all-off-" + str(scene),
                scene=scene, all_off_selector=254, group_cache=scene_cache(),
                raw=((0xA6 + scene - 1, 255, 30), (0xAA + scene - 1, 255, 254)))
        seed_scenes(pp)
        for label, opts in (("out-of-range-scene", {"scene": 5, "normal_selector": 30}),
                            ("unused-selector", {"scene": 1, "normal_selector": 255}),
                            ("zero-selector", {"scene": 1, "normal_selector": 0}),
                            ("duplicate-selector", {"scene": 1, "normal_selector": 21}),
                            ("both-selectors", {"scene": 1, "normal_selector": 30, "all_off_selector": 31}),
                            ("unresolved-selector", {"scene": 1, "normal_selector": 40})):
            self.refuse(pp, editor, row, "scene-" + label, group_cache=scene_cache(), **opts)
        for name, value in (("SceneIndex", "1 1 2 3"), ("SceneTablePointer", "179 194 210 226"),
                            ("ActionSelectorAllOff", "10 21 22 23"),
                            ("SceneTable", " ".join(str(v) for g in [2, *range(2, 33)] for v in (g, 128)))):
            seed_scenes(pp)
            pp.set(name, value)
            self.refuse(pp, editor, row, "scene-invalid-" + name, scene=1, normal_selector=30, group_cache=scene_cache())
        seed_scenes(pp)
        plan = editor.plan(pp.values(), identity=(pp.unit_type, pp.firmware, pp.catalog_number),
                           scene=1, normal_selector=30, group_cache=scene_cache())
        pp.set("SceneCommandRampRate", "1 1 2 3")
        before = pp.values()
        with self.assertRaises(PPEditError):
            editor.apply(pp, plan)
        self.assertEqual(pp.values(), before)
        row["refused_without_changes"].append("scene-stale-ramp-rate")
        seed_scenes(pp)
        prior.IopeWorkflowNativeTest.check(self, pp, editor, row, "scene-final-selector",
            scene=2, normal_selector=30, group_cache=scene_cache(), raw=((0xA7, 255, 30),))

    def cli_workflows(self, client, host, port, network, report):
        cases, persisted = [], []
        for offset, family in enumerate(("join-groups", "scene-selectors")):
            address = 50 + offset
            NativeDatabase(client).create_unit(network, address, "SyntheticCli" + str(address),
                                               "IOPE2C4", "1.2.00", catalog_number="5752PP/2R/2D")
            source = f"/db{network}/p/{address}"
            with Programmer(client).load(network, source) as pp:
                seed(pp)
                if family == "scene-selectors":
                    seed_scenes(pp)
                    edits = {"scene": 2, "normal_selector": 30, "group_cache": scene_cache()}
                else:
                    edits = {"first_group": 22, "second_group": 23, "group_cache": group_cache()}
                pp.save_to_source()
            client.command("PROJECT SAVE " + network.split("/")[2])
            prefix = ("--spec-dir", os.environ["CBUS_UNITSPEC_DIR"], family)
            database = (*prefix, "database", "--host", host, "--port", port,
                        "--lock-address", network, "--source", source)
            original = self.cli(*database, "--export")
            initial_view = self.cli(*database, "--show")
            with tempfile.TemporaryDirectory(prefix="iope-selectors-cli-") as folder:
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
                bad_cache = deepcopy(edits["group_cache"])
                if family == "join-groups":
                    bad_cache["applications"][0]["groups"].append(41)
                    edits.update(first_group=24, group_cache=bad_cache)
                else:
                    bad_cache["action_selectors"][0]["addresses"].append(40)
                    edits.update(normal_selector=31, group_cache=bad_cache)
                snapshot.write_text(json.dumps(after))
                edits_file.write_text(json.dumps(edits))
                bad_plan = self.cli(*prefix, "plan", snapshot, "--edits", edits_file)
                plan_file.write_text(json.dumps(bad_plan))
                error = self.cli(*database, "--plan", plan_file, "--exclusive-project", status=1)
                self.assertIn("current native database" if family == "join-groups" else "complete native group levels",
                              error["error"])
                self.assertEqual(self.cli(*database, "--export"), after)
                cases.append({"family": family, "offline_plan_matches_dry_run": True,
                              "dry_run_preserved_database": True, "save_and_fresh_reload_passed": True,
                              "stale_plan_refused_without_changes": True,
                              "unsupported_native_group_cache_refused_without_changes": True,
                              "unrelated_parameters_preserved": applied["unrelated_parameters_preserved"]})
                persisted.append((database, after))
        project = network.split("/")[2]
        for operation in ("CLOSE", "LOAD", "USE"):
            self.assertEqual(client.command(f"PROJECT {operation} {project}").code, 200)
        for (database, after), case in zip(persisted, cases):
            self.assertEqual(self.cli(*database, "--export"), after)
            case["project_close_load_passed"] = True
        report["cli"] = cases

    def test_join_groups_and_scene_selectors_profile_matrix(self):
        from cbus_toolkit.iope_join_groups import IopeJoinGroups
        from cbus_toolkit.iope_scene_selectors import IopeSceneSelectors
        from research.local_cgate import LocalCGate
        self.store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        vendor, specs = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"]), Path(os.environ["CBUS_UNITSPEC_DIR"])
        report = {"format": "cbus-iope-join-groups-native-acceptance-v1", "backend": "owned-local-native",
                  "scope": "Bounded Join group and Scene selector controls on closed synthetic database units",
                  "physical_hardware_verified": False, "original_toolkit_form_executed": False,
                  "source_sha256": {"cgate.jar": sha256(vendor / "cgate.jar"),
                                    "cbusunits.xml": sha256(vendor / "unitspec/cbusunits.xml"),
                                    **{name: sha256(specs / name) for name in
                                       ("I_IOPE.xml", "IOPE1R1.xml", "IOPE2R2.xml", "IOPE2C4.xml")}},
                  "implementation_sha256": implementation_hashes(), "profiles": [], "passed": False}
        service = LocalCGate(vendor, java=os.environ["CBUS_CGATE_JAVA"])
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
        with service, CGateClient("127.0.0.1", service.port, timeout=30) as client, \
                closed_network_project(client, "IJ") as project:
            network = f"//{project}/254"
            database = NativeDatabase(client)
            for app in scene_cache()["applications"]:
                application = app["address"]
                database.add(network, "application", application, "SyntheticApplication" + str(application))
                for address in app["groups"]:
                    database.add(network + "/" + str(application), "group", address, "SyntheticGroup" + str(address))
            for row in scene_cache()["action_selectors"]:
                for address in row["addresses"]:
                    response = database.add(network + "/202/7", "level", address, "SyntheticAction" + str(address))
                    if address == 30:
                        oid = next(line.split("OID=", 1)[1] for line in response.lines if "OID=" in line)
                        database.set("!" + oid + "/Value", 99)
            client.command("PROJECT SAVE " + project)
            for index, (unit_type, catalog) in enumerate(PROFILES):
                for revision, firmware in enumerate(FIRMWARE):
                    with self.subTest(unit_type=unit_type, firmware=firmware):
                        self.exercise(client, network, 20 + index * 3 + revision, unit_type, catalog, firmware, report)
            NativeDatabase(client).create_unit(network, 40, "SyntheticOld", "IOPE1R1", "0.9.99",
                                               catalog_number="5752PP/1R")
            with Programmer(client).load(network, f"/db{network}/p/40") as pp:
                for cls, opts in ((IopeJoinGroups, {"first_group": 22, "group_cache": group_cache()}),
                                  (IopeSceneSelectors, {"scene": 1, "normal_selector": 30, "group_cache": scene_cache()})):
                    before = pp.values()
                    with self.assertRaises(PPEditError):
                        cls(self.store.load("IOPE1R1.xml")).configure(pp, **opts)
                    self.assertEqual(pp.values(), before)
            report["action_address_differs_from_value"] = {"address": 30, "value": 99, "selector_used_address": True}
            report["profile_refusals"] = [{"unit_type": "IOPE1R1", "firmware": "0.9.99", "unchanged": True}]
            self.cli_workflows(client, "127.0.0.1", service.port, network, report)
        report["native_service"] = {key: service.report[key] for key in
                                    ("vendor_jar_sha256", "java_version", "java_sha256",
                                     "listener_ownership_verified", "projects_adopted", "cleanup_complete",
                                     "process_exit_confirmed", "work_removed", "reserved_sockets_closed")}
        report["passed"] = len(report["profiles"]) == 9 and report["native_service"]["cleanup_complete"]
        self.assertTrue(report["passed"])
        if path := os.environ.get("CBUS_IOPE_JOIN_GROUPS_REPORT"):
            Path(path).write_text(json.dumps(report, indent=2) + "\n")


class IopeJoinGroupsNativeReceiptTest(unittest.TestCase):
    def test_receipt_is_scoped_complete_and_bound_to_submitted_sources(self):
        text = (ROOT / "research/fixtures/iope-join-groups-native-acceptance.json").read_text()
        report = json.loads(text)
        self.assertEqual(report["format"], "cbus-iope-join-groups-native-acceptance-v1")
        self.assertTrue(report["passed"])
        self.assertFalse(report["physical_hardware_verified"])
        self.assertFalse(report["original_toolkit_form_executed"])
        self.assertEqual(report["implementation_sha256"],
                         {name: sha256(ROOT / name) for name in IMPLEMENTATION_FILES})
        expected = {(unit_type, catalog, firmware) for unit_type, catalog in PROFILES for firmware in FIRMWARE}
        self.assertEqual({(row["unit_type"], row["catalog_number"], row["firmware"])
                          for row in report["profiles"]}, expected)
        self.assertEqual(len(report["profiles"]), 9)
        for row in report["profiles"]:
            self.assertTrue(row["save_reload_passed"])
            self.assertTrue(row["project_close_load_passed"])
            self.assertGreater(row["reloaded_parameter_count"], 100)
            self.assertGreater(len(row["refused_without_changes"]), 25)
            self.assertGreater(len(row["raw_byte_assertions"]), 70)
            for observed in row["raw_byte_assertions"]:
                self.assertEqual(observed["actual"] & observed["mask"], observed["expected"])
        self.assertEqual({row["family"] for row in report["cli"]}, {"join-groups", "scene-selectors"})
        for row in report["cli"]:
            for key in ("offline_plan_matches_dry_run", "dry_run_preserved_database", "save_and_fresh_reload_passed",
                        "stale_plan_refused_without_changes", "project_close_load_passed",
                        "unsupported_native_group_cache_refused_without_changes"):
                self.assertTrue(row[key])
        service = report["native_service"]
        for key in ("listener_ownership_verified", "cleanup_complete", "process_exit_confirmed",
                    "work_removed", "reserved_sockets_closed"):
            self.assertTrue(service[key])
        self.assertFalse(service["projects_adopted"])
        self.assertEqual(service["vendor_jar_sha256"], report["source_sha256"]["cgate.jar"])
        for marker in ("/Users/", "/Volumes/", "Clipsal", "PRIVATE KEY", "127.0.0.1"):
            self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
