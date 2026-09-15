# eDLT HVAC Temperature Display

`cbus_toolkit.edlt_hvac.EdltHVACTemperatureWidget` configures original widget type 13 for **KEYGL5 / 5055EDL / firmware 5.5.00** in a database PP session. It covers the original HVAC panel's communication group, zone, decimal places, temperature units, static display text and built-in icon selection. It does not send HVAC commands or verify a physical display.

```python
editor = EdltHVACTemperatureWidget(spec)
plan = editor.plan(
    session.values(), page=1, position=1, group=42,
    zone=4, decimal_places=2, units='fahrenheit',
    icon_index=38, label_text='Room',
)
result = editor.apply(session, plan)  # validates and reads back PP; does not save
session.save_to_source()             # explicit database persistence
```

The API is `plan(current, *, page, position, group, zone=None, decimal_places=None, units=None, icon_index=None, page_mode=None, label_text=None, label_index=None)`. `snapshot`, `crcs`, `apply` and `configure` follow the existing eDLT interfaces. Every optional setting preserves the current value for an existing HVAC widget. Changing the widget type first applies original defaults, including allocating or reusing the text `Temperature`; that allocation remains a reported side effect even when the requested label subsequently changes or clears.

| Setting | Accepted values |
| --- | --- |
| `group` | Integer 0..255;255 is unused. Application is fixed172. |
| `zone` | Integer 0..4;0 is Unswitched and 1..4 select zones. |
| `decimal_places` | Integer 0..2. |
| `units` | `celsius` or `fahrenheit`. |
| `icon_index` | 0(blank),1..38,128..141,252..254. |
| `label_text` | Unicode, at most63 UTF-8 bytes, no NUL; blank/whitespace detaches. |
| `label_index` | An exact existing reference 0..63, or255 to detach; mutually exclusive with text. |

Page 0 selects standby positions 1..5. A single functional page allows positions 1..5; multiple pages 1..4 each allow positions 1..4. An existing preceding two-slice Time/Date widget covers its next standby slot: shrink that widget before configuring the covered slot. Replacing two-slice Time/Date itself with HVAC makes it one slice and preserves the neighbor's current bytes.

The original icon editor is visible only on functional widgets when the existing global `UseBigIcon` is 1. Explicit icon edits enforce both conditions. Omitting the option preserves its byte even when hidden. The helper does not change `UseBigIcon`, and the selector exposes built-in images rather than custom image uploads.

The communication group is a numeric reference in application 172, independent of the unit's primary and secondary applications. Create or edit database group tags through the separate database API. The original `ZoneGroup` getter can trigger automatic creation of a missing database group; with auto-add disabled it instead changes the reference to255. This helper does not invoke that getter side effect and reports `group_metadata_verified=false` and `database_group_created=false`.

## Byte and preservation contract

| Offset | Meaning | Original default |
| --- | --- | --- |
| 0 | Type |13 |
| 1 | Application 172 communication group |255 |
| 2 | Zone |0 |
| 3 | Decimal places |0 |
| 4 | Units |0 Celsius |
| 5 | Built-in icon |135 |
| 6 | Shared static text reference |Allocated/reused `Temperature` |
| 7..31 | Opaque bytes |Preserved |

Standby widgets have no schema-backed RestoreLevel field. A new functional HVAC widget resets its RestoreLevel to 0; same-type edits, including group changes, retain it. The original model has no HVAC forced-value override or AppGroup restore lookup. Existing valid widget types can be replaced subject to the original placement and shared-reference guards. Malformed source references and layouts fail before mutation, including unselectable type 13 label 64; the narrow existing type 12 Measurement label 64 allowance is unchanged.

Allocation uses the shared whole-unit reference enumeration, including scenes, page names, hidden widgets and sentinels. Exact text reuses the first matching slot; an explicit index retains duplicate-text slot identity. New text uses the highest unreferenced slot and the original used-set capacity check. The temporary pre-default byte 6 reference participates in the default allocation as in the original model. Unrepresentable transitional references are rejected rather than discarded.

The shared original save hook also normalizes existing MRA siblings' multiplexer/zone bits from the original first MRA widget, before CRC calculation; these changes appear explicitly in the plan.

Plans report both `allocations.default_label` and `allocations.label`, exact bytes and changes. Applying a plan verifies profile/schema, reconstructs its canonical contents, rejects stale full PP snapshots, reads back every resulting PP value and verifies five CRCs. Ordinary failures attempt to restore only attempted parameters while the session remains synchronized. Disconnection stops recovery I/O and reports the unsaved partial outcome. Persistence is a separate explicit action.

## Evidence and limits

[NativeEdltHVACProbe.cs](../research/NativeEdltHVACProbe.cs) executes the unchanged original `HVACTempDisplayData`, widget type setter, UI availability method, `BeforeSavePPData`, memory encoder and CRC calculation. [NativeEdltGraphicsProbe.py](../research/NativeEdltGraphicsProbe.py) independently executes original graphics exports for all 255 indexes in bounded x86 emulation; the only used imported-function shim is exact `memset`. The original graphics DLL SHA256 is `e319379709c47f97dca477c4f631880f231c060530cb2ec45a3f731b1a5d1991`.

Native defaults reuse `Temperature` at static slot 18:

```text
0DFF000000871200000000000000000000000000000000000000000000000000
```

Group 42, zone 4, two decimal places, Fahrenheit, icon 38 and new `Room` at 63:

```text
0D2A040201263F00000000000000000000000000000000000000000000000000
```

The tests use literal vectors independent of the helper, shared-reference and rollback cases, all icon choices, all original placement boundaries, original DLL comparisons, native raw widget/static bytes, all five CRCs, and save/close/load PP equality. Projects are disposable and remain `state=new`; no network is opened. The model scaffold uses explicit canonical empty scene pointers 255 to isolate widget edits from original whole-unit SaveScenes normalization of native defaults 65535. Configuration version starts in the original AfterLoad state 1.0; the probe reads original MultiPage to exercise its255→0 getter normalization. Short original UTF-8 PP lists are expanded through the original memory encoder for the 64-byte comparison.

Run the native tests with `CBUS_CGATE_TEST_HOST`, `CBUS_CGATE_TEST_PORT`, `CBUS_UNITSPEC_DIR` and `CBUS_TOOLKIT_EXE` pointing at the isolated oracle and local vendor installation. `CBUS_EDLT_HVAC_REPORT` optionally records the detailed report. Native model probes require the pinned Mono container; graphics checks require `pefile` and `unicorn`. Vendor assemblies and artwork are not packaged with the CLI.

The final combined helper and CLI acceptance passed **12 tests with zero skips** on Python3.10.20 (49.006s) and Python3.13.14 (42.035s). The compact [acceptance fixture](../research/fixtures/edlt-hvac-acceptance.json) records literal outputs, CRC cases, source hashes and scope.
