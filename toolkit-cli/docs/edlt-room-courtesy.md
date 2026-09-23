# eDLT Room Courtesy widgets

`EdltRoomCourtesyWidget` configures Room Courtesy widgets for **5055EDL / KEYGL5 firmware 5.5.00** in database PP sessions. It implements the original Bell Press and Unused modes, off/on colours, group/application, page placement and shared or dynamic label/status references. Plans verify the whole PP snapshot and five Toolkit configuration CRCs. Physical button execution, panel colour behaviour and custom state icons are outside this workflow.

```python
from cbus_toolkit.edlt_room_courtesy import EdltRoomCourtesyWidget

editor = EdltRoomCourtesyWidget(spec)
plan = editor.plan(
    session.values(), page=1, position=1, group=42,
    application="secondary", mode="bell-press",
    off_colour="red", on_colour="green",
    label_text="Courtesy", status_text="Available",
)
print(plan.as_dict())
result = editor.apply(session, plan)  # verified=True, saved=False
session.save_to_source()
```

The CLI provides `edlt room-courtesy-plan SNAPSHOT ...` and `cgate ... unit ... edlt-room-courtesy ...`. Native destinations must be database units. `--dry-run` validates a native preview without saving; normal native execution saves the verified result.

| Setting | Accepted values |
|---|---|
| `group` | Required integer 0..254 |
| `application` | `primary` (default) or `secondary`; selected application must be assigned in 48..127 or equal 136 |
| `mode` | `bell-press` or `unused`; omitted preserves a valid existing mode |
| `off_colour`, `on_colour` | `none`, `white`, `red`, `green`, `blue`, `cyan`, `magenta`, `yellow`, `orange`; omitted preserves a valid existing colour |
| `page_mode` | `single` or `multiple`; omitted retains the current interpretation |
| `page`, `position` | Single: page 1, positions 1..5. Multiple: pages 1..4, positions 1..4 |
| `label_type`, `status_type` | `blank`, `static`, `dynamic-text`, `dynamic-icon` |
| `label_index`, `status_index` | Static slot 0..63 or dynamic variant 0..3, for a display using that index |
| `label_text`, `status_text` | Select static display and allocate/reuse text; incompatible with the corresponding explicit index or a different display type |

Colours are named strings at the public boundary; integers, booleans and unrecognized names are rejected. New widgets default to Bell Press, colours `none`/`none`, blank label/status and state icons 132/132. Creating this widget allocates no default text. Existing invalid macro/colour values require an explicit valid replacement. The original model performs no extra value forcing for this type. Existing custom icon bytes and unrelated opaque fields remain intact.

The application range comes from the original primary/secondary application selectors: their range is 48..127 with explicit additional value 136. Native PP, original model selection, CRC and save/reload tests cover 127 and 136. This extends the evidence for this helper only; older helpers retain their documented bounded ranges. The helper uses the selected assigned application and does not change global application choices or infer application names from numeric addresses.

## Dependencies and preservation

The shared text allocator reuses the first exact string match, otherwise selecting the highest unused slot. It enumerates all known widget, page and scene name references. The second allocation sees the first reference, so two different strings get distinct slots and equal strings share one slot. Explicit indexes select exact existing slots, including duplicate text. Text must be nonblank, contain no NUL and occupy 1..63 UTF-8 bytes. Exhaustion and malformed reference tables fail before mutation.

Dynamic references select existing variants; they do not upload or fetch network labels. The original model derives text versus icon from network metadata that is absent from PP. Changing group/application or explicitly assigning a dynamic index therefore requires an explicit corresponding display type. This includes assigning the same index: both original RCP index setters refresh metadata unconditionally. Omit an unchanged index to retain its current type. Switching between dynamic text and icon retains the index; switching categories resets it to zero before an explicit index is applied.

Although the Room Courtesy UI hides restore-level text, its inherited group setter still copies restore level from the first other known AppGroup widget with the same numeric group, in widget order and across applications. With no match it uses zero. An unchanged numeric group retains the selected widget's restore level. Plans report the value and source widget. Unsupported AppGroup records in standby slots are rejected because they have no schema-backed restore field.

