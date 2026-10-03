# Thermostat settings

`cbus-toolkit thermostat settings` edits the zone, plant, fan, user-interface and remote-control settings of one closed database thermostat. Remote references are resolved against the complete project graph in the same transaction. It supports PC_TSA/PC_TSA5, which use `THERMOSTATA.xml`, and PC_TSB/PC_TSB5, which use `THERMOSTATB.xml`.

```sh
export CBUS_UNITSPEC_DIR=/private/decoded/unitspec

cbus-toolkit thermostat settings preview //HOME/254/p/4 \
  --set InstalledZones=7 --set ControlledZones=7 --set HeatingPlantStages=2 \
  --host 127.0.0.1 --port 20023 --exclusive-project

cbus-toolkit thermostat settings apply //HOME/254/p/4 \
  --set InstalledZones=7 --set ControlledZones=7 --set HeatingPlantStages=2 \
  --host 127.0.0.1 --port 20023 --exclusive-project --backup-project HOMEBAK
```

## Admitted settings

| Group | Parameters |
| --- | --- |
| Zones | `InstalledZones`, `ControlledZones`, `HeatingPlantInstalledZones`, `CoolingPlantInstalledZones`, `VentingPlantInstalledZones`, `InternalPlantZones`, `MeasuredZones`, `UIAllocatedZones` |
| Plant | `HeatingPlantType`, `CoolingPlantType`, `HeatCoolPlantType`, `VentingPlantType`, `InternalPlantType`, `InternalPlantModes`, `VentPlantType`, `HeatingPlantStages`, `CoolingPlantStages`, `FanOperationMode`, `PlantMinimumOnTime`, `PlantMinimumOffTime`, `PlantCycleTime`, `DamperModulationEnable`, `VariableFanCoilEnable`, `VariableFanCoilTiming`, the five `EvapCooler*Time` values |
| Fans | `Heating`/`CoolingPlantFan` + `SpeedControlEnable`, `Speeds`, `DefaultSpeed`, `OnDelay`, `OffDelay`, `Enable` |
| Interface, PID and offset | the four backlight brightnesses, `BacklightActiveTime`, `BacklightDimTime`, `BeepEnable`, `TemperatureUnits`, `ZoneTemperatureDisplay`, `HeatCoolIntegralFactor`, `HeatCoolDifferentialFactor`, `TemperatureOffset`, `TemperatureSendDifferential` |
| Temperature limits and comfort | `MaximumSetTemperature`, `MinimumSetTemperature`, the six `Guard*Temperature` values, `SetbackLevel`, `EvapStartProportionalTemperature`, `EvapStopProportionalTemperature`, `EvapComfortStartTemp`, `EvapComfortStepSize` |
| THERMOSTATA only | `TimeUnits`, `EvapProgramEnabled`, `NonEvapProgramEnabled`, `SendInterval`, `ScheduleControlledZones` |
| THERMOSTATB only | `TimerEnable` |

Output group and relay addresses use the ordered `--output-group` control below; they are not raw `--set` edits. The separate Load Template workflow also reassigns them ([thermostat-templates.md](thermostat-templates.md)). Raw values are bytes in the unit's own encoding; use [thermostat-temperature.md](thermostat-temperature.md) for temperature conversions.

## Rules

Each value must be a one-byte integer within the range declared by the decoded unit specification; the zone masks are limited to `$00`–`$1F`. Settings that belong to the other family are refused.

The editor checks each edit against the recovered fields of the original form load/save. If this projection would rewrite an edited value, the edit is refused and the error names the value that save would write. Untouched fields in this projection are listed as `dependent_form_save_changes` and **are applied in the same save**. `expected` combines requested and dependent values; `changed_parameters` includes both. The recovered rules are:

