# eDLT Timer widgets

`EdltTimerWidget` configures **5055EDL / KEYGL5 firmware 5.5.00** Timer widgets in database PP sessions. It implements the original UI's Toggle/Retrigger mode, duration, target and expiry levels, ramp time, group/application, page placement and shared or dynamic label/status references. It verifies the entire staged PP snapshot and five Toolkit configuration CRCs. Physical timer execution and custom button icons are outside this workflow.

```python
from cbus_toolkit.edlt_timer import EdltTimerWidget

editor = EdltTimerWidget(spec)
plan = editor.plan(
    session.values(), page=1, position=1, group=42,
    application="secondary", duration_seconds=300,
    target_level=127, expiry_level=100, ramp_seconds=20,
    label_text="Timer", status_text="Ready",
)
print(plan.as_dict())
result = editor.apply(session, plan)  # verified=True, saved=False
session.save_to_source()
```

The CLI provides `edlt timer-plan SNAPSHOT ...` and `cgate ... unit ... edlt-timer ...`. Page, position and group are required. `--dry-run` verifies a native preview without saving; the normal native command explicitly saves the result. Native destinations must be database units.

| Setting | Accepted values |
|---|---|
| `group` | Required integer 0..254 |
| `application` | `primary` (default) or `secondary`; the selected application must be assigned in 48..95 |
| `duration_seconds` | Integer 0..64800; fresh default 60 |
| `target_level` | Integer 1..255; fresh default 255 |
| `expiry_level` | Integer 0..255; fresh default 0 |
| `ramp_seconds` | 0, 4, 8, 12, 20, 30, 40, 60, 90, 120, 180, 300, 420, 600, 900 or 1020; fresh default 1020 |
| `page_mode` | `single` or `multiple`; omitted retains the current interpretation |
| `page`, `position` | Single: page 1, positions 1..5. Multiple: pages 1..4, positions 1..4 |
| `label_type` | `blank`, `static`, `dynamic-text`, `dynamic-icon` |
| `status_type` | `blank`, `timer`, `static`, `dynamic-text`, `dynamic-icon` |
| `label_index`, `status_index` | Static slot 0..63 or dynamic variant 0..3, only for a display using that index |
| `label_text`, `status_text` | Select static display and allocate/reuse text; incompatible with the corresponding explicit index or another display type |

Omitted timing and level options retain valid existing values. The original Timer default stores ramp index 15, which is **1020 seconds (17 minutes)**. It is reproduced exactly; callers can explicitly select `ramp_seconds=0` for instant operation. Existing target zero is normalized to one by the original `SetForcedValues` method, even when the target option is omitted. An explicit request for zero is rejected because the original target control permits 1..255. Existing duration, expiry or ramp values outside the supported UI ranges require an explicit valid replacement.

Only Toggle/Retrigger is offered by the original Timer UI. Every plan binds macro bytes 35/34; no independent mode option is exposed. Zero duration is a supported original control value, but this database workflow does not establish physical behavior for it. The original expiry model stores a signed word and can serialize negative values; their meaning is unverified, so only the UI's 0..255 range is supported.

`configure(session, **settings)` checks database identity before reading PP values. `apply` requires an unchanged full source snapshot, matching native schema, and a canonical plan with verified settings and allocation metadata. Partial staging failures attempt verified rollback while the connection remains synchronized. After disconnection, no recovery I/O is sent; `EdltApplyError.details` reports attempted fields, rollback errors and `saved=False`.

## Default text and reference preservation

Creating a Timer widget reproduces `TimerData.SetToDefault`, including its static **Fan** label and timer status. This allocation occurs before requested label/status edits, even if the final label is blank. The plan reports `default_label_allocation`, `static_allocation` and `status_allocation` separately.

The shared allocator reuses the first exact string match, otherwise selecting the highest unused slot. It examines all known widget, page and scene name references. Each allocation sees bindings created by the preceding allocation; equal requested strings share a slot. Text must be nonblank, contain no NUL and occupy 1..63 UTF-8 bytes. Exhausted or malformed tables are rejected before mutation.

| Initial table | Default Fan | Custom Timer | Status Ready |
|---|---|---|---|
| Isolated original-DLL scaffold, no Fan text | Allocate 63 | Allocate 62 | Reuse the now-unreferenced slot 63 |
| Exact native KEYGL5 defaults, Fan already at 2 | Reuse 2 | Allocate 63 | Allocate 62 |

Both sequences are independently reproduced by the original DLL probe. The native sequence preserves Fan at slot 2. Allocation metadata describes the sequence; the plan's final changes contain final contents if a later allocation overwrites an intermediate unreferenced string.

Dynamic references do not upload or fetch network labels. The original model chooses text versus icon from network variant metadata, which is absent from PP. Changing group/application or explicitly assigning a dynamic index therefore requires an explicit corresponding display type. This includes assigning the **same index**, because the original Timer setters refresh metadata on every assignment. Omit the index to retain an unchanged reference without declaring its type. Switching between dynamic text and icon retains the index; changing display categories resets the index to zero before an explicit index is applied.