Only blank, unused or existing Room Courtesy slots can be configured. Other widget types, active records after a terminator, unsupported catalog/firmware profiles and invalid shared references are rejected. The full source snapshot, schema, identity and canonical plan are checked before staging. A staging failure attempts verified rollback while the connection remains synchronized; after disconnection, no recovery I/O is sent. `EdltApplyError.details` preserves attempted fields, rollback errors and `saved=False`.

## Original evidence

`research/NativeEdltRCPProbe.cs` executes unchanged Toolkit 1.18 `CBusLogicModel.dll` methods on explicit synthetic PP objects. The DLL SHA256 is `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`. Vendor assemblies and decompiled files remain ignored; the repository contains the independent probe and literal result evidence.

| Original source | Verified mapping |
|---|---|
| `EDLTWidget.CreateData`, `RCAWidget` | Widget type 15 uses `RCPData` |
| `RCAWidget.SetUpDataSource`, `CommonConstants.DualKeyMacroFunctionsRCP` | One `KeyMacrofunction` at byte 7: Bell Press 25 or Unused 255; byte 8 is a label index |
| `RCPData.OffColour`, `.OnColour`, `CommonConstants.KeyColours` | Bytes 10/11; ordered names none through orange encode 0..8 |
| `RCPData.LabelValueIndex`, `.StatusValueIndex` | Bytes 8/9, including unconditional dynamic metadata refresh on setter calls |
| `StatusLabelTypeData` | Label category in byte 1 bits 4..6; status category in low four bits |
| `FunctionStatusTypesRCP`, `RCAWidget` | Blank 0, static 5 and dynamic text/icon 6/7; level/percent/bar/timer status is not offered |
| `StatusLabelAppGroupData` | Group byte 6, application variant in byte 1 bit 7; inherited numeric-group restore lookup |
| `CBusBaseUnit`, `BindingListCBusObject` | Primary/secondary choices include 48..127 plus explicit 136 |
| `RCPData.SetToDefault` | Icons 132/132, colours 0/0, macro 25, blank categories and no static text allocation |
| `RCPData.StatusIconIndex`, `RCAWidget` | A single state icon setter writes both icon bytes; setting custom icons remains outside this bounded API |

The original macro table defines Bell Press 25 as `OnKey, Idle, OffKey, OffKey`. This establishes the selected macro's serialized identity; physical event behavior has not been exercised.

Literal original-DLL records:

```text
default, unbound: 0F0084840000FF19000000000000000000000000000000000000000000000000
default group42:  0F00848400002A19000000000000000000000000000000000000000000000000
unused red/green: 0F80848400002AFF000002030000000000000000000000000000000000000000
custom text:      0FB5848400002AFF3F3E02030000000000000000000000000000000000000000
bell, same text:  0FB5848400002A193F3E02030000000000000000000000000000000000000000
dynamic icons:    0FA7848400002A19010302030000000000000000000000000000000000000000
same-index edit:  0FA7848400002A19020002030000000000000000000000000000000000000000
```

These use explicit synthetic group 42, secondary application 57 where selected, and strings Courtesy/Available in slots 63/62. The original probe also covers all nine colours, opaque fields, categories already blank before defaulting, same-index text-to-icon metadata changes, cross-application restore copying, selected applications 127/136 and the absence of forced-value changes.

## Acceptance

`tests/test_edlt_room_courtesy.py` combines independent original-DLL literals, all modes/colours, strict settings, dynamic dependency guards, shared allocation/exhaustion, exact index selection, opaque fields, restore lookup, page placement, profile/layout guards, stale/forged plans and rollback/disconnection tests.

Its native test uses an owned unopened C-Gate 3.4.0.2001 project. It verifies default/custom/dynamic raw records, restore bytes, shared Māori UTF-8 text, unchanged other widgets and scenes, all five CRCs against the original DLL, and complete PP equality after save/close/load for applications 127 and 136 separately. The network remains `state=new`.

`tests/test_cli_edlt_room_courtesy.py` covers the CLI boundary. Run both suites from `toolkit-cli`:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_ROOM_COURTESY_REPORT=research/runtime/edlt-room-courtesy-report.json \
PYTHONPATH=src:tests python3 -m unittest test_edlt_room_courtesy test_cli_edlt_room_courtesy -v
```

The original DLL test uses the pinned Mono Docker image shared with the other eDLT acceptance probes. Compact results are saved in `research/fixtures/edlt-room-courtesy-acceptance.json`. Physical panel invocation and custom state-icon authoring remain unverified.
