# Thermostat quick-zone event ordering

Static recovery from the pinned Toolkit 1.18.0.2754 executable. The
[receipt](thermostat-quick-zone-events-static.json) records 44 method spans and
SHA-256 digests, 26 passing structural checks, selected direct call edges and
48 initial-load application/group lookup sites. This extends the
[dialog-rule subset](thermostat-settings-form-static.md); it does **not**
establish complete original dialog execution or an exposed quick-zone action.
No original executable was run and no project or hardware was changed.

| Input | SHA-256 |
| --- | --- |
| `CBusToolkit.exe` | `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab` |
| `CBusToolkit.map` | `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb` |

Reproduce from `toolkit-cli/` with the research dependencies installed:

```sh
python research/thermostat_quick_zone_event_static.py --exe CBusToolkit.exe --map CBusToolkit.map
```

The verifier checks both source hashes before inspection and rereads them
afterwards. Its edges contain only resolved, selected direct calls; they are
not an exhaustive callback graph. No original instruction bytes are retained.

## Initial form and accepted click

`TddThermostat.InitialiseSubForms` (`0x1132a24`) initializes CBus, UI, Zone
Management, Plant, Temperature Control and Templates in that order. It binds
the Templates zone callback at `+0x30/+0x34` to the parent's virtual slot
`+0x90`, resolved as `HandleEnableDisableZone` (`0x1132d1c`). That method calls
UI, Zone Management, Plant and Temperature Control `EnableDisableZone`, in
that order. Plant's helper additionally updates cycle-limiting enable state;
this route does not directly invoke `EnableDisablePlantModes`.

Plant `Initialise` (`0x112725c`) sets `+0x2a` during initial setup, suppressing
the isolated Vent fallback recovered earlier. Templates `Initialise`
(`0x111df60`) sets `+0x29` around `SetupComponents`; therefore the first
`UpdateQuickOptions` does not execute `UpdateFlashZoneVariables`.
`SetupComponents` (`0x111e220`) hides the published `gbControlledZones`
component at `+0x39c` for a basic thermostat. A public GUI-equivalent
quick-zone workflow must not expose that hidden action for basic models.

`HandleChbUsedZoneClick` (`0x111db64`) holds Templates `+0x28` throughout the
accepted Include/Exclude operation, then clears it in its finalization path.
The model-zone callback `HandleUnitZoneChange` (`0x111df48`) calls
`UpdateQuickOptions`, whose first guard returns while `+0x28` is set.
The click method has no subsequent direct quick-options refresh. Thus it is
incorrect to append an unconditional union-based `UpdateFlashZoneVariables`
rewrite, or the isolated Vent enable-state fallback, to every accepted click.

The explicit target sequence in `IncludeZone` (`0x111d7cc`) and `ExcludeZone`
(`0x111d98c`) is UsedZones → UIAllocatedZones → InternalPlantZones →
MeasuredZones → ScheduleControlledZones → InstalledZones → ControlledZones →
HeatingPlantInstalledZones → CoolingPlantInstalledZones →
VentingPlantInstalledZones. Include gates internal plant by the **retained**
master flag, schedule by programmable master, and the three plant-zone masks
by their current nonzero type. Exclude clears the applicable fields. The
parent enable callback follows those writes. Last-zone refusal and accepted
unswitched-zone confirmation remain required by the click handler.

## Nested model effects and save

`TZoneManagerService.HookEvents` (`0xfde088`) connects the zone object
attributes to `HandleZoneAfterChange` (`0xfde684`). Under its own `+0x130`
guard, that handler checks heating, cooling and venting installed masks and
sets each corresponding type to zero when its mask is empty. It then forwards
zone change. In Include, the manager ControlledZones write precedes the three
plant-zone writes. Consequently an initially empty plant mask can zero a
nonzero type before Include reaches that type's conditional write. The pure
`quick_zone_transition` helper does not model this nested effect.

Type changes can reach `TThermostat.HandleZoneManagerPlantTypeChange`
(`0xfecd3c`), recompute internal modes and VentPlantType, and reach
`TPlantControlService.HandleVentPlantTypeChange` (`0xfe1d20`) with fan-setting
effects. A proposed type-stable profile would require every nonzero heating,
cooling and venting type to have nonempty installed zones both before and after
the one-bit action. This is a candidate exclusion predicate, not current
public action admission. The generic notification chain still needs closure.

