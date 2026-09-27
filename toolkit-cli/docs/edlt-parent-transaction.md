# eDLT ordered parent transaction

`EdltParentTransaction` applies two through 22 ordered control operations to
one **KEYGL5 / 5055EDL firmware 5.5.00** database snapshot. It composes
15 configurable widget operations, including Blank and all three MRA models,
plus eleven direct parent/settings operations and an optional operation-1
Reset graph baseline. One additional `scene-manager` operation can apply an
ordered retained SceneManager edit through that same final transaction. The
direct set includes the Applications and Corridor cache dialogs when the
caller supplies their complete ordered application cache. SceneManager
composition requires the superset `cbus-edlt-scene-manager-cache-v1`. Every
operation reuses its accepted retained or standalone model contract. The owned
fields then enter one retained lifecycle state, one terminal
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

To edit retained scenes in the same save, use the complete SceneManager cache
and place its operation before any Scene widget:

```json
[
  {
    "op": "scene-manager",
    "operations": [
      {"op": "set-name-text", "scene": 1, "text": "Evening"},
      {"op": "set-level", "scene": 1, "item_id": 1, "level": 153}
    ]
  },
  {"op": "scene", "page": 1, "position": 1, "scene": 1}
]
```

A Reset-first transaction uses an exact raw export and a complete application
cache, for example:

