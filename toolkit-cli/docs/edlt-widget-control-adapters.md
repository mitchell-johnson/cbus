# eDLT widget control adapters

The ordered parent transaction accepts explicit label/status histories for
Enable, Timer, Shutter, Multi Level, Fan and Room Courtesy, and explicit Scene
widget property and cycle callbacks. Each history runs after its ordinary
widget projection, inside the same parent load, terminal normalization and
CRC calculation. The parent owns the PP save. This is a source-backed software
profile for KEYGL5 / 5055EDL firmware 5.5.00; complete Toolkit workflow, original
GUI scheduling and physical acceptance remain open.

## Parent workflow and inputs

Put `label_controls` or `scene_controls` inside its owning widget operation.
The parent document remains a JSON array of 2..22 operations with distinct
widget ownership. For example, this Enable history selects observed variant 2
and commits a static status name:

```json
[
  {
    "op": "enable", "page": 1, "position": 1,
    "variable": 42, "level": 128,
    "label_controls": [
      {"target": "label", "type": 10, "events": [
        {"event": "selected-row", "index": 1,
         "identity": "label:203/42/1", "value": 1}
      ]},
      {"target": "status", "type": 5, "events": [
        {"event": "input", "text": "Enabled"}, {"event": "enter"}
      ]}
    ]
  },
  {"op": "general", "debounce_ms": 50}
]
```

The identity above is valid only if the selected project's current Enable
group 42 exposes that exact row at ordinal 1. Enable uses application 203;
the other five families retain their ordinary application-selection rules.
Use `group` instead of `variable` for those families.

Preview an exact local PP export and native project snapshot:

```sh
cbus-toolkit edlt parent-transaction-plan values.json \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --operations operations.json
```

For an existing database unit, preview against fresh automatic metadata:

```sh
cbus-toolkit cgate --host SERVER unit \
  --lock-address //PROJECT/254 --source /db//PROJECT/254/p/20 \
  --dry-run edlt-parent-transaction \
  --auto-metadata --exclusive-project --operations operations.json
```

After reviewing the plan, apply with a new backup name:

```sh
cbus-toolkit cgate --host SERVER unit \
  --lock-address //PROJECT/254 --source /db//PROJECT/254/p/20 \
  edlt-parent-transaction --auto-metadata --exclusive-project \
  --operations operations.json --backup-project BEFORE_WIDGET_CONTROLS
```

Keep every network in that project closed and declare exclusive ownership.
The source network lock must match the selected unit. `--backup-project` is
an apply option and cannot accompany `--dry-run`. Metadata changes, PP SAVE
and target PROJECT SAVE are separate operations; an uncertain save is never
automatically retried or rolled back. Inspect the failure evidence before
any further write. See [parent transactions](edlt-parent-transaction.md) and
[automatic metadata](edlt-parent-metadata.md) for the complete save contract.

Dynamic rows come from the exact project XML, current default language and
bound image inputs at this operation's position. Earlier admitted Language
changes can affect them; later changes cannot. FONT/ICON or other
image-dependent rows need the corresponding proven provider. Add
`--project-images-export images.json --project-images-sha256 SHA256` when
required, and consult [label controls and images](edlt-label-controls-images.md)
for the export, DLTP and decoder limits. Missing image metadata is not an
image-absence fact.

## Six AppGroup family schemas

`label_controls` contains 1..64 ordered records of the form
`{"target": TARGET, "type": TYPE, "events": [...]}`. `type` is optional;
each event array contains at most 512 callbacks. Unknown keys, caller state
and caller binding/mode changes are refused.

| `op` | Targets | Label type choices | Status type choices | Stored label/status offsets |
| --- | --- | --- | --- | --- |
| `enable` | `label`, `status` | 0, 10, 3 | 0, 3, 10, 1, 2, 5 | 11 / 12 |
| `timer` | `label`, `status` | 0, 10, 3 | 0, 10, 5, 4 | 17 / 18 |
| `shutter` | `label`, `status` | 0, 10, 3 | 0, 3, 10, 1, 2, 5 | 10 / 11 |
| `multilevel` | `label`, `status`, `status-low`, `status-medium`, `status-high` | 0, 10, 3 | No type picker on any status target | 9 / 10; Low 11, Medium 12, High 13 |
| `fan` | `label`, `status`, `status-low`, `status-medium`, `status-high` | 0, 10, 3 | No type picker on any status target | 9 / 10; Low 11, Medium 12, High 13 |
| `room-courtesy` | `label`, `status` | 0, 10, 3 | 0, 10, 5 | 8 / 9 |

Label 0 is Blank, 3 is Static Text and 10 requests the source dynamic
text/icon resolution. Status 0 is Blank, 5 is Static Text and 10 requests
dynamic resolution; 1 is Level, 2 is Percent, 3 is Bar and 4 is the
Timer-specific Timer type. These are the actual panel catalogues. The
lower-level property API has separate admissible values and does not add
type pickers to a panel. Shutter uses its inherited bound status catalogue.

