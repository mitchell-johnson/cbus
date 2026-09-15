# eDLT lighting widgets

`EdltLighting` implements a bounded, semantic widget workflow for **5055EDL,
KEYGL5.xml, firmware 5.5.00**. It configures the two physical key actions for
Lighting **Off/On** or **Dimmer**, chooses a page and position, assigns an
existing primary or secondary Lighting application and group, selects label
and status references, sets a restore level, and configures dimmer ramp time.
It stages a database PP session and verifies every parameter before returning.
The caller separately saves that session.

This is verified widget programming, rather than only generic PP writes or
application label transport. It does not establish full eDLT or Toolkit parity.
Physical eDLT programming and display behaviour have not been exercised.

## Source and byte mapping

The Toolkit 1.18 installer contains readable .NET assemblies `eDLT.dll`,
`CBusLogicModel.dll`, and `EDLTCommon.dll`. The mapping comes from the original
models and their UI bindings:

- `eDLT.WidgetPanels.LightingWidget` selects widget type 2.
- `FrmBaseUnit.FilterWidgets` maps pages onto the unit's widget collection.
- `LightingData`, `AppGroupButtonFunctionsData`, `StatusLabelAppGroupData` and
  `StatusLabelTypeData` bind settings to generic PP widget bytes.
- `CommonConstants`, `MacroFunctionTypes` and `MicroFunctions` define the
  paired key presets, active inputs and ramp-time selector.
- `EDLTUnit.BeforeSavePPData` maintains widget termination and the direct
  application pair; `CBusBaseUnit.CalculateCRCForPPAttributes` calculates the
  section CRCs.

`KEYGL5.xml` independently fixes the PP addresses. Each widget occupies 32
bytes, beginning at logical address `0x220 + (widget_number - 1) * 32`.
Byte 0 is `WidgetNWidgetType`; bytes 1–31 are `WidgetNWidgetByteValue1` through
`WidgetNWidgetByteValue31`.

The shared save normalization follows the original `BeforeSavePPData`: an
earlier functional end marker becomes blank, and the first slot after the last
active functional widget becomes the end marker. With no active functional
widgets, slot 6 becomes the end marker. A changed type also resets that slot's
`RestoreLevel` to zero; an unchanged type preserves its restore level. Opaque
record bytes and slots beyond the new terminator remain unchanged. This was
corrected after the 887-test wheel checkpoint. Eight original DLL cases and
native PP/save/reload acceptance are recorded in
[edlt-normalization-acceptance.json](../research/fixtures/edlt-normalization-acceptance.json).

This behavior applies to the staged model at save time. Toolkit's separate
`LoadWidgetsFromAttributes` lifecycle also removes end markers and clears
records after them when loading into its UI model. The helpers reject active
functional records after a terminator; they do not silently discard raw PP
records to reproduce that loading path.

| Record byte | Meaning for a Lighting widget |
| --- | --- |
| 0 | Widget type 2 |
| 1, bit 7 | Primary application 0; secondary application 1 |
| 1, bits 4–6 | Label mode: blank 0, dynamic text 1, dynamic icon 2, static 3 |
| 1, bits 0–3 | Status: blank 0, level 1, percent 2, bar 3, static 5, dynamic text 6, dynamic icon 7 |
| 2, 3 | On/off status icon indexes; new Lighting defaults 2 and 1 |
| 6 | Group address; helper accepts 0–254 |
| 7, 8 | Left/right macro codes: Off/On 10/9; Dimmer 15/16 |
| 9 | Ramp selector index, not an application-message opcode |
| 10, 11, 12 | Target levels and offset; retained because these presets do not use them |
| 13, 14 | Label and status reference indexes |

Dynamic references use indexes 0–3; static references use indexes 0–63.
Ramp indexes 0–15 correspond to seconds
`0, 4, 8, 12, 20, 30, 40, 60, 90, 120, 180, 300, 420, 600, 900, 1020`.
Only Dimmer accepts a ramp setting. Off/On acts on a short press; Dimmer uses
short-release off/on, long-press down/up and long-release end-ramp.

The two key codes are deliberately named **Off/On** in this API: this is the
original model's left/right order, even where help prose says “On/Off”.

In multiple-page mode, each of four pages contains four functional positions:
page 1 maps to widgets 6–9, page 2 to 10–13, page 3 to 14–17, and page 4 to
18–21. The fifth screen position is navigation. Single-page mode uses widgets
6–10 as five functional positions. Widgets 1–5 belong to standby and are
outside this helper. Changing page mode requires an explicit `page_mode` value;
otherwise the existing navigation mode applies. An uninitialized `FF` mode
is treated as single-page, as in Toolkit's model.

