# eDLT MultiLevel widgets

`EdltMultiLevelWidget` configures type 16 widgets for **5055EDL / KEYGL5 firmware 5.5.00** in database PP sessions. It supports one, two or three levels, their thresholds, page placement, group/application selection, a widget label and four static status references. It verifies the complete staged PP snapshot and five Toolkit CRCs. This is database configuration acceptance; physical button operation has not been verified.

```python
from cbus_toolkit.edlt_multilevel import EdltMultiLevelWidget

editor = EdltMultiLevelWidget(spec)
plan = editor.plan(
    session.values(), page=1, position=1, group=42,
    application="secondary", levels=3,
    low_threshold=84, high_threshold=170,
    label_text="Ventilation", off_text="Stopped",
    low_text="Low", medium_text="Medium", high_text="High",
)
print(plan.as_dict())
editor.apply(session, plan)  # complete staged readback; saved=False
session.save_to_source()
```

| Setting | Contract |
|---|---|
| `group` | Required integer 0..254 |
| `application` | Select the unit's `primary` or `secondary` application; selected value must be 48..127 or 136 |
| `levels` | 1, 2 or 3; omitted retains valid source thresholds; fresh default is 3 |
| `low_threshold` | Two levels: 1..254, stored in both threshold bytes. Three levels: 1..253 and less than high threshold |
| `high_threshold` | Three levels only: 2..254 and greater than low threshold |
| `page_mode`, `page`, `position` | Single page 1 with positions 1..5, or multiple pages 1..4 with positions 1..4 |
| `label_type` | `blank`, `static`, `dynamic-text` or `dynamic-icon` |
| `label_index` | Static slot 0..63 or dynamic variant 0..3, according to display type |
| `label_text` | Select static display and allocate/reuse text; cannot accompany a label index or another label type |
| `off_text`, `low_text`, `medium_text`, `high_text` | Allocate/reuse status text in its corresponding stored slot |
| `off_index`, `low_index`, `medium_index`, `high_index` | Select an exact static slot 0..63; mutually exclusive with the matching text option |

The application range comes from the original `CBusBaseUnit.PopulateAllLists`: inclusive 48..127 with 136 explicitly included. `BindingListCBusObject.PopulateList` treats the last argument as additional included values. The helper selects an already assigned application; it does not change the unit's primary/secondary values or create groups. Native acceptance covers 48, 95, 96, 127 and 136, including full PP save/reload and original CRC comparison. Other application values are rejected before edits.

Explicit `levels` invokes the original mode setter before threshold overrides: one writes 0/0, two writes 127/127, and three writes 84/170. Supplying the current level count still resets thresholds. One level rejects threshold options. Two levels accepts only `low_threshold`, writing both bytes. Three levels requires the final pair `1 <= low < high <= 254`. Invalid source thresholds require an explicit level count to reset them.

The Toolkit UI links two `LevelControl` instances and adjusts a neighboring slider when they cross. This API validates the requested final pair; it does not emulate individual slider movements or silently change a neighboring threshold.

The stable API names `low`, `medium` and `high` identify bytes 11, 12 and 13. Toolkit calls them Level 1, Level 2 and Level 3 status labels. Off and High are visible in every level mode; Low is visible with two or three levels, and Medium only with three. Hidden references remain reserved and unchanged. Requests to edit a hidden status are rejected. One-level mode therefore uses the stored Off/High references, and two-level mode uses Off/Low/High.

## Defaults and save ordering

Type 16 calls `MultiLevelData.SetToDefault`, including its AppGroup and status/label base defaults. It writes a blank widget label with index 255, static status type 5, icons 134/134 and thresholds 84/170. It makes exactly four nonblank text allocation calls, in order: Off, Low, Medium, High. No default widget-label text is allocated. `default_allocations` records those four calls even if the requested level count hides some statuses.

| Initial table | Off / Low / Medium / High | Requested Ceiling / Stopped / Slow / Normal / Fast |
|---|---|---|
| Original DLL scaffold with only Lamp at 1 | 63 / 62 / 61 / 60 | 59 / 58 / 63 / 62 / 61 |
| Native KEYGL5 defaults | Reuse 12 / 13 / 14 / 15 | 63 / 62 / 61 / 60 / 59 |

Each allocation sees preceding edits, reserves currently used widget/page/scene references and chooses the first exact existing text match. An explicit index selects that slot even when an earlier duplicate exists. Equal requested strings share a slot. Low/Medium/High remain references when hidden; a full or malformed table rejects before mutation. New text must be nonblank, contain no NUL and occupy 1..63 UTF-8 bytes. Blank status-sentinel authoring is outside this helper.

`label_text` selects static display before allocating text. This order matters: the original model permits allocating text while the label remains blank, leaving that string unreferenced and available for a later allocation to overwrite. The helper performs the complete static-label action.

