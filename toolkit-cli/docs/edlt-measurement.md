# eDLT Measurement widgets

`EdltMeasurementWidget` configures **5055EDL / KEYGL5 firmware 5.5.00** Measurement widgets in database PP sessions. It supports source device/channel, decimal places, explicit gain and offset mantissa/exponent pairs, shared prefix/suffix/label text, standby and functional placement, and built-in icons. It verifies the full staged PP snapshot and five Toolkit configuration CRCs. Incoming measurements, physical display behavior and custom image uploads are outside this workflow.

```python
from cbus_toolkit.edlt_measurement import EdltMeasurementWidget

editor = EdltMeasurementWidget(spec)
plan = editor.plan(
    session.values(), page=1, position=1, device_id=42, channel=3,
    decimal_places=1,
    gain_mantissa=125, gain_exponent=-2,       # 1.25
    offset_mantissa=-25, offset_exponent=-1,  # -2.5
    prefix_text="Temperature", suffix_text="C", label_text="Room", icon_index=38,
)
print(plan.as_dict())
result = editor.apply(session, plan)  # verified=True, saved=False
session.save_to_source()
```

The CLI provides `edlt measurement-plan SNAPSHOT ...` and `cgate ... unit ... edlt-measurement ...`. Native destinations must be database units. `--dry-run` verifies a preview without saving; normal native execution saves the verified result.

| Setting | Accepted values |
|---|---|
| `device_id`, `channel` | Required integers 0..254 |
| `decimal_places` | Integer 0..5; fresh default 2 |
| `gain_mantissa` | Signed integer -32768..32767, excluding zero; fresh default 1 |
| `gain_exponent` | Signed integer -128..127; fresh default 0 |
| `offset_mantissa` | Signed integer -32768..32767; fresh default 0 |
| `offset_exponent` | Signed integer -128..127; fresh default 0 |
| `page_mode` | `single` or `multiple`; omitted retains the current interpretation |
| `page`, `position` | Standby: page 0, positions 1..5 in either page mode. Functional single: page 1, positions 1..5. Functional multiple: pages 1..4, positions 1..4 |
| `prefix_index`, `suffix_index` | Exact static slot 0..63, or detached value 255 |
| `label_index` | Exact static slot 0..63, original default sentinel 64, or detached value 255 |
| `prefix_text`, `suffix_text`, `label_text` | Allocate/reuse static text; empty or whitespace-only text detaches to 255. Incompatible with the corresponding explicit index |
| `icon_index` | Optional built-in icon: 0..38, 128..141, 252..254; functional widgets with existing `UseBigIcon=1` only |

Omitted optional settings retain existing values. New widgets default to device/channel 0, precision 2, gain 1×10⁰, offset 0×10⁰, prefix/suffix 255, label 64 and icon 135. Defaulting a functional widget resets its restore level to zero and preserves bytes 14..31. Existing functional Measurement widgets retain their restore level and omitted icon byte. Standby widgets have no schema-backed RestoreLevel field; their plans report `restore_level=None` and never synthesize that parameter. Invalid existing precision requires an explicit valid replacement.

The optional `icon_index` maps directly to byte 12. The original selector offers 56 indices, including 0 for a blank icon. Explicit edits enforce the original panel visibility: selected widget number greater than 5 and the existing global `UseBigIcon` bit enabled. The helper validates that bit's layout at `0x118`, bit 4, and never changes it. Standby icon edits are rejected even when the global bit is enabled. Omitted raw icon bytes, including 39, 200 and 255 that cannot be selected through this UI, are preserved on existing Measurement widgets. Plans report `icon_index` and `icon_editable`. Both CLI paths accept `--icon-index`.

The model has no group/application selector, action macro, threshold, units enum or dynamic-label variant. Its `DeviceID` is the named measurement source field; this workflow does not equate it with a physical unit address or perform source discovery. Prefix and suffix are caller-chosen text. The global primary and secondary application choices remain unchanged; their ordinary save-time `Application` mirror is maintained.

## Explicit scaling and original UI conversion limits

The effective gain is `gain_mantissa × 10**gain_exponent`; offset uses the corresponding pair. The result reports exact decimal strings `gain_value` and `offset_value` without binary floating-point rounding or dependence on the caller's Decimal context.

This API implements the original public integer/exponent model properties. It **does not implement the UI's `GainComposite` and `OffsetComposite` conversion**. The unchanged DLL probe demonstrates that converter losing values: `0.29` becomes `0.28`, `1.15` becomes `1.14`, `32768` becomes `32760`, and `1.23456` becomes `1.2346`. The first two conversions even return the converter's “exact” result. These observations come from the pinned original-DLL Mono test environment; they do not establish every platform's floating-point formatting behavior.

