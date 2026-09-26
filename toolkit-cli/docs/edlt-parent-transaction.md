# eDLT ordered parent transaction

`EdltParentTransaction` applies two through 22 ordered control operations to
one **KEYGL5 / 5055EDL firmware 5.5.00** database snapshot. It composes
14 configurable widget panels, including all three MRA models, plus nine
direct parent/settings operations. Every operation is validated by its accepted standalone
editor. The owned fields then enter one retained lifecycle state, one terminal
`BeforeSavePPData` projection and one five-CRC projection.

Create an operation file such as `operations.json`:

```json
[
  {
    "op": "measurement",
    "page": 1,
    "position": 1,
    "device_id": 42,
    "channel": 3,
    "decimal_places": 1,
    "gain_value": "1.5",
    "offset_value": "-2.5",
    "measurement_culture": "en-NZ",
    "prefix_text": "Temperature"
  },
  {
    "op": "lighting",
    "page": 1,
    "position": 2,
    "group": 12,
    "mode": "dimmer",
    "ramp_seconds": 20,
    "label_text": "Bedroom light",
    "restore_level": 99
  },
  {
    "op": "activation",
    "wake_mode": "primary-event",
    "group": 42,
    "level_percent": "50"
  }
]
```

Preview it without connecting:

```sh
cbus-toolkit edlt parent-transaction-plan snapshot.json \
  --metadata lifecycle-cache.json \
  --operations operations.json
```

Apply it to a database unit:

```sh
cbus-toolkit cgate unit \
  --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 \
  --dry-run edlt-parent-transaction \
  --metadata lifecycle-cache.json \
  --operations operations.json
```

Remove `--dry-run` only when the returned plan is correct. A successful
non-dry-run command writes each changed PP parameter once, reads the complete
PP state back once and issues one database `SAVE`. A failed write attempts one
reverse-order rollback while the connection remains usable. An interrupt
returns `edlt_parent_transaction_evidence`, including attempted parameters and
whether PP state is uncertain; it never issues the database save.

The caller-cache form above remains useful when dynamic image facts came from
a separately controlled observation. For one exact native project snapshot,
the [automatic parent metadata workflow](edlt-parent-metadata.md) can derive
the required application/group/level/static-label facts and deterministically
plan missing applications or groups:

```sh
cbus-toolkit edlt parent-transaction-plan snapshot.json \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --operations operations.json
cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run edlt-parent-transaction \
  --auto-metadata --exclusive-project --operations operations.json
```

That native path creates a backup before mutation. It composes metadata and PP
staging before one PP SAVE and one target PROJECT SAVE, but C-Gate provides no
atomic commit across those operations. It rolls back only before PP SAVE is
attempted and reports later failures as potentially partial without retry.

## Operation contract

The JSON document must be an array with two through 22 entries, contain no
duplicate object keys or non-finite JSON constants, and include at least one
widget operation. Unknown operation types and fields fail closed. The accepted
fields are the public arguments of these existing editors:

| `op` | Required fields | Optional fields |
| --- | --- | --- |
| `measurement` | `page`, `position`, `device_id`, `channel` | Decimal places; exact Gain/Offset pairs or culture-aware decimal text; page mode; prefix, suffix and label text/indexes; icon index |
| `lighting` | `page`, `position`, `group`, `mode` | Application, page mode, label/status type/index/text, ramp and restore level |
| `enable` | `page`, `position`, `variable`, `level` | Page mode and label/status type/index/text |
| `fan` | `page`, `position`, `group` | Application, speed count and thresholds, page mode, widget label and four state texts/indexes |
| `hvac` | `page`, `position`, `group` | Zone, precision, units, built-in icon, page mode and label |
| `multilevel` | `page`, `position`, `group` | Application, level count and thresholds, page mode, widget label and four state texts/indexes |
| `room-courtesy` | `page`, `position`, `group` | Application, mode, colours, page mode and label/status type/index/text |
| `scene` | `page`, `position` | Scene/cycle selection, mode, ramp/offset, page mode and label/status type/index/text |
| `shutter` | `page`, `position`, `group` | Application, mode, presets, page mode and label/status type/index/text |
| `time-date` | `page`, `position` | One/two slices, display, page mode and unit-wide date/time/leading-zero settings |
| `timer` | `page`, `position`, `group` | Application, duration/levels/ramp, page mode and label/status type/index/text |
| `zone-control` | `page`, `position` | MRA variant, multiplexer, zone, page mode, key mode, ramp, static label/status text or index and built-in on/off icons |
| `source-select` | `page`, `position` | MRA variant, multiplexer, zone, page mode, absolute sources, static label/status text or index and built-in icon |
| `source-control` | `page`, `position` | MRA variant, multiplexer, zone, page mode, static label text/index and built-in icon |
| `activation` | None | Wake mode, group, `level_percent` or `action`, activation page and first-key behavior |
| `general` | None | Key timings, status interval, Tools lock and power restore mode |
| `display` | None | Large-text owner, big icons, Timer flash and Fan wrap |
| `standby` | None | Enabled/duration, destination and nightlight settings |
| `colours` | None | All fixed colours/brightness values and six control groups |
| `navigation` | None | Page mode/variant, temperature source, dynamic group and page names/indexes |
| `quick-status` | None | Mode, group, thresholds and three colours |
| `page-control` | None | Enable-application group or disabled value 255 |
| `mra-globals` | At least one of `multiplexer` 1..3 or `zone` 1..8 | None |