Zone writes do not themselves set `ZoneManagerMasterSlave` in the inspected
action and model handlers. Initial AfterLoad sets that distinct property from
whether the original raw ControlledZones is positive. BeforeSave's nested
`GetControlledZones` (`0x12946cc`) reads **InstalledZones** when this retained
property is master; slave returns zero. For example, a loaded master with
ControlledZones `3` and InstalledZones `17` saves ControlledZones `17` even
without a requested zone edit. Recomputing master from post-edit raw
ControlledZones, or preserving its old raw byte as the master save result,
does not reproduce that method.

`TBooleanAttribute.SetAsBoolean` (`0x7f45e0`) skips unchanged values.
`TZones.SetZones` (`0xca55e8`) writes the five booleans sequentially. A future
implementation must preserve actual event ordering rather than assume every
whole-mask assignment is one atomic notification.

## Project graph boundary

InstalledZones changes reach `TThermostat.HandleInstalledZonesChange`
(`0xfea824`) and `TPlantControlService.UpdateDamperGroups` (`0xfe5318`). The
latter visits all four switched zones. An installed zone with an assigned
non-255 object preserves it. An absent zone fills an empty cache with its
previous assigned object and selects the unused group. An installed unassigned zone can restore
a cached object, find the generated damper tag, or allocate/rename a group for
a master. Raw PP does not contain these retained caches or group objects.

Initial AfterLoad also performs project lookups before any click. An
output-application map alone is insufficient: the receipt identifies
`CreateSpecialApplications`, AC zone-group, application115/116, remote-setback
and output/damper/relay group lookup sites. Independent group recovery confirms
that ordinary load preserves any existing damper or relay tag, whereas the
14 plant-output default getters can enter default logic for generated
`[CGnn]` tags. Address255 may require creation of the unused sentinel. Merely
observing a numeric address cannot establish that the original object exists.

A future bounded fresh-form profile could require every consumed application
and group to exist, exact plant-output tags to avoid the default branch, the
unused sentinel to exist, and every surviving installed switched zone to have
an assigned damper. A captured object graph or an explicitly constructed
synthetic project fixture could prove those predicates. Raw PP alone cannot.
Continuing original sessions additionally require explicit damper-cache state.

## Exact next recovery and acceptance work

The next source closure needs these methods and their dispatch/binding sites:

- Generic `TCISAttribute.Changed`, `ResolveChange`, `EndUpdate`,
  `TCustomFlashObject.Changed`/`DoChangeNotification`, object-change
  registration and `TFlashObjectExpressionLink` callbacks. Resolve callback
  ordering while the initialization and click flags are set.
- `TZoneManagerService.Handle*PlantTypeAfterChange`,
  `TThermostat.HandleZoneManagerPlantTypeChange`,
  `TPlantControlService.HandleVentPlantTypeChange` and fan-speed updates,
  unless source-backed profile predicates exclude every such transition.
- `TPlantControlService.UpdateDamperGroups`, `FindExistingGroup`,
  `GetUnusedGroup`, `CreateAndRenameGroup`, all four
  `GetDefaultDamperNOutputGroup` methods and the 14
  `GetDefault*OutputGroupForPlantType` methods, composed with ordinary
  AfterLoad and any relevant group-attribute subscribers.
- `TCBusThermostatCGateAgent.CreateSpecialApplications`,
  `TThermostat.GetACApplicationObject`, `TCBUSApplicationManager`
  `ApplicationByAddress`/`ApplicationByTagName`, `TCBusGroupManager`
  `GroupByAddress`/`GetNextAvailableAddress`, and remote-setback application
  selection in AfterLoad. Define exact metadata and creation/refusal rules.

Then test at least one owned, fresh synthetic project through the whole
declared phase: initial graph → bound form/model → accepted click →
BeforeSave → native database save → fresh reload. Compare dependent scalar
and group state as well as requested masks. Existing PP save/reload evidence
remains persistence evidence, not original quick-zone dialog acceptance.
This slice adds no production action API, no acceptance vectors claiming
original execution, and no completeness promotion.
