# Seven-panel quick-zone binding boundary

The [checker](../../thermostat_quick_zone_gui_binding_static.py) and
[receipt](thermostat-quick-zone-gui-binding-static.json) extend the earlier
[checkbox callback evidence](thermostat-quick-zone-callback-static.md) without
changing it. They pin the original EXE/MAP, the corrected synthetic native
database seed, seven DFM resources, and the selected method spans. No original
instructions or native UI execute in this checker. All initialized-form and
public-action acceptance flags remain false.

There are **83 direct Prepare sites** in the seven SetupFlashComponents
methods: C-Bus 8, UI 11, Zone Management 20, Plant 22, Temperature Control 16,
Templates 1, Scheduling 5. Each site has its published component name, ECX
expression, and owner-relative link path. ECX is the list expression for an
element combo; its separate value expression is captured from the stack.
The inventory also preserves direct lifecycle calls, literal callback
assignments and DFM events. It records source sites, not branch execution or
a complete live subscriber graph.

Reproduce from `toolkit-cli/`:

```sh
python research/thermostat_quick_zone_gui_binding_static.py \
  --exe CBusToolkit.exe --map CBusToolkit.map \
  --seed research/experiments/2026-09-30/thermostat-quick-zone-native-seed.json \
  --output NEW.json
```

## Fresh initialization changes the core premise

`CIS_TcdThermostatTemplates.TcdThermostatTemplates.Initialise` sets `+0x29=1`
at `0x111df72`, calls SetupComponents at `0x111e0ba`, then clears the flag at
`0x111e0c2`. SetupComponents calls UpdateQuickOptions, which updates the quick
checkboxes but skips UpdateFlashZoneVariables while that flag is set
(`0x111eacf..0x111ead6`). Displaying the union of the seven source masks therefore
does **not** establish `UsedZones=1` in the model.

`CIS_TcdThermostatTemplates.UpdateFlashZoneVariables` (`0x111e7d8`) resets both
UsedZones and InstalledZones before rebuilding them from the quick controls.
Inserting this helper to manufacture UsedZones=1 would also change the
candidate's InstalledZones=3 premise. The separate corrected
[Advanced UI core receipt](thermostat-quick-zone-advanced-ui-core-original.json)
uses constructor-empty UsedZones: the isolated include produces `0→2`, while
the four other changed masks become `1→3`. It remains a prepared model graph.

The UI panel's HookEvents (`0x11217b8`) only subscribes its
HandleUIInstalledZonesChange to TCBusParameters.InstalledZonesChangeSubscribe.
It does not call the base TUIService.HookEvents or repair the programmable
AdvancedUI callback difference. The older four-callback synthetic fixture
must not be treated as an initialized programmable form.

## Parent enable behavior

`CIS_TddThermostat.TddThermostat.HandleEnableDisableZone` (`0x1132d1c`) dispatches
UI, Zone Management, Plant, then Temperature Control. Plant.EnableDisableZone
(`0x1126f1c`) changes the selected checkbox's Enabled property and calls
EnableCycleLimitingControls (`0x11293e0`). It does not invoke
EnableDisablePlantModes or its Vent fallback.

Temperature Control has an additional synchronous path: EnableSliders
(`0x112d618`) calls trkMinimumSetTempChange (`0x112f2d4`),
trkMaximumSetTempChange (`0x112f1c8`), then minimum again. With initialized
Celsius positions `minimum=15 < maximum=32` and chbEnableGuard unchecked,
the pinned comparisons skip every SetPosition and model-setter path in these
handlers. The raw seed matches those values; this is conditional source
evidence, not proof that all native slider initialization has executed.

Enabled setters themselves can dispatch CM_ENABLEDCHANGED and EnableWindow.
The receipt does not replace native message behavior with an assumed no-op.

## Combo focus and Plant messages

The earlier callback receipt listed dropdown/wheel/key population sites.
`CIS_TFlashComboBox.TFlashComboBox.DoEnter` (`0xae5e6c`) also populates the list
on focus. DoExit (`0xae5e88`) calls ExitingControl and RenderDisplay. All
**13** element combo Prepare sites pass value-controller ImmediateApply=1;
PrepareFlashComboBox writes this to `+0x58` at `0xc0fe28`. ExitingControl
(`0x84da68`) skips Apply when that flag is nonzero. Thus those exact prepared
element combos do not defer a model assignment until blur.

PopulateList and RenderDisplay have no direct Change/DoIndexChange call.
RenderedValueChange and RenderDisplay update text. Controls.SetText
(`0x6f62d8`) skips equal text; changed text reaches SetTextBuf. Stable model
pointers alone do not establish stable native text or an empty message queue.

The original dynamic method table resolves notification code 5 through
StdCtrls.TCustomCombo.CNCommand (`0x6876b4`) to
TFlashComboBox.Change (`0xae6aac`), then TCustomCombo.Change (`0x687830`),
which invokes OnChange at `+0x288`. Notification code 1 also reaches the
inherited Select path. Plant's DFM binds cmbInternalPlantType.OnChange to
`CIS_TfrmThermostatPlant.TfrmThermostatPlant.cmbInternalPlantTypeChange`
(`0x11221fc`), which posts `0x423` without an initialization/equality guard.

`HandlePlantTypeChange` (`0x11221c8`) dispatches the callback currently in
`+0x460/+0x464`. Plant.SetupFlashComponents assigns this callback at
`0x1127493`, after the combo Prepare call at `0x1127460`. Its target,
`CIS_TcdThermostatPlant.TcdThermostatPlant.HandleInternalPlantTypeAfterChange`
(`0x112947c`), calls UpdateParametersToMatchPlantType (`0x1129508`). This is
not protected by the same-controller Apply lock. The method can change
plant parameters/types and groups; it cannot be omitted just because the
explicit quick-zone action changes no plant-type byte.

## Smallest remaining prerequisite

The missing join is an original ready-form state: controller activation and
native control text/selection/focus after initialization, plus the origin and
dispatch ordering of native combo notifications and pending Plant `0x423`
messages. It must establish either that the candidate has no applicable
pending message, or execute any such message and admit its resulting model
and project changes. A readback of raw PP and existing group255 objects does
not supply that state. No household hardware is needed to investigate this;
an owned native UI/message fixture would be separate work.

Only the selected source branches, binding inventory and corrected core
fixture are accepted here. Seven-panel initialization, outer user click,
project-object graph and save/reload are not joined into a complete original
workflow.