`level_percent` remains canonical fixed-point JSON text, not a JSON number. It
uses the original `NumUpDownPercentage` arithmetic. The percentage is valid
only for the resulting `primary-event` mode; `action` uses the same raw byte in
`trigger-event` mode. The operation result reports the raw value, exact rebound
percentage, visibility and meaning before and after the edit.

Operations are applied in array order. That matters for shared static text:
the second widget sees text allocated and referenced by the first, so equal
text reuses the same index and different text receives a distinct safe slot.
The order is an explicit CLI transaction contract. It is not evidence that an
operator performed the same selection order in the original form.

Order also controls dependencies between panels. A `display` operation can
enable big icons before a later HVAC icon edit. A `standby` operation can
enable idle brightness/group controls before a later `colours` edit. A
`navigation` operation establishes the page mode that later widgets must use.
An MRA widget must exist before `mra-globals`; it may come from the retained
snapshot or an earlier operation. Display must enable big icons before an MRA
operation can set an explicit icon. Multiplexer and zone are independently
owned shared components, so a second operation cannot explicitly own the same
component. An operation that omits them consumes the effective retained values.
Reversing these sequences fails when the earlier retained state does not make
the dependent control editable. A two-slice Time/Date operation owns both
adjacent 32-byte records, so another operation cannot target its second slot.

The source-pinned Lighting selection branch is `ShowWidget` →
`BaseWidget.SetWidgetData` → base data-source setup → assign the selected
`LightingData` source → `ResetBindings(false)`. Ramp rate, Offset and Target
Level 1 use default `OnValidation` bindings. Their three editability/visibility
bindings use `Never`. These are per-selection component facts; source does not
prove a particular operator's multi-selection order or pending-focus state.

## Ownership and preservation

Each widget operation owns its selected 32-byte record and, for functional
widgets, its restore byte. Time/Date owns a second complete record when two
slices are selected. The transaction rejects overlapping slots. Each direct
settings panel and activation may appear once because a second instance would
own the same fields. All widget/navigation operations must resolve to one page
mode; an explicit conflict is rejected. `NavWidgetType` is written once as
that reconciled parent constraint.

MRA widget operations own the same complete selected record and restore byte.
Their shared multiplexer bits (`0xc0`) and zone bits (`0x38`) are separate
transaction constraints distributed by the terminal serializer to every
stored type 7/8/9 record. The per-record status bits (`0x07`) remain intact.
The first existing MRA record is read before converting a newly selected
earlier widget, matching the retained original behavior. Stored standby MRA
placements and the noncanonical stored raw multiplexer value 3 are accepted
only inside this retained parent path and remain preserved when omitted.

Every operation-introduced application/group reference must have explicit
positive evidence in the caller cache before any write. This includes Enable
application 203, HVAC application 172, selected primary/secondary widget
groups, activation, colour groups, navigation, Quick Status and Page Control.
Every effective dynamic text/icon binding, including a retained type omitted
from a later edit, additionally requires known image facts and must match the
selected variant's text/icon state. Navigation Logo consumes variant 0;
Dynamic Labels consumes the unique effective page indexes. The automatic
metadata workflow derives safe empty/TEXT facts, rejects DYNAMIC/FONT/ICON dependencies
that require project or DLTP files, and adds missing application/group objects
in deterministic order.
MRA record fields and its static text indexes consume no application/group or
dynamic-label records. Automatic metadata still resolves every dependency
required by the retained lifecycle; it does not invent Audio Control groups.

New static text fields are claimed by the operation that allocated them.
Duplicate or conflicting ownership of any claimed PP parameter is rejected
before a programming write. CRC fields, scene serialization, MRA propagation,
forced widget values and the functional terminator belong to the terminal
lifecycle serializer rather than an individual operation.

The plan reports each operation's `owned_parameters`, the transaction-wide
ownership table, selected slots and the exact deltas for:

1. retained load normalization;
2. bound controls;
3. terminal save normalization; and
4. the five CRC fields.

During the control phase every unowned parameter remains byte-for-byte equal
to the retained after-load model. The terminal phase may change only the
documented lifecycle-owned fields. Retained scene objects and the original MRA
source remain attached. Selected-record bytes not set by their standalone
editor are preserved, as are nonselected records and unrelated parent fields
outside independently documented lifecycle normalization.

## One terminal sequence

Standalone widget and activation planners calculate self-contained plans so
their record bytes can be compared with their existing accepted behavior.
Those standalone `changes` dictionaries are never applied directly. A
temporary validation view places each earlier widget so the next distinct
editor can inspect a valid functional layout and shared text references.

After every operation succeeds, the complete bound-control state enters the
same retained model produced by one lifecycle load. The transaction then runs
one terminal save projection. That projection serializes retained scenes,
propagates retained MRA globals, places one functional terminator, applies the
original forced values and calculates all five CRCs once. Canonical plan
verification is repeated immediately before mutation; the accepted terminal
projection is written in one parameter pass and verified by one full readback.
The plan lists all five fields in `lifecycle.crc_fields_calculated`; a CRC whose
stored value was already correct need not appear in the `phases.crc` delta.
The native CLI then makes one database `SAVE` call. If that call raises or is
interrupted, the CLI does not retry or roll back because the save may already
have taken effect. Its error contains `edlt_parent_transaction_evidence` with
the prior PP readback confirmation, `saved=false`, `save_attempted=true`,
`save_outcome_uncertain=true`, and explicit PP/database state uncertainty.
Here `saved=false` means that persistence was not confirmed; it does not prove
that the database remained unchanged.

When MRA operations are present, the terminal projection uses their final
effective pair instead of the originally loaded pair and performs one
distributed upper-bit pass. This is the only point at which unselected MRA
records change. The plan reports that constraint under
`ownership.mra_global_bits`, including component owners, the pre-conversion
source widget, masks and final effective values.

## Evidence boundary

[`edlt-parent-transaction-evidence.json`](../research/fixtures/edlt-parent-transaction-evidence.json)
pins the original parent sequence, percentage and retained save model.
[`edlt-parent-panels-evidence.json`](../research/fixtures/edlt-parent-panels-evidence.json)
pins all selected original panel sources and the independently accepted
standalone fixtures reused by this extension. Together they retain evidence
for:

- actual Measurement panel validation and model conversion;
- original records, event/control bindings, static allocation and CRCs for
  every admitted widget/settings panel;
- original terminator normalization plus standalone native database
  persistence; and
- the standalone original percentage control and arithmetic.

[`edlt-parent-mra-evidence.json`](../research/fixtures/edlt-parent-mra-evidence.json)
additionally pins the original/native MRA component fixture, first-widget and
stored-standby/raw-3 normalization probes, parent sequence and existing
uncertain-write contract. The new tests execute the Python composition and an
optional disposable native database save/reload; they do not claim that an
operator performed this multi-edit sequence in the original WinForms form.

The portable transaction tests freshly verify ordered differential records,
shared allocation, duplicate ownership rejection, one terminal lifecycle/CRC
call including a normalized source with unchanged CRC bytes, exact
unrelated-field preservation, stale-state rejection, one write per
changed parameter, full readback, rollback, CLI dry-run/save behavior, and PP
write and database-save interruption evidence. An optional native test creates a disposable database
unit, performs the multi-edit, saves once, closes, reloads and compares the
complete PP state when `CBUS_CGATE_TEST_HOST` and `CBUS_UNITSPEC_DIR` are set.

The parent transaction still excludes the Applications and Corridor
cache-driven dialogs, Blank/Reset transitions and SceneManager editing. Blank
uses an issued retained-model transition and Reset constructs a fresh complete
model graph; neither has evidence for chaining inside arbitrary ordered
controls, so they remain separate workflows. The original full `FrmBaseUnit` and an
original interactive multi-panel sequence have not been executed for this
feature. Focus, caret, validation dialogs, rendering, operator timing,
physical transfer and physical display/control behavior remain unverified.
Output therefore keeps
`native_parent_form_executed=false`,
`native_multi_edit_parent_form_executed=false` and
`physical_device_verified=false`.

Run the portable focused checks from `toolkit-cli/`:

```sh
PYTHONPATH=src:. python3.13 -m unittest \
  tests.test_edlt_parent_panels \
  tests.test_edlt_parent_mra \
  tests.test_edlt_parent_transaction \
  tests.test_cli_edlt_parent_transaction -v
```
