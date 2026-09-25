# eDLT ordered parent transaction

`EdltParentTransaction` applies two through 22 ordered control operations to
one **KEYGL5 / 5055EDL firmware 5.5.00** database snapshot. The implemented
operation types are Measurement widgets, Lighting widgets and the unit-wide
proximity activation binding, including its Percentage/action path. Every
operation is validated by the corresponding accepted standalone editor. Their
bound fields then enter one retained lifecycle state, one terminal
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

## Operation contract

The JSON document must be an array with two through 22 entries, contain no
duplicate object keys or non-finite JSON constants, and include at least one
widget operation. Unknown operation types and fields fail closed. The accepted
fields are the public arguments of these existing editors:

| `op` | Required fields | Optional fields |
| --- | --- | --- |
| `measurement` | `page`, `position`, `device_id`, `channel` | `decimal_places`; exact Gain/Offset mantissa and exponent pairs; `gain_value`, `offset_value`, `measurement_culture`; page mode; prefix, suffix and label text/indexes; icon index |
| `lighting` | `page`, `position`, `group`, `mode` | primary/secondary application, page mode, label/status type/index/text, ramp seconds, restore level |
| `activation` | None | wake mode, group, `level_percent` or `action`, activation page and first-key behavior |

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

The source-pinned Lighting selection branch is `ShowWidget` →
`BaseWidget.SetWidgetData` → base data-source setup → assign the selected
`LightingData` source → `ResetBindings(false)`. Ramp rate, Offset and Target
Level 1 use default `OnValidation` bindings. Their three editability/visibility
bindings use `Never`. These are per-selection component facts; source does not
prove a particular operator's multi-selection order or pending-focus state.

## Ownership and preservation

Each widget operation owns its selected 32-byte record and, for functional
widgets, its restore byte. The transaction rejects two operations that target
the same slot. It also rejects a second activation operation because both
would own the same parent fields. All widget operations must resolve to one
page mode; an explicit conflicting mode is rejected. `NavWidgetType` is
written once as that reconciled parent constraint.

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

## Evidence boundary

[`edlt-parent-transaction-evidence.json`](../research/fixtures/edlt-parent-transaction-evidence.json)
pins the original parent, Measurement, Lighting, percentage and save-model
source hashes. It also pins retained independent evidence for:

- actual Measurement panel validation and model conversion;
- original Lighting records, static allocation and CRCs;
- original terminator normalization plus standalone native database
  persistence; and
- the standalone original percentage control and arithmetic.

The portable transaction tests freshly verify ordered differential records,
shared allocation, duplicate ownership rejection, one terminal lifecycle/CRC
call including a normalized source with unchanged CRC bytes, exact
unrelated-field preservation, stale-state rejection, one write per
changed parameter, full readback, rollback, CLI dry-run/save behavior, and PP
write and database-save interruption evidence. An optional native test creates a disposable database
unit, performs the multi-edit, saves once, closes, reloads and compares the
complete PP state when `CBUS_CGATE_TEST_HOST` and `CBUS_UNITSPEC_DIR` are set.

The original full `FrmBaseUnit` and an original interactive multi-selection
sequence have not been executed for this feature. Focus, caret, validation
dialogs, rendering, operator timing, physical transfer and physical display or
control behavior remain unverified. Output therefore keeps
`native_parent_form_executed=false`,
`native_multi_edit_parent_form_executed=false` and
`physical_device_verified=false`.

Run the portable focused checks from `toolkit-cli/`:

```sh
PYTHONPATH=src:. python3.13 -m unittest \
  tests.test_edlt_parent_transaction \
  tests.test_cli_edlt_parent_transaction -v
```
