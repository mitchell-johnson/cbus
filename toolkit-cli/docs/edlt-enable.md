# eDLT Enable Off/Preset widgets

`EdltEnableWidget` configures **5055EDL / KEYGL5 firmware 5.5.00** Enable widgets in database PP sessions. It implements the original UI's sole Enable mode, Off/Preset, with a required Enable network variable and preset level, page placement, static text and dynamic label/status references. It verifies staged PP values and all five Toolkit configuration CRCs. Hardware execution and custom button icons are outside this bounded workflow.

```python
from cbus_toolkit.edlt_enable import EdltEnableWidget

editor = EdltEnableWidget(spec)
plan = editor.plan(
    session.values(), page=1, position=1, variable=42, level=127,
    label_text="Enable name", status_text="Ready",
)
print(plan.as_dict())
result = editor.apply(session, plan)  # verified=True, saved=False
session.save_to_source()
```

`configure(session, **settings)` checks source identity before reading the full PP snapshot, then plans and applies the edit. Native database source identity, parameter schema and the complete snapshot must match. Stale or modified plans are rejected before writing. Failed writes attempt verified rollback while the connection remains synchronized; a disconnected client receives no recovery I/O. `EdltApplyError.details` reports attempted parameters, rollback errors and `saved=False`.

The CLI exposes `edlt enable-plan SNAPSHOT ...` and `cgate ... unit ... edlt-enable ...`. Both require `--page`, `--position`, `--variable` and `--level`. The native command accepts database destinations only; `--dry-run` previews the verified staged result without saving. The CLI handles the explicit save operation.

| Setting | Accepted values |
|---|---|
| `variable` | Required integer 0..254, on fixed Enable application 203 |
| `level` | Required integer 0..255; zero is valid and is not forced to one |
| `page_mode` | `single` or `multiple`; omitted retains the current interpretation |
| `page`, `position` | Single: page 1, positions 1..5. Multiple: pages 1..4, positions 1..4 |
| `label_type` | `blank`, `static`, `dynamic-text`, `dynamic-icon` |
| `status_type` | `blank`, `level`, `percent`, `bar`, `static`, `dynamic-text`, `dynamic-icon` |
| `label_index`, `status_index` | Static slot 0..63 or dynamic variant 0..3, only for a display using that index |
| `label_text`, `status_text` | Select static display and allocate/reuse shared text; incompatible with the corresponding explicit index or another display type |

Text uses the existing whole-unit shared allocator: reuse the first exact string match, otherwise the highest unused slot. Scene names, page names and all known widget references are considered. Allocating the second string sees the first new reference, so equal strings share a slot and different strings receive distinct available slots. Text must be nonblank, contain no NUL, and occupy 1..63 UTF-8 bytes. A full table is an error; referenced strings are not overwritten.

Dynamic references do not upload or fetch network labels. The original model chooses text versus icon from the selected network group's dynamic metadata, which is absent from a PP snapshot. Changing a variable or an existing dynamic variant therefore requires an explicit corresponding `label_type` or `status_type`. Retaining the variable and variant preserves the current type. Switching between dynamic text and icon preserves the index; switching display categories resets its index to zero before applying any explicit index.

The original `GroupAddress` setter also changes the selected widget's restore level. It scans other widgets in order and copies the first `StatusLabelAppGroupData` widget's restore level with the same numeric group address, **without comparing application addresses**. With no match it uses zero; retaining the selected variable preserves its existing restore level. The helper matches this behavior for the exact known AppGroup types (Lighting, Shutter, Fan, Timer, Enable, RCP and MultiLevel) and reports `restore_level` and `restore_source_widget`. The latter is the selected widget when preserved, another widget when copied, or `None` for the no-match zero. AppGroup types in unsupported standby positions are rejected because their schema has no restore-level parameter.

