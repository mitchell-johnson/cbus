# eDLT Fan widgets

`EdltFanWidget` configures **5055EDL / KEYGL5 firmware 5.5.00** Fan widgets in database PP sessions. It implements one, two or three speeds, thresholds, group/application, page placement, the widget label and four static status labels. It verifies the complete staged PP snapshot and five Toolkit configuration CRCs. Physical fan operation and custom button icons are outside this workflow.

```python
from cbus_toolkit.edlt_fan import EdltFanWidget

editor = EdltFanWidget(spec)
plan = editor.plan(
    session.values(), page=1, position=1, group=42,
    application="secondary", speeds=3,
    low_threshold=84, high_threshold=170,
    label_text="Ceiling", off_text="Stopped",
    low_text="Slow", medium_text="Normal", high_text="Fast",
)
print(plan.as_dict())
result = editor.apply(session, plan)  # verified=True, saved=False
session.save_to_source()
```

| Setting | Accepted values |
|---|---|
| `group` | Required integer 0..254 |
| `application` | `primary` (default) or `secondary`; selected application must be assigned in 48..95 |
| `speeds` | 1, 2 or 3; omitted preserves valid source thresholds, fresh default is 3 |
| `low_threshold` | Two speeds: 1..254, sets both stored thresholds. Three speeds: 1..253 and less than high threshold. Not used for one speed |
| `high_threshold` | Three speeds only: 2..254 and greater than low threshold |
| `page_mode` | `single` or `multiple`; omitted retains current interpretation |
| `page`, `position` | Single: page 1, positions 1..5. Multiple: pages 1..4, positions 1..4 |
| `label_type` | `blank`, `static`, `dynamic-text`, `dynamic-icon` |
| `label_index` | Static slot 0..63 or dynamic variant 0..3, for a display using an index |
| `label_text` | Select static display and allocate/reuse text; incompatible with explicit label index or another label type |
| `off_text`, `low_text`, `medium_text`, `high_text` | Allocate/reuse the corresponding static status text |
| `off_index`, `low_index`, `medium_index`, `high_index` | Select an exact static slot 0..63; mutually exclusive with the corresponding text option |

Explicit `speeds` invokes the original mode setter: 1 writes thresholds 0/0, 2 writes 127/127, and 3 writes 84/170, before requested threshold overrides. This resets thresholds even if the same speed count is supplied. Omit `speeds` to retain existing thresholds. Invalid source thresholds require an explicit speed count to reset them.

The helper validates the requested final threshold pair. The original UI shifts the neighboring threshold when a slider crosses it; this API requires an explicit valid pair and does not infer an unrequested neighboring value.

Off and High status labels are available for every speed count. Low is editable with two or three speeds; Medium with three only. Requests to edit hidden labels are rejected, while existing hidden references remain reserved and unchanged. One-speed means Off/High; two-speed means Off/Low/High; three-speed means Off/Low/Medium/High.

The original Fan model always forces status display to static. If an existing source has another status category, the plan sets it to static and resets the Off index to zero, matching `MultiLevelData.SetForcedValues`. `status_forced` reports this change; `status_indices` reports all four resulting references. The original save hook forces static status after edits, discarding an Off edit made on a nonstatic source. Such a combination is rejected; apply a normalization plan first, then use `off_text` or `off_index` in a second plan. Slot zero is whatever text the source stores there—native defaults contain `Light`. No generic status-type or button-macro option is exposed.

`configure(session, **settings)` checks database identity before reading PP values. `apply` checks native schema, unchanged full source snapshot and a canonical plan including allocation metadata. It verifies all staged PP values. A partial staging failure attempts verified rollback while the connection is synchronized. After disconnection it sends no recovery I/O; `EdltApplyError.details` reports attempted fields, rollback errors and `saved=False`. Saving remains explicit.

## Default text and shared references

Creating a Fan reproduces both `MultiLevelData.SetToDefault` and `FanControllerData.SetToDefault`. The base creates Off, Low, Medium and High, then the subclass creates Fan and reuses the four status texts. Nine nonblank allocation calls occur even when the requested final speed count hides some labels. `default_allocations` records those calls in order, including repeated reuse. Requested label allocation appears in `static_allocation`; requested status allocations appear in `status_allocations`.

| Initial table | Default Fan / Off / Low / Medium / High | Custom Ceiling / Stopped / Slow / Normal / Fast |
|---|---|---|
| Isolated original-DLL scaffold, only Lamp at 1 | 59 / 63 / 62 / 61 / 60 | 58 / 59 / 63 / 62 / 61 |
| Exact native KEYGL5 defaults | Reuse 2 / 12 / 13 / 14 / 15 | 63 / 62 / 61 / 60 / 59 |

Each allocation reserves the current binding until the new binding is installed. Later allocations see earlier edits. Text reuse chooses the first exact string match; an explicit index selects that exact slot, including a later slot containing duplicate text. Equal requested strings share a slot. Unused intermediate text may be overwritten by a later allocation; final `changes` describe final contents.