- `EvapProgramEnabled` and `NonEvapProgramEnabled` must be 0 or 1. The original load changes a larger Evap value to 0 and a larger NonEvap value to 1.
- Fan on/off delays are loaded as `Round(value / 6)` using banker's rounding, then saved multiplied by 6. Only multiples of 6 survive.
- Cooling fan control is active when `InternalPlantModes` has Cool (bit 2) or Heat/Cool (bit 3), or when `VentPlantType` is 2. Heating fan control is active for Heat (bit 1), Heat/Cool, or `VentPlantType` 1.
- When a master (`ControlledZones` > 0) has cooling but not heating fan control, the heating `SpeedControlEnable`, `Speeds` and `DefaultSpeed` values are copied from the cooling side if the Vent mode (bit 4) is set. Without Vent mode, speed control and speeds are saved as 0. The reverse applies with the sides swapped. In every other case each side keeps its own values if Vent mode is set or the unit is a slave; otherwise its speed control and speeds are saved as 0. A kept speed of 0 is saved as 1 when that side's mode bit is set. Fan delays and `Enable` always come from the side's own values.
- `DamperModulationEnable` is saved as its 0/1 flag multiplied by the factor for the internal plant type: 0 for plant 0, 2 for plant 2, 3 for plants 6 and 10, and 1 for the others. Unit type 8 counts as virtual type 11 when it has cooling or heat-fan outputs.
- The four backlight brightness values pass through the original integer level-to-percent and percent-to-level helpers: `(((raw + 2) * 100) // 255 * 255) // 100`. For example, 1 becomes 2, 128 becomes 127 and 254 becomes 255.
- `BeepEnable`, `VariableFanCoilEnable` and the basic thermostat's `TimerEnable` become 0 or 1. `TemperatureUnits` and programmable `TimeUnits` above 1 become 0. Programmable `SendInterval` above 6 becomes 2.
- A master saves `ControlledZones` from `InstalledZones`; a slave saves it as 0. This comes from the original `GetControlledZones` helper, rather than an inferred mask constraint. An edit to `ControlledZones` on a master must equal the resulting installed mask to survive save.
- A slave saves `InternalPlantType` and `InternalPlantZones` as 0. A master's virtual plant type 11 saves as 8. `EnableHVACRelayDrive` always saves as 0.
- With `RemoteSetbackControlSource=0`, untouched setback group bytes save as `RemoteSetbackOnGroup=30` and `RemoteSetbackOffGroup=31`. Sources 1 and 2 are resolved by the native settings manager as described below; the standalone PP projection has no project graph. Sources 3–255 are refused: original AfterLoad clears their group references, then BeforeSave enters a positive-source branch that dereferences them.
- On programmable units, when normalized Evap and NonEvap program flags are both off, save writes `RemoteScheduleEnable=0` and On/Off/Override groups `32/33/34`. Raw `RemoteScheduleEnable` is ignored during the original load. This includes raw Evap values above 1, which load as off, provided raw NonEvap is zero. Disabling the two admitted program flags therefore includes these untouched dependent writes.

`disabled_remote_defaults.parameters` identifies the disabled branch outputs. The native settings command also resolves enabled references and plans the original getter-created applications/groups. The pure `plan_settings` function remains a PP-only component; the native owner composes it with `plan_remote_references` before any write.

## Remote references

All four unit aliases admit `RemoteSetbackControlSource`, `RemoteSetbackOnGroup` and `RemoteSetbackOffGroup`. Source 0 disables setback and saves groups 30/31. Source 1 resolves groups in the existing scalar `ApplicationNumber` application; the admitted application families are Lighting 48–95 and Enable Control 203. Source 2 resolves groups in Enable Control 203. This numeric mapping follows the original code; the descriptions in the decoded base specifications reverse the two labels. ApplicationNumber itself remains read-only here, and the generic `Application` array does not select these groups.

Programmable aliases additionally admit `RemoteScheduleOnGroup`, `RemoteScheduleOffGroup` and `RemoteScheduleOverrideGroup`. `RemoteScheduleEnable` is derived from the normalized Evap/NonEvap program flags and cannot be edited directly. Disabled scheduling saves 0/32/33/34, but its lookup can still create missing application 203.

```sh
cbus-toolkit thermostat settings preview //HOME/254/p/4 \
  --set RemoteSetbackControlSource=2 \
  --set RemoteSetbackOnGroup=21 --set RemoteSetbackOffGroup=22 \
  --set EvapProgramEnabled=1 \
  --set RemoteScheduleOnGroup=12 --set RemoteScheduleOffGroup=13 \
  --set RemoteScheduleOverrideGroup=14 \
  --host 127.0.0.1 --port 20023 --exclusive-project
```

