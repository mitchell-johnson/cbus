# Thermostat settings

`cbus-toolkit thermostat settings` edits the zone, plant, fan and user-interface settings of one closed database thermostat at PP level. It supports PC_TSA/PC_TSA5, which use `THERMOSTATA.xml`, and PC_TSB/PC_TSB5, which use `THERMOSTATB.xml`.

```sh
export CBUS_UNITSPEC_DIR=/private/decoded/unitspec

cbus-toolkit thermostat settings preview //HOME/254/p/4 \
  --set ControlledZones=7 --set HeatingPlantStages=2 \
  --host 127.0.0.1 --port 20023 --exclusive-project

cbus-toolkit thermostat settings apply //HOME/254/p/4 \
  --set ControlledZones=7 --set HeatingPlantStages=2 \
  --host 127.0.0.1 --port 20023 --exclusive-project --backup-project HOMEBAK
```

## Admitted settings

| Group | Parameters |
| --- | --- |
| Zones | `InstalledZones`, `ControlledZones`, `HeatingPlantInstalledZones`, `CoolingPlantInstalledZones`, `VentingPlantInstalledZones`, `InternalPlantZones`, `MeasuredZones`, `UIAllocatedZones` |
| Plant | `HeatingPlantType`, `CoolingPlantType`, `HeatCoolPlantType`, `VentingPlantType`, `InternalPlantType`, `InternalPlantModes`, `VentPlantType`, `HeatingPlantStages`, `CoolingPlantStages`, `FanOperationMode`, `PlantMinimumOnTime`, `PlantMinimumOffTime`, `PlantCycleTime`, `DamperModulationEnable`, `VariableFanCoilEnable`, `VariableFanCoilTiming`, the five `EvapCooler*Time` values |
| Fans | `Heating`/`CoolingPlantFan` + `SpeedControlEnable`, `Speeds`, `DefaultSpeed`, `OnDelay`, `OffDelay`, `Enable` |
| Interface, PID and offset | the four backlight brightnesses, `BacklightActiveTime`, `BacklightDimTime`, `BeepEnable`, `TemperatureUnits`, `ZoneTemperatureDisplay`, `HeatCoolIntegralFactor`, `HeatCoolDifferentialFactor`, `TemperatureOffset`, `TemperatureSendDifferential` |
| THERMOSTATA only | `TimeUnits`, `EvapProgramEnabled`, `NonEvapProgramEnabled`, `SendInterval`, `ScheduleControlledZones` |
| THERMOSTATB only | `TimerEnable` |

Output group and relay addresses are not admitted, because they refer to project groups. The Load Template workflow reassigns them ([thermostat-templates.md](thermostat-templates.md)). Raw values are bytes in the unit's own encoding; use [thermostat-temperature.md](thermostat-temperature.md) for temperature conversions.

## Rules

Each value must be a one-byte integer within the range declared by the decoded unit specification; the zone masks are limited to `$00`–`$1F`. Settings that belong to the other family are refused.

The editor checks each edit against the recovered context-independent fields of the original form load/save. If this projection would rewrite an edited value, the edit is refused and the error names the value that save would write. Untouched fields in this projection are listed as `dependent_form_save_changes` and **are applied in the same save**. `expected` combines requested and dependent values; `changed_parameters` includes both. The recovered rules are:

- `EvapProgramEnabled` and `NonEvapProgramEnabled` must be 0 or 1. The original load changes a larger Evap value to 0 and a larger NonEvap value to 1.
- Fan on/off delays are loaded as `Round(value / 6)` using banker's rounding, then saved multiplied by 6. Only multiples of 6 survive.
- Cooling fan control is active when `InternalPlantModes` has Cool (bit 2) or Heat/Cool (bit 3), or when `VentPlantType` is 2. Heating fan control is active for Heat (bit 1), Heat/Cool, or `VentPlantType` 1.
- When a master (`ControlledZones` > 0) has cooling but not heating fan control, the heating `SpeedControlEnable`, `Speeds` and `DefaultSpeed` values are copied from the cooling side if the Vent mode (bit 4) is set. Without Vent mode, speed control and speeds are saved as 0. The reverse applies with the sides swapped. In every other case each side keeps its own values if Vent mode is set or the unit is a slave; otherwise its speed control and speeds are saved as 0. A kept speed of 0 is saved as 1 when that side's mode bit is set. Fan delays and `Enable` always come from the side's own values.
- `DamperModulationEnable` is saved as its 0/1 flag multiplied by the factor for the internal plant type: 0 for plant 0, 2 for plant 2, 3 for plants 6 and 10, and 1 for the others. Unit type 8 counts as virtual type 11 when it has cooling or heat-fan outputs.
- The four backlight brightness values pass through the original integer level-to-percent and percent-to-level helpers: `(((raw + 2) * 100) // 255 * 255) // 100`. For example, 1 becomes 2, 128 becomes 127 and 254 becomes 255.
- `BeepEnable`, `VariableFanCoilEnable` and the basic thermostat's `TimerEnable` become 0 or 1. `TemperatureUnits` and programmable `TimeUnits` above 1 become 0. Programmable `SendInterval` above 6 becomes 2.
- A slave saves `InternalPlantType` and `InternalPlantZones` as 0. A master's virtual plant type 11 saves as 8. `EnableHVACRelayDrive` always saves as 0.