## Preservation and validation

The helper requires all current PP parameters and checks the native device's
catalogue, firmware and full schema before applying a plan. It rejects stale
snapshots, hidden active widgets after a terminator, unsupported selected
widget types, unassigned application selections and invalid page/index values.
It currently supports Lighting Type applications 48–95.

Configuring a blank widget applies the original Lighting defaults while
preserving unrelated opaque bytes. Updating an existing Lighting widget keeps
unspecified fields. The helper changes preceding `FF` terminators to blank
type 0 only as needed to expose the selected widget, and retains an `FF`
terminator after the last active widget. Other widgets, standby content,
scene data and static strings outside a new allocation remain unchanged. New text can
replace one unreferenced static slot, as recorded in its allocation plan.
Required application-pair, version initialization and CRC metadata changes
appear in the returned plan.

`label_text` reuses an already stored UTF-8 static label by exact text, or
allocates a shared-table slot after enumerating every unit reference. Explicit
static and dynamic indexes are supported; dynamic text/icon selection is
explicit and does not guess which content exists on the network. The helper does not transmit label
content or create application groups.

New widgets start with restore level 0 unless specified. Changing an existing
widget's group requires an explicit `restore_level`: Toolkit's model can copy
this value from another widget sharing the group, including other widget
classes whose semantics are outside this implementation. The helper does not
guess that cross-widget state. Updating the same group preserves its restore
level. `Widget6RestoreLevel` begins at logical address `0x1A0`.

## Shared static text allocation

`allocate_static_text(values, text)` returns an immutable allocation plan;
`static_references(values)` reports each used index and the fields referring
to it. Lighting `label_text` and `status_text` use the same allocator and stage
new text and widget references in one verified PP operation. They do not alter another
widget's reference or rename a shared label in place.

When both texts are supplied, the helper follows the original model's property
order: select static label mode, allocate and bind the label, then select
static status mode, allocate and bind the status. Changing a display mode first
resets its index to zero, as the original setter does. The second lookup sees
the first binding and any old reference that has been released. Two equal
texts share one index. Two different texts get separate slots, which need not
be consecutive: the second allocation can use a slot released by the first.
The plan reports label allocation in `static_allocation` and status allocation
in `status_allocation`. If either allocation fails, no PP edits are staged.

Toolkit's exact ordinal search returns the first matching index in 0–63.
Existing duplicates remain in place; matching is case-sensitive and does not
normalize Unicode. If no match exists, `GetStaticTextIndex` selects the highest
unreferenced index, searching from 63 down to 0. The existing text in an unused
slot can be overwritten even when it is nonempty. The helper follows this
behaviour. Reserving a slot in a plan alone does not consume it: its new widget
reference must be staged before a subsequent allocation treats it as used.

References include navigation page names when `NavWidgetVariant == 6`, the
name of each of the eight scene records, and the static references below.
The table lists record-byte offsets, not static-table indexes:

| Widget type | Conditional label/status bytes | Always referenced text bytes |
| --- | --- | --- |
| 0, FF blank; 10, 11 time/date | None | None |
| 2 Lighting | 13 / 14 | None |
| 3 Shutter | 10 / 11 | None |
| 4 Fan, 16 Multilevel | 9 / 10 | 11, 12, 13 |
| 5 Timer | 17 / 18 | None |
| 6 Scene | Status 12 | None |
| 7 MRA zone | Status 12 | 11 |
| 8 MRA source select | None | 9, 10 |
| 9 MRA source control | None | 7 |
| 12 Measurement | None | 10, 11, 13 |
| 13 HVAC temperature | None | 6 |
| 14 Enable | 11 / 12 | None |
| 15 RCP | 8 / 9 | None |

Conditional label/status bytes count only for static label mode 3 or static
status mode 5. MRA zone status uses the low three control bits; its zone occupies
the following three bits. This enumeration is verified against the original DLL for
every class; it does not add programming support for those other widget types.
Unknown types and malformed references are rejected before allocation.
Toolkit clamps some invalid conditional indexes to zero; the helper rejects
them instead of guessing whether firmware uses that same fallback.

Scene pointers are 16-bit offsets into the 232-byte `SceneBucket`, starting
at logical `0x2112`. A populated record's name index is its fifth byte. Each
record's five-byte header and three bytes per declared group must fit within
the bucket. Empty pointers use `FFFF`, and a pointed-to first byte `FF` is an
empty record. The original loader visits all eight pointers regardless of
`SceneCount`; the helper does the same. It reads these references without
rewriting scene data.