Functional widgets 6..21 map to the supported pages. The helper preserves standby widgets, other active widgets, scene records and names, selected opaque/inactive bytes and existing application configuration. It rejects replacement of another widget type, unsupported profiles, malformed references and active widgets following a terminator. Required terminator changes use the existing shared placement logic.

## Exact original evidence

`research/NativeEdltEnableProbe.cs` calls the original, unchanged Toolkit 1.18 `CBusLogicModel.dll` on synthetic in-memory objects. DLL SHA256 is `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`. Source mappings from the decompiled original assembly and WinForms UI are:

| Source | Proven mapping |
|---|---|
| `EnableWidget` and `CommonConstants.lDualKeyMacroFunctionsEnable` | Widget type 14, only Off/Preset pair 10/23, Enable Level numeric input 0..255; application picker hidden |
| `EnableData.GetSelectedApplication` | Fixed application 203 even when existing control bit 7 is set |
| `EnableData.TargetLevel1` | Record byte 9; inactive `TargetLevel2` at byte 10 is preserved |
| `StatusLabelAppGroupData.GroupAddress` | Variable at byte 6 and numeric-group restore lookup described above |
| `StatusLabelTypeData` and `EnableData` | Label type in byte 1 bits 4..6, status type in bits 0..3; indexes in bytes 11/12; overridden index setters cause category-reset semantics |
| `BaseStatusLabel` and `CommonConstants.lFunctionStatusTypes` | Blank, Bar, Dynamic Label/Icon, Level, Percent and Static Text |
| `EnableData.SetToDefault` | Default icons 34/33, macros 10/23, blank display types and application-variant bit zero; opaque bytes survive |
| `AppGroupButtonFunctionsData` | Macro default handling may set preset 255; this helper always requires and writes an explicit preset |

No ramp-time option is exposed: Enable does not serialize its inherited `RampRate` property and its UI has no ramp control. New-widget defaults clear an index only when the old corresponding display category was nonblank. Existing Enable control bit 7 and inactive byte 10 remain preserved. These behaviors are covered by opaque-data and literal original-DLL tests.

Some original DLL vectors:

```text
default:         0E0022210000FF0A17FF00000000000000000000000000000000000000000000
preset127/static:0E35222100002A0A177F003F3E00000000000000000000000000000000000000
dynamic-icons:   0E27222100002A0A177F00010300000000000000000000000000000000000000
dynamic-text:    0E16222100002A0A177F00020000000000000000000000000000000000000000
variable43:      0E27222100002B0A177F00020000000000000000000000000000000000000000
```

The last vector changes variable 42 to 43 and refreshes dynamic types from an explicitly constructed synthetic group. Original DLL restore-level output changes from 0 to 137, copied from Lighting widget 7 on application 56 despite Enable using application 203. These values are deliberate fixtures, not captured user settings.

## Acceptance

`tests/test_edlt_enable.py` verifies literal original-DLL bytes, boundaries and display styles, exact restore lookup, shared-text preservation/exhaustion, page limits, malformed input, profile/schema/stale-plan guards, canonical plan validation, rollback and disconnect behavior. Its native test uses an owned, unopened C-Gate 3.4.0.2001 project and synthetic 5055EDL unit, reads exact widget/static/restore PP bytes, compares five CRCs with the original DLL method, saves/closes/reloads, and compares the entire normalized PP snapshot. The network remains `state=new`.

`tests/test_cli_edlt_enable.py` independently exercises offline planning, preview, native save/reload, UTF-8 shared-text deduplication, restore lookup and database destination guards. Run all 12 tests with no opt-in skips from `toolkit-cli`:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_ENABLE_REPORT=research/runtime/edlt-enable-report.json \
PYTHONPATH=src:tests python3 -m unittest test_edlt_enable test_cli_edlt_enable -v
```

The native probe requires Docker with the pinned Mono image used by other eDLT acceptance tests. Vendor binaries and full runtime reports remain ignored. A compact evidence record is stored in `research/fixtures/edlt-enable-acceptance.json`.
