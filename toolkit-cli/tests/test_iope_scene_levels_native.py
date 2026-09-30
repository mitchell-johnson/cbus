"""Owned native acceptance for synthetic retained IOPE scene levels."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
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
from test_iope_workflow_native import NATIVE, REASON, ROOT, PROFILES, FIRMWARE, sha256, IopeWorkflowNativeTest
from test_iope_join_groups_native import seed, seed_scenes, scene_cache

IMPLEMENTATION_FILES = (
    "src/cbus_toolkit/iope_scene_levels.py", "src/cbus_toolkit/iope_scene_selectors.py",
    "src/cbus_toolkit/iope_workflow_cli.py", "src/cbus_toolkit/din_output_settings.py",
    "tests/test_iope_scene_levels_native.py", "tests/test_iope_join_groups_native.py",
    "tests/test_iope_workflow_native.py",
)


def implementation_hashes():
    result = {}
    for name in IMPLEMENTATION_FILES:
        path = ROOT / name
        if name.startswith("src/"):
            module = importlib.import_module(name.removeprefix("src/").removesuffix(".py").replace("/", "."))
            path = Path(module.__file__)
        result[name] = sha256(path)
    return result


def raw_scene(pp):
    value = bytes.fromhex(pp.get_raw_data(0xA2, 80).lines[-1].split("RawData=", 1)[1])
    if len(value) != 80:
        raise AssertionError("Native scene/header raw image is incomplete")
    return value


@unittest.skipUnless(NATIVE, REASON)
class IopeSceneLevelsNativeTest(unittest.TestCase):
    cli = IopeWorkflowNativeTest.cli
    refuse = IopeWorkflowNativeTest.refuse

    def check(self, pp, editor, row, label, *, scene, command, encoded, sync_levels=False, **options):
        before, raw_before = pp.values(), raw_scene(pp)
        result = editor.configure(pp, scene=scene, command=command, sync_levels=sync_levels,
                                  group_cache=scene_cache(), **options)
        after, actual = pp.values(), raw_scene(pp)
        self.assertTrue(result["verified"], label)
        self.assertLessEqual(set(result["changes"]), {"SceneTable"})
        untouched = set(before) - set(result["changes"])
        self.assertEqual({n: before[n] for n in untouched}, {n: after[n] for n in untouched})
        expected = bytearray(raw_before)
        indices = range(8) if sync_levels else [command - 1]
        addresses = [0xB2 + (scene - 1) * 16 + index * 2 + 1 for index in indices]
        for address in addresses:
            expected[address - 0xA2] = encoded[addresses.index(address)] if isinstance(encoded, tuple) else encoded
        self.assertEqual(actual, bytes(expected), label)
        row["positive"].append({"case": label, "changed_fields": sorted(result["changes"]),
                                 "unrelated_parameters_preserved": len(untouched),
                                 "selected_scene": scene, "synchronized": sync_levels})
        row["raw_vectors"].append({"start": 0xA2, "count": 80,
                                    "before_sha256": hashlib.sha256(raw_before).hexdigest(),
                                    "owned_level_addresses": addresses,
                                    "expected_hex": bytes(expected).hex(), "actual_hex": actual.hex(),
                                    "preserved_byte_count": 80 - len(addresses)})

    def exercise(self, client, network, address, unit_type, catalog, firmware, report):
        from cbus_toolkit.iope_scene_levels import IopeSceneLevels, plan_from_dict
        NativeDatabase(client).create_unit(network, address, "SyntheticLevels" + str(address),
                                           unit_type, firmware, catalog_number=catalog)
        source = f"/db{network}/p/{address}"
        row = {"unit_type": unit_type, "catalog_number": catalog, "firmware": firmware,
               "positive": [], "refused_without_changes": [], "raw_vectors": []}
        with Programmer(client).load(network, source) as pp:
            seed(pp); seed_scenes(pp)
            editor = IopeSceneLevels(self.store.load(unit_type + ".xml"))
            for scene in range(1, 5):
                for command, level in ((1, 0), (8, 255), (4, 128)):
                    self.check(pp, editor, row, f"raw-scene-{scene}-command-{command}",
                               scene=scene, command=command, raw_level=level, encoded=level)
                self.check(pp, editor, row, f"percent-scene-{scene}",
                           scene=scene, command=2, percent=50, encoded=128)
                self.check(pp, editor, row, f"sync-raw-scene-{scene}",
                           scene=scene, command=6, raw_level=1, encoded=1, sync_levels=True)
                self.check(pp, editor, row, f"sync-percent-scene-{scene}",
                           scene=scene, command=3, percent=100, encoded=255, sync_levels=True)
            seed_scenes(pp)
            table = list(parse_values(pp.values()["SceneTable"]))
            table[1:16:2] = [125, 126, 127, 128, 129, 1, 255, 0]
            pp.set("SceneTable", " ".join(map(str, table)))
            self.check(pp, editor, row, "sync-percent-equality-per-command", scene=1, command=1,
                       percent=50, sync_levels=True, encoded=(127, 126, 127, 128, 127, 127, 127, 127))
            self.check(pp, editor, row, "raw-equality-noop", scene=1, command=2, raw_level=126, encoded=126)
            for label, opts in (("raw-negative", {"raw_level": -1}), ("raw-overflow", {"raw_level": 256}),
                                ("percent-negative", {"percent": -1}), ("percent-overflow", {"percent": 101}),
                                ("both-modes", {"raw_level": 1, "percent": 1}), ("no-mode", {}),
                                ("boolean-level", {"raw_level": True}), ("boolean-command", {"command": True, "raw_level": 1}),
                                ("scene-low", {"scene": 0, "raw_level": 1}), ("scene-high", {"scene": 5, "raw_level": 1}),
                                ("command-low", {"command": 0, "raw_level": 1}), ("command-high", {"command": 9, "raw_level": 1}),
                                ("nonboolean-sync", {"sync_levels": 1, "raw_level": 1})):
                self.refuse(pp, editor, row, label, group_cache=scene_cache(),
                            **({"scene": 1, "command": 1} | opts))
            for name, value in (("SceneIndex", "1 1 2 3"), ("SceneTablePointer", "157 194 210 226"),
                                ("ActionSelector", "10 11 12 255"), ("Application", "202 57")):
                seed(pp); seed_scenes(pp); pp.set(name, value)
                self.refuse(pp, editor, row, "invalid-" + name, scene=1, command=1,
                            raw_level=10, group_cache=scene_cache())
            for field in ("Application", "SceneTriggerGroup", "SceneIndex", "SceneCommandRampRate",
                          "ActionSelector", "ActionSelectorAllOff", "SceneTablePointer", "SceneTable"):
                seed(pp); seed_scenes(pp)
                plan = editor.plan(pp.values(), identity=(unit_type, firmware, catalog),
                                   scene=1, command=1, raw_level=10, group_cache=scene_cache())
                changed = list(parse_values(pp.values()[field])); changed[0] ^= 1
                pp.set(field, " ".join(map(str, changed))); before = pp.values()
                with self.assertRaises(PPEditError): editor.apply(pp, plan)
                self.assertEqual(pp.values(), before); row["refused_without_changes"].append("stale-" + field)
            seed(pp); seed_scenes(pp)
            plan = editor.plan(pp.values(), identity=(unit_type, firmware, catalog),
                               scene=2, command=8, raw_level=12, group_cache=scene_cache())
            before = pp.values()
            with self.assertRaises(PPEditError): editor.apply(pp, replace(plan, changes={"ActionSelector": (30, 11, 12, 13)}))
            self.assertEqual(pp.values(), before); row["refused_without_changes"].append("forged-write")
            document = plan.as_dict(); document["unexpected"] = True
            with self.assertRaises(PPEditError): plan_from_dict(document)
            row["refused_without_changes"].append("forged-fields")
            self.check(pp, editor, row, "final-independent-component-save", scene=2, command=8,
                       raw_level=12, encoded=12)
            after = pp.values(); pp.save_to_source()
        project = network.split("/")[2]
        for operation in ("SAVE", "CLOSE", "LOAD", "USE"):
            self.assertEqual(client.command(f"PROJECT {operation} {project}").code, 200)
        with Programmer(client).load(network, source) as pp: self.assertEqual(pp.values(), after)
        row.update(save_reload_passed=True, project_close_load_passed=True, reloaded_parameter_count=len(after))
        report["profiles"].append(row)

    def cli_workflow(self, client, service, network, report):
        NativeDatabase(client).create_unit(network, 50, "SyntheticCliLevels", "IOPE2C4", "1.2.00",
                                           catalog_number="5752PP/2R/2D")
        source = f"/db{network}/p/50"
        with Programmer(client).load(network, source) as pp:
            seed(pp); seed_scenes(pp); pp.save_to_source()
        client.command("PROJECT SAVE " + network.split("/")[2])
        prefix = ("--spec-dir", os.environ["CBUS_UNITSPEC_DIR"], "scene-levels")
        database = (*prefix, "database", "--host", "127.0.0.1", "--port", service.port,
                    "--source", source, "--lock-address", network)
        original = self.cli(*database, "--export")
        with tempfile.TemporaryDirectory(prefix="iope-levels-cli-") as folder:
            snapshot, edits_file, plan_file = [Path(folder) / n for n in ("snapshot.json", "edits.json", "plan.json")]
            snapshot.write_text(json.dumps(original))
            self.assertEqual(self.cli(*prefix, "show", snapshot), self.cli(*database, "--show"))
            edits = {"scene": 3, "command": 8, "percent": 40, "sync_levels": True, "group_cache": scene_cache()}
            edits_file.write_text(json.dumps(edits))
            plan = self.cli(*prefix, "plan", snapshot, "--edits", edits_file)
            plan_file.write_text(json.dumps(plan))
            preview = self.cli(*database, "--plan", plan_file, "--dry-run", "--exclusive-project")
            self.assertEqual(preview["changes"], plan["changes"])
            self.assertFalse(preview["pp_save_attempted"]); self.assertFalse(preview["saved"])
            self.assertEqual(self.cli(*database, "--export"), original)
            applied = self.cli(*database, "--plan", plan_file, "--exclusive-project")
            for flag in ("saved", "pp_save_completed", "project_save_completed", "fresh_reload_verified"):
                self.assertTrue(applied[flag])
            after = self.cli(*database, "--export")
            stale = self.cli(*database, "--plan", plan_file, "--exclusive-project", status=1)
            self.assertIn("changed since", stale["error"]); self.assertEqual(self.cli(*database, "--export"), after)
            for label, cache in (("false-group", deepcopy(scene_cache())), ("incomplete-actions", deepcopy(scene_cache()))):
                if label == "false-group": cache["applications"][0]["groups"].append(41)
                else: cache["action_selectors"][0]["addresses"].append(40)
                edits.update(raw_level=10, group_cache=cache); edits.pop("percent", None)
                snapshot.write_text(json.dumps(after)); edits_file.write_text(json.dumps(edits))
                plan_file.write_text(json.dumps(self.cli(*prefix, "plan", snapshot, "--edits", edits_file)))
                error = self.cli(*database, "--plan", plan_file, "--exclusive-project", status=1)
                self.assertIn("current native database" if label == "false-group" else "complete native group levels", error["error"])
                self.assertEqual(self.cli(*database, "--export"), after)
        project = network.split("/")[2]
        for operation in ("CLOSE", "LOAD", "USE"):
            self.assertEqual(client.command(f"PROJECT {operation} {project}").code, 200)
        self.assertEqual(self.cli(*database, "--export"), after)
        report["cli"] = {"family": "scene-levels", "offline_plan_matches_dry_run": True,
                         "dry_run_preserved_database": True, "save_and_fresh_reload_passed": True,
                         "stale_plan_refused_without_changes": True, "group_metadata_refused_without_changes": True,
                         "action_inventory_refused_without_changes": True, "project_close_load_passed": True,
                         "unrelated_parameters_preserved": applied["unrelated_parameters_preserved"]}

    def test_scene_levels_native_matrix(self):
        from cbus_toolkit.iope_scene_levels import IopeSceneLevels
        from research.local_cgate import LocalCGate
        self.store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        vendor = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"]); specs = Path(os.environ["CBUS_UNITSPEC_DIR"])
        report = {"format": "cbus-iope-scene-levels-native-acceptance-v1", "backend": "owned-local-native",
                  "scope": "Fresh non-live SceneManager retained command levels; component PP persistence only",
                  "physical_hardware_verified": False, "original_toolkit_form_executed": False,
                  "whole_scene_manager_save_executed": False,
                  "source_sha256": {"cgate.jar": sha256(vendor / "cgate.jar"),
                                    "cbusunits.xml": sha256(vendor / "unitspec/cbusunits.xml"),
                                    **{n: sha256(specs / n) for n in ("I_IOPE.xml", "IOPE1R1.xml", "IOPE2R2.xml", "IOPE2C4.xml")}},
                  "implementation_sha256": implementation_hashes(), "profiles": [], "passed": False}
        service = LocalCGate(vendor, java=os.environ["CBUS_CGATE_JAVA"])
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
        with service, CGateClient("127.0.0.1", service.port, timeout=30) as client, closed_network_project(client, "IL") as project:
            network = f"//{project}/254"; database = NativeDatabase(client)
            for app in scene_cache()["applications"]:
                database.add(network, "application", app["address"], "SyntheticApp" + str(app["address"]))
                for group in app["groups"]:
                    database.add(network + "/" + str(app["address"]), "group", group, "SyntheticGroup" + str(group))
            for action in scene_cache()["action_selectors"][0]["addresses"]:
                database.add(network + "/202/7", "level", action, "SyntheticAction" + str(action))
            client.command("PROJECT SAVE " + project)
            for index, (unit_type, catalog) in enumerate(PROFILES):
                for revision, firmware in enumerate(FIRMWARE):
                    self.exercise(client, network, 20 + index * 3 + revision, unit_type, catalog, firmware, report)
            database.create_unit(network, 40, "SyntheticOldLevels", "IOPE1R1", "0.9.99", catalog_number="5752PP/1R")
            with Programmer(client).load(network, f"/db{network}/p/40") as pp:
                before = pp.values()
                with self.assertRaises(PPEditError):
                    IopeSceneLevels(self.store.load("IOPE1R1.xml")).configure(pp, scene=1, command=1, raw_level=10, group_cache=scene_cache())
                self.assertEqual(pp.values(), before)
            report["profile_refusals"] = [{"unit_type": "IOPE1R1", "firmware": "0.9.99", "unchanged": True}]
            self.cli_workflow(client, service, network, report)
        report["native_service"] = {key: service.report[key] for key in
                                    ("vendor_jar_sha256", "java_version", "java_sha256", "listener_ownership_verified",
                                     "projects_adopted", "cleanup_complete", "process_exit_confirmed", "work_removed", "reserved_sockets_closed")}
        report["passed"] = len(report["profiles"]) == 9 and report["native_service"]["cleanup_complete"]
        self.assertTrue(report["passed"])
        if path := os.environ.get("CBUS_IOPE_SCENE_LEVELS_REPORT"):
            Path(path).write_text(json.dumps(report, indent=2) + "\n")


class IopeSceneLevelsNativeReceiptTest(unittest.TestCase):
    def test_receipt_binds_profiles_raw_images_and_implementation(self):
        report = json.loads((ROOT / "research/fixtures/iope-scene-levels-native-acceptance.json").read_text())
        self.assertTrue(report["passed"]); self.assertEqual(report["implementation_sha256"], {n: sha256(ROOT / n) for n in IMPLEMENTATION_FILES})
        for flag in ("physical_hardware_verified", "original_toolkit_form_executed", "whole_scene_manager_save_executed"):
            self.assertFalse(report[flag])
        self.assertEqual({(r["unit_type"], r["catalog_number"], r["firmware"]) for r in report["profiles"]},
                         {(u, c, f) for u, c in PROFILES for f in FIRMWARE})
        for row in report["profiles"]:
            self.assertEqual(len(row["positive"]), 27); self.assertGreaterEqual(len(row["refused_without_changes"]), 27)
            self.assertTrue(row["save_reload_passed"]); self.assertTrue(row["project_close_load_passed"])
            for vector in row["raw_vectors"]:
                self.assertEqual(vector["expected_hex"], vector["actual_hex"])
                self.assertEqual(len(bytes.fromhex(vector["actual_hex"])), vector["count"])
        for key, value in report["native_service"].items():
            if key.endswith("verified") or key in ("cleanup_complete", "process_exit_confirmed", "work_removed", "reserved_sockets_closed"):
                self.assertTrue(value)
        self.assertFalse(report["native_service"]["projects_adopted"])
        for key, value in report["cli"].items():
            if key.endswith("passed") or key.endswith("changes") or key in ("offline_plan_matches_dry_run", "dry_run_preserved_database"):
                self.assertTrue(value)


if __name__ == "__main__":
    unittest.main()
