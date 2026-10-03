# MRA controls in an owning eDLT transaction

The `zone-control`, `source-select` and `source-control` parent operations admit
an ordered `mra_controls` callback history for KEYGL5 5.5.00. Use automatic
project metadata so the parent issues the exact binding; caller JSON cannot
supply a binding, retained name cache or continuation capability.

```json
[
  {"op":"source-select","page":1,"position":1,"page_mode":"multiple",
   "mra_controls":[
     {"event":"binding-write","target":"variant","value":2,
      "identity":"mra-source-select-variant:2"},
     {"event":"binding-write","target":"source1","value":6,"identity":"mra-source:6"},
     {"event":"input","target":"label","text":"Music"},
     {"event":"enter","target":"label"},
     {"event":"get-view"}]},
  {"op":"general","debounce_ms":50}
]
```

The parent requires 2–22 operations with distinct owned widget slots. Preview
offline with `edlt parent-transaction-plan SNAPSHOT --project-xml PROJECT.xml
--unit //PROJECT/NETWORK/p/UNIT --operations OPERATIONS.json`. Preview a database
unit with `cgate unit --source /db//PROJECT/NETWORK/p/UNIT
--lock-address //PROJECT/NETWORK --dry-run edlt-parent-transaction
--auto-metadata --exclusive-project --operations OPERATIONS.json`.
Use the existing apply form only after reviewing the complete parent receipt.
Keep every project network closed and maintain exclusive project ownership.

## Offered bindings

| Target | Families | Offered values / identity |
| --- | --- | --- |
| `variant` | Zone | 0–3 / `mra-zone-control-variant:N` |
| `variant` | Select, Control | 0–2 / `mra-source-select-variant:N`, `mra-source-control-variant:N` |
| `status-type` | Zone | 0, 3, 1, 2, 5 / `mra-status:N` |
| `macro` | Zone | `15\|16`, `21\|22` / `mra-zone-macro:PAIR` |
| `ramp-rate` | Zone | raw 0–15 / `mra-ramp:N` |
| `source1`, `source2` | Select | raw 0–6 / `mra-source:N` |
| `icon-on` | All | raw byte 0–255; no choice identity |
| `icon-off` | Zone | raw byte 0–255; no choice identity |

Each row uses `event: binding-write`, its exact `target`, `value` and identity
where specified. These callbacks explicitly invoke the recovered binding.
They do not infer that a host selection committed a value. Icon Index writes
require the causal `UseBigIcon` setting and do not infer a modal chooser result
or image-array membership. Select writes coupled icons on/off; Control writes
off/on. Ordinary `source1`/`source2` arguments retain their existing 1–7 grammar.

All families have a `label` Text binding. Zone and Select also have `status`.
Flat Text events are `input`, Enter-key `enter`, `leave`, `arrow-preview`,
`selected-name`, `list-refresh` and `close`, with the shared explicit static
text control fields. `enter` is a key event, not focus Enter. Eligibility and
visibility are supplied callback facts; no notification dispatcher is inferred.
Pending text refuses the owning save. Closing does not commit pending text;
callbacks after that target closes refuse. The full 64 retained Names are
sealed independently of their truncated stored PP rows. Allocation retains
the old raw reference until assignment, including Select's hidden status index.
Exact full-name reuse chooses the first duplicate before checking capacity.

`get-view`, `get-property`, `read-properties` and `get-used-static-text` are
nonmutating reads. The separate Zone `get-zone-macro` callback invokes the
recovered getter: an unsupported stored pair becomes `15|16`. A read-only view
never invokes it. Zone's unimplemented LabelDisplayType accessors refuse.
Raw property setters and source defaults belong to the pure model API and
are separate from the finite panel choices exposed here.

## Causal parent and save

Callback-only edits retain hidden variants, macro/ramp/source values, raw own
text references, opaque bytes and RestoreLevel. A type conversion executes the
recovered ordered defaults before callbacks. Explicit ordinary scalar fields
keep their existing configuration validation and normalizer before callbacks.
Other ordinary panels keep their existing static-reference admission; a later
panel can therefore refuse a raw MRA pointer admitted by this callback profile.

In a history containing MRA callbacks, initialized audio globals come from the
first surviving loaded MRA model, before any conversion. Removing that model
does not discard its initialized globals. A discarded terminator tail does not
supply them. Reset starts a fresh initialization context. Explicit multiplexer
and zone operations update the two independent parent constraints. Callback
views observe their source record fields; distribution applies only in the
parent's terminal BeforeSave pass. This also preserves stored raw multiplexer 3
when no public multiplexer choice replaces it.

Operation-1 Reset retains its existing initialization profile: initial
navigation must be 0 or 1, and stored widget types must be 0, 2, 6, 7, 8, 10
or 255. These are prerequisite bounds, not acceptance of arbitrary prior MRA
form histories; initial Source Control type 9 remains outside that profile.
The new callbacks do not relax the remaining model, cache or raw-string checks.
See [Reset initialization](edlt-reset.md).

The issued instance binds the complete causal PP snapshot, operation position,
family, widget, full Names, reference inventory and available project/provider
digests. Copied or reconstructed bindings and detached receipts cannot resume.
The parent owns placement, static/scenes, RestoreLevel, checksums and one PP
save. Database apply preserves the existing backup, closed-network, OID,
stale-source and save-uncertainty guards. An uncertain PP/project save is never
retried or automatically restored.

Source-pinned record and callback tests establish a bounded software model.
Complete original form dispatch, culture-specific suggestions, modal picker
outcomes, implicit framework reads/notifications, rendering, audio delivery,
other firmware/models and physical/power-cycle acceptance remain open. Neither
these callbacks nor the Rust command surface establishes full Toolkit parity.
