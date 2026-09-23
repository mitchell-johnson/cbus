# eDLT Shutter widgets

`EdltShutterWidget` configures **5055EDL / KEYGL5 firmware 5.5.00** Shutter widgets in database PP sessions. It implements the original UI's two modes, group/application selection, left/right presets, page placement and shared or dynamic label/status references. It verifies the entire staged PP snapshot and five Toolkit configuration CRCs. Physical shutter movement and custom button icons are outside this workflow.

```python
from cbus_toolkit.edlt_shutter import EdltShutterWidget

editor = EdltShutterWidget(spec)
plan = editor.plan(
    session.values(), page=1, position=1, group=42,
    application="secondary", mode="two-key-presets",
    preset_left=6, preset_right=248,
    label_text="Shade", status_text="Ready",
)
print(plan.as_dict())
result = editor.apply(session, plan)  # verified=True, saved=False
session.save_to_source()
```

The CLI provides `edlt shutter-plan SNAPSHOT ...` and `cgate ... unit ... edlt-shutter ...`. Page, position and group are required. `--dry-run` verifies a native preview without saving; the normal native command explicitly saves the result. Native destinations must be database units.

| Setting | Accepted values |
|---|---|
| `group` | Required integer 0..254 |
| `application` | `primary` (default) or `secondary`; the selected application must be assigned in 48..95 |
| `mode` | `two-key` (default) or `two-key-presets` |
| `preset_left`, `preset_right` | Integers 6..248; accepted only in `two-key-presets` mode |
| `page_mode` | `single` or `multiple`; omitted retains the current interpretation |
| `page`, `position` | Single: page 1, positions 1..5. Multiple: pages 1..4, positions 1..4 |
| `label_type` | `blank`, `static`, `dynamic-text`, `dynamic-icon` |
| `status_type` | `blank`, `level`, `percent`, `bar`, `static`, `dynamic-text`, `dynamic-icon` |
| `label_index`, `status_index` | Static slot 0..63 or dynamic variant 0..3, only for a display using that index |
| `label_text`, `status_text` | Select static display and allocate/reuse text; incompatible with the corresponding explicit index or another display type |

Omitted presets retain valid existing values. Fresh widgets start with left 86 and right 170. Switching back to `two-key` preserves both preset bytes. The original model clamps preset setters/getters to 6..248; this helper rejects invalid requested or existing selected values so an invalid source is not silently normalized. Repair an invalid preset through an explicit value in `two-key-presets` mode.

`configure(session, **settings)` checks database identity before reading PP values. `apply` requires an unchanged full source snapshot, matching native schema, and a canonical plan with verified settings and allocation metadata. Partial staging failures attempt verified rollback while the connection remains synchronized. After disconnection, no recovery I/O is sent; `EdltApplyError.details` reports attempted fields, rollback errors and `saved=False`.

## Default text and shared references

Creating a Shutter widget reproduces `ShutterRelayData.SetToDefault`, including its static **Blind** label. This allocation occurs before requested label/status edits, even if the final label is blank. Its metadata is reported as `default_label_allocation`; requested text allocations appear as `static_allocation` and `status_allocation`.

The allocator reuses the first exact string match, otherwise selecting the highest unused slot. It examines all known widget references, page names and scene names. The current reference remains reserved until the new allocation is bound; the next allocation sees the updated binding. Equal requested strings share a slot. Text must be nonblank, contain no NUL and occupy 1..63 UTF-8 bytes. Exhausted or malformed shared tables are rejected before mutation.

Initial state changes the resulting slot numbers:

| Initial table | Default Blind | Custom Shade | Status Ready |
|---|---|---|---|
| Isolated original-DLL scaffold, no Blind text | Allocate 63 | Allocate 62 | Reuse the now-unreferenced slot 63 |
| Exact native KEYGL5 defaults, Blind already at 5 | Reuse 5 | Allocate 63 | Allocate 62 |

Both sequences are independently reproduced by the original DLL probe. The second sequence preserves the existing Blind string at slot 5. Allocation metadata describes the sequence; the plan's final `changes` contains the final contents if a later allocation overwrites an intermediate unreferenced string.

Dynamic references do not upload or fetch network labels. The original model selects text versus icon using the chosen group's dynamic metadata, which is absent from PP. Changing group or application, or explicitly assigning a dynamic index, therefore requires an explicit corresponding display type. This includes reassigning the same index: the original Shutter setters refresh network metadata on every assignment. Omit the index to retain an unchanged reference without declaring its type. Switching between dynamic text and icon retains its index; changing display categories resets the index to zero before any explicit index is applied.

