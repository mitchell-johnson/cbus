"""P7.02 (#52) pure-offline boundary pins for the resident scene slice.

The audit-identified slice is the resident scene/macro/label selector
inventory plus learn/capture/trigger/storage semantics in
``device_scenes.py`` (``DeviceScenes``, ``action_selector`` 0..255) and
``scenes.py`` (``play``/``record``). No committed receipt, fixture or
document describes the unadmitted behavior, so the Python model must not
invent it. These pins lock the provable-offline selector inventory and
the refusal surfaces, and name the exact next evidence needed, following
the KeyglHydraBoundaryTests pattern in tests/test_barcode_scanner.py.
They establish no original GUI, native-selector or hardware acceptance;
native selector acceptance stays open.

Already pinned elsewhere and not duplicated here:
``SceneNamedRejectLoopbackTest`` (named SCENE PLAY/RECORD 401 rejects vs
the accepted scene-file workflow), the fixed/compact codec edges, the
shared-trigger/join guards and the custom-preset helpers.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_device_scenes as device_tests
from cbus_toolkit import macros as classic_macros
from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.device_scenes import (LAYOUTS, PROFILE, DeviceSceneError, DeviceScenes,
                                        RAMP_SECONDS, SceneEntry)
from cbus_toolkit.scenes import (MAX_ACTIONS, MAX_FILE_BYTES, SceneAction, SceneError,
                                 SceneExecutor, SceneFile)
from cbus_toolkit.unitspec import UnitSpecStore
from test_macros import Session

ROOT = Path(__file__).resolve().parents[1]
DEVICE_DOC = (ROOT / "docs/device-scenes.md").read_text()

# Identifiers a KEYE1 scene-modify storage proof would have to contain. The
# committed neo receipts pin method hashes and the template-25 branch only;
# none pins which JP nibble values the KEYE1 dialog writes or what its
# SR/LP/LR nibbles, block or trigger writes mean.
MISSING_MODIFY_EVIDENCE = ("TfrmKeySceneModify", "SetKeyValues modify", "scene-modify JP",
                           "modify ramp", "modify trigger")
# Identifiers a middle-scene delete/renumbering proof would have to contain
# as PP before/after vectors. The committed doc names the routine only.
MISSING_RENUMBER_EVIDENCE = ("ShuffleEmptyScenesToEndOfList before/after",
                             "middle-scene delete PP vectors", "scene renumbering plan")
# Identifiers a shared-block relocation proof would have to contain.
MISSING_RELOCATION_EVIDENCE = ("RefreshBlocksFromTemplateScene shared-block PP vectors",
                               "block relocation plan")


def script_client():
    class ScriptClient:
        def __init__(self):
            self.commands = []

        def command(self, command):
            self.commands.append(command)
            return CGateResponse(("200 OK",), "200 OK", 200)

    return ScriptClient()


def write_keye_spec(directory):
    """Recreate the fixture spec as decoded vendor XML; no vendor material."""
    spec = device_tests.fixture()
    params = []
    for name, parameter in spec.parameters.items():
        inner = "".join(f"<{key}>{value}</{key}>" for key, value in parameter.fields.items()
                        if key not in ("Name", "Type"))
        params.append(f"<Param><Name>{name}</Name><Type>{parameter.type}</Type>{inner}</Param>")
    (directory / "KEYE.xml").write_text(
        "<UnitSpecification><Type>KEYE1</Type><Parameters>"
        + "".join(params) + "</Parameters></UnitSpecification>")
    return UnitSpecStore(directory).load("KEYE.xml")


class ResidentSelectorInventoryTests(unittest.TestCase):
    def setUp(self):
        self.spec = device_tests.fixture()
        self.editor = DeviceScenes(self.spec)
        self.current = self.spec.defaults()

    def test_profile_constant_admits_exactly_keye1_2500(self):
        # Next: a decoded vendor spec plus native PP session per profile
        # before PROFILE admits any other unit type, firmware or file.
        self.assertEqual(PROFILE, ("KEYE1", "2.5.00", "5031NMML", "KEYE.xml"))

    def test_ramp_table_is_the_documented_sixteen_entry_toolkit_table(self):
        # Provenance stays with the gated DeviceSceneSourceTest (EXE VA
        # 0x13B702C); this locks the table against drift offline.
        self.assertEqual(RAMP_SECONDS, (0, 4, 8, 12, 20, 30, 40, 60, 90, 120,
                                       180, 300, 420, 600, 900, 1020))

    def test_action_selector_nibble_roundtrip_full_range(self):
        for selector in range(256):
            with self.subTest(selector=selector):
                plan = self.editor.plan(self.current, scene=1, key=1,
                                        ramp_rate=0, action_selector=selector)
                values = device_tests.after(plan)
                high, low = divmod(selector, 16)
                self.assertEqual((values["LPCommand"][0], values["LRCommand"][0]),
                                 (high, low))
                self.assertEqual(self.editor.inspect(values)["key_bindings"][0]["action_selector"],
                                 selector)

    def test_all_eight_key_selectors_report_scene_ramp_and_trigger(self):
        values = dict(self.current,
                      SceneKeySelector="1 1 1 1 1 1 1 1",
                      JPCommand="14 14 14 14 14 14 14 14",
                      SRCommand="0 1 2 3 4 5 6 7",
                      LPCommand="0 1 2 3 4 5 6 7",
                      LRCommand="15 14 13 12 11 10 9 8")
        bindings = self.editor.inspect(values)["key_bindings"]
        self.assertEqual(len(bindings), 8)
        for index, binding in enumerate(bindings):
            with self.subTest(key=index + 1):
                self.assertEqual(binding["key"], index + 1)
                self.assertEqual(binding["physical_key"], index == 0)
                self.assertEqual(binding["function"], "scene")
                self.assertEqual(binding["scene"], index + 1)
                self.assertEqual(binding["ramp_rate"], index)
                self.assertEqual(binding["ramp_seconds"], RAMP_SECONDS[index])
                self.assertEqual(binding["action_selector"], index * 16 + (15 - index))

    def test_non_scene_jp_reports_unwritable_modify_function(self):
        # The report vocabulary is the whole modify surface: plan() never
        # writes these nibbles (see SceneModifyBoundaryTests).
        for nibble in list(range(14)) + [15]:
            with self.subTest(jp=nibble):
                values = dict(self.current, SceneKeySelector="1 0 0 0 0 0 0 0",
                              JPCommand=f"{nibble} 0 0 0 0 0 0 0")
                (binding,) = self.editor.inspect(values)["key_bindings"]
                self.assertEqual(binding["function"], "modify_scene_unsupported")
                self.assertEqual((binding["scene"], binding["ramp_rate"],
                                  binding["action_selector"]), (1, 0, 0))

    def test_learn_compatible_boundary_four_vs_five_scenes(self):
        current = self.current
        for scene in range(1, 5):
            current = device_tests.after(
                self.editor.plan(current, scene=scene, entries=[SceneEntry(scene, 1)]))
        self.assertTrue(self.editor.inspect(current)["scene_learn_compatible"])
        self.assertEqual(self.editor.inspect(current)["layout"], "fixed")
        current = device_tests.after(
            self.editor.plan(current, scene=5, entries=[SceneEntry(5, 1)]))
        info = self.editor.inspect(current)
        self.assertFalse(info["scene_learn_compatible"])
        self.assertEqual(info["layout"], "compact")

    def test_trigger_group_255_clears_a_set_group(self):
        current = device_tests.after(self.editor.plan(self.current, scene=1, trigger_group=23))
        self.assertEqual(current["ControlAppGroupAddress"], (23,))
        plan = self.editor.plan(current, scene=1, trigger_group=255)
        self.assertEqual(plan.changes, {"ControlAppGroupAddress": (255,)})
        self.assertEqual(self.editor.inspect(device_tests.after(plan))["trigger_group"], 255)

    def test_only_physical_key_1_is_plannable(self):
        for key in (0, 2, 3, 8, True):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.editor.plan(self.current, scene=1, key=key)
        with self.assertRaisesRegex(ValueError, "Physical KEYE1 key"):
            self.editor.plan(self.current, scene=1, key=2)

    def test_configure_refuses_wrong_profile_before_any_write(self):
        session = Session(self.spec)
        session.firmware, session.catalog_number = "2.5.00", "OTHER"
        with self.assertRaisesRegex(DeviceSceneError, "Native session must be KEYE1"):
            self.editor.configure(session, scene=1, entries=[])
        self.assertEqual(session.calls, [])


class SceneFileWorkflowBoundaryTests(unittest.TestCase):
    def test_empty_play_queues_nothing_without_device_claim(self):
        client = script_client()
        playback = SceneExecutor(client).play(SceneFile())
        self.assertEqual((playback.responses, playback.queued, playback.device_verified),
                         ((), True, False))
        self.assertEqual(client.commands, [])

    def test_empty_record_preserves_triggers_and_comments(self):
        scene = SceneFile(play_trigger="254/56/27", record_trigger="254/56/33",
                          comments=("# keep",))
        recorded = SceneExecutor(script_client()).record(scene)
        self.assertEqual(recorded.actions, ())
        self.assertEqual((recorded.play_trigger, recorded.record_trigger),
                         ("254/56/27", "254/56/33"))
        self.assertEqual(recorded.comments, ("# keep",))

    def test_action_capacity_boundary(self):
        self.assertEqual(len(SceneFile(tuple(SceneAction("a", 1)
                                             for _ in range(MAX_ACTIONS))).actions), MAX_ACTIONS)
        with self.assertRaises(SceneError):
            SceneFile(tuple(SceneAction("a", 1) for _ in range(MAX_ACTIONS + 1)))

    def test_empty_file_serializes_to_empty_text(self):
        self.assertEqual(SceneFile().to_text(), "")
        parsed = SceneFile.parse("")
        self.assertEqual((parsed.actions, parsed.play_trigger, parsed.record_trigger,
                          parsed.comments), ((), None, None, ()))

    def test_file_size_boundary(self):
        text = "# " + "x" * (MAX_FILE_BYTES - 3) + "\n"
        self.assertEqual(len(text.encode("utf-8")), MAX_FILE_BYTES)
        self.assertEqual(SceneFile.parse(text).actions, ())
        with self.assertRaisesRegex(SceneError, "1 MiB"):
            SceneFile.parse(text + "x")


class OfflineCliBoundaryTests(unittest.TestCase):
    """End-to-end unit-scenes routing over a synthetic spec dir and snapshot.

    No vendor specification or native server is involved: the KEYE.xml is
    rebuilt from the in-memory layout fixture and the snapshot carries the
    exact PROFILE identity. The subprocess tests the worktree via an
    explicit PYTHONPATH so the shared venv's installed package is bypassed.
    """

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.directory = Path(folder.name)
        spec = write_keye_spec(self.directory)
        snapshot = {"format": "cbus-cli-parameters-v1", "unit_type": "KEYE1",
                    "firmware": "2.5.00", "catalog_number": "5031NMML",
                    "parameters": spec.defaults()}
        self.snapshot = self.directory / "snap.json"
        self.snapshot.write_text(json.dumps(snapshot))

    def cli(self, *args, status=0):
        env = {key: value for key, value in os.environ.items()
               if key != "CBUS_UNITSPEC_DIR"}
        env["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                                capture_output=True, text=True, timeout=60,
                                cwd=ROOT, env=env)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        if status == 2:
            return result.stdout + result.stderr
        return json.loads(result.stdout or result.stderr)

    def test_inspect_reports_empty_table_offline(self):
        info = self.cli("unit-scenes", "--spec-dir", self.directory, "inspect", self.snapshot)
        self.assertEqual(info["format"], "cbus-device-scenes-v1")
        self.assertEqual(info["commands_used"], 0)
        self.assertEqual(len(info["scenes"]), 8)
        self.assertTrue(info["scene_learn_compatible"])
        self.assertEqual(info["key_bindings"], [])

    def test_plan_maps_ramp_seconds_to_native_rate(self):
        plan = self.cli("unit-scenes", "--spec-dir", self.directory, "plan", self.snapshot,
                        "--scene", 1, "--entry", "12=255", "--key", 1,
                        "--ramp-seconds", 12, "--action-selector", 7, "--trigger-group", 23)
        self.assertEqual(plan["changes"]["JPCommand"], [14, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(plan["changes"]["SRCommand"], [3, 0, 0, 0, 0, 0, 0, 0])
        self.assertNotIn("LPCommand", plan["changes"])  # high nibble 0 is already stored
        self.assertEqual(plan["changes"]["LRCommand"], [7, 0, 0, 0, 0, 0, 0, 0])
        self.assertFalse(plan["saved"])
        self.assertFalse(plan["device_verified"])

    def test_plan_rejects_malformed_entry_offline(self):
        error = self.cli("unit-scenes", "--spec-dir", self.directory, "plan", self.snapshot,
                         "--scene", 1, "--entry", "bad", status=1)
        self.assertIn("GROUP=LEVEL", error["error"])

    def test_plan_rejects_seconds_outside_toolkit_table(self):
        output = self.cli("unit-scenes", "--spec-dir", self.directory, "plan", self.snapshot,
                          "--scene", 1, "--ramp-seconds", 13, status=2)
        self.assertIn("invalid choice", output)

    def test_plan_requires_spec_dir(self):
        error = self.cli("unit-scenes", "plan", self.snapshot, "--scene", 1, status=1)
        self.assertIn("--spec-dir", error["error"])

    def test_inspect_rejects_foreign_snapshot_identity(self):
        foreign = json.loads(self.snapshot.read_text())
        foreign["unit_type"] = "KEYM4"
        path = self.directory / "foreign.json"
        path.write_text(json.dumps(foreign))
        error = self.cli("unit-scenes", "--spec-dir", self.directory, "inspect", path, status=1)
        self.assertIn("differs from the selected profile", error["error"])


class SceneModifyBoundaryTests(unittest.TestCase):
    """KEYE1 scene-modify storage stays unmodeled.

    Next: an original-Toolkit Windows capture of the KEYE1 scene-modify
    dialog (accepted JP nibble set, SR/LP/LR meaning, block and trigger
    writes) through the ``SetKeyValues`` modify branch as PP before/after
    vectors, plus an EXE/MAP source review, before ``plan`` admits any
    non-14 JP nibble. Physical invocation stays open under #52.
    """

    def test_no_modify_storage_evidence_in_committed_sources(self):
        text = json.dumps({"layouts": dict(LAYOUTS)})
        for identifier in MISSING_MODIFY_EVIDENCE:
            with self.subTest(identifier=identifier):
                self.assertNotIn(identifier, text)

    def test_key_plans_always_write_the_scene_function_nibble(self):
        editor = DeviceScenes(device_tests.fixture())
        current = editor.spec.defaults()
        plan = editor.plan(current, scene=3, key=1, ramp_rate=4, action_selector=66)
        self.assertEqual(plan.changes["JPCommand"], (14, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(plan.changes["IndicatorBlockAssignment"][0], 2)

    def test_inspect_vocabulary_is_exactly_scene_or_unwritable_modify(self):
        editor = DeviceScenes(device_tests.fixture())
        values = dict(editor.spec.defaults(), SceneKeySelector="1 0 0 0 0 0 0 0")
        functions = set()
        for nibble in range(16):
            row = dict(values, JPCommand=f"{nibble} 0 0 0 0 0 0 0")
            functions.add(editor.inspect(row)["key_bindings"][0]["function"])
        self.assertEqual(functions, {"scene", "modify_scene_unsupported"})


class MiddleSceneDeleteBoundaryTests(unittest.TestCase):
    """Middle-scene deletion stays a refusal: renumbering is unmodeled.

    Next: an original-Toolkit Windows capture of
    ``TfrmSceneManager.ShuffleEmptyScenesToEndOfList`` (0xF88908) as PP
    before/after vectors, plus an explicit migration design, before
    ``_encode``/``plan`` admit relocation branches. Clearing the final
    populated scene (remote-trigger compatible) is the only supported
    removal and is pinned in tests/test_device_scenes.py.
    """

    def test_middle_clear_of_three_scenes_is_refused(self):
        editor = DeviceScenes(device_tests.fixture())
        current = editor.spec.defaults()
        for scene in range(1, 4):
            current = device_tests.after(
                editor.plan(current, scene=scene, entries=[SceneEntry(scene, 1)]))
        with self.assertRaisesRegex(DeviceSceneError, "contiguous prefix"):
            editor.plan(current, scene=2, entries=[])

    def test_no_renumber_vectors_in_committed_sources(self):
        for identifier in MISSING_RENUMBER_EVIDENCE:
            with self.subTest(identifier=identifier):
                self.assertNotIn(identifier, DEVICE_DOC)


class BlockRelocationBoundaryTests(unittest.TestCase):
    """Shared linear-block relocation stays a refusal.

    Next: an original-Toolkit Windows capture of the
    ``TInputKey.RefreshBlocksFromTemplateScene`` (0xD12788) shared-block
    branch as PP before/after vectors before ``plan`` relocates block 1.
    """

    def test_every_other_virtual_key_sharing_block_1_is_refused(self):
        editor = DeviceScenes(device_tests.fixture())
        options = {"scene": 1, "key": 1, "ramp_rate": 0, "action_selector": 0}
        for slot in range(1, 8):
            with self.subTest(slot=slot):
                masks = [1, 2, 4, 8, 16, 32, 64, 128]  # fixture BlockAllocation default
                masks[slot] |= 1  # another virtual key shares linear block 1
                values = dict(editor.spec.defaults(),
                              BlockAllocation=" ".join(map(str, masks)))
                with self.assertRaisesRegex(DeviceSceneError, "relocation"):
                    editor.plan(values, **options)

    def test_no_relocation_vectors_in_committed_sources(self):
        for identifier in MISSING_RELOCATION_EVIDENCE:
            with self.subTest(identifier=identifier):
                self.assertNotIn(identifier, DEVICE_DOC)


class ResidentMacroLabelBoundaryTests(unittest.TestCase):
    """Resident Neo macro/label selectors stay outside both key editors.

    Next: an original-Toolkit capture of KEYE1 ordinary-key macro nibble
    semantics and of resident label storage/transfer (PP locations plus
    save path) as committed vectors before any Neo macro planner or label
    selector is admitted. The eDLT scene/label interop suites stay the
    regression reference only and prove no resident behavior.
    """

    def test_classic_presets_do_not_cover_resident_neo_keys(self):
        self.assertNotIn("KEYE1", dict(classic_macros.SUPPORTED_UNITS))
        with self.assertRaises(classic_macros.MacroError):
            classic_macros.ClassicKeys(device_tests.fixture())

    def test_resident_scene_surface_has_no_label_selectors(self):
        editor = DeviceScenes(device_tests.fixture())
        info = editor.inspect(editor.spec.defaults())
        self.assertNotIn("label", {key.lower() for key in info})
        self.assertNotIn("label", {name.lower() for name in LAYOUTS})
        scene = SceneFile.parse("play 254/56/27\nset 254/56/12 255\n")
        self.assertFalse(any("label" in name.lower() for name in vars(scene)))

    def test_docs_keep_physical_invocation_and_learning_unclaimed(self):
        self.assertIn("Physical invocation and scene learning", DEVICE_DOC)
        self.assertIn("have not been tested", DEVICE_DOC)
        self.assertIn("does not establish that physical devices hold those levels",
                      SceneExecutor.__doc__)


if __name__ == "__main__":
    unittest.main()