The original group setter copies restore level from the first other known AppGroup widget with the same numeric group, in widget order, without comparing applications. With no match it uses zero. Retaining the numeric group preserves selected restore state, including when changing application. The plan reports `restore_level` and `restore_source_widget`: the selected widget when retained, another widget when copied, or `None` for the no-match zero. Unsupported AppGroup records in standby slots are rejected because they have no schema-backed restore field.

Functional widgets 6..21 map to supported pages. Other widgets, scene records and names, and opaque bytes are preserved. Replacing another widget type, active widgets after a terminator, malformed shared references and other catalog/firmware profiles are rejected.

## Original model evidence

`research/NativeEdltTimerProbe.cs` executes unchanged Toolkit 1.18 `CBusLogicModel.dll` on explicit synthetic objects. DLL SHA256 is `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`.

| Original source | Exact mapping |
|---|---|
| `EDLTWidget.CreateData`, `TimerWidget` | Type 5 uses `TimerData` |
| `CommonConstants.DualKeyMacroFunctionTimer`, `TimerWidget.SetUpDataSource` | Sole Toggle/Retrigger mode: bytes 7/8 = 35/34 |
| `TimerData.TargetLevel`, `TargetLevelControl` | Byte 9; target UI range 1..255 |
| `TimerData.TimerValue`, `TimerSelector` | Little-endian bytes 12/13; UI range 0..64800 seconds |
| `TimerData.ExpiryLevel`, `ExpiryLevelControl` | Little-endian bytes 14/15; bounded UI levels 0..255 |
| `TimerData.RampRate`, `CommonConstants.RampRates` | Byte 16, table index 0..15 |
| `StatusLabelAppGroupData` | Byte 6 group, byte 1 bit 7 primary/secondary application; numeric-group restore lookup |
| `TimerData`, `StatusLabelTypeData` | Label type in byte 1 bits 4..6; status in low four bits; indexes at bytes 17/18 |
| `TimerWidget.SetUpDataSource`, `FunctionStatusTypesTime` | Timer status 4, blank 0, static 5 and dynamic text/icon 6/7; generic level/percent/bar status is not offered |
| `TimerData.SetToDefault` | Static Fan label, timer status, icons 14/13, target 255, duration 60, expiry 0, ramp index 15; opaque bytes 4/5/10/11/19..31 remain |
| `TimerData.SetForcedValues` | Stored target 0 becomes 1 |

Literal original-DLL vectors:

```text
default, no Fan:  05340E0D0000FF2322FF00003C0000000F3F0000000000000000000000000000
64800 seconds:   05B40E0D00002A232201000020FDFF00003F0000000000000000000000000000
forced target1:  05B40E0D00002A2322010000000000000F3F0000000000000000000000000000
custom, no Fan:   05B50E0D00002A23227F00002C016400043E3F00000000000000000000000000
custom, Fan2:     05B50E0D00002A23227F00002C016400043F3E00000000000000000000000000
dynamic icons:   05A70E0D00002A23227F00002C01640004010300000000000000000000000000
```

The vectors choose secondary application 57 and group 42 where applicable. Custom timing uses duration 300, target 127, expiry 100 and ramp 20 seconds. These are deliberate fixture values, not user configuration. The probe also verifies zero duration, target forcing, opaque bytes, both initial static tables, same-index metadata refresh, status categories and restore level 137 copied from a Lighting widget on another application.

## Native acceptance

`tests/test_edlt_timer.py` covers original literal vectors, timing/level/ramp bounds, source target forcing, static table allocation and exhaustion, all supported status types, same-index dynamic guards, restore lookup, opaque and unrelated values, unsupported profiles/layouts, stale and forged plans, verified rollback and disconnection handling.

Its native test creates a uniquely marked, unopened C-Gate 3.4.0.2001 project with a synthetic 5055EDL unit. It checks native default Fan reuse, literal widget and restore bytes, static/dynamic labels, timing boundaries and forcing, five configuration CRCs against the original private DLL method, and complete PP equality after save/close/load. The original model changes network variants from text to icons and reassigns the same indexes; native tests reject such assignments without explicit types and confirm unchanged PP values. The network remains `state=new`.

`tests/test_cli_edlt_timer.py` checks offline planning, native preview, exact record and static string bytes, timing/level/ramp options, save/reload, unchanged source after invalid bounds, profile guards and database destination guards. Run both suites from `toolkit-cli`:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_TIMER_REPORT=research/runtime/edlt-timer-report.json \
PYTHONPATH=src:tests python3 -m unittest test_edlt_timer test_cli_edlt_timer -v
```

The original DLL probes require Docker with the pinned Mono image used by the other eDLT acceptance tests. Vendor files and full runtime outputs remain ignored. Compact evidence is recorded in `research/fixtures/edlt-timer-acceptance.json`.