The plan resolves setback On/Off before schedule On/Off/Override. Existing objects are reused by application and group identity. Missing application 203 is named `Enable Control`; missing Lighting groups are `Group N` and missing Enable groups are `Enable Network Variable N`. An enabled getter can create a real group 255 named `<Unused>`. Disabled schedule lookups never create group 255.

Optional level additions default to decline. Pass `--setback-levels accept` and, for programmable units, `--schedule-levels accept` to create missing addresses 1–31 in the resolved non-unused groups. Both options also accept `decline`. A choice applies only when the enabled feature has missing addresses; complete groups are unchanged. The basic family refuses schedule acceptance. Group 0 is a real target, while group 255 receives no levels.

New levels have Value equal to Address and the recovered `Setbk Enable`, `Setbk Disable`, `Sched Enable`, `Sched Disable` or `Sched Overrd` zone label. Existing levels retain their independent Values, labels, OIDs and other metadata, even when they differ from these defaults. All application/group creation precedes accepted setback levels, followed by accepted schedule levels, with addresses ascending within each role. The preview reports `planned_level_creations` and `remote_references.level_prompts`, including whether each prompt was required and its response used. See the [level source review](thermostat-remote-levels-source.md).

Setback permits one unused role, but requires at least one non-unused role. Every enabled schedule role must be non-unused. Reusing a non-unused object within or across the selected setback/schedule roles is refused. Equal numeric addresses in different applications are distinct objects and are permitted. Validation happens before database writes, even when lookups would have created objects.

Inspect `remote_references.getters`, `resolved_roles`, `remote_validation`, `planned_creations` and the complete project fingerprint. Omit `--set` to preview or apply the current snapshot's bounded load/save normalization and reference/level creation. Requested raw edits precede this projection. It models the final records from accepted or declined optional level prompts, but does not replay modal dialogs, original intermediate storage callbacks or the complete parent lifecycle. Whole-plan validation precedes writes; the original base form can create accepted setback levels before a later validator fails. The CLI does not reproduce that invalid-form mutation history. A lost create or Value/TagName response stops the workflow without replay, deletion or a later target save. See the [remote-reference source review](thermostat-remote-references-source.md).

This is exactly one projected load/save, not repeated normalization. With a master, Cool+Vent modes, VentPlantType 0 and both fan speeds 0, the first save writes heating 0/cooling 1. A later explicit save writes heating 1/cooling 1. Similarly, a slave's plant is cleared while its damper factor still uses the loaded plant model. The command never adds hidden saves to reach a fixed point.

`dialog_rule_subset` reports recovered individual enable, visibility and quick-zone rules. Quick-zone state is the union/intersection of UI, internal plant, measured, heating/cooling/venting installed masks, plus schedule-controlled zones for programmable units. Neither `InstalledZones` nor the zone manager's `ControlledZones` is a source of that state. The report includes per-zone enable masks, allowed plant modes, basic-only hidden controls, and fan/evaporative action enables. Its isolated Vent fallback is diagnostic only, because an original form guard can suppress it.

The pure Python `quick_zone_transition(values, family, zone, include, ...)` helper in `thermostat_settings_guard` reproduces one accepted quick-zone checkbox action, including its cross-control mask changes and last-zone refusal. Zone 0 removal requires the explicit accepted-prompt argument. It does no I/O and is separate from raw `--set` admission. See the [source recovery notes](../research/experiments/2026-09-30/thermostat-settings-form-static.md).

Complete dialog event ordering, parent visibility and control-to-raw-edit admission remain open: `dialog_enable_rules_reproduced` and `complete_form_lifecycle_reproduced` remain false. Raw edits are applied before the projected load; its master/slave state comes from that edited snapshot. This is not the retained master state of an already open GUI form. The quick-zone helper alone is not a complete save workflow: original installed-zone events can allocate damper groups, and plant-zone events can clear plant types and cascade into fan changes. See the [event recovery receipt](../research/experiments/2026-09-30/thermostat-quick-zone-events-static.json).

