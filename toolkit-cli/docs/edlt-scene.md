# eDLT Scene widgets

`EdltSceneWidget` configures a Scene widget on **5055EDL / KEYGL5 firmware 5.5.00** to invoke already configured local scenes through Off/On, Ramp, Nudge or Cycle modes. It stages a database PP session and verifies every resulting PP value. It preserves scene records, scene pointers, names, unrelated widgets and inactive selected-widget bytes. This covers a concrete Scene widget workflow; it does not establish physical eDLT behavior or complete Scene widget parity.

The selected scene must have a valid record containing at least one output item or an assigned Trigger Control group. A trigger-only scene is supported. Human scene numbers are 1..8; the widget stores zero-based references. The helper does not accept a new trigger group/action selector, create scene records, edit items, or change an existing scene name.

```python
from cbus_toolkit.edlt_scene import EdltSceneWidget

editor = EdltSceneWidget(spec)  # exact KEYGL5.xml layout required
plan = editor.plan(
    session.values(), page=1, position=1, scene=2,
    label_type="scene", status_text="Scene ready",
)
print(plan.as_dict())
result = editor.apply(session, plan)  # verified=True, saved=False
session.save_to_source()
```

`configure(session, **settings)` makes and applies a plan after checking the database source identity. `scene_reference(values, scene)` returns validated, read-only metadata: scene number, bucket pointer, application, item count, trigger group/action selector, and name index. Unassigned trigger/name fields are `None`. The helper requires a complete PP snapshot, matching native schema and exact catalog/firmware. A plan becomes invalid if any PP value changes before application. Failure attempts to restore and verify original PP values; if the connection loses synchronization, rollback stops without further recovery I/O and reports uncertain PP state. Saving is explicit and separate.

Page placement matches the Lighting helper: multi-page mode has pages 1..4 and positions 1..4; single-page mode has page 1 and positions 1..5. These map to functional widgets 6..21; standby widgets 1..5 are preserved. `page_mode` can be `single` or `multiple`, or omitted to retain the current interpretation. Replacing a different widget type and malformed layouts with active widgets after a terminator are rejected.

Mode options preserve the original Off/On default:

| `mode` | Required reference | Active optional settings | Original button pair |
|---|---|---|---|
| `off-on` (default) | `scene=1..8` | None | Off / On, 26/27 |
| `ramp` | `scene=1..8` | `ramp_seconds` | Off & Ramp Down / On & Ramp Up, 28/29 |
| `nudge` | `scene=1..8` | `offset=0..255` | Off & Nudge Down / On & Nudge Up, 32/33 |
| `cycle` | `scenes=[...]`, 1..8 entries | `cycle_variant="cycle"` or `"select"` | Cycle Down / Cycle Up, 30/31 |

Cycle mode cannot accompany the single `scene` argument. It preserves scene order and duplicates; every selected scene must be configured. The result has `scene_reference=None` and an ordered `cycle_references` array. The original UI Add button scans eight entries; the ninth storage byte remains a terminator. Nine active entries are outside this UI workflow even though the model exposes nine bytes. Shorter lists fill all remaining cycle bytes with `FF`.

Ramp times are 0, 4, 8, 12, 20, 30, 40, 60, 90, 120, 180, 300, 420, 600, 900 and 1020 seconds. If `ramp_seconds` is omitted, a valid existing ramp index is preserved; an invalid active index requires an explicit value. Nudge offset 0 is valid in the original Scene model and its LevelControl; this differs from Lighting's forced offset behavior. Omitted offset/cycle variant values are preserved. A setting for an inactive mode is rejected, and changing modes preserves unrelated inactive bytes.

All scene label and dynamic display requirements below apply to every entry in a cycle. For example, a cycle using scene labels cannot include a scene without a name reference.

Supported display options:

| Setting | Values and meaning |
|---|---|
| `label_type` | `blank`, `dynamic-text`, `dynamic-icon`, `scene` |
| `label_index` | Dynamic label/icon variant 0..3 only |
| `status_type` | `blank`, `static`, `dynamic-text`, `dynamic-icon` |
| `status_index` | Static slot 0..63 or dynamic variant 0..3 |
| `status_text` | Allocate or reuse shared static text; incompatible with `status_index` or another status type |

A `scene` label uses the selected scene's existing name reference; it does not use the widget's byte 11 as a static-text index. Dynamic displays require an assigned trigger in the referenced scene. They configure references only; uploading text/icons remains a separate label operation. Static status text uses the same complete-unit reference enumeration and first-match/highest-unused-slot allocator as Lighting. Text must contain 1..63 UTF-8 bytes, be nonblank, and contain no NUL. Existing text and source references are preserved. The result reports `status_allocation`.