The allocator examines all known widget, page and scene names, including hidden Low/Medium/High Fan references. New text must be nonblank, contain no NUL and occupy 1..63 UTF-8 bytes. Full or malformed tables are rejected before mutation. Blank status-sentinel authoring is outside this workflow; existing unconditional hidden references are preserved.

Dynamic widget labels require explicit `label_type` when changing group/application or assigning an index, including assigning the same index. The original model consults network metadata to choose text versus icon on every index assignment; that metadata is not in PP. Omit the index to retain an unchanged reference. Static status labels do not depend on dynamic metadata.

The group setter copies restore level from the first other known AppGroup widget with the same numeric group, regardless of application. No match gives zero. An unchanged numeric group retains selected restore state, including when changing application. `restore_source_widget` reports the selected/other widget, or `None` for no match.

The helper preserves other widgets, scenes, opaque bytes and the global `EnableFanControlLevelWrap` setting. It rejects replacing another widget type, unsupported standby AppGroup records, active widgets after a terminator, malformed shared references and other catalog/firmware profiles.

## Original model evidence

`research/NativeEdltFanProbe.cs` executes unchanged Toolkit 1.18 `CBusLogicModel.dll` on explicit synthetic scaffolds. DLL SHA256 is `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`.

| Original source | Exact mapping |
|---|---|
| `EDLTWidget.CreateData`, `FanControlWidget` | Type 4 uses `FanControllerData`, inheriting `MultiLevelData` |
| `MultiLevelData.IsOneSpeed/IsTwoSpeed/IsThreeSpeed` | Bytes 7/8 are thresholds; setters write 0/0, 127/127 or 84/170 |
| `MultiLevelWidget2`, linked `LevelControl` instances | Speed visibility, threshold limits and neighboring-value adjustment |
| `StatusLabelAppGroupData` | Group byte 6, application bit 7 of byte 1, numeric-group restore lookup |
| `MultiLevelData.LabelValueIndex/StatusValueIndex` | Widget label byte 9, Off status byte 10; label type in byte 1 bits 4..6, status in low nibble |
| `MultiLevelData.LowStatusTextIndex/MedStatusTextIndex/HighStatusTextIndex` | Bytes 11/12/13, always included in static references |
| `FanControllerData.SetToDefault` and base | Static Fan label, static status texts, icons 4/3; opaque bytes 4/5/14..31 remain |
| `MultiLevelData.SetForcedValues` | Static status code 5; Off index reset when its category changes |

The Fan thresholds occupy storage named as macro bytes by some base classes; the actual Fan UI and model use thresholds. There is no Fan macro pair or ramp field in this workflow. Global level-wrap is a separate unit setting at logical address 0x117 bit 5 and remains unchanged.

Literal original-DLL vectors:

```text
native default:   0435040300002A54AA020C0D0E0F000000000000000000000000000000000000
one speed:        04B5040300002A0000020C0D0E0F000000000000000000000000000000000000
two, threshold254:04B5040300002AFEFE020C0D0E0F000000000000000000000000000000000000
three,253/254:    04B5040300002AFDFE020C0D0E0F000000000000000000000000000000000000
custom labels:    04B5040300002AFDFE3F3E3D3C3B000000000000000000000000000000000000
indexes50..53:    04B5040300002AFDFE3F32333435000000000000000000000000000000000000
```

The vectors use group 42 and secondary application 57 where applicable. These are synthetic fixture values. The probe also verifies duplicate strings versus exact indexes, bounds 0/63, opaque bytes, static status forcing, same-index dynamic refresh and restore copied across applications.

## Native acceptance

The CLI provides `edlt fan-plan SNAPSHOT ...` and `cgate ... unit ... edlt-fan ...`. Native destinations must be database units; `--dry-run` previews without saving. `tests/test_cli_edlt_fan.py` verifies offline/native preview, all speed modes, explicit indexes, raw bytes, save/reload and invalid settings.

`tests/test_edlt_fan.py` covers literal original vectors, all speed modes and thresholds, original allocation order, static reuse/dedup/full-table guards, exact duplicate indexes, hidden references, same-index dynamic metadata, status forcing, profiles/layouts, stale/forged plans, rollback and disconnection handling.

Its native test uses a uniquely marked, unopened C-Gate 3.4.0.2001 project with a synthetic 5055EDL unit. It validates native defaults, exact widget/static/restore raw bytes, all speed modes, explicit indexes and text reuse, dynamic guards, status forcing, five CRCs against the original private DLL method, and full PP equality after save/close/load. The network remains `state=new`.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_FAN_REPORT=research/runtime/edlt-fan-report.json \
PYTHONPATH=src:tests python3 -m unittest test_edlt_fan test_cli_edlt_fan -v
```

Original DLL probes require Docker with the pinned Mono image used by the eDLT tests. Vendor files and full outputs remain ignored; compact evidence is recorded in `research/fixtures/edlt-fan-acceptance.json`.
