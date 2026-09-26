# eDLT multiroom audio widgets and shared zone settings

`EdltMRAWidget` implements Toolkit's Zone Control (type7), Source Select (type8), and Source Control (type9) editors for **KEYGL5 / 5055EDL / firmware5.5.00**. It edits a database programming session, verifies every parameter after applying a plan, and calculates the five original configuration CRCs. It does not send Audio Control messages, configure amplifiers or matrix switchers, or verify physical audio behavior.

The [ordered parent transaction](edlt-parent-transaction.md) also exposes these
as `zone-control`, `source-select` and `source-control` operations, plus an
ordered `mra-globals` operation. That composition validates every selected
record first, then enters the final multiplexer/zone pair through its single
retained terminal save and five-CRC pass. It preserves stored standby MRA
placements, raw multiplexer 3, each record's low three status bits and all
unrelated bytes. See the parent contract for shared-bit ownership and ordering.

The original model, UI option lists, icon chooser and native PP state are the evidence. This is a bounded device-editor implementation, not a claim of complete Toolkit or audio-system parity. The compact acceptance record is [edlt-mra-acceptance.json](../research/fixtures/edlt-mra-acceptance.json).

## Public API

```python
editor = EdltMRAWidget(spec)  # exact KEYGL5.xml layout and supported identity
plan = editor.plan(current, page=1, position=1, kind="zone-control",
                   variant="volume", key_mode="decrease-increase",
                   ramp_seconds=12, multiplexer=1, zone=1,
                   label_text="Living", status_type="percent")
result = editor.apply(session, plan)
# Explicit persistence is a separate database PP save operation.

shared = editor.plan_globals(current, multiplexer=2, zone=4)
```

`configure(session, **options)` and `configure_globals(session, **options)` include planning and application. `snapshot`, `crcs`, immutable plans and `as_dict()` follow the other eDLT editors. Result metadata reports `saved=false`, `physical_device_verified=false` and `audio_control_sent=false`; `verified=true` means the database PP readback matched the plan. CLI commands are `edlt mra-plan`, `edlt mra-globals-plan`, `cgate unit edlt-mra` and `cgate unit edlt-mra-globals`.

All three types use functional slots6..21: single-page positions1..5, or four pages with positions1..4. The UI does not offer them in standby slots. Public multiplexer numbers1..3 and zone numbers1..8 map to stored zero-based values. There is no standalone PP multiplexer or zone field: each MRA record stores them in byte1 alongside its status bits. Global-only plans therefore require an existing MRA widget.

| Kind | Variants | Additional settings |
| --- | --- | --- |
| `zone-control` | `volume`, `treble`, `bass`, `balance` | `key_mode`, `ramp_seconds`, static label, `status_type`, static status text, separate on/off icons |
| `source-select` | `next-previous`, `one-absolute`, `two-absolute` | Sources1..7 when visible, static label/status text, one icon setter updates both stored icons |
| `source-control` | `dynamic-1`, `dynamic-2`, `dynamic-1-and-2` | Static label, one icon setter updates both stored icons |

Zone key modes are `decrease-increase` (macros15/16) and `nudge` (21/22). The former exposes ramp durations0,4,8,12,20,30,40,60,90,120,180,300,420,600,900,1020 seconds. Nudge hides the ramp; the existing ramp byte remains intact. The model has a raw offset property, but no corresponding bound control was found in the original Zone widget panel; the API preserves and reports it instead of inventing an editor option. Status choices are `blank`, `bar`, `level`, `percent` and `static`. Static status text is editable only for `static`.

Source Select's next/previous variant hides both absolute sources and status text. One-absolute exposes source1 and status text; two-absolute exposes both sources and status text. Hidden source bytes are preserved, including out-of-range legacy values; activating them requires valid values or explicit replacements. Its hidden status index still participates in static-text reference accounting.