The original capacity check counts the unused scene-name sentinel `255` in
the used-index set. The helper retains that check, which can report a full
table with one otherwise free slot when 63 real indexes and sentinel255 are
present. Exact-match reuse still succeeds in a full table.

New labels must be nonblank, valid Unicode, contain no NUL, and encode to at
most **63 UTF-8 bytes**, leaving byte64 for NUL. The full 64-byte PP field is
written with zero padding. The original setter truncates at 63 bytes and can
split a UTF-8 character; the helper rejects that input rather than losing
text. Invalid existing UTF-8 encountered during lookup is also rejected.

Set `label_type="blank"` or `status_type="blank"` to detach a reference. The old shared-table text remains
stored and becomes available for later allocation if no other reference uses
it. There is no implicit compaction, reindexing, duplicate merging or global
rename. Standalone shared-table editing/removal remains outside this workflow.

Complete native errors can trigger rollback of staged fields, followed by
verification of the original snapshot. If command synchronization is lost,
the helper performs no recovery I/O and reports the attempted parameters and
uncertain PP state. No plan or error claims that it saved a database or device.

## Toolkit configuration CRCs

The implementation was tested by executing the original, unchanged
`CBusLogicModel.dll` methods under Mono, not solely against a second Python
implementation. `research/NativeEdltProbe.cs` supplies a PP model scaffold and
calls the vendor property setters and private CRC calculation method.

The vendor CRC uses polynomial `0x1021`, initial value `0xFA50`, MSB-first
processing and no final XOR. Independent original-DLL vectors are:

| Bytes | CRC |
| --- | --- |
| Empty | `FA50` |
| `00 01 02 FF` | `E68A` |
| ASCII `123456789` | `0156` |

Toolkit constructs a temporary **9216-byte zero-initialized CRC buffer** from
the full PP snapshot. Logical addresses below 256 are excluded; higher
addresses map to buffer offset `logical_address - 256`. Zero bytes in this
temporary buffer do not represent inferred physical EEPROM contents.

| CRC parameter | Buffer start | Length | PP storage |
| --- | --- | --- | --- |
| GlobalParameterCRC | 16 | 239 | `0x104` |
| WidgetsCRC | 256 | 3839 | `0x106` |
| StaticTextCRC | 4096 | 4095 | `0x108` |
| ScenesCheckSum | 8192 | 1023 | `0x10A` |
| OverallCRC | 16 | 9199 | `0x102` |

The ranges use exact exclusive lengths from the original DLL. CRCs are stored
as high byte then low byte. These are Toolkit eDLT configuration CRCs; this
does not resolve the separate legacy KEY4 firmware EEPROM checksum algorithm.

## API and acceptance

```python
editor = EdltLighting(spec)  # KEYGL5.xml, 5055EDL, firmware 5.5.00
plan = editor.plan(session.values(), page=2, position=3, page_mode="multiple",
                   mode="dimmer", group=42, application="primary",
                   label_text="Lounge", status_text="Ceiling lights",
                   ramp_seconds=20, restore_level=0)
result = editor.apply(session, plan)
session.save_to_source()
```

`configure(session, **options)` combines plan and apply. Both methods require
a database source such as `/db//TEST/254/p/20`; physical sources are rejected.
`plan.as_dict()` includes all changed PP fields and the 32-byte widget record.

The native acceptance creates a unique marked project with an unopened CNI at
`127.0.0.1:1`, loads a database-backed 5055EDL PP session and resets defaults.
It configures an Off/On widget and a page-4 Dimmer, allocates the UTF-8 label
`Māori Lounge` and distinct status `Room state`, verifies shared-index reuse,
checks raw PP records and both complete static-table fields,
compares all five CRCs with the original DLL, saves the project, closes and
loads it, then checks every PP value through a fresh session. It deletes the
disposable project afterward. It avoids C-Gate's observed bare `PP NEW`
KEYGL5 allocation limitation by binding the existing database unit first.

From the `toolkit-cli` directory:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_REPORT=research/runtime/edlt-acceptance.json PYTHONPATH=src \
python3 -m unittest discover -s tests -p test_edlt.py -v
```

The original-DLL test also needs Docker and the pinned Mono image named in the
test. `NativeEdltStaticProbe.cs` separately exercises original allocation,
reuse, release and all widget classes' reference methods. Vendor files and
full runtime captures remain ignored. Compact independent
records, original assembly hashes and CRC results are retained in
[`edlt-acceptance.json`](../research/fixtures/edlt-acceptance.json).

Remaining work includes standalone shared-label table editing, other key presets,
custom macros, standby/navigation customization, other widget types, eDLT
scenes, additional catalogues/firmware and physical-device read/write/display
acceptance. These boundaries are enforced instead of being counted as parity.
