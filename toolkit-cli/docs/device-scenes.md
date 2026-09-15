# Stored keypad scenes

`DeviceScenes` implements scene-table editing and the Scene key function for
**KEYE1, firmware 2.5.00, catalog 5031NMML**, using the user's decoded `KEYE.xml`
and its includes. These scenes are stored in the unit's programming memory;
`scenes.py` separately handles C-Gate filesystem scenes.

The implemented workflow appends or replaces a scene, clears the last populated
scene, binds the physical key, and sets its ramp and trigger settings. It
validates the exact native profile and schema, detects stale plans, preserves
other fields, and verifies PP readback. Physical invocation and scene learning
have not been tested. Other device profiles and complete scene-dialog parity
remain outside this evidence.

```python
from cbus_toolkit.device_scenes import DeviceScenes, SceneEntry
from cbus_toolkit.unitspec import UnitSpecStore

editor = DeviceScenes(UnitSpecStore(spec_directory).load("KEYE.xml"))
plan = editor.plan(
    session.values(), scene=1,
    entries=[SceneEntry(12, 255), SceneEntry(24, 127)],
    key=1, ramp_rate=1, action_selector=66, trigger_group=23,
)
print(plan.as_dict())
editor.apply(session, plan)
session.save_to_source()  # explicit persistence, separate from the helper
```

`configure(session, **options)` combines planning and application.
`inspect(values)` returns all eight scene slots, storage usage, the trigger
group, and scene-key bindings. Virtual key fields are reported and preserved;
only physical key 1 is configured by this workflow. Input values can come from
`session.values()` or a complete exported parameter mapping.

Examples using the CLI:

```sh
cbus unit-scenes --spec-dir /path/to/decoded-specs inspect unit.json
cbus unit-scenes --spec-dir /path/to/decoded-specs plan unit.json \
  --scene 1 --entry 12=255 --entry 24=127 \
  --key 1 --ramp-rate 1 --action-selector 66 --trigger-group 23
cbus cgate --host 127.0.0.1 unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/230 --dry-run device-scene \
  --spec-dir /path/to/decoded-specs --scene 1 --entry 12=255 --entry 24=127 \
  --key 1 --ramp-rate 1 --action-selector 66 --trigger-group 23
```

Use the existing project, network, and unit address in the final command.
`--dry-run` applies and verifies a temporary PP session without saving it.
Omitting that option invokes the CLI's explicit edit-and-save workflow. The
helper itself never saves or opens a network. `--entries FILE` accepts a JSON
array of `{ "group": 12, "level": 255 }` records. `--clear` means an empty
entry list; omitting entry options preserves the scene's current contents.

## Record layout and dependencies

A scene entry is a group byte followed by a level byte. Groups are 0..254,
levels are 0..255, and duplicate groups in one scene are rejected. Scene
commands use the unit's primary Lighting Type application (48..95). They do
not change that application or infer database group names.

The supported limits are eight scene slots, ten commands per scene, and forty
commands across the unit. `SceneTable` stores 80 bytes at address `0xA2`;
`SceneTablePointer` stores eight absolute byte addresses at `0x98`.

| Layout | Condition | Pointers and padding |
|---|---|---|
| Fixed | At most four populated scenes | `A2 B6 CA DE FF FF FF FF`; twenty bytes reserved per scene |
| Compact | Five to eight populated scenes | Each populated scene points to the byte after its predecessor's final group/level pair |

Unused bytes and pointers are `FF`. With four or fewer populated scenes the
layout is compatible with Toolkit's scene-learning predicate; this reports
storage compatibility and does not verify physical learning.

Toolkit moves empty scenes to the end before serialization. This helper
requires populated scenes to form a contiguous prefix, so adding content
starts with scene 1 and then the next empty slot. Removing content from a
middle scene would renumber other scenes and is rejected. Replacing a scene
or changing between fixed and compact layouts preserves every other scene's
ordered entries. Clearing the final populated scene retains any key binding
to that now-empty scene, which Toolkit supports for remote scene triggering.
Sparse, duplicate, misaligned, out-of-range, or noncanonical existing data is
rejected before editing; it is never silently normalized.

For the Scene key function, the original Toolkit serializer writes:

| Parameter for key 1 | Value |
|---|---|
| `SceneKeySelector[0]` | 1 |
| `IndicatorBlockAssignment[0]` | scene number minus 1 |
| `JPCommand[0]` | `0xE` |
| `SRCommand[0]` | ramp-rate code, 0..15 |
| `LPCommand[0]`, `LRCommand[0]` | high and low nibbles of the action selector |