`label_text`/`label_index` and `status_text`/`status_index` are mutually exclusive. Indexes0..63 and the unused sentinel255 are supported. Blank or whitespace text selects255. Nonblank text reuses the first exact existing match or allocates the highest unreferenced slot. Full-table behavior includes all original static-reference sentinels. Source Select first assigns the default status text `Source`, before requested label/status edits; that intermediate allocation affects capacity and allocation order. The native catalog defaults already contain `Source` at11 and `Kitchen` at26; empty fixtures allocate different indexes.

Explicit icon edits require `UseBigIcon=1`, as in the original UI. The unchanged graphics DLL offers0..38,128..141,252..254. Default record icons remain assigned even when icon display is disabled. No custom image import is implemented here.

## Original save behavior and preservation

`InitializeMRAGlobalValues` reads the first existing MRA widget before a selected type conversion. `BeforeSavePPData` propagates those globals to every MRA widget, preserving each record's low three status bits. Adding an earlier MRA or removing the first one still uses the originally loaded globals. Explicit requested settings replace those loaded values.

The pure `normalize_mra_globals` helper provides byte1-only changes and metadata for this behavior. The shared `_place_record` save normalization now calls it for the existing eDLT editors. Two internal preservation flags retain stored raw multiplexer3 and stored standby MRA placements on unrelated edits: the original save hook handles both although the UI would not offer them. Metadata marks raw3's human value4 as `multiplexer_ui_canonical=false`. Typed MRA editing continues to validate offered settings and placements.

MRA types7/8/9 have no additional `SetForcedValues` override. Changing type applies the original defaults and resets the functional restore level. Reassigning the same type preserves the restore value and opaque record bytes. Zone's key-mode getter normalizes an invalid existing macro pair to15/16; the plan exposes that normalization. Source Select and Source Control preserve hidden source/opaque fields that their original defaults leave untouched.

Unrelated static strings, scene data, widget bytes and parameters remain intact except for documented shared MRA propagation, functional terminator/restore normalization, application synchronization, initial configuration-version handling and CRCs. Existing widgets' unrelated forced-value behaviors are not expanded by this module.

Plans are canonical and bound to a complete current snapshot. Invalid identity/schema, stale state and forged plans fail before changes. Ordinary failures attempt rollback only on the existing live connection and verify it. Connection loss stops recovery I/O. `KeyboardInterrupt` and `SystemExit` propagate unchanged with `edlt_mra_evidence`, attempted parameters and uncertainty; interruption during rollback also records the original error. No reconnect, retry or automatic persistence occurs.

## Reproducing evidence

The executable research harness is [NativeEdltMRAProbe.cs](../research/NativeEdltMRAProbe.cs). It invokes unchanged original `CBusLogicModel.dll` and `eDLT.dll` code. Full native comparisons use original `PPHelper.SetMemoryFromParamStringValue` for fixed-width text memory and original CRC calculation. Original source text setters return partial arrays, which are not mistaken for full PP memory.

[Test vectors and native acceptance](../tests/test_edlt_mra.py) cover original defaults, all49 source pairs, all24 global combinations, original UI placements, shared text allocation/capacity, icon choices, hidden settings, typed guards, rollback and interruption evidence. Native tests use a uniquely named disposable closed database network and compare full parameters after save/close/load. [Shared normalization tests](../tests/test_edlt_mra_normalization.py) independently execute five original save cases, including noncanonical stored values and first-widget conversion.

Set `CBUS_CGATE_TEST_HOST`, `CBUS_CGATE_TEST_PORT`, `CBUS_UNITSPEC_DIR`, and `CBUS_TOOLKIT_EXE` to owned fixtures. `CBUS_EDLT_MRA_REPORT` optionally retains the machine-readable detailed report. The original model runs in the pinned Mono image already used by the project; no vendor DLL or catalog is bundled in the package. Optional fixture gates must actually run for native acceptance and are never counted as passes when skipped.