The later [core runtime receipt](../research/experiments/2026-09-30/thermostat-quick-zone-core-original.json) executes one original `IncludeZone(1)` in declared synthetic objects: used/UI/internal/measured/schedule masks change from 1 to 3, installed/controlled masks stay 3, and the three plant-installed masks stay 1. The actual UI, plant, measurement and schedule handlers call `TThermostat.HandleZoneChange` and the guarded quick-options refresh in that order. It covers 76 original methods, 15,840 original instruction events and 1,273 unique instructions. Only owned uncontended locks and Boolean variant cleanup use explicit ABI adapters. This is core-model evidence; constructors, GUI subscribers, workspace, parent-enable callbacks and PP load/save are absent.

That earlier synthetic graph is not the freshly initialized programmable graph. The [constructor receipt](../research/experiments/2026-09-30/thermostat-quick-zone-constructor-static.json) pins 29 checks, 47 methods and 130 model attribute declarations. Programmable construction uses `TAdvancedUIService`; its virtual hook overrides install the two program-flag callbacks without the inherited UI zone callback. Fresh `UsedZones` starts at zero, and initial Templates binding suppresses its recomputation. The displayed union of zone masks therefore does not prove an initial model `UsedZones=1`.

The [corrected AdvancedUI runtime receipt](../research/experiments/2026-09-30/thermostat-quick-zone-advanced-ui-core-original.json) executes actual AdvancedUI HookEvents, the include helper and UnhookEvents over a declared prepared graph. It produces `UsedZones: 0→2`, UI/internal/measured/schedule `1→3`, and only the plant/measurement/schedule callbacks. Installed and controlled masks remain 3. Its single network-denied run exited successfully after 15,926 original instruction events across 77 method spans, with no writes outside owned state. This refines the core evidence; constructor execution, initial GUI binding, Windows message ordering and PP load/save remain excluded.

The [historical launch record](../research/experiments/2026-09-30/thermostat-quick-zone-advanced-ui-launch.json) preserves the exact successful outer command, interpreter, inline network-denial profile and exit log. No profile file was used. This records the accepted harness execution; it does not authorize a new launch or establish other harnesses' runtime acceptance.

The [callback receipt](../research/experiments/2026-09-30/thermostat-quick-zone-callback-static.json) adds 37 source checks over 44 methods and 3 DFM resources. Changed zone-checkbox refreshes suppress Click, controller refresh locks Apply, and list/root combo notifications defer population until another user gesture. Those barriers do not prove that every initialized GUI callback or queued message is harmless.

The [seven-panel binding receipt](../research/experiments/2026-09-30/thermostat-quick-zone-gui-binding-static.md) extends that boundary with 44 checks over 69 method spans, 83 Prepare sites and seven DFM resources. All 13 element combos use immediate Apply, so those prepared controllers do not defer a model assignment until blur. Focus can still populate a combo, and changed native text can dispatch its notification path. Parent enable propagation is source-pinned; the candidate's Celsius minimum 15, maximum 32 and unchecked guard take the temperature slider handlers' no-write branches. These conditional facts do not establish an initialized native control state or an empty Windows message queue.

The [initialization receipt](../research/experiments/2026-09-30/thermostat-quick-zone-initialization-static.json) adds 96 source checks over 59 methods and 3 DFM resources. A [native seed capture](../research/experiments/2026-09-30/thermostat-quick-zone-native-seed.json) provides 123 raw PP fields and a synthetic closed project after native save/reload, with existing applications 56/115/116/172/203 and unused groups 56/255,172/255,203/255. It uses `ApplicationNumber=56`, disabled remote schedule/setback, remote group bytes 30/31/32/33/34, actual `MasterNetworkAddress=254`, Celsius fixed-point temperatures and active brightness 201. This independently verifies candidate storage, not an original AfterLoad execution or a joined quick-zone/save workflow.