`EDLTUnit.BeforeSavePPData` saves shared text and scenes, then calls each widget's `SetForcedValues`. MultiLevel always forces static status. Changing an existing nonstatic category resets its Off index to zero, while retaining the other status references. Such plans report `status_forced=True`. An Off edit on that nonstatic source would be discarded by the original save ordering, so the helper rejects it: first apply a normalization plan, then edit Off in a second plan. Slot zero retains its source meaning; native defaults contain `Light` there.

Dynamic label assignments consult network metadata in the original model, including when assigning the same index. The PP snapshot does not contain that metadata. Changing a dynamic group/application/index requires explicit `label_type` to resolve text versus icon. Omit the index to retain an unchanged binding. Static status has no dynamic dependency.

The original group setter copies restore level from the first other AppGroup widget with the same numeric group, regardless of application. No match produces zero; an unchanged group retains its current restore level. `restore_source_widget` identifies the selected/other widget or `None` for no match. The helper preserves opaque bytes 4/5/14..31, scenes, other widgets and global level-wrap settings. Custom button icons and global level-wrap editing remain separate gaps.

`configure` checks identity before reading PP. `apply` verifies the exact schema, unchanged complete source and a canonical plan including allocation metadata, then verifies all staged values. On a partial staging failure it attempts verified rollback while the stream remains synchronized. A disconnected stream gets no recovery I/O. `EdltApplyError.details` records attempted fields, rollback evidence and `saved=False`. Replacement of another widget type, malformed layouts and other catalog/firmware profiles are rejected.

## Independent evidence

`research/NativeEdltMultiLevelProbe.cs` invokes the unchanged original `CBusLogicModel.dll` with explicit synthetic PP/network fixtures. It tests defaults, all three mode setters, threshold endpoints, allocation order, index/text behavior, forcing, dynamic same-index refresh, application selection, opaque bytes and numeric-group restore copying. DLL SHA256: `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`.

| Original source | Storage/behavior |
|---|---|
| `EDLTWidget.CreateData`, `MultiLevelWidget2` | Type 16 uses `MultiLevelData` |
| `MultiLevelData.IsOneSpeed/IsTwoSpeed/IsThreeSpeed` | Threshold bytes 7/8; defaults 0/0, 127/127, 84/170 |
| `MultiLevelWidget2`, `LevelControl` | Visibility and UI threshold limits |
| `StatusLabelAppGroupData` | Group byte 6, application bit 7 of byte 1, restore lookup |
| `MultiLevelData.LabelValueIndex/StatusValueIndex` | Widget label byte 9, Off byte 10; display categories in byte 1 |
| `LowStatusTextIndex/MedStatusTextIndex/HighStatusTextIndex` | Bytes 11/12/13, unconditional shared references |
| `MultiLevelData.SetToDefault/SetForcedValues`, `EDLTUnit.BeforeSavePPData` | Four default allocations; save-time static status forcing |

Literal original vectors with native default text slots:

```text
default:       1005868600002A54AAFF0C0D0E0F000000000000000000000000000000000000
one level:     1085868600002A0000FF0C0D0E0F000000000000000000000000000000000000
two at254:     1085868600002AFEFEFF0C0D0E0F000000000000000000000000000000000000
three253/254:  1085868600002AFDFEFF0C0D0E0F000000000000000000000000000000000000
custom labels: 10B5868600002AFDFE3F3E3D3C3B000000000000000000000000000000000000
```

`edlt multilevel-plan SNAPSHOT ...` produces an offline plan; `cgate ... unit ... edlt-multilevel ...` applies a database configuration. `--dry-run` previews without saving. `tests/test_cli_edlt_multilevel.py` covers original vectors, offline/native preview agreement, all modes, secondary applications96/127/136, unchanged source on rejected settings, database-only saves and full parameter reload.

`tests/test_edlt_multilevel.py` compares these literals to the helper and executes the original probe. Its native fixture creates a uniquely marked, unopened C-Gate project and database unit. It verifies widget/static/restore raw bytes, all five CRCs using the original private DLL method, and complete PP equality after save/close/load. Each tested application boundary gets its own save/reload and CRC comparison. Network state remains `new`; no physical endpoint is opened.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_MULTILEVEL_REPORT=research/runtime/edlt-multilevel-report.json \
PYTHONPATH=src:tests python3 -m unittest tests.test_edlt_multilevel tests.test_cli_edlt_multilevel -v
```

The original DLL probe requires Docker with the pinned Mono image used by the native eDLT tests. Full runtime reports and vendor sources remain local; compact metadata is in `research/fixtures/edlt-multilevel-acceptance.json`. Database configuration acceptance does not establish physical MultiLevel behavior, other firmware profiles or full Toolkit parity.
