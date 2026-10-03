# Time/Date callbacks in the eDLT parent transaction

The KEYGL5 / 5055EDL firmware 5.5.00 parent transaction accepts explicit
`time_date_controls` inside an ordinary `time-date` operation. You can inspect a
retained display, apply the actual offered display/format bindings, and grow or
shrink a standby Time/Date widget without losing its opaque record bytes. These
settings format displays; they do not set a clock or select its time source.

A callback-only operation on a retained type 10 or 11 preserves the raw display
byte, including 255, until an explicit offered write changes it. A readonly view
does not repair it or invent a selection. An explicit scalar option or conversion
from another type first uses the existing ordinary Time/Date planner and its
validation/default contract. The old scalar API still refuses an invalid display
byte unless an explicit valid display is supplied.

## An explicit history

This example grows standby position 4 to two slices, selects Time & Date, and
changes the unit-wide date format. The empty static dialog supplies the second
operation required by the owning parent transaction.

```json
[
  {
    "op": "time-date", "page": 0, "position": 4, "page_mode": "multiple",
    "time_date_controls": [
      {"event": "get-view"},
      {"event": "binding-write", "target": "widget-type", "value": 11,
       "choice_index": 4, "identity": "time-date-widget-type:11"},
      {"event": "binding-write", "target": "display", "value": 2,
       "choice_index": 2, "identity": "time-date-display:2"},
      {"event": "binding-write", "target": "date-format", "value": 4,
       "choice_index": 4, "identity": "time-date-date-format:4"},
      {"event": "binding-read", "target": "widget-type"}
    ]
  },
  {"op": "static-text-dialog", "edits": []}
]
```

Use complete PP input and an exact native project snapshot for an offline plan.
The specification directory and all files/addresses in these examples are
explicit caller inputs.

```sh
cbus-toolkit edlt --spec-dir "$SPEC_DIR" parent-transaction-plan "$PP_FILE" \
  --project-xml "$PROJECT_XML" --unit "$UNIT" \
  --operations "$OPERATIONS" --display-preferences "$PREFERENCES"

cbus-toolkit cgate --host "$HOST" --port "$PORT" unit \
  --lock-address "$NETWORK" --source "$DATABASE_UNIT" --dry-run \
  edlt-parent-transaction --spec-dir "$SPEC_DIR" \
  --auto-metadata --exclusive-project --operations "$OPERATIONS" \
  --display-preferences "$PREFERENCES"

cbus-toolkit cgate --host "$HOST" --port "$PORT" unit \
  --lock-address "$NETWORK" --source "$DATABASE_UNIT" \
  edlt-parent-transaction --spec-dir "$SPEC_DIR" \
  --auto-metadata --exclusive-project --backup-project "$NEW_BACKUP" \
  --operations "$OPERATIONS" --display-preferences "$PREFERENCES"
```

Automatic project metadata is required to issue the callback binding; a manual
cache or detached JSON receipt cannot supply it. The native path requires
exclusive project editing, closed networks, and the selected network's source
lock. Preview is readonly. Apply follows the existing single parent PP save and
project save/reload protocol. An uncertain attempted save is never replayed,
retried or restored automatically.

## Offered choices and event grammar

Every list write contains exactly `event`, `target`, `value`, `choice_index` and
`identity`. Its ordinal, value and identity must all match the actual source list.
The `leading-zero` Checked write contains only `event`, `target`, `value` with
numeric 0 or 1. Caller-supplied choice lists, state, parsing and implicit notifications
are not accepted.

| Target | Source values in list order | Ordinal | Identity |
|---|---|---|---|
| `display` | Date (1), Time (0), Time & Date (2) | 0, 1, 2 | `time-date-display:N` |
| `date-format` | 0, 1, 2, 3, 4, 5, 6, 7 | same as value | `time-date-date-format:N` |
| `time-format` | 12 hour (3), 24 hour (1), 12 hour am/pm (0), 12 hour AM/PM (2) | 0, 1, 2, 3 | `time-date-time-format:N` |
| `widget-type` | Time & Date (10), Time & Date two-slice (11), within the full location list | see below | `time-date-widget-type:N` |
| `leading-zero` | numeric 0 or 1 | none | none |

