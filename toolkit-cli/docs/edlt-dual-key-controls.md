# Timer, Shutter and Room Courtesy callbacks

The ordered eDLT parent transaction accepts `dual_key_controls` in `timer`,
`shutter` and `room-courtesy` operations. It supplies explicit numeric callbacks,
macro/colour/icon bindings and mutating source property reads for KEYGL5
5.5.00 / 5055EDL. It does not execute the original WinForms application or infer
an automatic event schedule.

A callback-only operation may omit `group` when its selected slot already has
the same family. Its complete record is retained without ordinary scalar
macro/ramp/colour normalization. Conversion requires an explicit group and the
existing ordinary planner's default/allocation contract. Explicit ordinary
scalar options also run that planner first. Each operation owns one 32-byte
record and RestoreLevel; it cannot implicitly own an adjacent slot or reuse a
slot elsewhere in the parent history.

A retained Timer example explicitly reads its display, changes it, writes it,
and edits its target/expiry. The static dialog supplies a second parent
operation without further edits.

```json
[
  {
    "op": "timer", "page": 1, "position": 2, "page_mode": "multiple",
    "dual_key_controls": [
      {"event": "timer-read"},
      {"event": "timer-set-value", "seconds": 64800},
      {"event": "timer-write"},
      {"event": "level-read", "target": "target"},
      {"event": "level-set", "target": "target", "value": 127},
      {"event": "level-validating", "target": "target"},
      {"event": "level-set", "target": "expiry", "value": 64},
      {"event": "binding-write", "target": "ramp-rate", "value": 4,
       "identity": "dual-key-ramp:4"}
    ]
  },
  {"op": "static-text-dialog", "edits": []}
]
```

Plan using an exact project snapshot and its selected unit. `PP_FILE` is the
existing PP export/complete parameter mapping. Endpoint/source variables are
caller-owned; preference files use the existing explicit grammar.

