# Thermostat quick-zone controls

Thermostat settings compose explicit quick-zone and plant-control records with
the existing output Select/Add/Edit and damper history. Each preview or apply
creates one fresh settings owner from the selected unit's current PP and
complete project graph. The supported profile is
`fresh-source-owner-settled-explicit-quick-zone-controls-v1`.

This guide describes the bounded integration contract. The
[release report](feature-batch-2026-10-04-thermostat-quick-zone-controls.md) records 157 passing source pure-model tests plus
five passing subtest events, a separate 42-test source backend run, and one
199-test isolated installed-wheel run plus five passing subtest events, all
without skips or failures. The preceding
[plant/queue component checkpoint](thermostat-quick-zone-components.md) and
[damper checkpoint](thermostat-damper-controls.md) retain their separate evidence.

## Admitted source state

Use PC_TSA/PC_TSA5 or PC_TSB/PC_TSB5 with the corresponding decoded
THERMOSTATA/THERMOSTATB specification and the existing closed-project settings
workflow. Select `--temperature-preference celsius` explicitly; this is required
before client construction for any quick-zone/plant record. The process
preference is separate from the device's TemperatureUnits field.

The loaded control model must have MinimumSetTemperature 15,
MaximumSetTemperature 32 and GuardEnable 0. PlantMinimumOnTime and
PlantMinimumOffTime must each be integers 0–8; their sum plus 2 must be strictly
less than PlantCycleTime, which must be below 35. These settled controls avoid
unmodelled temperature/time-control edits during initialization.

Raw ZoneTemperatureDisplay must be 0–4, each heating/cooling/heat-cool/venting
role type 0–11, and VentPlantType 0–2 before setup. The owner validates its
consumed five-bit zone masks and complete required fields. Invalid loaded
values refuse before a Basic master initialization can replace them.
Address-ascending Group manager order is the supported allocation profile.
Application migration and alternative manager/locale profiles remain open.

## Ordered records

Repeat `--output-operation` once for each JSON object, in order. Records admit
only their specified fields. Booleans must be JSON Booleans; integers must be
JSON integers. Malformed names, duplicate JSON keys, non-finite values and
unknown fields refuse before client construction.

| Record | Source-owned behavior |
| --- | --- |
| `{"op":"quick-zone-view"}` | Record the current owner's state without invoking a control setter. |
| `{"op":"quick-zone-refresh"}` | Recompute partial/full checkbox state, then perform the eligible ordered UsedZones/InstalledZones refresh. This can change model values. |
| `{"op":"quick-zone-click","zone":1,"checked":true}` | Enter the explicit checkbox callback for zone 0–4, including its guarded Include/Exclude and nested source callbacks. Zone 0 is the unswitched zone. |
| `{"op":"select-plant-type","value":3}` | Select one of the twelve source-offered plant objects, values 0–11; run BeforeChange/index-change and issue the owning plant message. |
| `{"op":"dispatch-plant-type-change","posted_by":1}` | Consume the message issued by that earlier operation position and enter its live plant-change handler exactly once. |

For an unchecked zone-0 click, optional `"confirm_unswitched":true|false`
provides the explicit outcome if warning 7320 is reached. It is allowed only
for zone 0 with checked false. Accept excludes the unswitched zone; decline
rechecks it. Attempting to uncheck the last checked zone records warning 7321
and rechecks that checkbox.

Positions are one-based across the complete mixed history. `posted_by` counts
ordinary and damper records as well as quick-zone records. It selects a token
issued by a prior plant selection in this same owner. It cannot supply a
continuation, arbitrary subscriber, copied event or previously consumed event.

For example, after substituting the actual unit, specification directory and
connection values:

```sh
cbus-toolkit thermostat settings preview //PROJECT/NETWORK/p/UNIT \
  --spec-dir /path/to/decoded/specs --host HOST --port PORT \
  --exclusive-project \
  --temperature-preference celsius \
  --output-operation '{"op":"select-plant-type","value":3}' \
  --output-operation '{"op":"dispatch-plant-type-change","posted_by":1}' \
  --output-operation '{"op":"quick-zone-click","zone":1,"checked":true}' \
  --output-operation '{"op":"quick-zone-view"}'
```

Inspect the preview before applying the same history through the existing
[settings transaction](thermostat-settings.md). A view event itself is
read-only, but owner setup and the final recovered form save can still change
the plan. Inspect actual final changes rather than inferring a no-op from the
last event's name.

## One causal model