The sixteen ramp codes correspond to **0, 4, 8, 12, 20, 30, 40, 60, 90, 120,
180, 300, 420, 600, 900, 1020 seconds**. `RAMP_SECONDS` exports this exact
Toolkit table. The CLI accepts `--ramp-seconds` as an alternative to
`--ramp-rate` and only accepts those exact durations. A new Scene key requires an explicit rate and action selector;
an existing Scene key preserves either setting when its option is omitted.

The key binds to linear block 1: its allocation mask becomes 1, the block's
secondary-application bit is cleared, and its ordinary group becomes 255
(unassigned). If another virtual key uses block 1, the helper rejects the edit
because Toolkit's block relocation branch is not implemented here. It also
rejects join-mode binding. Timer, recall, indicator-function and colour fields
are preserved, including bits sharing an EEPROM byte with the scene selector
and scene number.

`trigger_group` updates `ControlAppGroupAddress`, shared by the unit's Scene
keys in Trigger Control application 202. A value of 255 clears the assignment.
Changing a group used by another scene key requires
`allow_shared_trigger_group=True`; an unchanged group needs no override.
This changes configuration, not the current state of the Trigger application.

Successful application returns `verified=True`, `saved=False`,
`device_verified=False`. A mutation or readback failure raises
`DeviceSceneApplyError` with its cause and attempted parameter names. The
helper issues no retry, rollback, save, or recovery read after a failed write.
The PP session can contain partial unsaved edits and should be inspected or
explicitly reloaded before continuing.

## Exact source evidence

The source audit uses the original Toolkit 1.18.0 EXE/MAP and decoded vendor
specifications supplied locally. No vendor executable or XML is distributed
with this module. Addresses are virtual addresses in that EXE build.

* Help 5018 documents eight scenes and ten commands per scene. Help 1036
  documents the trigger group and use of empty scenes for remote triggering.
* `TCoreNeoInputCGateAgent.GetNeoUnitSceneTableAsString`, `0xCCBCF8`, initializes
  80 bytes to `FF`, writes the group at `0xCCBE7B`, level at `0xCCBEC1`, and
  advances by two at `0xCCBEC8`. The compatible-layout branch computes
  `scene_index * 20` at `0xCCBDC2`.
* `GetNeoSceneTablePointersAsString`, `0xCCBFDC`, uses base `0xA2`, fixed
  twenty-byte strides for four scenes, or cumulative command counts times
  two. `GetSceneCommands`, `0xCCAF50`, loads those records into the unit's
  primary application and skips unused group bytes.
* `TCBusNeoInputUnit.IsSceneLearnCompatible`, `0xD08A90`, checks no more than
  four populated scenes and a largest scene of no more than ten commands.
  `TNeoSceneManager.AfterConstruction`, `0xC9AE74`, sets base `0xA2`, length
  `0x50`, forty total commands, and ten commands for the static layout.
* `TfrmSceneManager.ShuffleEmptyScenesToEndOfList`, `0xF88908`, moves populated
  records ahead of empty scenes. The current helper deliberately stops when
  an edit would require that renumbering workflow.
* `TCoreNeoInputCGateAgent.SetKeyValues`, `0xCCB854`, binds the scene selector,
  indicator assignment, `0x0E` function literal at `0xCCBCEC`, ramp code, and
  split action selector. The global trigger group is saved by
  `BeforeSaveProgrammingInformation`, `0xCCC358`.
* `TInputKey.RefreshBlocksFromTemplateScene`, `0xD12788`, binds the key's
  linear block, selects the primary application (`0xD12A10`), and assigns
  the unused group (`0xD12A2A`). The shared-block relocation branch is
  excluded from this implementation.
* `CIS_GUI.SecondsInCBusRampRate`, MAP segment 3 offset `0x1602C`, is the
  sixteen-element DWORD table at `0x13B702C`.

## Reproducible acceptance

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_TOOLKIT_HELP_DIR=research/vendor/toolkit-help \
CBUS_DEVICE_SCENE_REPORT=research/runtime/device-scenes-acceptance.json \
.venv/bin/python -m unittest discover -s tests -p test_device_scenes.py -v
```

The suite passed **14 tests with no skips** against native C-Gate 3.4.0 build
2001. Native acceptance includes **12 scene-table cases**, **16 key bindings**,
**1,144 raw bytes compared**, and **two database save/reloads**. It creates a
unique disposable project with a closed network and only loads/saves `/db`
units. It never opens a physical endpoint. Offline tests independently assert
literal bytes, transitions in both directions, failure handling, invalid
layouts and dependencies; source tests assert relevant original EXE bytes and
help text.

The compact [acceptance summary](device-scene-acceptance-summary.json) records
source hashes and counts. Full local output is
`research/runtime/device-scenes-acceptance.json`. Skipped native or source
checks are not evidence of a pass. Remaining gaps include other profiles,
scene-modify functions, shared-block relocation, middle-scene deletion and
renumbering, physical transfer/invocation/learning, and complete GUI
before/after comparison.
