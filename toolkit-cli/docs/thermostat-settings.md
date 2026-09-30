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

The editor also checks each edit against the recovered original form save (`BeforeSaveProgrammingInformation`, see [thermostat-templates.md](thermostat-templates.md)). If the next Toolkit save would rewrite an edited value, the edit is refused and the error names the value that save would write. Other fields that save would rewrite are listed as `dependent_form_save_changes`. The recovered rules are:

- `EvapProgramEnabled` and `NonEvapProgramEnabled` must be 0 or 1. The original load changes a larger Evap value to 0 and a larger NonEvap value to 1.
- Fan on/off delays are loaded as `Round(value / 6)` using banker's rounding, then saved multiplied by 6. Only multiples of 6 survive.
- Cooling fan control is active when `InternalPlantModes` has Cool (bit 2) or Heat/Cool (bit 3), or when `VentPlantType` is 2. Heating fan control is active for Heat (bit 1), Heat/Cool, or `VentPlantType` 1.
- When a master (`ControlledZones` > 0) has cooling but not heating fan control, the heating `SpeedControlEnable`, `Speeds` and `DefaultSpeed` values are copied from the cooling side if the Vent mode (bit 4) is set. Without Vent mode, speed control and speeds are saved as 0. The reverse applies with the sides swapped. In every other case each side keeps its own values if Vent mode is set or the unit is a slave; otherwise its speed control and speeds are saved as 0. A kept speed of 0 is saved as 1 when that side's mode bit is set. Fan delays and `Enable` always come from the side's own values.
- `DamperModulationEnable` is saved as its 0/1 flag multiplied by the factor for the internal plant type: 0 for plant 0, 2 for plant 2, 3 for plants 6 and 10, and 1 for the others. Unit type 8 counts as virtual type 11 when it has cooling or heat-fan outputs.

The original dialogs' enable, visibility and cross-control rules are not reproduced. For example, the editor does not check zone masks against `InstalledZones`.

## Apply

`preview` reads the unit XML and one read-only PP snapshot. `apply` rechecks both and returns `already_applied` if no value changes. Otherwise it saves and copies the project to a backup, sets only the changed parameters in one PP session, compares the staged values and issues one `PP SAVE_TO_SOURCE` and one target `PROJECT SAVE`. It then closes and reloads the project and verifies the result in a fresh session. The edits must match, every other parameter must be unchanged, and the unit identity and non-PP XML must be preserved. The command makes no retry and no rollback. The `pp_save_*`, `target_save_*` and `outcome_uncertain` fields identify an interrupted save. Every project network must be closed with synchronization idle, and `--exclusive-project` is required.

The Python API is `NativeThermostatSettings(client, UnitSpecStore(spec_dir)).plan(path, edits, exclusive_project=True)` followed by `apply(plan, backup_project=...)`; the offline planner is `plan_settings`.

## Evidence and limits

- **Offline tests.** Three tests with six subtests use a synthetic specification (`tests/test_thermostat_settings.py`).
- **Native acceptance.** Owned C-Gate 3.4.0.2001 passed two tests: [receipt](../research/experiments/2026-09-30/thermostat-settings-native-acceptance.json).
  - One PC_TSA unit and one PC_TSB unit each received 16 common edits, including zone masks and 0/31/255 boundaries, plus their family-specific settings.
  - After save, close and reload every edit read back unchanged and every other parameter was preserved. A second plan was a no-op.
  - The test refused an out-of-range zone mask, family-foreign settings, a fan delay the form save would round, an Evap value the load would normalise and an output-group edit, and the project was unchanged after each refusal.
  - No CNI connection occurred.
- **Open.** Dialog enable rules, output-group editing, the remaining Toolkit tabs and physical thermostats.