```json
[
  {
    "op": "reset",
    "active_tab": "widgets",
    "binding_variant": "audited-local-wiring",
    "dirty_parameters": []
  },
  {
    "op": "measurement",
    "page": 1,
    "position": 1,
    "device_id": 42,
    "channel": 3
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
Applications, Corridor and Reset require a complete
`cbus-edlt-application-cache-v1` document. The caller-cache form remains
available; the automatic project XML resolver can now derive the complete
persisted application/group lists in XML child order. Reset additionally uses
the exact raw `PP Value` strings in the selected Unit record so its
spelling-sensitive control phases can be replayed canonically. This automatic
list branch never projects a missing application or group and reports that its
`formatted_display` values are a deterministic TagName database view, because
Toolkit registry display/sort preferences are absent from DBGETXML. The same
plan may combine that list/Reset contract with automatic SceneManager
metadata. Existing ordered-list requirements still refuse missing objects;
objects carrying independent creation receipts from another admitted parent
operation or SceneManager are appended to the projected cache before PP
staging. Evidence keeps
`ordered_list_requirements_project_missing_objects=false` separate from
`operation_owned_creations_enter_cache_before_pp_staging`.
The automatic `scene-manager` branch uses the existing exact
SceneManager resolver and projects a missing
Trigger Control application, exact trigger groups and exact action levels with
Address=Value and four blank variants. Those objects join ordinary parent
Application/Group/NetVar creations in deterministic dependency order before
the issued parent plan performs one PP staging/readback/save. Image-dependent
project/DLTP facts still fail closed. The caller-cache path remains available
for independently observed image facts.

## Operation contract

The JSON document must be an array with two through 22 entries, contain no
duplicate object keys or non-finite JSON constants, and include at least one
widget operation, SceneManager operation or Reset. Unknown operation types and
fields fail closed. The accepted
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
| `blank` | `page`, `position` | None; placement is resolved against the effective page mode at this point in the array |
| `activation` | None | Wake mode, group, `level_percent` or `action`, activation page and first-key behavior |
| `general` | None | Key timings, status interval, Tools lock and power restore mode |
| `display` | None | Large-text owner, big icons, Timer flash and Fan wrap |
| `standby` | None | Enabled/duration, destination and nightlight settings |
| `colours` | None | All fixed colours/brightness values and six control groups |
| `navigation` | None | Page mode/variant, temperature source, dynamic group and page names/indexes |
| `quick-status` | None | Mode, group, thresholds and three colours |
| `page-control` | None | Enable-application group or disabled value 255 |
| `mra-globals` | At least one of `multiplexer` 1..3 or `zone` 1..8 | None |
| `applications` | `edits` | Ordered `primary`/`secondary` selections, each with an exact application address |
| `corridor` | `edits` | Ordered Link/Office/Corridor group or seconds edits from the standalone Corridor contract |
| `reset` | `active_tab`, `binding_variant` | `dirty_parameters`; Reset must be operation 1 and requires a complete application cache plus exact raw source |
| `scene-manager` | `operations` | One nonempty array of up to 256 retained SceneManager operations; requires a complete SceneManager cache |

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
An Applications operation updates the retained Primary/Secondary controls and
the exact widget application-selector bits changed by the original callback;
later operations see that state. Corridor uses the resulting primary
application. Both operations require complete ordered application and group
lists, and either may appear only once. A selector bit changed by Applications
cannot also be owned by a widget operation in the same transaction.

Applications must precede `scene-manager`, because the retained scene load
binds every output group to the effective primary or secondary application.
`scene-manager` must precede every Scene widget operation, so the widget's
scene-name, trigger/action and dynamic-label dependency checks observe the
final scene graph. Only one SceneManager operation may own the graph. Its
nested sequence may edit names, trigger/action selectors, group items, levels,
ramps and the retained clipboard using the standalone SceneManager contract.
An incomplete 64-item capacity prefix is review-only in the standalone editor
and is rejected before the parent writes PP.

Blank reserves the selected complete 32-byte slot and its functional restore
byte, while its retained transition mutates only the type and, on a genuine
type change, the restore byte. The remaining 31 bytes stay intact. Placement
uses the original Blank filter: covered standby positions and the multiple-page
navigation position are rejected.

Reset is an ordered baseline rather than a parallel byte owner. It must be the
first operation because the accepted `ResetEdlt` transition discards the old
21 widget and eight scene objects and supplies a genuinely fresh graph. Later
operations bind to that fresh graph and become the final owner of any field
they override. The plan lists the Reset baseline fields and every later
override separately. Blank can follow Reset only in the contiguous operation
prefix immediately after operation 1. The lifecycle issues each Blank receipt
against `ResetEdlt.fresh` plus the exact post-Reset control state, including
the Time/Date model installed at widget 10. A later Blank is rejected because
an intervening panel would make that receipt's graph state ambiguous.

SceneManager may follow Reset and its contiguous Blank prefix, then edits the
issued fresh eight-scene graph. It may also compose with retained Blank because
their receipts own disjoint graph and widget fields.

The source-pinned Lighting selection branch is `ShowWidget` →
`BaseWidget.SetWidgetData` → base data-source setup → assign the selected
`LightingData` source → `ResetBindings(false)`. Ramp rate, Offset and Target
Level 1 use default `OnValidation` bindings. Their three editability/visibility
bindings use `Never`. These are per-selection component facts; source does not
prove a particular operator's multi-selection order or pending-focus state.

## Ownership and preservation

Each widget operation, including Blank, owns its selected 32-byte record and, for functional
widgets, its restore byte. Time/Date owns a second complete record when two
slices are selected. The transaction rejects overlapping slots. Each direct
settings panel, Applications, Corridor and activation may appear once because
a second instance would own the same fields. All widget/navigation operations must resolve to one page
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

The SceneManager operation owns the complete `SceneCount`, 232-byte
`SceneBucket`, all eight start pointers and each static-name slot it allocates.
The terminal lifecycle consumes that issued graph without reloading it. A
64-item graph uses the retained original `SaveScenes` temporary 233rd `FF`
token for the sole CRC calculation while still staging only 232 native bucket
bytes.

The plan reports each operation's `owned_parameters`, the transaction-wide
ownership table, selected slots and the exact deltas for:

1. retained load normalization;
2. bound controls;
3. terminal save normalization; and
4. the five CRC fields.

During the control phase every unowned parameter remains byte-for-byte equal
to the retained after-load model, or to the fresh Reset baseline when Reset is
operation 1. The terminal phase may change only the documented lifecycle-owned
fields. Without Reset, retained scene objects and the original MRA source
remain attached. Reset deliberately replaces the scene/widget graph and the
plan reports that loss of old object identity. Selected-record bytes not set
by their standalone editor are preserved, as are nonselected records and
unrelated parent fields outside independently documented lifecycle
normalization.

## One terminal sequence

Standalone widget and activation planners calculate self-contained plans so
their record bytes can be compared with their existing accepted behavior.
Those standalone `changes` dictionaries are never applied directly. A
temporary validation view places each earlier widget so the next distinct
editor can inspect a valid functional layout and shared text references.

After every operation succeeds, the complete bound-control state enters the
retained model produced by one lifecycle load. Reset performs its source-
evidenced second load to create the fresh graph, then later controls use that
graph. The transaction still runs only one terminal save projection and one
CRC calculation. That projection serializes the selected retained or fresh scenes,
propagates retained MRA globals, places one functional terminator, applies the
original forced values and calculates all five CRCs once. Canonical plan
verification is repeated immediately before mutation. When SceneManager is
present, its exact scene-only receipt replaces the retained or fresh scene
serialization at this same terminal point; it does not run a second lifecycle
or standalone save. The accepted terminal projection is written in one
parameter pass and verified by one full readback.
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
The Applications and Corridor components reuse their separately captured
original/native acceptance, cache contracts, retained lifecycle models and
save/reload evidence. The parent regression composes both with a widget,
checks exact field ownership and cache refusal, executes one final parent
projection and verifies one-pass write/readback. It does not convert their
standalone evidence into an original interactive multi-dialog capture.

Blank reuses the captured
[`edlt-blank-windows-vectors.json`](../research/fixtures/edlt-blank-windows-vectors.json),
placement and acceptance fixtures. Reset reuses
[`edlt-reset-windows-vectors.json`](../research/fixtures/edlt-reset-windows-vectors.json)
and its native acceptance fixture. The parent result names those source
fixtures when the corresponding operation is present.

The portable transaction tests freshly verify ordered differential records,
shared allocation, duplicate ownership rejection, one terminal lifecycle/CRC
call including a normalized source with unchanged CRC bytes, exact
unrelated-field preservation, stale-state rejection, one write per
changed parameter, full readback, rollback, CLI dry-run/save behavior, and PP
write and database-save interruption evidence. An optional native test creates a disposable database
unit, performs the multi-edit, saves once, closes, reloads and compares the
complete PP state when `CBUS_CGATE_TEST_HOST` and `CBUS_UNITSPEC_DIR` are set.

Blank and Reset reuse their separately captured original/native placement,
raw-phase, model-identity and persistence evidence. The focused parent tests
verify Blank plus another widget, Reset-first plus a fresh-graph Blank and a
later widget, exact raw
canonical replay, reverse rollback to the raw source, one terminal CRC pass,
one database save and no replay after a lost save reply. They do not turn those
separate component captures into an original interactive Blank/Reset plus
multi-panel execution. SceneManager composition reuses the retained model vectors,
static allocator, 64-item CRC behavior and native persistence acceptance from
`edlt-retained-scene-editing`. The focused parent tests cover retained and
fresh Reset graphs, Blank, ordering, cache refusal, one terminal pass and one
CLI save path. No original `FrmBaseUnit` + `SceneManager` multi-dialog
sequence or complete SceneManager control binding was executed. The original
full `FrmBaseUnit` and an original interactive multi-panel sequence have not
been executed for this feature. Focus, caret, validation dialogs, rendering, operator timing,
physical transfer and physical display/control behavior remain unverified.
Output therefore keeps
`native_parent_form_executed=false`,
`native_multi_edit_parent_form_executed=false`,
`original_interactive_blank_reset_sequence_executed=false` and
`physical_device_verified=false`.

Run the portable focused checks from `toolkit-cli/`:

```sh
PYTHONPATH=src:tests:. python3.13 -m unittest \
  tests.test_edlt_parent_panels \
  tests.test_edlt_parent_mra \
  tests.test_edlt_parent_cache_panels \
  tests.test_edlt_parent_blank_reset \
  tests.test_edlt_parent_scene_manager \
  tests.test_edlt_parent_transaction \
  tests.test_cli_edlt_parent_transaction -v
```