Enable, Timer, Shutter and Room Courtesy use `ComboImageTagDLT` on both
targets. Multi Level and Fan use it on `label`; all four status targets use
`ComboBoxStaticText`, with `status` representing Off. A four-name example is:

```json
{
  "op": "fan", "page": 1, "position": 2, "group": 42,
  "label_controls": [
    {"target": "status", "events": [
      {"event": "input", "text": "Stopped"}, {"event": "leave"}]},
    {"target": "status-low", "events": [
      {"event": "input", "text": "Quiet"}, {"event": "enter"}]},
    {"target": "status-medium", "events": [
      {"event": "input", "text": "Usual"}, {"event": "enter"}]},
    {"target": "status-high", "events": [
      {"event": "input", "text": "Fast"}, {"event": "enter"}]}
  ]
}
```

For `ComboImageTagDLT`, the admitted callback shapes are:

| Event | Fields besides `event` |
| --- | --- |
| `input` | `text` |
| `enter`, `leave`, `close` | None |
| `key-preview` | `key`: `left`, `right`, `up`, `down`, `enter` or `other` |
| `selected-row` | `index`; selected rows also need exact `identity`, `value`. Optional booleans `data_source_present`, `data_manager_present` default true. An absent source or index -1 cannot carry identity/value. |
| `list-refresh` | `change_type`, `new_index`, `old_index`, `selected_index`; optional booleans `visible` (true), `list_updates_disabled` (false), `invoke_required` (false) |
| `drop-down` | `open`: boolean |

`change_type` is `reset`, `item-added`, `item-deleted`, `item-moved`,
`item-changed`, `property-descriptor-added`, `property-descriptor-deleted`
or `property-descriptor-changed`. Dynamic row identities are
`label:APPLICATION/GROUP/VARIANT`; the exact ordinal and value must match
the issued list, containing at most four variants. Native static suggestion
ordinals for this control remain refused because no culture-sorted list was
observed.

The four Multi Level/Fan static targets use the existing
[SceneName callback shapes](edlt-scene-name-control.md): `input`, `enter`,
`leave`, `arrow-preview`, `selected-name`, `list-refresh` and `close`.
`selected-name` supplies a nonnegative `selected_index` and an exact known
`name`, or an explicit no-selection index -1. Known-name membership comes
from the current 64 retained names and the source FixedStrings catalogue;
its supplied callback ordinal does not establish native culture sort order.

`enter` means the Enter key, not focus Enter. Eligible Enter-key/Leave
callbacks write the binding and then read it. Arrow suppression consumes one
selection callback. An eligible list refresh reads the binding and can
discard pending text without committing it. Asynchronous dispatch is refused.
Input is valid Unicode, NUL-free and at most 64 UTF-16 units. Input alone can
remain pending across histories for the same target, but unresolved pending
text cannot reach parent save; close never invents a commit.

The property projection preserves bit 7 and unrelated bytes. Generic dynamic
type 10 resolves from the exact selected image fact, including recursive
index-reset behavior. The virtual index getters clamp dynamic indices at 4
and static indices at 64 to zero. Enable's unchanged-index setter guard is
retained; the other families recompute even for an unchanged raw index. Low,
Medium and High Fan/Multi Level names retain their separate raw references.

## Scene widget callbacks

Add a flat array of 1..512 events under `scene_controls` in an existing
`scene` operation. For example, this explicitly selects the second source
scene after the ordinary operation:

```json
{
  "op": "scene", "page": 1, "position": 1,
  "scene": 1, "label_type": "blank", "status_type": "blank",
  "scene_controls": [
    {"event": "get-view"},
    {"event": "scene-selected", "index": 1,
     "identity": "scene:2", "value": 1}
  ]
}
```

The bound list contains all eight actual `ScenesNameValue` rows in source
order. Identities are `scene:1`..`scene:8`, values are 0..7 and names come
from the current retained scene-name cache. An earlier SceneManager edit is
visible; a later edit is not. The parent recalculates final scene references
from the resulting complete record.

