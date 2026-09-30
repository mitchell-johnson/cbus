# Thermostat dialog rule subset

Read-only recovery from Toolkit 1.18.0.2754. The original executable was not
run. The [machine-readable receipt](thermostat-settings-form-static.json)
records 25 method boundaries/digests, published Delphi component field names
and 15 extraction checks. No original instruction bytes, specification data
or private paths are included.

| Input | SHA-256 |
| --- | --- |
| `CBusToolkit.exe` | `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab` |
| `CBusToolkit.map` | `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb` |

Reproduce with:

```sh
python research/thermostat_settings_form_static.py --exe CBusToolkit.exe --map CBusToolkit.map
PYTHONPATH=src python -m pytest -q tests/test_thermostat_settings_dialog_rules.py tests/test_thermostat_settings_guard.py
```

The targeted tests passed: 16 tests and 28 subtests. Literal expected cases
are independent of the production tables; the extractor separately reads
the original twelve-entry allowed-mode jump table and compares that with the
production constants.

## Recovered zone rules

`ZonePartiallyOn` at `0x111e4c0` ORs six masks: UI allocated, internal plant,
measured, heating plant installed, cooling plant installed and venting plant
installed. A programmable thermostat also includes schedule controlled zones.
`ZoneFullyOn` at `0x111e624` ANDs these same masks. Neither method reads
`InstalledZones` or zone-manager `ControlledZones`.

`CheckBoxStateForZone` at `0x111e788` returns 0 for absent, 1 for fully
selected, and 2 for partially selected. The getters treat either 1 or 2 as
selected. This explains why a mask-subset check against `InstalledZones`
would invent a restriction absent from these recovered methods.

`UpdateFlashZoneVariables` at `0x111e7d8` clears and rebuilds the model's
UsedZones and InstalledZones from those selected checkboxes. This is an
event effect: `UpdateQuickOptions` at `0x111e97c` skips the write when its
initialization flag at `+0x29` is set. `Initialise` at `0x111df60` sets that
flag before `SetupComponents` and clears it afterwards. The helper does not
apply this as unconditional raw PP load/save normalization.

The enable methods take each used-zone state. UI allocated and measured-zone
checkboxes use it directly. Plant-zone checkboxes also require master mode;
the basic thermostat hides their group. Heating, cooling and venting
installed-zone checkboxes require both master mode and their respective
plant type to be nonzero. The original AfterLoad method sets master mode
when raw ControlledZones is positive, otherwise slave mode.

`IncludeZone` at `0x111d7cc` includes the selected bit in UsedZones, UI,
measured, installed and zone-manager controlled masks. It includes internal
plant zones only for a master, and schedule controlled zones only for a
programmable master. It includes each plant-installed mask only if that
plant type is nonzero. These master decisions precede updating
ControlledZones. `ExcludeZone` at `0x111d98c` clears the bit from all these
masks, with the schedule field present only for programmable thermostats.
`HandleChbUsedZoneClick` at `0x111db64` refuses removing the last quick zone,
and separately requires the accepted answer to its unswitched-zone removal
prompt. The pure helper models one accepted action from a loaded snapshot;
it does not manage a continuing original form instance.

## Recovered plant rules

`GetAllowedPlantModes` at `0xfdabb4` returns these masks for virtual plant
types 0–11: `1,19,21,31,19,21,31,31,3,31,31,31`. It masks its index with
`0x7f`; an unrecognized index returns 31. The existing pinned virtual-plant
rule converts stored type 8 into virtual type 11 when any of the ten
specified cooling/heat-fan outputs is assigned.

`EnableDisablePlantModes` at `0x1128ef4` enables the Heat, Cool, Heat/Cool
and Vent checkboxes using allowed bits 2, 4, 8 and 16 respectively, and
master mode. Its unguarded second half checks those controls' **Enabled**
states, not their Checked states. For a master, a vent type of 1 becomes 2
when Heat and Heat/Cool are unavailable; then a vent type of 2 becomes 1
when Cool and Heat/Cool are unavailable; finally neither kind available
forces vent type 0. A form flag at `+0x2a` suppresses these effects. The
report exposes this isolated result without applying it to PP values.

`EnableDisableVentPlantType` at `0x1128e6c` enables the vent selector when
Vent is checked and the unit is master. Separate action update methods
enable Fan Control when the Vent mode bit is set and VentPlantType is
nonzero; Fan Coil when the virtual plant type is 11 and the modes are
neither 0 nor Off-only (1); and Evaporative Cooling when internal plant
type is nonzero and at least one of the four zone-manager plant types
is 2, 6 or 10. These individual action methods do not add a master check.
The basic thermostat additionally hides the Damper Groups button.

## Limits

The subsequent [quick-zone event recovery](thermostat-quick-zone-events-static.md)
pins initialization and click guards, nested plant-type/damper effects and
retained-master save behavior. It explains why the explicit-mask helper alone
is insufficient for a public complete-form action.

`recovered_dialog_rules` reports this method subset, and
`quick_zone_transition` computes the separate accepted quick-zone action.
Neither admits or rejects a raw settings edit. Both complete-dialog and
original-dialog-executed indicators remain false.

Still missing: the complete original dialog event order, every control and
parent visibility rule, GUI-to-raw-edit admission, whole-form validation,
the owned native save/reload of an exposed quick-zone workflow, output-group
editing/default-group creation, and original GUI execution. In particular,
cycle-limiting controls have several writers whose ordering must be resolved
before assigning a single final enable state. Static rule recovery does not
establish physical thermostat behavior.