Explicit pairs avoid claiming parity with that converter. For example, mantissa 29 and exponent -2 intentionally store exactly 0.29. Plans set `ui_composite_conversion=False`. Native tests confirm the actual signed bytes at both mantissa and exponent boundaries; physical display range or behavior at those extremes is unverified.

The original `Gain` setter replaces zero with one, and its getter also mutates an existing stored zero to one. Explicit zero gain is rejected because it would not be retained. A source zero normalizes to one when planning, with its exponent preserved and `gain_normalized=True` reported. This is a getter-side model behavior, distinct from `SetForcedValues`, which is a no-op for Measurement.

## The label value 64 and shared text capacity

The original default label is **64**, while prefix and suffix default to 255. Its label getter returns empty for 64, and explicitly assigning empty text writes 255. Both values survive native PP storage, but this workflow does not claim their physical display meanings are identical.

The shared-reference reader permits 64 only at Measurement type 12, byte 13. It keeps that value in the used-reference set; it never reads or writes a nonexistent `StaticTextString64`. Every other text reference still rejects 64.

This matters because Toolkit's allocator counts all distinct used references, including 64 and the existing 255 sentinel. Independent original-DLL tests show 61 real slots plus 64 and 255 permitting one allocation, while 62 real slots plus those sentinels reject allocation despite a free slot. Explicitly clearing the Measurement label from 64 to 255 removes one counted reference and can make an allocation possible.

Nonblank text reuses the first exact existing string, otherwise taking the highest unused slot after inspecting all known page, scene and widget references. Edits run in prefix → suffix → label order, so later allocations see earlier bindings. Equal strings deduplicate; explicit indexes retain exact duplicate slots. Nonblank strings must contain no NUL and occupy at most 63 UTF-8 bytes. Empty or whitespace-only text detaches without allocating. Results report each nonblank allocation under `allocations` and the final references under `text_indices`.

| Initial table | Prefix Temperature | Suffix C | Label Room |
|---|---|---|---|
| Isolated original probe without Temperature | Allocate 63 | Allocate 62 | Allocate 61 |
| Native KEYGL5 defaults with Temperature at 18 | Reuse 18 | Allocate 63 | Allocate 62 |

Both sequences have independent original-DLL vectors. The native sequence preserves the existing Temperature text.

## Validation and source preservation

Only blank, unused or existing Measurement slots can be configured, including on standby. A preceding two-slice Time/Date widget covers the next standby slot: shrink that widget first. The selected type conversion restriction also applies on standby, so changing an existing Time/Date or HVAC slot to Measurement is outside this workflow. Original UI placement guards reject unsupported stored standby types and a two-slice Time/Date at position 5. Existing other widget types, active records after a terminator, unsupported profiles and malformed references are rejected. Page placement reproduces the original blank/terminator normalization, including restore resets when those types change. Other widget data, scenes, static references and opaque bytes remain intact except for the documented allocation and normalization effects.

`configure` checks database identity before reading PP data. `apply` checks the complete source snapshot, native schema and a canonical plan before mutation, then reads back all staged values. Ordinary staging errors attempt verified rollback while the connection remains synchronized. After disconnection, no recovery I/O is sent. `EdltApplyError.details` preserves attempted fields, rollback errors and `saved=False`.

## Source mapping and acceptance

`research/NativeEdltMeasurementProbe.cs` calls unchanged Toolkit 1.18 `MeasurementData`, `PPHelper` and allocator methods. The original `CBusLogicModel.dll` SHA256 is `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`. Vendor files remain ignored.

| Original source | Verified mapping |
|---|---|
| `EDLTWidget.CreateData`, `MeasurementWidget` | Widget type 12; direct `WidgetBaseData` subclass |
| `MeasurementData.DeviceID`, `.Channel`, `.Precision` | Bytes 1/2/3; UI bounds 0..254, 0..254, 0..5 |
| `MeasurementData.Gain`, `.GainExponent`, `WidgetBaseData` | Signed little-endian word at bytes 4/5, signed byte 6 |
| `MeasurementData.Offset`, `.OffsetExponent` | Signed little-endian word at bytes 8/9, signed byte 7 |
| `MeasurementData` text properties | Prefix byte 10, suffix byte 11, label byte 13 |
| `MeasurementData.BigIconIndex`, `MeasurementWidget.SetUpDataSource` | Byte 12, default 135; explicit built-in edits require functional placement and existing large-icon mode |
| `MeasurementData.SetToDefault`, `.GetUsedStaticText` | Label sentinel 64 remains a counted reference |
| `EDLTUnit.GetStaticTextIndex` | Empty text →255, exact-string reuse, counted-reference capacity and highest unused allocation |
| `PPHelper.BreakNumberIntoIntegerAndExponent` | UI composite conversion is separate from the implemented integer/exponent properties |