| Event | Fields besides `event` and required source state |
| --- | --- |
| `get-view` | None; reads the current nonmutating property/choice view |
| `set-widget` | None; records the explicit SetUpDataSource snapshot/binding/reset/restore requests |
| `type-selected` | `target`: `label` or `status`; exact `index`, `identity`, `value` from the type catalogue below |
| `variant-selected` | `target`, exact `index`, `identity`, `value` from the four-variant catalogue; requires the dynamic control to be visible |
| `scene-selected` | Exact `index`, `identity`, `value` from the eight scenes; requires single-selection mode |
| `macro-selected` | Exact `index`, `identity`, string `value` from the macro catalogue below |
| `cycle-variant-checked` | `radio`: `cycle` or `select`, and boolean `checked`; requires cycle mode |
| `get-cycle`, `get-can-add`, `get-can-remove` | None; each explicitly invokes the mutating SceneCycle getter |
| `cycle-current` | `index`: null, or exact `index`, `identity`, `value` from an earlier explicit cycle read |
| `cycle-row-selected` | Active observed `slot` (0..8) plus exact scene `index`, `identity`, `value` |
| `cycle-add`, `cycle-delete`, `cycle-delete-key` | None; Delete uses the explicitly supplied current row; null current is a no-op |
| `cycle-move-up`, `cycle-move-down` | `index`: null, or exact `index`, `identity` from an observed cycle row |
| `cycle-dirty` | `dirty`: boolean; journals CommitEdit(512) when true, without inferring a cell write |
| `cycle-data-error` | None; journals the source Cancel=false callback |
| `status-text` | `events`: the SceneName callback array; requires visible Static Text status |

Type catalogues, in ordinal order, are:

| Target | `(identity, value)` choices |
| --- | --- |
| Label | `(label-type:0, 0)`, `(label-type:1, 1)`, `(label-type:2, 2)`, `(label-type:3, 3)` |
| Status | `(status-type:0, 0)`, `(status-type:6, 6)`, `(status-type:7, 7)`, `(status-type:5, 5)` |
| Label variant | `label-variant:0`..`label-variant:3`, matching values 0..3 |
| Status variant | `status-variant:0`..`status-variant:3`, matching values 0..3 |
| Macro | `(scene-macro:30\|31, "30\|31")`, `(scene-macro:26\|27, "26\|27")`, `(scene-macro:28\|29, "28\|29")`, `(scene-macro:32\|33, "32\|33")` |

The macros are Cycle Down/Up, Off/On, Off and Ramp Down/On and Ramp Up,
and Off and Nudge Down/On and Nudge Up. Scene has no generic type 10 picker.
SceneData's index properties hide the inherited base properties rather than
override them: changing display type can reset a hidden base index without
changing stored bytes 11/12. Explicit variant writes change those raw bytes.
The source right-macro notification spelling mismatch is preserved; it does
not imply an automatic RampRateEditable callback.

An explicit SceneCycle read accepts raw scene values 0..8 across nine stored
slots. On the first value above 8 it preserves that byte and normalizes only
the following slots to 255. CanAdd and CanRemove invoke the same getter.
Add scans only the first eight slots: it inserts zero into the first value
above 7, clears the following scanned slots and leaves slot nine unchanged.
Delete shifts the nine-slot tail; moves swap adjacent observed rows. The
journal records ResetBindings and Position requests without manufacturing
framework currency selection or a new cycle read. `get-view` and receipt
serialization do not invoke SceneCycle.

Component acceptance of raw 8 does not establish a configured ninth scene.
The native parent save profile continues to require final configured scene
references 0..7. It permits an empty cycle when no dynamic display depends
on it, and refuses active unconfigured references. An explicit getter can
repair invalid trailing storage; there is no automatic repair at serialization.

## Ownership and evidence boundaries

Each native binding is issued to the exact in-process owner, original binding
instance, operation position/history, complete post-ordinary PP snapshot and
full 64 retained Names. AppGroup bindings also retain actual ordered dynamic
rows/provider provenance; Scene bindings retain all eight causal scene rows
and project/provider digests. A manual cache, JSON receipt, reconstructed
object or identical copied binding cannot issue or resume this authority.
Complete cached Names matter even when long UTF-8 names produce the same
truncated saved PP row.

Static assignments use the source retained-name lookup before free-slot
allocation and keep the old reference reserved during allocation. Refused
AppGroup projections do not install speculative Names. Parent planning and
canonical apply replay use isolated retained caches, preserving nested and
exception cleanup. Reset initializes a fresh cache and graph; it does not
carry an earlier control's pending state into its new widget.

Inspect `app_group_label_bindings`, `scene_widget_bindings`, each
`operation_results` control receipt, static allocations, final references,
preservation evidence and terminal execution counts. A detached receipt is
review evidence, not a capability. Exact callback sequences are additive CLI
operations, not commands claimed to exist in the original Toolkit.

The sanitized source proofs and literal vectors are
`research/fixtures/edlt-app-group-label-{source-annex,vectors}.json` and
`research/fixtures/edlt-scene-widget-control-{source-annex,vectors}.json`.
They pin static methods and independent byte expectations. No original or
framework instructions were executed for this implementation. Culture sort
order, implicit notifications, null binding conversions, reflective host
selection, asynchronous dispatch, arbitrary pending-close order and screen
rendering remain outside the profile. Owned-backend verification does not
prove original C-Gate/WinForms scheduling, physical labels or full Toolkit
parity.
