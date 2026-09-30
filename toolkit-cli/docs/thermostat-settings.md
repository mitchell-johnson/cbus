# Thermostat settings

`cbus-toolkit thermostat settings` edits the zone, plant, fan and user-interface settings of one closed database thermostat at PP level. It supports PC_TSA/PC_TSA5, which use `THERMOSTATA.xml`, and PC_TSB/PC_TSB5, which use `THERMOSTATB.xml`.

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

Output group and relay addresses are not admitted, because they refer to project groups. The Load Template workflow reassigns them ([thermostat-templates.md](thermostat-templates.md)). Raw values are bytes in the unit's own encoding; use [thermostat-temperature.md](thermostat-temperature.md) for temperature conversions.

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

This is exactly one projected load/save, not repeated normalization. With a master, Cool+Vent modes, VentPlantType 0 and both fan speeds 0, the first save writes heating 0/cooling 1. A later explicit save writes heating 1/cooling 1. Similarly, a slave's plant is cleared while its damper factor still uses the loaded plant model. The command never adds hidden saves to reach a fixed point.

`dialog_rule_subset` reports recovered individual enable, visibility and quick-zone rules. Quick-zone state is the union/intersection of UI, internal plant, measured, heating/cooling/venting installed masks, plus schedule-controlled zones for programmable units. Neither `InstalledZones` nor the zone manager's `ControlledZones` is a source of that state. The report includes per-zone enable masks, allowed plant modes, basic-only hidden controls, and fan/evaporative action enables. Its isolated Vent fallback is diagnostic only, because an original form guard can suppress it.

The pure Python `quick_zone_transition(values, family, zone, include, ...)` helper in `thermostat_settings_guard` reproduces one accepted quick-zone checkbox action, including its cross-control mask changes and last-zone refusal. Zone 0 removal requires the explicit accepted-prompt argument. It does no I/O and is separate from raw `--set` admission. See the [source recovery notes](../research/experiments/2026-09-30/thermostat-settings-form-static.md).

Complete dialog event ordering, parent visibility and control-to-raw-edit admission remain open: `dialog_enable_rules_reproduced` and `complete_form_lifecycle_reproduced` remain false. Raw edits are applied before the projected load; its master/slave state comes from that edited snapshot. This is not the retained master state of an already open GUI form. The quick-zone helper alone is not a complete save workflow: original installed-zone events can allocate damper groups, and plant-zone events can clear plant types and cascade into fan changes. See the [event recovery receipt](../research/experiments/2026-09-30/thermostat-quick-zone-events-static.json).

The later [core runtime receipt](../research/experiments/2026-09-30/thermostat-quick-zone-core-original.json) executes one original `IncludeZone(1)` in declared synthetic objects: used/UI/internal/measured/schedule masks change from 1 to 3, installed/controlled masks stay 3, and the three plant-installed masks stay 1. The actual UI, plant, measurement and schedule handlers call `TThermostat.HandleZoneChange` and the guarded quick-options refresh in that order. It covers 76 original methods, 15,840 original instruction events and 1,273 unique instructions. Only owned uncontended locks and Boolean variant cleanup use explicit ABI adapters. This is core-model evidence; constructors, GUI subscribers, workspace, parent-enable callbacks and PP load/save are absent.

The [callback receipt](../research/experiments/2026-09-30/thermostat-quick-zone-callback-static.json) adds 37 source checks over 44 methods and 3 DFM resources. Changed zone-checkbox refreshes suppress Click, controller refresh locks Apply, and list/root combo notifications defer population until another user gesture. Those barriers do not prove that every initialized GUI callback or queued message is harmless.

The [initialization receipt](../research/experiments/2026-09-30/thermostat-quick-zone-initialization-static.json) adds 96 source checks over 59 methods and 3 DFM resources. A [native seed capture](../research/experiments/2026-09-30/thermostat-quick-zone-native-seed.json) provides 123 raw PP fields and a synthetic closed project after native save/reload, with existing applications 56/115/116/172/203 and unused groups 56/255,172/255,203/255. It uses `ApplicationNumber=56`, disabled remote schedule/setback, remote group bytes 30/31/32/33/34, actual `MasterNetworkAddress=254`, Celsius fixed-point temperatures and active brightness 201. This independently verifies candidate storage, not an original AfterLoad execution or a joined quick-zone/save workflow.

The smallest remaining runtime prerequisite is to build the source-derived initialized form around that candidate and keep its bound controls and queued-message state. Relevant source boundaries are `TCBusThermostatCGateAgent.AfterLoadProgrammingInformation` (`0x128e06c`), programmable AfterLoad (`0x12994d0`), the inherited unit preamble and the seven programmable panels. The plant combo's `cmbInternalPlantTypeChange` (`0x11221fc`) posts message `0x423`; `HandlePlantTypeChange` (`0x11221c8`) dispatches its `+0x460` callback to `TcdThermostatPlant.HandleInternalPlantTypeAfterChange` (`0x112947c`). That custom path, parent enable propagation and original BeforeSave must be closed before exposing the action. The available pinned EXE/MAP and confined emulator can investigate these boundaries without household hardware; they do not supply a running initialized Delphi form by themselves.

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

`preview` reads the unit XML and one read-only PP snapshot. `apply` rechecks both and returns `already_applied` only if neither requested nor dependent values change. Otherwise it saves and copies the project to a backup, sets the changed parameters in one PP session, compares the staged values and issues one `PP SAVE_TO_SOURCE` and one target `PROJECT SAVE`. It then closes and reloads the project and verifies the result in a fresh session. All expected values must match, every other parameter and stored PP record must be unchanged, and the network inventory, unit identity and non-PP XML must be preserved. The command makes no retry and no rollback. The `pp_save_*`, `target_save_*` and `outcome_uncertain` fields identify an interrupted save. Every project network must be closed with synchronization idle, and `--exclusive-project` is required.

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
- **Current packaged check.** The [temperature acceptance receipt](../research/experiments/2026-09-30/thermostat-temperature-focused-acceptance.json) records 45 passing offline tests (598 subtests) and five passing native tests. A fresh installed wheel passed the same 45 offline and five native tests; all 258 package files matched source and installation. No selected test skipped and no full suite ran.
- **Open.** Complete dialog lifecycle and edit admission, initialization group/application effects, an exposed quick-zone save workflow, output-group editing, the remaining Toolkit tabs and physical thermostats. Template post-load replay has its separate evidence and limits.