The original group setter copies restore level from the first other `StatusLabelAppGroupData` widget with the same numeric group, in widget order, without comparing applications. With no match it uses zero. Retaining the numeric group preserves selected restore state, including when changing application. The helper reports `restore_level` and `restore_source_widget`: the selected widget when retained, another widget when copied, or `None` for the no-match zero. Unsupported AppGroup records in standby slots are rejected because they have no schema-backed restore field.

Functional widgets 6..21 map to supported pages. Other widgets, scene records and names, opaque bytes and inactive presets are preserved. Replacing another widget type, active widgets after a terminator, malformed shared references and other catalog/firmware profiles are rejected.

## Original model evidence

`research/NativeEdltShutterProbe.cs` executes unchanged Toolkit 1.18 `CBusLogicModel.dll` on explicit synthetic objects. DLL SHA256 is `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`.

| Original source | Exact mapping |
|---|---|
| `EDLTWidget.CreateData`, `ShutterRelayWidget` | Type 3 uses `ShutterRelayData` |
| `CommonConstants.lShutterRelayKeyFunction`, `ShutterRelayWidget.SetUpDataSource` | Two Key = 0; Two Key with Presets = 1; UI binds the single mode to `LeftButtonMacrofunction` at byte 7 |
| `ShutterRelayData.TargetLevel1/2`, `LevelControl` bindings | Left/right presets at bytes 8/9, range 6..248 |
| `StatusLabelAppGroupData` | Byte 6 group, byte 1 bit 7 primary/secondary application; original numeric-group restore lookup |
| `ShutterRelayData`, `StatusLabelTypeData` | Label type in byte 1 bits 4..6; status in low four bits; label/status indexes at bytes 10/11 |
| `BaseStatusLabel` | Actual Shutter status UI inherits generic `FunctionStatusTypes`, including Level/Percent/Bar; the separate `FunctionStatusTypesShutter` constant is not bound by this UI |
| `ShutterRelayData.SetToDefault` | Static Blind label, blank status, icons 18/17, mode 0, presets 86/170; preserves opaque bytes 4/5/12..31 |

Byte 8 is a preset in this widget, despite the inherited base class also naming that storage `RightButtonMacrofunction`. The Shutter UI binds a single mode at byte 7, and its override of `SetKeyFunctionDefaults` does not initialize a dual macro pair. The helper follows the actual Shutter model and binding.

Literal original-DLL vectors:

```text
default, no Blind:033012110000FF0056AA3F000000000000000000000000000000000000000000
presets 6/248:    03B0121100002A0106F83F000000000000000000000000000000000000000000
custom, no Blind: 03B5121100002A0106F83E3F0000000000000000000000000000000000000000
custom, Blind5:   03B5121100002A0106F83F3E0000000000000000000000000000000000000000
dynamic icons:   03A7121100002A0006F801030000000000000000000000000000000000000000
```

The vectors deliberately choose secondary application 57 and group 42 where applicable. The original probe also verifies opaque bytes, getter/setter clamping, mode-switch retention, dynamic category updates, status styles and restore level 137 copied from a synthetic Lighting widget on primary application 56. They are fixture values, not captured user configuration.

## Native acceptance

`tests/test_edlt_shutter.py` covers original literal vectors, both allocation starting states, full-table/reference guards, presets and mode transitions, dynamic metadata requirements including same-index assignments, restore lookup, opaque and unrelated values, invalid profiles/layouts, stale and forged plans, verified rollback and disconnection handling. Its original DLL probe changes the selected network variants from text to icons and reassigns the same indexes; the resulting control byte changes from `96` to `A7`. Native tests reject such assignments without explicit types and confirm unchanged PP values, then accept the explicit icon types and verify the literal raw record.

Its native test creates a uniquely marked, unopened C-Gate 3.4.0.2001 project with a synthetic 5055EDL unit. It checks native default Blind reuse, exact widget/static/restore raw bytes, both modes, static/dynamic labels and every supported status category, five configuration CRCs against the original private DLL method, and complete PP equality after save/close/load. The network remains `state=new`.

`tests/test_cli_edlt_shutter.py` checks offline planning, native preview/save/reload, default allocation metadata, preset retention and database destination guards. Run both suites from `toolkit-cli`:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_SHUTTER_REPORT=research/runtime/edlt-shutter-report.json \
PYTHONPATH=src:tests python3 -m unittest test_edlt_shutter test_cli_edlt_shutter -v
```

The original DLL probes require Docker with the pinned Mono image used by other eDLT acceptance tests. Vendor files and full runtime outputs remain ignored. Compact evidence is recorded in `research/fixtures/edlt-shutter-acceptance.json`.