This is exactly one projected load/save, not repeated normalization. With a master, Cool+Vent modes, VentPlantType 0 and both fan speeds 0, the first save writes heating 0/cooling 1. A later explicit save writes heating 1/cooling 1. Similarly, a slave's plant is cleared while its damper factor still uses the loaded plant model. The command never adds hidden saves to reach a fixed point.

`dialog_rule_subset` reports recovered individual enable, visibility and quick-zone rules. Quick-zone state is the union/intersection of UI, internal plant, measured, heating/cooling/venting installed masks, plus schedule-controlled zones for programmable units. Neither `InstalledZones` nor the zone manager's `ControlledZones` is a source of that state. The report includes per-zone enable masks, allowed plant modes, basic-only hidden controls, and fan/evaporative action enables. Its isolated Vent fallback is diagnostic only, because an original form guard can suppress it.

The pure Python `quick_zone_transition(values, family, zone, include, ...)` helper in `thermostat_settings_guard` reproduces one accepted quick-zone checkbox action, including its cross-control mask changes and last-zone refusal. Zone 0 removal requires the explicit accepted-prompt argument. It does no I/O and is separate from raw `--set` admission. See the [source recovery notes](../research/experiments/2026-09-30/thermostat-settings-form-static.md).

Complete dialog event ordering, parent visibility and control-to-raw-edit admission remain open: `dialog_enable_rules_reproduced` and `complete_form_lifecycle_reproduced` remain false. The editor does not invent a mask-subset constraint against `InstalledZones`. Temperature-offset/differential normalization also remains open because the original helpers consume a separate Toolkit process temperature preference that this command does not receive. Those fields retain raw PP semantics.

## Apply

`preview` reads the unit XML and one read-only PP snapshot. `apply` rechecks both and returns `already_applied` only if neither requested nor dependent values change. Otherwise it saves and copies the project to a backup, sets the changed parameters in one PP session, compares the staged values and issues one `PP SAVE_TO_SOURCE` and one target `PROJECT SAVE`. It then closes and reloads the project and verifies the result in a fresh session. All expected values must match, every other parameter and stored PP record must be unchanged, and the network inventory, unit identity and non-PP XML must be preserved. The command makes no retry and no rollback. The `pp_save_*`, `target_save_*` and `outcome_uncertain` fields identify an interrupted save. Every project network must be closed with synchronization idle, and `--exclusive-project` is required.

The Python API is `NativeThermostatSettings(client, UnitSpecStore(spec_dir)).plan(path, edits, exclusive_project=True)` followed by `apply(plan, backup_project=...)`; the offline planner is `plan_settings`.

## Evidence and limits

- **Original source.** Fresh pinned EXE/MAP inspection covers [13 scalar routines](../research/experiments/2026-09-30/thermostat-settings-save-static.json) and [25 dialog methods](../research/experiments/2026-09-30/thermostat-settings-form-static.json). Literal vectors independently check brightness, fan ordering and quick-zone transitions. This inspects original code; it does not execute the original form.
- **Offline tests.** Focused synthetic-specification tests cover requested/dependent ownership, one-save ordering, malformed dependencies, scalar boundaries and the recovered dialog helpers.
- **Packaged check.** The [focused acceptance receipt](../research/experiments/2026-09-30/thermostat-form-focused-acceptance.json) records 39 source tests with 62 subtests and seven native tests; a fresh installed wheel passed the same 39 offline and seven native tests. All 258 package files matched the source. No selected tests skipped and no full suite ran.
- **Native acceptance.** Owned C-Gate 3.4.0.2001 passed four tests: [normalization receipt](../research/experiments/2026-09-30/thermostat-settings-normalization-native.json).
  - One PC_TSA unit and one PC_TSB unit each received 16 common edits, including zone masks and 0/31/255 boundaries, plus their family-specific settings.
  - After save, close and reload every requested/dependent value read back as planned and every other parameter was preserved.
  - PC_TSA, PC_TSA5, PC_TSB and PC_TSB5 each received seeded untouched normalization cases with literal source-derived first-save expectations. A second explicit save reproduced the heating/cooling copy ordering, then a third plan was a no-op.
  - A hidden PP record injected only into the returned XML after a real save/reload failed preservation verification even though the PP snapshot matched.
  - The test refused an out-of-range zone mask, family-foreign settings, a fan delay the form save would round, an Evap value the load would normalise and an output-group edit, and the project was unchanged after each refusal.
  - No CNI connection occurred.
- **Open.** Complete dialog lifecycle and edit admission, preference-dependent normalization, an exposed quick-zone save workflow, output-group editing, the remaining Toolkit tabs and physical thermostats. Template post-load replay has its separate evidence and limits.