The smallest remaining runtime prerequisite is an original ready-form state around that candidate: controller activation, native control text/selection/focus and the provenance/order of applicable notifications or already-posted messages. Relevant source boundaries are `TCBusThermostatCGateAgent.AfterLoadProgrammingInformation` (`0x128e06c`), programmable AfterLoad (`0x12994d0`), the inherited unit preamble and the seven programmable panels. The plant combo's `cmbInternalPlantTypeChange` (`0x11221fc`) posts message `0x423`; `HandlePlantTypeChange` (`0x11221c8`) dispatches its `+0x460` callback to `TcdThermostatPlant.HandleInternalPlantTypeAfterChange` (`0x112947c`). This callback reads plant state at dispatch time and can change parameters and groups. A complete candidate must establish that no applicable message is pending, or execute it and admit its effects, before joining original BeforeSave and save/reload. The available pinned EXE/MAP can support static investigation without household hardware; the prepared emulator graph does not supply a running initialized Delphi form by itself.

## Output-group controls

`--output-group PARAMETER=ADDRESS` selects an existing group after ordinary
thermostat model loading. Repeat it in the intended control order, including
repeated parameters. `--resolve-output-groups` runs that load without an explicit
selection. `--output-operation JSON` adds an ordered select or accepted/cancelled
Add outcome and can be interleaved with `--output-group`. Omitting all output
options retains the earlier bounded remote-only graph
projection. All selected and saved values must fit the decoded specification.

```sh
cbus-toolkit thermostat settings preview //HOME/254/p/4 \
  --output-group CoolFanLowOutput=255 \
  --output-group CoolFanMediumOutput=20 \
  --output-group CoolFanLowOutput=21 \
  --host 127.0.0.1 --port 20023 --exclusive-project
```

That history swaps current low/medium groups 20/21 through unused group 255.
A direct first selection of 21 is refused while the medium selector uses it.
Each selection must refer to a group present after loading or created by an
earlier accepted Add. See [typed output Add](thermostat-output-add.md) for its
exact JSON records, naming rules and cancellation behavior. The exact field
names are:

| Controls | Parameters |
| --- | --- |
| Cooling and heating | `Cool`/`Heat` + `ActivationOutput`, `Stage1Output`–`Stage3Output`, `FanLowOutput`, `FanMediumOutput`, `FanHighOutput` |
| Dampers | `DamperZone1Output`–`DamperZone4Output` |
| Internal relays | `InternalRelay1GroupNumber`–`InternalRelay5GroupNumber` |

Loading first resolves application 172 (`Air Conditioning`) and `ZoneGroup`
(`Communication Group N`, or `<Unused>` for 255), preserving existing names.
It binds the scalar `ApplicationNumber`, independently of generic `Application`,
then resolves setback references, fourteen outputs, four dampers, five relays,
and programmable schedule references in that order. The bounded output profile
admits applications 48–95 or 203. Missing application 56 is `Lighting`, 95 is
`DALI`, 203 is `Enable Control`, and other admitted application names are their
decimal address. This range is a CLI boundary, not a recovered GUI filter.

A manually named output group is retained. An automatically named group with
this unit's `[CGnn]` prefix can be renamed using the loaded plant/installation.
A missing source address can reuse a uniquely matching generated name elsewhere
or create a group at the source address. Ambiguous generated names and consumed
non-ASCII name searches are refused because original manager/locale ordering is
not established. This path does not use template allocation or infer manager
order from XML. Loading effects remain in the transaction even when a later
selection chooses another group.

The selected control must be enabled in the loaded model. Cooling and heating
use their recovered plant gates; heat fans are disabled for virtual plant 8.
Dampers are programmable-only and require a nonzero plant plus an internal
plant zone among zones 1–4. Internal relays are visible only on PC_TSA5/PC_TSB5
and enabled only for a loaded master. Cooling, heating and dampers each reject
repeated non-unused identities within their own collection. Sharing across
collections is allowed; relays have no uniqueness rule. A programmable slave
can admit a damper selection but saves its address as 255. The plan reports the
selection and the saved value separately.