```sh
cbus-toolkit edlt parent-transaction-plan "$PP_FILE" \
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

The database path requires exclusive ownership, every project network closed,
and a source lock matching the selected network. PP SAVE and target PROJECT
SAVE are separate persistence boundaries. Never retry, replay or restore
an uncertain attempted save automatically.

The parent issues each binding from causal postordinary PP, the original
operation, selected family/slot, operation position, all 64 retained Names and
project/provider digests. Projection checks the exact issued instance and its
original payload. A detached receipt or caller state cannot resume it. Full PP
strings and 16-bit sentinels retain their identity; selected record, RestoreLevel
and all static rows are byte-strict. Numeric callbacks preserve Names and other
widgets. Result adoption follows successful checked projection.

## Offered binding writes

List events contain `event`, `target`, `value` and the exact `identity` below.
Icon events contain only `event`, `target`, `value` and require canonical
`UseBigIcon=1`. An Index write does not establish a modal image selection.

| Family | Target | Values | Identity | Source field/order |
|---|---|---|---|---|
| Timer | `ramp-rate` | 0..15 | `dual-key-ramp:N` | byte 16 |
| Shutter | `macro` | 0, 1 | `dual-key-shutter-macro:N` | byte 7; InputValues notification even when unchanged |
| Room Courtesy | `macro` | 255, 25 | `dual-key-room-courtesy-macro:N` | byte 7 |
| Room Courtesy | `off-colour`, `on-colour` | 0..8 | `dual-key-colour:N` | bytes 10 / 11 |
| Timer, Shutter | `icon-on`, `icon-off` | 0..255 | none | bytes 2 / 3 |
| Room Courtesy | `icon-on` | 0..255 | none | Off byte 3 before On byte 2 |

Shutter choices are 2 Key (0) and 2 Key with Presets (1). Room Courtesy offers
Unused (255), Bell Press (25), and colours None/White/Red/Green/Blue/Cyan/Magenta/
Yellow/Orange in that order. Timer's macro control is hidden, so no new offered
macro write exists. Room Courtesy's inherited Off icon is hidden and has no
independent offered write.

## Explicit numeric callbacks

Timer LevelControl targets are `target` and `expiry`; Shutter targets are
`preset1` and `preset2`. Each retains its own display, trackbar, numeric and
enabled state, initially zero/zero/zero/true. Reads are explicit. This profile
is unlinked and has no populated Group selection, Group Add/Edit or supplied
list/linked-control state.

| Event | Additional fields | Source effect |
|---|---|---|
| `level-read` | `target` | Read model, then run Value setter |
| `level-value` | `target`, signed32 `value` | Direct Value setter plus UpdateControls |
| `level-set` | `target`, signed32 `value` | SetValue; equal requested value returns before clamp |
| `level-no-changed` | `target`, signed32 `value` | Suppress ValueChanged delivery, retain binding writes |
| `level-trackbar-changed`, `level-numeric-changed` | `target`, `value` 0..255 | Explicit callback, then SetValue when changed |
| `level-validating` | `target` | Write current display once; no neighbours here |
| `level-mouse-down` | `target`, signed32 `x` | Source trackbar preview; no inferred ValueChanged |
| `level-enabled` | `target`, Boolean `enabled` | Enabled/border callback, no model-value change |
| `level-advanced` | `target` | Source empty handler |

MouseDown subtracts seven with unchecked signed 32-bit wrap before clamping
the trackbar preview. Values Int32.MinValue through MinValue+6 wrap to the
upper preview boundary; MinValue+7 produces zero. This does not infer host
ValueChanged dispatch or a model write.

SetValue bounds are Timer target 1..255, expiry 0..255, and both Shutter presets
6..248. Direct Value first calls OnValueChanged and Binding.WriteValue, then
UpdateControls recursively clips to NumericUpDown's 0..255 bounds. A supplied
Shutter Value zero can leave display zero while the model stores six; an
explicit read synchronizes it. Disabled controls can still run these supplied
callbacks without a claim that the host would deliver a user gesture.

Timer ExpiryLevel reads signed16, high byte 15/low byte 14; its setter masks the
low 16 bits. Shutter preset getters repair values outside 6..248 only on
explicit read. An out-of-range Shutter setter assigns the boundary recursively
and then again in the outer call. Receipts retain equal-value assignment
intents as well as changed bytes.

`timer-read`, `timer-get`, `timer-write` contain only `event`.
`timer-set-value` adds signed32 `seconds`; `timer-value-changed` adds explicit
time-of-day integer `seconds` in 0..86399. Display clamps to 0..64800 (18 hours).
Display/read does not invent a binding write; `timer-write` supplies it.
TimerValue writes shifted high byte 13 then masked low byte 12. PPAttribute
clamps individual byte writes to 0..255, rather than wrapping them. The direct
property API retains that distinction for signed32 input. Date/time string
parsing and recursive host-event counts remain outside this profile.

## Reads, source flags and composition

`get-view` observes raw values/private flags without mutating getters.
`get-property` names one actual family member; `read-properties` supplies an
ordered array of distinct members. Common members are StatusIconOnIndex/OffIndex,
Left/RightButtonMacrofunction, DualButtonMacrofunction, RampRate, TargetLevel1/2,
Offset and their four Editable flags. Timer adds TargetLevel/ExpiryLevel/TimerValue;
Room Courtesy adds KeyMacrofunction/OffColour/OnColour/StatusIconIndex. Inherited
virtual properties are model members, not extra offered pickers.
`get-used-static-text` consumes nonmutating clamped static-index getters while
preserving the raw bytes.

Explicit DualButtonMacrofunction reads run SetKeyFunctionDefaults. Timer and
Room Courtesy use the ordered macro-input walk and false-to-true default
assignments. Shutter overrides it with InputValues notification only. Retained
models begin with constructor flags true; new Timer defaults leave flags false
after setting 35|34. The trusted issuer records this without a JSON state override.
`force-values` explicitly runs forced values: Timer target zero becomes one.
The parent terminal lifecycle performs its normal forced-value pass separately.

Shutter alone accepts `property-changed` with a bounded explicit `property` name.
Its subscriber matches LeftButtonMacrofunction or the source spelling
RightButtonMacrofunctin and notifies TargetLevel1Editable only. No setter
notification implicitly invokes this subscriber or refreshes a control.

Existing [label_controls](edlt-widget-control-adapters.md) retain their label/
status type/text profile. When both are present they run before dual-key
callbacks. Pending text still refuses parent save until an explicit supported
commit/read; numeric callbacks do not clear it. An event tail is not modal close.
Source assignment/notification intents remain distinct from PP transport writes.

The [annex](../research/fixtures/edlt-dual-key-control-source-annex.json),
[extractor](../research/edlt_dual_key_control_static.py),
[literals](../research/fixtures/edlt-dual-key-control-literal-vectors.json) and
[provenance](../research/fixtures/edlt-dual-key-control-provenance.json) pin
metadata/body/IL hashes, inheritance, declaration spans, source calls, macro
inputs, bindings and complete records. No vendor instruction bodies or raw vendor files are
published; the annex includes source display choices. Static occurrence order is not a runtime event trace. Constructor
binding declarations and SetUpDataSource replacements differ from activation
and callback scheduling.

[Pure tests](../tests/test_edlt_dual_key_controls.py) cover literal records,
ownership and continuation. [Public tests](../tests/test_cgate_edlt_dual_key_controls_interop.py)
cover both owned backends, preview/apply, fresh readback, refusal and successful
save-response loss. A test definition is not its execution receipt; consult the
batch's retained validation for actual epochs. Original host parsing/implicit
binding/currency/notification scheduling, linked/populated LevelControl, modal
selection, rendering and physical acceptance remain open. Time/Date controls
are outside this chunk. See the [parent contract](edlt-parent-transaction.md)
and [native metadata guide](edlt-native-parent-metadata.md).