Date-format labels, in order, are `dddd dd Mmm`, `ddd dd Mmm`, `ddd dd/mm`,
`ddd mm/dd`, `dd/mm`, `mm/dd`, `dd Mmm`, `Mmm dd`. The controls include their
source example text; ordinal selection does not depend on a guessed culture sort.

Type 10 is ordinal 3 in the standby list and ordinal 13 in the complete
15-row functional list. Type 11 is ordinal 4 only at standby positions 1..4.
Standby position 5 excludes type 11. The complete source list is retained for
binding observations, but this new write profile admits only types 10 and 11.
It does not introduce conversions to the other widget families.

| Event | Additional fields | Effect |
|---|---|---|
| `get-view` | none | Observe retained raw model values and exact choice lists |
| `get-property` | `property` | Explicit source getter |
| `read-properties` | distinct ordered `properties` array | Explicit source getters in supplied order |
| `binding-read` | `target` | Explicit declared Binding.ReadValue request |
| `binding-write` | fields above | Explicit declared Binding.WriteValue request |
| `setup-widget-selection` | none | Source clear/replacement/restore binding sequence, then ReadValue |
| `widget-type-selected-index-changed` | none | Source empty handler; no inferred write |

Properties are `DisplayType`, `WidgetType`, `DateFormat`, `TimeFormat` and
`TimeDateLeadingZero`. Each operation accepts 1..512 explicit events. Binding
observations, source setter calls, assignment intents and notification intents
are recorded separately from changed PP fields. Equal numeric global assignments
may be source no-ops; raw PP token equality and actual host notification delivery
are not inferred from a normalized numeric cache.

## Placement, ownership and preservation

Changing to type 11 clears the next widget's type to Blank (0), preserves its
bytes 1..31, and owns both complete records. An already Blank neighbor skips its
source default call. Retaining type 11 or shrinking 11 to 10 leaves a configured
neighbor untouched and owns only the selected slot. If ordinary scalar growth
happened earlier in the same operation, that already-cleared adjacent slot remains
owned even when the later callback shrinks the selected widget. A covered standby
slot, unavailable two-slice location or duplicate cleared-slot owner is refused.

TimeAndDate defaults delegate to inherited RestoreLevel zero. KEYGL5 exposes
persistent Restore fields only for functional slots 6..21, so the parent never
invents a standby Restore parameter. Callback binding admission pins the actual
available fields and refuses fabricated standby fields or missing functional
Restore fields. Other opaque bytes and all 64 static rows remain exact.

DateFormat, TimeFormat and TimeDateLeadingZero apply to the whole unit. The
parent merges changed fields under its existing ownership guard; conflicting
changed global claims are refused. The separate `LevelBarStyle` field at bit 7
of byte 0x119 is preserved. A new callback cannot commit a pending SceneName or
other pending text history. Fresh Reset and retained models use distinct causal
source snapshots, and Reset retains its existing complete-profile bounds.

Each binding pins the exact parent owner, original operation/position, selected
slot, complete PP strings/numeric arrays, project digest and issued instance.
Canonical apply replays those bindings against the same source. It cannot use a
copied binding, caller state or an earlier source snapshot.

## Evidence and limits

The [source annex](../research/fixtures/edlt-time-date-control-source-annex.json),
[literals](../research/fixtures/edlt-time-date-control-literal-vectors.json),
[provenance](../research/fixtures/edlt-time-date-control-provenance.json) and
[static extractor](../research/edlt_time_date_control_static.py) pin retained
managed methods, declarations, inheritance, bindings and complete source effects.
The public [parent literals](../tests/time-date-public-literals.json) and
[tests](../tests/test_cgate_edlt_time_date_controls_interop.py) supply independent
full-record/global oracles for both owned services.

These are static source and explicit software callback contracts. Original
WinForms activation/implicit scheduling, parsing, notification delivery, rendering,
clock behavior, firmware/physical acceptance and full Toolkit parity remain open.
No vendor instruction bodies, specifications, certificates, keys or site projects
are published. See the [batch validation scope](feature-batch-2026-10-03-time-date-recovery.md)
and [parent contract](edlt-parent-transaction.md).
