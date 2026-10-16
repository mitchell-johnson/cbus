# Thermostat prepared zone properties

Thermostat settings admit explicit selection of the 34 Boolean properties
prepared by the retained UI, Plant, Temperature and Zone Management panels.
Each record runs its property's synchronous setter and callbacks in the same
fresh settings owner as output Select/Add/Edit, damper, quick-zone and plant
records. This is a prepared-property workflow: it does not dispatch a native
GUI click or establish native Enabled, Visible, focus or mouse admission.

Use the [settings transaction](thermostat-settings.md) and the
[fresh quick-zone owner](thermostat-quick-zone-controls.md). PC_TSA, PC_TSA5,
PC_TSB and PC_TSB5 use their corresponding decoded specifications. Explicit
`--temperature-preference celsius` is required before client construction.
The existing settled profile still requires live minimum/maximum temperatures
15/32, GuardEnable 0, minimum on/off times each 0–8, and their sum plus 2
strictly below a PlantCycleTime below 35. Loaded display, role-type, vent and
mask bounds remain those of the fresh owner. Group allocation uses its fixed
address-ascending manager profile.

## Exact records and bindings

Repeat `--output-operation` with one JSON record at each causal position:

```json
{"op":"zone-checkbox-binding","binding":"MeasuredZones.Zone2","checked":true}
```

Exactly `op`, `binding` and `checked` are admitted. `checked` must be a JSON
Boolean; `0`, `1`, strings, unknown fields and unknown bindings refuse before
client construction. Binding names are case-sensitive.

| Property prefix | Exact suffixes | Count |
| --- | --- | --- |
| `UIAllocatedZones` | `UnswitchedZone`, `Zone1`, `Zone2`, `Zone3`, `Zone4` | 5 |
| `InternalPlantZones` | `UnswitchedZone`, `Zone1`, `Zone2`, `Zone3`, `Zone4` | 5 |
| `InternalPlantModes` | `Heat`, `Cool`, `HeatCool`, `Vent` | 4 |
| `MeasuredZones` | `UnswitchedZone`, `Zone1`, `Zone2`, `Zone3`, `Zone4` | 5 |
| `CoolingPlantInstalledZones` | `UnswitchedZone`, `Zone1`, `Zone2`, `Zone3`, `Zone4` | 5 |
| `VentingPlantInstalledZones` | `UnswitchedZone`, `Zone1`, `Zone2`, `Zone3`, `Zone4` | 5 |
| `HeatingPlantInstalledZones` | `UnswitchedZone`, `Zone1`, `Zone2`, `Zone3`, `Zone4` | 5 |

Join the prefix and suffix with a dot. `UnswitchedZone` is bit 0; zones 1–4
are their corresponding bits. The four mode properties are bits 1–4 in the
listed order. Standby, InstalledZones, ControlledZones and
ScheduleControlledZones are not offered bindings.

After substituting actual connection and unit values, preview an ordered
history:

```sh
cbus-toolkit thermostat settings preview //PROJECT/NETWORK/p/UNIT \
  --spec-dir /path/to/decoded/specs --host HOST --port PORT \
  --exclusive-project --temperature-preference celsius \
  --output-operation '{"op":"zone-checkbox-binding","binding":"MeasuredZones.Zone2","checked":true}' \
  --output-operation '{"op":"zone-checkbox-binding","binding":"InternalPlantModes.Vent","checked":false}' \
  --output-operation '{"op":"quick-zone-view"}'
```

Apply the reviewed history through `thermostat settings apply` with a fresh
`--backup-project` name. Inspect full PP changes, creations, renames and
`output_projection.quick_zone_controls.prepared_zone_bindings`. Each binding
receipt records its position, panel/control, before/after mask and source
calls. Its position is in the complete mixed history; ordinary records also
count toward plant-message `posted_by` positions.

## Callbacks and final save

An equal Boolean assignment publishes no changed event and performs no
setter Begin/End callbacks. A changed assignment uses the existing Boolean
primitive, with intermediate locked notifications followed by the final
unlocked notification. Nested callbacks consume live values before the next
explicit record. The final value can differ from a requested mask after
template refresh; the receipt reports the actual result.

Internal plant and mode properties enter the guarded plant/unit/template
chain. Measured properties enter the unit chain. Heating, cooling and
venting installed properties enter the zone handler, which can clear empty
role types and cascade through modes, vent rules and programming flags.
Basic UI uses its recovered unit callback; the advanced UI override does not
inherit that base zone hook. Ordered template refresh can rewrite UsedZones
and InstalledZones and update damper references.

The owner retains its loaded master/slave role. Basic final save writes its
OperationZone and the separately loaded UI/sensor flags last; intermediate
property masks do not replace those save rules. Basic loading also resets its
damper references to unused regardless of raw stored damper addresses. A
changed installed-zone callback can consequently create missing generated
damper groups at the first free addresses while preserving the old groups.
Programmable save uses final live references and its recovered schedule
enable/address rules. Removing Vent can clear saved fan speed controls even
when the operation selected another prepared property. Review these dependent
changes rather than treating a property assignment as an isolated PP bit edit.

The fresh owner issues the original binding registry and records its complete
history. A copied, replaced or foreign controller cannot authorize save, nor
can caller JSON supply subscribers or a save receipt. Every queued plant
message must be delivered in this owner before terminal save.

## Transaction and compatibility boundary

The existing manager rechecks the full snapshot before mutation, keeps every
project Network closed and binds the complete expected PP and graph. An
actual change uses a source backup, at most one PP save and one target project
save; graph-only changes skip PP save. An actual no-op writes nothing.
An unchanged property record alone does not establish a whole-plan no-op:
initialization and the final save can still normalize values or references.

Any failed or uncertain mutation/save stops without automatic retry,
rollback, inverse writes or a later target save. Retain the attempt evidence
and inspect through a fresh read before choosing another action.

The profile is `explicit-source-prepared-zone-Boolean-bindings-v1`. It models
the retained prepared-property setters and synchronous source callbacks.
Native scheduling, control enabled/visible/focus admission, Windows message
dispatch, implicit GUI notifications and physical timing remain unverified.
Explicitly selecting a property of a control hidden in the original Basic
GUI is not evidence that a user could click that control there.

This is the bounded workflow in [issue #136](https://github.com/mitchell-johnson/cbus/issues/136).
Application migration, output Delete and the complete original form remain
open under [issue #42](https://github.com/mitchell-johnson/cbus/issues/42).
It does not promote the category ledger or overall Toolkit parity gate.