The owner shares current scalar values, output/damper references, the Group
resolver and inherited remote-reference store. Existing Groups retain their
identities, OIDs and opaque optional Level.Value metadata through shared
Select/Add/Edit and source-generated allocation. Diagnostic receipt JSON
cannot initialize caches or a new owner.

The initial owned phase reads the full loaded model to settle its dirty state.
It records the CBus, UI, ZoneManagement, Plant, TempControl and Templates setup
order. Templates guards suppress its initial checkbox-driven writes.
Programmable scheduling has its separately recorded direct initialization
callback and source visibility/initializing gates.

Include/Exclude and type/mode callbacks consume live values in source order.
InstalledZones assignment visits the five Boolean fields in order 0–4; changed
assignments can run the owner's fixed subscribers before the next field. An
unchanged Boolean assignment publishes no changed event. The resulting mask
can therefore differ from a requested mask after nested quick-zone refresh.
The earlier explicit damper-only profile continues to expose its separate
assignment/update events; adding a quick-zone record selects this initialized
owner's synchronous notification profile.

Plant dispatch performs default modes and vent rules, live parameter/fan
branches and Group allocation, default role types, current-installation reset,
stage rules and parent-view reads with the recovered Begin/End/finally order.
Installation item 0 is the actual source `<Custom>` object. The installation
manager offers codes 0,1,4,5,6,8,9 on Basic units and 0–9 on Programmable units.
Capacity warning 7327 follows its source branch and cleanup order.

Selection issues message 1059 (`0x423`) with zero parameters into a private
queue. Dispatch reads the current model at delivery time. Tokens are consumed
before the handler runs, including if it fails; there is no automatic replay.
Every pending token must be delivered before terminal save. The posted queue
and save receipt are diagnostics, and neither is transferable authority.

## Model state and final saved values

The owner retains the master/slave role derived during source loading.
Later zone-mask changes, including zero transitions, do not redefine that
role. A changed scalar ControlledZones edit is refused in this full-owner
profile. This comparison requires the authoritative readonly unit snapshot; it
is checked after connection and before mutation. Record schema and the explicit
Celsius requirement are checked before client construction. Other admitted
scalar edits retain the existing pre-load overlay behavior.

For Programmable units, a retained master saves ControlledZones from the
final InstalledZones model. A retained slave saves ControlledZones 0 and
clears InternalPlantType/InternalPlantZones. The model's plant type 11 uses
the recovered stored type 8 projection. Enabled schedule roles come from the
same final live reference store; disabled scheduling retains its source
32/33/34 saved-address defaults.

Basic setup assigns ZoneTemperatureDisplay 0 for a retained master before the
first quick refresh. Its final OperationZone is the bit selected by that live
display enum. The separately loaded user-controlled and sensor-enabled
Booleans determine UIAllocatedZones and MeasuredZones; quick-mutated masks do
not redefine them. A Basic master's final InstalledZones, ControlledZones and
InternalPlantZones become OperationZone. Heating/cooling installed masks
follow their respective role types; the source Venting installed-mask rule
deliberately follows CoolingPlantType. These Basic tail values override the
generic mask projection last.

Modulation saves the recovered plant factor, which can be 0–3 rather than the
checkbox's Boolean. Common installation save reads the actual current
installation Code, or saves 0 for nil. The original owner-issued save result
binds the current complete values, Groups/Levels, references, installation and
history. Final schedule enable and addresses are derived again from that
store. Caller JSON cannot override the retained role or saved expectations.

## Apply and evidence boundary

The existing settings manager binds a fresh project/PP snapshot, checks
freshness again before mutation, and keeps all project networks closed under
exclusive ownership. Review creations, renames, full PP changes and
`output_projection.quick_zone_controls`, including `state`, `source_calls`,
`posted_changes`, `save_facts` and `save_projection`.

Actual changes use one settings transaction: a source backup, at most one PP
save and one target project save. Graph-only changes skip PP save; an actual
no-op writes nothing. Fresh readback checks the complete planned PP and project
state. Any uncertain mutation/save stops without automatic replay or
restoration; retain its evidence and inspect through a fresh read.

This profile implements the fixed fresh owner's source-derived callbacks and
explicit queue delivery. Windows PostMessage delivery, native control
SetText/SetEnabled/focus notifications, arbitrary external subscribers, modal
rendering and a complete original initialized form remain outside it.
Original/native-server and physical thermostat timing acceptance remain
separate. Application migration, output Delete and wider unsupported histories
remain open under [issue #42](https://github.com/mitchell-johnson/cbus/issues/42).
The category ledger and overall parity gate are not promoted by this guide.