Literal records:

```text
default:          0C000002010000000000FFFF8740000000000000000000000000000000000000
device254/ch254:  0CFEFE05010000000000FFFF8740000000000000000000000000000000000000
gain1.25/off-2.5: 0C2A03017D00FEFFE7FFFFFF8740000000000000000000000000000000000000
isolated text:    0C2A03017D00FEFFE7FF3F3E873D000000000000000000000000000000000000
native text:      0C2A03017D00FEFFE7FF123F873E000000000000000000000000000000000000
all text cleared:0C2A03017D00FEFFE7FFFFFF87FF000000000000000000000000000000000000
```

`tests/test_edlt_measurement.py` covers original literals, signed bounds, exact reporting, zero normalization, sentinel scope/capacity, text allocation and clearing, defaults/opaque values, page placement, identity/schema/stale/forged plans and rollback. Its native test uses an owned unopened C-Gate 3.4.0.2001 project, confirms literal raw widget/restore/text bytes, checks all five CRCs against the original DLL, and verifies complete PP equality after save/close/load with label 64 retained. It also checks that an existing Room Courtesy allocator safely handles a Measurement neighbor containing 64.

`tests/test_cli_edlt_measurement.py` covers offline planning, native preview and save/reload, original native text reuse, scaling options, bounds and database destination guards. Run both suites from `toolkit-cli`:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_MEASUREMENT_REPORT=research/runtime/edlt-measurement-report.json \
PYTHONPATH=src:tests python3 -m unittest test_edlt_measurement test_cli_edlt_measurement -v
```

The original DLL probes require the pinned Mono Docker image used by other eDLT tests. The initial functional-placement evidence is saved in `research/fixtures/edlt-measurement-acceptance.json`.

The standby extension has a separate original-model probe, `research/NativeEdltMeasurementStandbyProbe.cs`, and `tests/test_edlt_measurement_standby.py`. The original UI offers type12 at all five standby positions. Its unchanged constructors, setters and save hook confirm the same default/scaled bytes and no RestoreLevel field at those positions. Native tests cover positions1/3/5, signed mantissa/exponent boundaries, label64, raw text bytes, all five original CRCs, full save/close/load equality, and an unchanged functional widget21 on a multiple-page unit. CLI coverage includes standby offline/preview/save/reload and rejects covered slots without mutation. The compact standby report is `research/fixtures/edlt-measurement-standby-acceptance.json`; set `CBUS_EDLT_MEASUREMENT_STANDBY_REPORT` for optional detailed native output.

Run `python3 -m unittest tests.test_edlt_measurement tests.test_edlt_measurement_standby tests.test_cli_edlt_measurement` with the same native environment to include all Measurement coverage. The source/device identifiers retain their existing numeric semantics; this extension adds placement without claiming new physical behavior.

Before built-in icon authoring was added, the Measurement suite including standby and CLI coverage passed **16 tests with zero skips** on Python 3.13.14 (34.749s) and Python 3.10.20 (40.761s). Those earlier fixtures retain their historical scope and hashes; they do not establish icon authoring acceptance.

The icon extension has separate evidence in `research/fixtures/edlt-measurement-icons-acceptance.json`. `research/NativeEdltMeasurementIconProbe.cs` executes the unchanged original icon getter/setter and no-op forced-values method for every raw byte at five standby/functional locations. It checks that same-type save preserves hidden raw 200. `research/NativeEdltGraphicsProbe.py` executes the original graphics DLL exports for all 255 candidate slots; the only imported function used is an exact `memset` shim. The selector set matches the original wrapper's content test plus its explicit blank option. Vendor images are not packaged.

`tests/test_edlt_measurement_icons.py` checks all accepted and rejected icon bytes, hidden-edit and layout guards, stale visibility and forged plans. Seven native cases compare all 874 PP parameters and all five CRCs with the original DLL, including a blank icon, icon 38 with scaling and text, upper-range icons, and omitted hidden 39/255. Every case checks raw widget bytes and save/close/load equality. CLI acceptance independently verifies offline planning, preview preservation, explicit icons, hidden rejection without mutation, and retained raw values. The test networks remain closed with `state=new`.

Run all four modules to include the extension:

```sh
python3 -m unittest tests.test_edlt_measurement tests.test_edlt_measurement_standby \
  tests.test_edlt_measurement_icons tests.test_cli_edlt_measurement
```

Use the same native environment above, plus `pefile` and `unicorn` for the graphics probe. Set `CBUS_EDLT_MEASUREMENT_ICONS_REPORT` to record detailed native icon results.

The complete suite with icon authoring passed **23 tests with zero skips** on Python 3.13.14 (67.366s) and Python 3.10.20 (82.151s). The seven native icon reports were identical across interpreters.
