# eDLT global display settings

`EdltDisplaySettings` edits four unit-wide settings for KEYGL5.xml, catalog
5055EDL, firmware 5.5.00. It plans against a complete database PP snapshot,
checks exact native identity/schema and unchanged values, applies the changes,
and verifies the full resulting PP state. The Python helper leaves saving
explicit; the CLI saves to the database source unless `--dry-run` is supplied.
No physical device display or programming transfer is claimed as verified.

```sh
cbus-toolkit edlt --spec-dir SPECS display-plan exported-parameters.json \
  --large-text status --no-timer-flash

cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run edlt-display \
  --spec-dir SPECS --large-text status --no-timer-flash
```

`CBUS_UNITSPEC_DIR` can supply the specification directory. The offline command
accepts a complete parameter mapping or an export whose profile matches exactly.
For a native edit, `--source` and any explicit `--destination` must be database
addresses. Physical destinations are rejected before loading/editing the PP
session. A preview uses an isolated PP session and verifies its planned result
without saving the source database.

The Python API is:

```python
editor = EdltDisplaySettings(spec)
plan = editor.plan(values, large_text="status", big_icons=True,
                   timer_flash=False, fan_level_wrap=True)
result = editor.apply(database_session, plan)
# result["verified"] describes staged PP readback; result["saved"] is False.
# The caller can then explicitly save the database programming session.
```

`configure(session, **options)` creates and applies the same plan. Every option
is optional. Boolean arguments must be actual Booleans; CLI flags use both
positive and negative forms, such as `--big-icons` and `--no-big-icons`.

| Option | PP field | Logical memory | Explicit setting |
|---|---|---|---|
| `large_text` | `FontStyle` | 0x118 bits 0..2 | `label` → 1; `status` → 2 |
| `big_icons` | `UseBigIcon` | 0x118 bit 4 | true → 1; false → 0 |
| `timer_flash` | `EnableTimerFlash` | 0x116 bit 2 | true → 1; false → 0 |
| `fan_level_wrap` | `EnableFanControlLevelWrap` | 0x117 bit 5 | true → 1; false → 0 |

The original model spells its timer property `EnableTimeFlash`, while the PP
field includes `Timer`. Fan/Multi Level wrapping, Timer flashing and icon/text
choices apply across the unit; this helper does not author those widgets.
The vendor defaults for these four fields are 1.
The original checkbox bound to `UseBigIcon` is labelled “Display Icons”, and
widget icon-panel visibility is bound to it. The API retains the field-derived
`big_icons` name; changing icon size is not independently established here.

## Omitted values and preservation

An omitted font option preserves all valid raw FontStyle values 0..7. Original
`LargeStatusText` is true only for raw value 2; `LargeLabeltext` is true for every
other raw value. An explicit selection writes canonical 1 or 2. Plans report
both `font_style` and `font_style_ui_canonical`, so preserved values outside 1/2
are visible. This follows original model getters/setters and does not assume
how a rendered WinForms binding would coerce a noncanonical stored value.

Omitted Boolean options preserve their stored bits. Native raw-byte tests verify
that the masks are 0x04 at 0x116, 0x20 at 0x117 and 0x17 at 0x118; other bits are
retained. The synthetic schema separately supplies nonzero adjacent opaque bits
to check preservation. Static text and scene payloads are not rewritten by a
display-option selection.

Plans also apply the verified save-hook effects, even when no display option is
changed:

* Copy the first existing MRA widget's multiplexer/zone into the upper bits of
  every MRA control byte, retaining each widget's low three status bits.
* Normalize functional widget terminators. Only an actual blank/terminator type
  transition resets its restore value. With no active functional widget, the
  terminator is widget 6; unrelated restore values remain intact.
* Synchronize the legacy `Application` pair with PrimaryApplication and
  SecondaryApplication, then recalculate all five configuration CRCs.

The result exposes `mra_propagation`, `normalization_changes` and all parameter
`changes`. For example, source widget 6 control 0x6D causes widgets 7/8 controls
0xB2/0x03 to become 0x6A/0x6B. The first widget supplies multiplexer 2 and zone 6;
the three low status bits remain 5, 2 and 3 respectively.

Stored MRA multiplexer raw value 3 is preserved and propagated during this
unrelated display edit, matching original model save behavior. It is reported
as multiplexer 4 with `multiplexer_ui_canonical: false`; it is not offered as a
new user-selectable MRA setting. With no MRA widget, there is no distributed
MRA parameter to change. MRA authoring and its supported UI choices are separate.
An existing MRA record in a standby position is also preserved and included in
the original first-widget propagation order. This does not enable creating MRA
widgets at standby positions that the original UI does not offer.

## Save and failure boundaries

Plans are immutable snapshots of expected values, options and calculated
changes. `apply` reconstructs the plan, rejects forged or stale data, checks the
exact database profile and full native parameter layout, writes only changed
parameters, and verifies the entire resulting PP mapping.

An ordinary error rolls back attempted parameters in reverse order while the
connection remains usable, then verifies the original PP snapshot. A lost or
unsynchronized connection stops recovery I/O; rollback success is not claimed.
KeyboardInterrupt/SystemExit preserve the original exception with
`edlt_display_evidence`, attempted parameters and uncertainty metadata. The CLI
emits nested evidence and exits 130 for KeyboardInterrupt. There is no automatic
session reopen, parameter replay after disconnect, or physical recovery write.

`verified: true` means native staged PP readback matched the plan.
`saved: true` is a separate CLI result after database save completes. Native
acceptance saves/closes/reloads the project and compares all parameters; the
network remains unopened. `physical_device_verified` remains false.

## Original implementation and acceptance

`research/NativeEdltDisplayProbe.cs` executes the unchanged CBusLogicModel.dll
without rendering the UI. Its 56 model vectors comprise eight raw font getter
states, 32 Boolean font-setter transitions, and all 16 canonical combinations of
the four settings. An unrelated synthetic attribute remains 173 throughout.

The full native fixtures invoke original `InitializeMRAGlobalValues`, the four
display properties, `BeforeSavePPData(true, false)` and original CRC calculation.
Python output is compared against all 874 PP parameters in 27 cases: 16 canonical
combinations, eight omitted raw font styles, normal MRA propagation and stored
raw-3/standby MRA propagation. Tests independently inspect the three relevant native
memory bytes, verify shared data preservation, and save/reload the database.
The scenes in those fixtures use an explicit staged empty-scene representation;
this does not claim to emulate every unrelated GUI load/scene/text transformation.

`tests/test_cli_edlt_display.py` additionally covers offline planning, real parser
Boolean options, raw font preservation, explicit font normalization, MRA/whole-unit
metadata, preview source preservation, database save/reload, physical-destination
rejection and interruption evidence through the actual CLI entry point.

The acceptance ledger, exact source/probe/specification hashes and execution
counts are in
[edlt-display-acceptance.json](../research/fixtures/edlt-display-acceptance.json).
Vendor assemblies/specifications remain user-supplied research inputs rather
than package contents. LCD/indicator colours, brightness, standby/proximity,
quick status, navigation authoring, physical rendering and other firmware/device
profiles are separate capabilities.
