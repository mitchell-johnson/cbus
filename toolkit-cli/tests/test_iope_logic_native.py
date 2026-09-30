"""Owned-native acceptance for IOPE logic and Join Recovery controls.

This is separate from the threshold/corridor receipt. Every network is closed,
all units and groups are synthetic, and PP sources are database addresses.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.pp_editor import PPEditError
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitSpecStore
from test_macros import closed_network_project
import test_iope_workflow_native as prior
from test_iope_workflow_native import FIRMWARE, NATIVE, PROFILES, REASON, ROOT, sha256

IMPLEMENTATION_FILES = ("src/cbus_toolkit/iope_logic.py", "src/cbus_toolkit/iope_join_recovery.py",
                        "src/cbus_toolkit/iope_workflow_cli.py", "src/cbus_toolkit/iope_environment.py",
                        "src/cbus_toolkit/iope_block_timer.py",
                        "tests/test_iope_logic_native.py", "tests/test_iope_workflow_native.py")


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
            "applications": [{"address": 56, "groups": list(range(10, 31))},
                             {"address": 203, "groups": [40, 41]}]}


def seed_join(pp, branch):
    values = ((20, 21, 255, 255) if branch == "primary" else (255, 255, 40, 41))
    for name, value in zip(("FirstJoinPrimaryApplication", "SecondJoinPrimaryApplication",
                            "FirstJoinEnableControlApplication", "SecondJoinEnableControlApplication"), values):
        pp.set(name, str(value))


@unittest.skipUnless(NATIVE, REASON)
class IopeLogicNativeTest(unittest.TestCase):
    refuse = prior.IopeWorkflowNativeTest.refuse
    cli = prior.IopeWorkflowNativeTest.cli

    def check(self, pp, editor, row, label, *, arrays=None, **options):
        result = prior.IopeWorkflowNativeTest.check(self, pp, editor, row, label, **options)
        if arrays:
            after = pp.values()
            for name, expected in arrays.items():
                actual = [int(value, 16 if value.lower().startswith("0x") else 10) for value in after[name].split()]
                self.assertEqual(actual, list(expected), (label, name))
                row["full_array_assertions"].append({"case": label, "parameter": name,
                                                      "expected": list(expected), "actual": actual})
        return result

    def join_recovery(self, pp, row):
        from cbus_toolkit.iope_join_recovery import IopeJoinRecovery
        editor = IopeJoinRecovery(self.store.load(pp.unit_type + ".xml"))
        # Both neighbouring sensor startup bits and all lower byte3E flags
        # remain set across every Join Recovery selection.
        for name in ("Sensor1EnabledStartup", "Sensor2EnabledStartup", "ClockGenEnable", "EEPROMLevelStore",
                     "Sensor1Enabled", "Sensor2Enabled", "Sensor1EnableStateStoreEnabled",
                     "Sensor2EnableStateStoreEnabled", "Burden"):
            pp.set(name, "1")
        cache = group_cache()
        for branch, masks in (("primary", (4, 8, 12, 0)), ("enable-control", (16, 32, 48, 0))):
            seed_join(pp, branch)
            for recovery, bits in zip(("first-join", "second-join", "quad-join", "restore"), masks):
                self.check(pp, editor, row, "join-" + branch + "-" + recovery,
                           recovery=recovery, group_cache=cache,
                           raw=((0x1C, 63, bits | 3), (0x3E, 255, 255 if recovery == "restore" else 127)))
        seed_join(pp, "primary")
        pp.set("SecondJoinPrimaryApplication", "255")
        self.check(pp, editor, row, "join-first-group-only",
                   recovery="first-join", group_cache=cache, raw=((0x1C, 63, 7), (0x3E, 255, 127)))
        self.refuse(pp, editor, row, "join-unknown-recovery", recovery="disabled", group_cache=cache)
        pp.set("FirstJoinPrimaryApplication", "255")
        pp.set("SecondJoinPrimaryApplication", "21")
        self.refuse(pp, editor, row, "join-second-group-alone", recovery="restore", group_cache=cache)
        seed_join(pp, "primary")
        pp.set("FirstJoinEnableControlApplication", "40")
        self.refuse(pp, editor, row, "join-dual-populated-first", recovery="restore", group_cache=cache)
        seed_join(pp, "primary")
        pp.set("SecondJoinPrimaryApplication", "255")
        pp.set("SecondJoinEnableControlApplication", "41")
        self.refuse(pp, editor, row, "join-mixed-effective-applications", recovery="restore", group_cache=cache)
        seed_join(pp, "primary")
        pp.set("FirstJoinPrimaryApplication", "31")
        self.refuse(pp, editor, row, "join-unresolved-group", recovery="restore", group_cache=cache)
        seed_join(pp, "primary")
        plan = editor.plan(pp.values(), identity=(pp.unit_type, pp.firmware, pp.catalog_number),
                           recovery="quad-join", group_cache=cache)
        pp.set("FirstJoinPrimaryApplication", "22")
        before = pp.values()
        with self.assertRaises(PPEditError):
            editor.apply(pp, plan)
        self.assertEqual(pp.values(), before)
        row["refused_without_changes"].append("join-stale-group-dependency")
        self.check(pp, editor, row, "join-final-primary-quad",
                   recovery="quad-join", group_cache=cache, raw=((0x1C, 63, 15), (0x3E, 255, 127)))
        row["workflows"].append("join-recovery")

    def logic(self, pp, row):
        from cbus_toolkit.iope_logic import IopeLogic
        editor = IopeLogic(self.store.load(pp.unit_type + ".xml"))
        cache = group_cache()
        cache["format"] = "cbus-iope-logic-groups-v1"
        count = {"IOPE1R1": 1, "IOPE2R2": 2, "IOPE2C4": 4}[pp.unit_type]
        seed = {"OutputGroupAddress": "10 11 12 13", "OutputLogicGroupAddress": "20 21 22 23",
                "LightLevelOutput": "179 181 183 185 51 63 77 89", "LevelStoreEnable": "1 0 1 0",
                "LogicLevelStoreEnable": "0 1 0 1", "RestrikeChannel": "1 0 1 0",
                "LogicGA13Associations": "0 1 0 1", "LogicGA14Associations": "0 0 1 0",
                "LogicGA15Associations": "0 1 1 0", "LogicGA16Associations": "0 0 0 1",
                "LogicFunction": "0 1 0 1"}
        for name, value in seed.items():
            pp.set(name, value)
        self.check(pp, editor, row, "logic-all-four-slot-associations-or",
                   channels={1: {"logic_groups": [1, 2, 3, 4], "logic_function": "or"}}, group_cache=cache,
                   arrays={"LogicGA13Associations": [1, 1, 0, 1], "LogicGA14Associations": [1, 0, 1, 0],
                           "LogicGA15Associations": [1, 1, 1, 0], "LogicGA16Associations": [1, 0, 0, 1],
                           "LogicFunction": [1, 1, 0, 1], "RestrikeChannel": [1, 0, 1, 0]},
                   raw=((0x70, 207, 207),))
        self.check(pp, editor, row, "logic-and-preserves-associations-and-restrike",
                   channels={1: {"logic_function": "and"}}, group_cache=cache,
                   raw=((0x70, 207, 79),))
        if count == 4:
            self.check(pp, editor, row, "dimmer-channel-has-source-backed-and-or",
                       channels={3: {"logic_function": "or"}}, group_cache=cache,
                       raw=((0x72, 207, 198),))
        self.check(pp, editor, row, "group-change-copies-last-matching-logic-row-unquantized",
                   logic_groups={1: {"group_address": 23}}, group_cache=cache,
                   arrays={"OutputLogicGroupAddress": [23, 21, 22, 23],
                           "LightLevelOutput": [179, 181, 183, 185, 89, 63, 77, 89],
                           "LogicLevelStoreEnable": [1, 1, 0, 1]},
                   raw=((0x5C, 255, 23), (0x0C, 255, 89), (0x6E, 255, 181)))
        # Source GroupChanged visits all four logic rows, then only active
        # outputs in order. Its last active output match outranks row four.
        pp.set("OutputGroupAddress", "10 10 10 10")
        pp.set("OutputLogicGroupAddress", "10 21 22 10")
        pp.set("LightLevelOutput", "179 181 183 185 51 63 77 89")
        pp.set("LogicLevelStoreEnable", "0 1 0 1")
        copied = [179, 181, 183, 185][count - 1]
        copied_store = [1, 0, 1, 0][count - 1]
        expected_levels = [179, 181, 183, 185, copied, 63, 77, 89]
        expected_store = [copied_store, 1, 0, 1]
        self.check(pp, editor, row, "same-group-copy-last-active-output-wins",
                   logic_groups={1: {"group_address": 10}}, group_cache=cache,
                   arrays={"LightLevelOutput": expected_levels, "LogicLevelStoreEnable": expected_store},
                   raw=((0x0C, 255, copied), (0x6E, 255, (160 | (copied_store << 4) | 5))))
        expected_levels[count - 1] = 123
        pp.set("LightLevelOutput", " ".join(map(str, expected_levels)))
        expected_levels[4] = 123
        self.check(pp, editor, row, "same-address-selection-reruns-raw-copy-cascade",
                   logic_groups={1: {"group_address": 10}}, group_cache=cache,
                   arrays={"LightLevelOutput": expected_levels, "LogicLevelStoreEnable": expected_store},
                   raw=((0x0C, 255, 123),))
        self.check(pp, editor, row, "unused-group-skips-copy-cascade",
                   logic_groups={1: {"group_address": 255}}, group_cache=cache,
                   arrays={"LightLevelOutput": expected_levels, "LogicLevelStoreEnable": expected_store,
                           "OutputLogicGroupAddress": [255, 21, 22, 10]}, raw=((0x5C, 255, 255),))
        # Recovery modal opening alone quantizes every logic slot; physical
        # output slots retain their literal raw levels. Checkbox does not255.
        pp.set("OutputLogicGroupAddress", "20 21 22 23")
        pp.set("LightLevelOutput", "179 181 183 185 179 51 77 89")
        pp.set("LogicLevelStoreEnable", "0 1 0 1")
        self.check(pp, editor, row, "recovery-modal-rounds-all-four-slots-store-retains-level",
                   logic_groups={1: {"level_store": True}}, group_cache=cache,
                   arrays={"LightLevelOutput": [179, 181, 183, 185, 178, 51, 76, 89],
                           "LogicLevelStoreEnable": [1, 1, 0, 1], "LevelStoreEnable": [1, 0, 1, 0]},
                   raw=((0x0C, 255, 178), (0x0E, 255, 76), (0x6E, 255, 181)))
        self.check(pp, editor, row, "logic-recovery-percent-conversion",
                   logic_groups={3: {"recovery_percent": 50}}, group_cache=cache,
                   arrays={"LightLevelOutput": [179, 181, 183, 185, 178, 51, 127, 89]},
                   raw=((0x0E, 255, 127),))
        self.refuse(pp, editor, row, "recovery-slider-disabled-by-store",
                    logic_groups={1: {"recovery_percent": 50}}, group_cache=cache)
        for percent, raw_level in ((0, 0), (100, 255)):
            self.check(pp, editor, row, "logic-recovery-percent-boundary-" + str(percent),
                       logic_groups={3: {"recovery_percent": percent}}, group_cache=cache,
                       raw=((0x0E, 255, raw_level),))
        self.refuse(pp, editor, row, "logic-output-channel-outside-profile",
                    channels={count + 1: {"logic_function": "or"}}, group_cache=cache)
        self.refuse(pp, editor, row, "logic-function-outside-source-radio",
                    channels={1: {"logic_function": "min"}}, group_cache=cache)
        self.refuse(pp, editor, row, "logic-slot-outside-four",
                    logic_groups={5: {"group_address": 20}}, group_cache=cache)
        self.refuse(pp, editor, row, "logic-group-outside-byte",
                    logic_groups={1: {"group_address": 256}}, group_cache=cache)
        self.refuse(pp, editor, row, "logic-group-unresolved",
                    logic_groups={1: {"group_address": 31}}, group_cache=cache)
        self.refuse(pp, editor, row, "logic-recovery-percent-outside-domain",
                    logic_groups={3: {"recovery_percent": 101}}, group_cache=cache)
        plan = editor.plan(pp.values(), identity=(pp.unit_type, pp.firmware, pp.catalog_number),
                           logic_groups={1: {"group_address": 10}}, group_cache=cache)
        pp.set("OutputGroupAddress", "11 10 10 10")
        before = pp.values()
        with self.assertRaises(PPEditError):
            editor.apply(pp, plan)
        self.assertEqual(pp.values(), before)
        row["refused_without_changes"].append("logic-stale-output-group-copy-dependency")
        self.check(pp, editor, row, "logic-clear-all-active-channel-associations",
                   channels={channel: {"logic_groups": []} for channel in range(1, count + 1)}, group_cache=cache)
        self.refuse(pp, editor, row, "logic-group-selector-disabled-without-active-association",
                    logic_groups={4: {"group_address": 24}}, group_cache=cache)
        row["workflows"].append("logic")

    def block_timer(self, pp, row):
        from cbus_toolkit.iope_block_timer import IopeBlockTimer
        editor = IopeBlockTimer(self.store.load(pp.unit_type + ".xml"))
        cache = group_cache()
        seed = {"InputGroupAddress": "10 11 12 13 14 15 16 17", "FirstCorridorLinkEnable": "1",
                "SecondCorridorLinkEnable": "1", "CorridorGroupBlock": "2",
                "FirstCorridorOfficeGroupBlock": "3", "SecondCorridorOfficeGroupBlock": "4",
                "CorridorMasterGroup": "255", "TimerHighByte": "1 2 3 4 5 6 7 8",
                "TimerLowByte": "11 12 13 14 15 16 17 18", "TimerExpiryCommand": "64 64 64 64 64 64 64 87"}
        for name, value in seed.items():
            pp.set(name, value)
        self.check(pp, editor, row, "block-corridor-minimum-toggle",
                   block=3, seconds=60, expiry="toggle", group_cache=cache,
                   arrays={"TimerHighByte": [1, 2, 0, 4, 5, 6, 7, 8],
                           "TimerLowByte": [11, 12, 60, 14, 15, 16, 17, 18],
                           "TimerExpiryCommand": [64, 64, 79, 64, 64, 64, 64, 87]},
                   raw=((0x42, 255, 0), (0x4A, 255, 60), (0x38, 255, 79)))
        self.check(pp, editor, row, "block-first-office-zero-idle",
                   block=4, seconds=0, expiry="idle", group_cache=cache,
                   arrays={"TimerHighByte": [1, 2, 0, 0, 5, 6, 7, 8],
                           "TimerLowByte": [11, 12, 60, 0, 15, 16, 17, 18],
                           "TimerExpiryCommand": [64, 64, 79, 0, 64, 64, 64, 87]},
                   raw=((0x43, 255, 0), (0x4B, 255, 0), (0x39, 255, 0)))
        self.check(pp, editor, row, "block-second-office-maximum-on",
                   block=5, seconds=65535, expiry="on", group_cache=cache,
                   arrays={"TimerHighByte": [1, 2, 0, 0, 255, 6, 7, 8],
                           "TimerLowByte": [11, 12, 60, 0, 255, 16, 17, 18],
                           "TimerExpiryCommand": [64, 64, 79, 0, 71, 64, 64, 87]},
                   raw=((0x44, 255, 255), (0x4C, 255, 255), (0x3A, 255, 71)))
        for expiry, code in (("toggle", 79), ("on", 71), ("off", 64)):
            self.check(pp, editor, row, "block-first-office-expiry-" + expiry,
                       block=4, expiry=expiry, group_cache=cache, raw=((0x39, 255, code),))
        self.refuse(pp, editor, row, "block-corridor-below-sixty", block=3, seconds=59, group_cache=cache)
        self.refuse(pp, editor, row, "block-duration-overflow", block=4, seconds=65536, group_cache=cache)
        self.refuse(pp, editor, row, "block-without-environment-role", block=1, seconds=60, group_cache=cache)
        self.refuse(pp, editor, row, "block-outside-eight", block=9, seconds=60, group_cache=cache)
        self.refuse(pp, editor, row, "block-unsupported-selected-expiry", block=4, expiry="recall", group_cache=cache)
        pp.set("TimerExpiryCommand", "64 64 79 87 71 64 64 87")
        self.refuse(pp, editor, row, "block-unsupported-retained-expiry", block=4, expiry="off", group_cache=cache)
        pp.set("TimerExpiryCommand", "64 64 79 64 71 64 64 87")
        pp.set("TimerLowByte", "11 12 59 0 255 16 17 18")
        self.refuse(pp, editor, row, "block-retained-corridor-below-sixty", block=3, seconds=60, group_cache=cache)
        pp.set("TimerLowByte", "11 12 60 0 255 16 17 18")
        pp.set("FirstCorridorLinkEnable", "0")
        self.refuse(pp, editor, row, "block-environment-disabled", block=3, seconds=60, group_cache=cache)
        pp.set("FirstCorridorLinkEnable", "1")
        pp.set("InputGroupAddress", "10 11 12 255 14 15 16 17")
        self.refuse(pp, editor, row, "block-no-assigned-group", block=4, seconds=60, group_cache=cache)
        pp.set("InputGroupAddress", "10 11 12 13 14 15 16 17")
        pp.set("FirstCorridorOfficeGroupBlock", "2")
        self.refuse(pp, editor, row, "block-environment-initialization-would-change-state", block=3, seconds=60,
                    group_cache=cache)
        pp.set("FirstCorridorOfficeGroupBlock", "3")
        plan = editor.plan(pp.values(), identity=(pp.unit_type, pp.firmware, pp.catalog_number),
                           block=3, seconds=120, group_cache=cache)
        pp.set("InputGroupAddress", "10 11 30 13 14 15 16 17")
        before = pp.values()
        with self.assertRaises(PPEditError):
            editor.apply(pp, plan)
        self.assertEqual(pp.values(), before)
        row["refused_without_changes"].append("block-stale-group-dependency")
        row["workflows"].append("block-timer")

    def exercise(self, client, network, address, unit_type, catalog, firmware, report):
        NativeDatabase(client).create_unit(network, address, "SyntheticLogic" + str(address),
                                           unit_type, firmware, catalog_number=catalog)
        source = f"/db{network}/p/{address}"
        row = {"unit_type": unit_type, "catalog_number": catalog, "firmware": firmware,
               "workflows": [], "positive": [], "refused_without_changes": [],
               "raw_byte_assertions": [], "full_array_assertions": []}
        with Programmer(client).load(network, source) as pp:
            self.assertEqual((pp.unit_type, pp.firmware, pp.catalog_number), (unit_type, firmware, catalog))
            self.logic(pp, row)
            self.join_recovery(pp, row)
            self.block_timer(pp, row)
            after = pp.values()
            pp.save_to_source()
        project = network.split("/")[2]
        for operation in ("SAVE", "CLOSE", "LOAD", "USE"):
            self.assertEqual(client.command(f"PROJECT {operation} {project}").code, 200)
        with Programmer(client).load(network, source) as pp:
            self.assertEqual(pp.values(), after)
        row.update(save_reload_passed=True, project_close_load_passed=True, reloaded_parameter_count=len(after))
        report["profiles"].append(row)

    def cli_workflows(self, client, host, port, network, report):
        cases, persisted = [], []
        for offset, family in enumerate(("logic", "join-recovery", "block-timer")):
            address = 50 + offset
            NativeDatabase(client).create_unit(network, address, "SyntheticCli" + str(address),
                                               "IOPE2C4", "1.2.00", catalog_number="5752PP/2R/2D")
            source = f"/db{network}/p/{address}"
            cache = group_cache()
            if family == "logic":
                cache["format"] = "cbus-iope-logic-groups-v1"
                edits = {"channels": {"1": {"logic_groups": [1, 4], "logic_function": "or"}},
                         "logic_groups": {"1": {"group_address": 20, "level_store": True},
                                          "4": {"group_address": 23, "level_store": False,
                                                "recovery_percent": 50}}, "group_cache": cache}
            else:
                with Programmer(client).load(network, source) as pp:
                    if family == "join-recovery":
                        seed_join(pp, "enable-control")
                        edits = {"recovery": "restore", "group_cache": cache}
                    else:
                        for name, value in (("FirstCorridorLinkEnable", "1"),
                                            ("InputGroupAddress", "10 11 12 13 14 15 16 17")):
                            pp.set(name, value)
                        edits = {"block": 3, "seconds": 60, "expiry": "toggle", "group_cache": cache}
                    pp.save_to_source()
            client.command("PROJECT SAVE " + network.split("/")[2])
            prefix = ("--spec-dir", os.environ["CBUS_UNITSPEC_DIR"], family)
            database = (*prefix, "database", "--host", host, "--port", port,
                        "--lock-address", network, "--source", source)
            original = self.cli(*database, "--export")
            initial_view = self.cli(*database, "--show")
            with tempfile.TemporaryDirectory(prefix="iope-logic-cli-") as folder:
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
                # Assert positive group metadata against fresh native objects,
                # including an otherwise unconsumed false cache claim.
                bad_cache = json.loads(json.dumps(cache))
                bad_cache["applications"][0]["groups"].append(31)
                snapshot.write_text(json.dumps(after))
                edits["group_cache"] = bad_cache
                if family == "logic":
                    edits = {"channels": {"1": {"logic_function": "and"}}, "group_cache": bad_cache}
                elif family == "join-recovery":
                    edits["recovery"] = "first-join"
                else:
                    edits["seconds"] = 120
                edits_file.write_text(json.dumps(edits))
                bad_plan = self.cli(*prefix, "plan", snapshot, "--edits", edits_file)
                plan_file.write_text(json.dumps(bad_plan))
                error = self.cli(*database, "--plan", plan_file, "--exclusive-project", status=1)
                self.assertIn("current native database groups", error["error"])
                self.assertEqual(self.cli(*database, "--export"), after)
                cases.append({"family": family, "unit_type": "IOPE2C4", "firmware": "1.2.00",
                              "offline_plan_matches_dry_run": True, "dry_run_preserved_database": True,
                              "save_and_fresh_reload_passed": True, "stale_plan_refused_without_changes": True,
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

    def refused_profile(self, client, network, report):
        from cbus_toolkit.iope_block_timer import IopeBlockTimer
        from cbus_toolkit.iope_join_recovery import IopeJoinRecovery
        from cbus_toolkit.iope_logic import IopeLogic
        NativeDatabase(client).create_unit(network, 40, "SyntheticOld", "IOPE1R1", "0.9.99",
                                           catalog_number="5752PP/1R")
        cases = []
        with Programmer(client).load(network, f"/db{network}/p/40") as pp:
            for cls, options in ((IopeLogic, {"channels": {1: {"logic_function": "or"}}}),
                                 (IopeJoinRecovery, {"recovery": "restore"}),
                                 (IopeBlockTimer, {"block": 3, "seconds": 60})):
                before = pp.values()
                with self.assertRaises(PPEditError):
                    cls(self.store.load("IOPE1R1.xml")).configure(pp, group_cache=group_cache(), **options)
                self.assertEqual(pp.values(), before)
                cases.append(cls.__name__)
        report["profile_refusals"] = [{"unit_type": "IOPE1R1", "firmware": "0.9.99",
                                        "editors": cases, "unchanged": True}]

    def test_logic_and_join_profile_matrix_preservation_and_cold_reload(self):
        from research.local_cgate import LocalCGate
        self.store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        vendor, specs = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"]), Path(os.environ["CBUS_UNITSPEC_DIR"])
        report = {"format": "cbus-iope-logic-native-acceptance-v1", "backend": "owned-local-native",
                  "scope": "Bounded output logic, Join Recovery and Environment block timers on closed synthetic database units",
                  "physical_hardware_verified": False, "original_toolkit_form_executed": False,
                  "source_sha256": {"cgate.jar": sha256(vendor / "cgate.jar"),
                                    "cbusunits.xml": sha256(vendor / "unitspec/cbusunits.xml"),
                                    **{name: sha256(specs / name) for name in
                                       ("I_IOPE.xml", "IOPE1R1.xml", "IOPE2R2.xml", "IOPE2C4.xml")}},
                  "implementation_sha256": implementation_hashes(), "profiles": [], "passed": False}
        service = LocalCGate(vendor, java=os.environ["CBUS_CGATE_JAVA"])
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
        with service, CGateClient("127.0.0.1", service.port, timeout=30) as client, \
                closed_network_project(client, "IL") as project:
            network = f"//{project}/254"
            database = NativeDatabase(client)
            for app in group_cache()["applications"]:
                application = app["address"]
                database.add(network, "application", application, "SyntheticApplication" + str(application))
                for address in app["groups"]:
                    database.add(network + "/" + str(application), "group", address, "SyntheticGroup" + str(address))
            client.command("PROJECT SAVE " + project)
            for index, (unit_type, catalog) in enumerate(PROFILES):
                for revision, firmware in enumerate(FIRMWARE):
                    with self.subTest(unit_type=unit_type, firmware=firmware):
                        self.exercise(client, network, 20 + index * 3 + revision, unit_type, catalog, firmware, report)
            self.refused_profile(client, network, report)
            self.cli_workflows(client, "127.0.0.1", service.port, network, report)
        report["native_service"] = {key: service.report[key] for key in
                                    ("vendor_jar_sha256", "java_version", "java_sha256",
                                     "listener_ownership_verified", "projects_adopted", "cleanup_complete",
                                     "process_exit_confirmed", "work_removed", "reserved_sockets_closed")}
        report["passed"] = len(report["profiles"]) == 9 and report["native_service"]["cleanup_complete"]
        self.assertTrue(report["passed"])
        if path := os.environ.get("CBUS_IOPE_LOGIC_REPORT"):
            Path(path).write_text(json.dumps(report, indent=2) + "\n")


class IopeLogicNativeReceiptTest(unittest.TestCase):
    def test_receipt_is_scoped_complete_and_bound_to_submitted_sources(self):
        text = (ROOT / "research/fixtures/iope-logic-native-acceptance.json").read_text()
        report = json.loads(text)
        self.assertEqual(report["format"], "cbus-iope-logic-native-acceptance-v1")
        self.assertTrue(report["passed"])
        self.assertFalse(report["physical_hardware_verified"])
        self.assertFalse(report["original_toolkit_form_executed"])
        self.assertEqual(report["implementation_sha256"],
                         {name: sha256(ROOT / name) for name in IMPLEMENTATION_FILES})
        expected = {(unit_type, catalog, firmware) for unit_type, catalog in PROFILES for firmware in FIRMWARE}
        self.assertEqual({(row["unit_type"], row["catalog_number"], row["firmware"])
                          for row in report["profiles"]}, expected)
        self.assertEqual(len(report["profiles"]), len(expected))
        families = {"logic", "join-recovery", "block-timer"}
        required = {"logic-all-four-slot-associations-or", "same-group-copy-last-active-output-wins",
                    "same-address-selection-reruns-raw-copy-cascade",
                    "recovery-modal-rounds-all-four-slots-store-retains-level", "join-primary-restore",
                    "join-enable-control-quad-join", "block-corridor-minimum-toggle",
                    "block-first-office-zero-idle", "block-second-office-maximum-on"}
        for row in report["profiles"]:
            self.assertEqual(set(row["workflows"]), families)
            self.assertTrue(row["save_reload_passed"])
            self.assertTrue(row["project_close_load_passed"])
            self.assertGreater(row["reloaded_parameter_count"], 100)
            self.assertTrue(required <= {case["case"] for case in row["positive"]})
            self.assertGreater(len(row["refused_without_changes"]), 20)
            self.assertGreater(len(row["full_array_assertions"]), 20)
            for observed in row["raw_byte_assertions"]:
                self.assertEqual(observed["actual"] & observed["mask"], observed["expected"])
            for observed in row["full_array_assertions"]:
                self.assertEqual(observed["actual"], observed["expected"])
        self.assertEqual({row["family"] for row in report["cli"]}, families)
        for row in report["cli"]:
            for key in ("offline_plan_matches_dry_run", "dry_run_preserved_database",
                        "save_and_fresh_reload_passed", "stale_plan_refused_without_changes",
                        "project_close_load_passed", "unsupported_native_group_cache_refused_without_changes"):
                self.assertTrue(row[key])
        self.assertEqual(report["profile_refusals"], [{"unit_type": "IOPE1R1", "firmware": "0.9.99",
            "editors": ["IopeLogic", "IopeJoinRecovery", "IopeBlockTimer"], "unchanged": True}])
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