Inspect `output_projection`, `planned_renames` and ordered `graph_operations`.
All load effects and selections share one existing save owner with remote
references and optional levels. A rename checks the current OID and previous
TagName immediately before one OID-addressed write. A lost reply stops without
retry, rollback, deletion or a later save. Whole-project verification permits
only planned renames and creations, while preserving all retained metadata.
The [source annex](thermostat-output-groups-source.md) describes this component
projection. [Typed Add outcomes](thermostat-output-add.md) extend this ordered
history on the same graph and save owner. Accepted/cancelled
[output Edit outcomes](thermostat-output-edit.md) also interleave in that
history: they rename the currently selected non-unused object without changing
its address or identity. An omitted name retains the complete preloaded text;
explicit replacements use the original 32 UTF-16 entry limit before trimming.
Zone history, application changes, template callbacks and complete initialized
GUI behavior remain separate work. The recovered thermostat combo action
mask exposes Add/Edit; generic Delete/Clear methods are not visible controls.

## Temperature preference

Pass `--temperature-preference celsius` or `--temperature-preference fahrenheit` to reproduce the 15 recovered temperature fields' untouched load/save normalization. This is the original **Toolkit process preference**, independent of the thermostat's `TemperatureUnits` PP setting. Without this option, all temperature fields retain raw PP semantics and the plan reports `temperature_normalization.reproduced=false`.

```sh
cbus-toolkit thermostat settings preview //HOME/254/p/4 \
  --set PlantCycleTime=20 --temperature-preference fahrenheit \
  --host 127.0.0.1 --port 20023 --exclusive-project
```

The projection reproduces the original field-specific conversion pairs and byte casts. Setpoint limits use simple whole-degree conversions. Six guard fields use shifted quarter-degree conversions; only `GuardUpperTemperature` and `GuardMaximumUpperTemperature` receive the additional upper clamp of 127. Setback, evaporative proportional temperatures, measurement offset/differential and UI comfort values use their respective original helpers. Signed fields load as signed bytes and save through the original low-byte cast. `TemperatureSendDifferential`, `EvapComfortStartTemp` and `EvapComfortStepSize` use plain integers without an implicit byte cast.

For example, untouched `TemperatureOffset=3` saves as 4 with Celsius or 5 with Fahrenheit, while raw 128 is signed −128 and saves as byte 129. `TemperatureSendDifferential=128` is unsigned and saves as 127. Some comfort conversions produce 256 (for example raw 255); the planner refuses a result outside the unit specification or byte range rather than wrapping it. Requested values must survive the selected conversion, and every dependent result is checked before staging.

## Apply

`preview` reads the complete project XML and a read-only PP snapshot. `apply` rechecks the unit, all PP values and the complete graph, and returns `already_applied` only if both PP and graph changes are empty. Otherwise it saves and copies the project to a backup, creates and renames references in the planned order, stages changed parameters in one PP session and verifies them. Parameter changes use one `PP SAVE_TO_SOURCE`; graph-only changes use none. Both paths issue one final target `PROJECT SAVE`, then close/reload and verify fresh PP plus complete graph preservation. The backup source save is counted separately.

Every existing object identity, unrelated parameter and opaque project/network/unit/application/group/level field is preserved; only explicitly planned group names may change. New objects' metadata is bound immediately after creation and checked after reload. The comparison permits only the documented regenerated project Config OIDs, selected-unit PP record ordering by unique Name, and absent/empty Level TagsDLT equivalence. Every project network must be closed with synchronization idle, and `--exclusive-project` is required. The selected unit's firmware must fit the caller's decoded base specification.

Plans are immutable, manager-issued and single-use. The command performs no automatic retry or rollback; database creation, PP save and project save are separate operations. Inspect `objects`, `renames`, `graph_operations`, `pp_save_*`, `target_save_*`, backup attempt fields and `outcome_uncertain` after a failure. A failed transaction can leave confirmed new graph objects or an uncertain saved result; review the actual state before making a fresh plan.

The Python API is `NativeThermostatSettings(client, UnitSpecStore(spec_dir)).plan(path, edits, exclusive_project=True, temperature_preference='fahrenheit')` followed by `apply(plan, backup_project=...)`; the offline planner is `plan_settings`. The preference is optional and bound to the immutable plan.

## Evidence and limits