## Exact vendor evidence

`research/NativeEdltSceneProbe.cs` executes the original, unchanged Toolkit 1.18 `CBusLogicModel.dll` on synthetic in-memory objects. Its hash is `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`. The source paths below are decompiled original assembly types under ignored `research/vendor/edlt-decompiled`:

- `SceneData.SceneItem`: byte 6; the WinForms `SceneWidget` binds the single-scene selector to this property. `EDLTUnit.ScenesNameValue` gives it zero-based indexes.
- `CommonConstants.lDualKeyMacroFunctionsScenes`: Off/On is 26/27. `MacroFunctionTypes` maps these to `SceneOff`/`SceneSet`. All four button pairs are implemented; `MicroFunctions` identifies the active inputs for each pair.
- `SceneData`: byte 1 bits 4..6 select label type and bits 0..3 select status type; byte 11 is the dynamic label variant and byte 12 the status index. Bit 7 is cycle/select variant; byte 9 is ramp index, byte 10 is nudge offset, and bytes 13..21 form the cycle list. Inactive fields are preserved.
- `SceneData.SetToDefault`: sets icons 38/37, the first cycle slot 255, default macros 30/31, blank display modes and restore level 0. It preserves opaque bytes and index bytes. `SceneData` hides the base index properties instead of overriding them, so changing display modes does **not** reset bytes 11/12. Direct DLL vectors verify this behavior.
- `EDLTUnit.LoadScenes`: inspects all eight pointers independently of `SceneCount`; reads a 5-byte header and 3 bytes per output item. This helper only reads/validates those records and rejects truncated, overlapping, unconfigured or unsupported records. It does not infer a new scene layout.
- `EDLTUnit.SaveScenes`: the test fixture uses its actual output. Unused pointers are 255; native schema defaults use 65535. Both sentinels are accepted by shared static-reference enumeration. Other out-of-bucket pointers remain errors.

Literal original-DLL widget outputs:

```text
default:         060026250000001E1F00000000FF000000000000000000000000000000000000
scene2/off-on:   063526250000011A1B0000003FFF000000000000000000000000000000000000
dynamic3/status2:061626250000011A1B00000302FF000000000000000000000000000000000000
ramp1020:        061626250000011C1D0F000302FF000000000000000000000000000000000000
nudge255:        0616262500000120210FFF0302FF000000000000000000000000000000000000
cycle-select:    069626250000011E1F0FFF0302000100FFFFFFFFFFFF00000000000000000000
cycle-eight:     061626250000011E1F0FFF03020001000100010001FF00000000000000000000
```

The second vector references scene 2, uses its scene label and static status slot 63. The third shows the dynamic variant bytes retained after original property changes. The later vectors change only active mode inputs, preserving the prior single-scene index, ramp and offset when they become inactive. Original `SceneCycle.Count` returns 3 and 8 for the cycle vectors.

The original `SaveScenes` fixture contains scene 1 (Trigger 42/action 77, primary Lighting 56, group 9→127 at ramp index 4, name slot 1) and scene 2 (Trigger 42/action 88, no local items, name slot 1). Its bucket begins `02012a4d0114097f02002a5801`; the remaining 219 bytes are 255. The fixture deliberately chooses these values. They are not captured user settings or claims about reserved hardware defaults.

## Native acceptance

`tests/test_edlt_scene.py` checks independent literal vectors, shared references, opaque-byte preservation, invalid settings, malformed/empty/overlapping scenes, identity/schema/stale-plan guards, forged changes, rollback and disconnect behavior. The native test executes both original DLL probes, imports their synthetic scene serialization into an isolated C-Gate 3.4.0.2001 database unit, applies two widgets and exercises every supported mode, verifies raw bytes, saves/closes/reloads the project and compares the entire PP snapshot. It also checks all five configuration CRCs against the original private DLL method. The network remains unopened and `state=new` throughout.

Run from `toolkit-cli`:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_SCENE_REPORT=research/runtime/edlt-scene-report.json \
PYTHONPATH=src python3 -m unittest discover -s tests -p '*edlt*.py' -v
```

Docker and the pinned Mono image are required to execute the original DLL, with no binary modification. Vendor binaries and private runtime material remain ignored. A compact acceptance summary is stored in `research/fixtures/edlt-scene-acceptance.json`.
