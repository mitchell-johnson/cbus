# Toolkit 1.18 thermostat Load Template: static review

Scope: issue #42 (P5.05), the thermostat "Load Template" workflow. This static review did not execute any vendor code or open a project. It used no C-Gate, CNI or PCI endpoint. Native C-Gate behavior was checked separately in [thermostat-template-native-acceptance.json](thermostat-template-native-acceptance.json).

## Inputs

| Input | Identity |
| --- | --- |
| `CBusToolkit.exe` 1.18.0.2754 | SHA-256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab` |
| `CBusToolkit.map` | SHA-256 `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb` |
| `cgate.jar` 3.4.0.2001 | SHA-256 `3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630` |
| Decoded template specifications | Per-file SHA-256 values are in the JSON receipt; the content is not committed |
| Help topics 2770, 2919, 2975, 2982, 2990, 2995, 3054, 3813 and 3850 | The SHA-256 values are in the JSON receipt |

To reproduce the receipt, run this command. It needs the private original files, `capstone` and `pefile`:

```sh
python research/thermostat_template_static.py --exe CBusToolkit.exe --map CBusToolkit.map \
  --help-dir toolkit-help --cgate-jar cgate.jar --spec-dir "$CBUS_UNITSPEC_DIR"
```

## Findings

1. **Installation list.** `TCBusThermostatCGateAgent.LoadThermostatInstallations` adds index 0, `<Custom>`, which has no template file. Indexes 1–9 then use template number N. The script checks the `System.@IsClass(TProgrammableThermostat)` guard and the literal filenames:
   - Programmable units receive `THERMOSTATA_TEMPLATE01`–`09`.
   - Other thermostats receive `THERMOSTAT_TEMPLATE01`, `04`, `05`, `06`, `08` and `09`.
   - Installations 2, 3 and 7 are added only for programmable units. `THERMOSTAT_TEMPLATE02`, `03` and `07` exist in C-Gate's unit specification directory, but the original dialog never offers them.
2. **Classes.** VMT parent chains give TPC_TSA5 → TPC_TSA → TProgrammableThermostat and TPC_TSB5 → TPC_TSB → TBasicThermostat. The committed [dialog map](../../../docs/toolkit-dialog-map.json) registers PC_TSA, PC_TSA5, PC_TSB and PC_TSB5 to those classes. Their catalogue revisions select `THERMOSTATA.xml` or `THERMOSTATB.xml`. No catalogue revision selects plain `THERMOSTAT.xml`, which is only an included base.
3. **No firmware or specification gate.** The list depends only on the class. Every template declares firmware `0`–`9`. `HandleBtnLoadClick` passes only the verb `LoadFromTemplate` and the file name. It does not use `CheckTemplateIsCompatible`, which belongs to the generic UnitTemplate path.
4. **Overlay without reset.** `TCBusUnitCGateAgent.AgentLoad` passes `IsInVerbs("ResetToDefaults")` to `ParameterProgrammingLoadFromTemplate`, and the thermostat call leaves that flag false. The routine then runs `PP LOAD_FROM_FILE <session> <file>`, `ParameterProgrammingGetAll`, the agent's `AfterLoadProgrammingInformation`, `EnsureTagNameIsNotBlank`, `SetUnitEditedState` and `SaveBurdenOriginalState`. In decompiled C-Gate, `lD`/`lP` apply each template parameter's default value at that parameter's own address. Other session bytes are left untouched, and C-Gate performs no unit-type check.
5. **Toolkit post-load adjustments.** These are recorded, but the CLI does not replay them:
   - `ClearOriginalDamperGroups` zeroes four PlantControlService fields.
   - A ZoneManagerMasterSlave value of 1 is set to 0.
   - `UpdateQuickOptions` runs.
   - `TPlantControlService.UpdateParametersForPlantType` runs. This 6,300-byte routine reassigns output and relay groups by plant type through `GetUnusedGroup`/`GetGroup` and may create labelled groups.
   - `UpdateEvapProgramParameters` applies to programmable units only. It sets `EvapProgramEnabled=0`, and sets `NonEvapProgramEnabled=0` when the internal plant enum is 0 or 2.
   - The form writes the resulting model back only on its later save.
   - `TddThermostat.HandleBeforeLoadTemplate` and `HandleLoadTemplate` bracket the load by setting and then clearing two suppression flags.
6. **Help.** None of the nine thermostat topics names Load Template or typical installations in text. Their dialog figures are images. The help establishes no additional rule.

## Unresolved

- The internal plant enum mapping used by `UpdateEvapProgramParameters`, and the complete group reassignment in `UpdateParametersForPlantType`.
- The captions and descriptions from resource strings, and the images that are shown. Only the bitmap file names were seen.
- The combined effect of the original form's AfterLoad/BeforeSave model round-trip.
- The per-byte protection that `LOAD_FROM_FILE` copies from the template. For example, `InstalledZones` is `none` in most templates and `factory` in the unit specification. This protection could affect physical programming.
- Behavior on physical thermostats.