- **Original source.** Fresh pinned EXE/MAP inspection covers [13 scalar routines](../research/experiments/2026-09-30/thermostat-settings-save-static.json) and [25 dialog methods](../research/experiments/2026-09-30/thermostat-settings-form-static.json). Literal vectors independently check brightness, fan ordering and quick-zone transitions. This inspects original code; it does not execute the original form.
- **Offline tests.** Focused synthetic-specification tests cover requested/dependent ownership, one-save ordering, malformed dependencies, scalar boundaries and the recovered dialog helpers.
- **Earlier packaged check.** The [first slice acceptance receipt](../research/experiments/2026-09-30/thermostat-form-focused-acceptance.json) records the prior context-independent implementation and its package hashes. It predates temperature normalization and the `ControlledZones` correction.
- **Native acceptance.** Owned C-Gate 3.4.0.2001 passed four tests: [normalization receipt](../research/experiments/2026-09-30/thermostat-settings-normalization-native.json).
  - One PC_TSA unit and one PC_TSB unit each received 16 common edits, including zone masks and 0/31/255 boundaries, plus their family-specific settings.
  - After save, close and reload every requested/dependent value read back as planned and every other parameter was preserved.
  - PC_TSA, PC_TSA5, PC_TSB and PC_TSB5 each received seeded untouched normalization cases with literal source-derived first-save expectations. A second explicit save reproduced the heating/cooling copy ordering, then a third plan was a no-op.
  - A hidden PP record injected only into the returned XML after a real save/reload failed preservation verification even though the PP snapshot matched.
  - The test refused an out-of-range zone mask, family-foreign settings, a fan delay the form save would round, an Evap value the load would normalise and an output-group edit, and the project was unchanged after each refusal.
  - No CNI connection occurred.
- **Temperature source and arithmetic.** The [temperature source receipt](../research/experiments/2026-09-30/thermostat-settings-temperature-static.json) pins 87 checks over 64 routines. Independent composition of previously captured original conversion results covers every byte and both preferences for all 15 fields (7,680 comparisons); production conversion code did not generate the expected vectors. This recovers call sites, signed loads, two upper clamps, setters and model ranges; it does not execute the entire original form.
- **Temperature and mask persistence.** The [new native receipt](../research/experiments/2026-09-30/thermostat-settings-temperature-native.json) records public CLI preview/apply for all four unit aliases with both preferences, deliberately opposite device `TemperatureUnits`, untouched dependent changes, save/reload and preservation. All eight temperature cases saved correctly and preview did not write. The owned C-Gate sentinel received no hardware connection.
- **Earlier temperature packaged check.** The [temperature acceptance receipt](../research/experiments/2026-09-30/thermostat-temperature-focused-acceptance.json) records 45 passing offline tests (598 subtests) and five passing native tests. A fresh installed wheel passed the same 45 offline and five native tests; all 258 package files matched source and installation. No selected test skipped and no full suite ran.
- **Disabled remote saves.** The [source receipt](../research/experiments/2026-09-30/thermostat-remote-save-static.json) pins 129 checks over 20 methods and nine independent branch examples. The [focused acceptance receipt](../research/experiments/2026-09-30/thermostat-disabled-remotes-focused-acceptance.json) records 50 offline tests with 618 subtests and seven owned native tests. Public CLI parsing/dispatch covers all four aliases, unrelated PP and group preservation, one save/reload followed by a no-op, and invalid-source refusal without writes. No CNI connection occurred. Packaging was unchanged and no new wheel or full suite was run for this slice.
- **Typed output Add.** Accepted Add and direct cancellation interleave with existing selections after ordinary loading. The [operator workflow](thermostat-output-add.md) distinguishes static source rules, exact name transport, complete preflight and owned backend validation from deferred original/native or physical acceptance. All effects remain inside this settings owner.
- **Typed output Edit.** Accepted Edit and direct cancellation target the selected non-unused group within the same ordered history. The [operator guide](thermostat-output-edit.md) covers omitted/preloaded names, explicit input limits, duplicate exclusion, quoted TagName storage and the explicit owned same-name no-op projection. Address, identity and reference assignments remain intact.
- **Open.** Complete dialog lifecycle and edit admission, initialization group/application effects outside the bounded remote getters, an exposed quick-zone save workflow, application-change controls, the remaining Toolkit tabs and physical thermostats. Generic output Delete/Clear are not exposed by the recovered thermostat action mask. Template post-load replay has its separate evidence and limits.
