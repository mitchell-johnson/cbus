# Quick-zone checkbox feedback barriers

The [receipt](thermostat-quick-zone-callback-static.json) pins 44 original
method spans, three Delphi form resources and 37 passing checks. It extends
the [event-order receipt](thermostat-quick-zone-events-static.md), using the
same pinned Toolkit EXE/MAP hashes. Source hashes are checked before and after
inspection. Original code was not executed by this checker; no complete GUI
or public quick-zone action is claimed.

Reproduce from `toolkit-cli/`:

```sh
python research/thermostat_quick_zone_callback_static.py --exe CBusToolkit.exe --map CBusToolkit.map
```

## Candidate and proven consumers

The smallest investigated candidate is one accepted IncludeZone(1), bit2,
from a fresh programmable master whose seven quick-zone source masks are 1,
InstalledZones and ControlledZones are 3, and heating/cooling/venting plant
types are zero. All output/damper/relay references resolve to an existing
unused group255. This is an investigation profile, not current admission.

The explicit method route adds bit2 to UsedZones, UIAllocatedZones,
InternalPlantZones, MeasuredZones and ScheduleControlledZones. The already
set Installed/Controlled bits cause no Boolean notification; zero plant types
skip the three plant-installed writes. Their masks remain1. The separate
original core-callback work must establish actual notification execution;
this receipt establishes the following presentation barriers.

| Original component | Expression bound by SetupFlashComponents |
| --- | --- |
| UI `chbZone1` | `UIAllocatedZones.Zone1` |
| Plant `chbPlantZone1` | `InternalPlantZones.Zone1` |
| Temperature Control `chbMeasuredZone1` | `MeasuredZones.Zone1` |

All three DFM components are exactly `TFlashCheckBox`, with no DFM event
binding. The selected setup methods do not assign their optional value-change
callback at `+0x288`. The measured checkbox does receive an ordinary OnClick
callback at `+0x110`; that distinction matters.

`TFlashCheckBox.ControllerValueChange` (`0xae8120`) saves inherited flag
`+0x270`, sets it to1, calls the original checked-state setter and restores the
flag. The VMT resolves this setter to `StdCtrls.TCustomCheckBox.SetChecked`
(`0x68a038`) → `SetState` (`0x68a04c`). `SetState` skips dynamic Click when
`+0x270` is nonzero. A programmatic refresh therefore does not run the measured
OnClick callback or normal checkbox Change/model-writeback route. This is a
source-backed omission for those three checkbox consumers, not all controls.

## Notification lock and stable leaves

`TFlashExpressionController.DoFlashHandleChanged` (`0x84d8c4`) brackets its
consumer calls with LockUpdate/UnlockUpdate. The lock is nesting counter
`+0x54`; it is **not** byte `+0x4c`, which separately gates writes.
Boolean, String and Element controller Apply methods (`0x84f0c4`,
`0x84f2f8`, `0x84f484`) test GetUpdateLocked before model assignment. Their
common Apply (`0x84d7d0`) clears dirty flag `+5` even when assignment is skipped.
Thus same-controller cache changes during a notification do not produce
model writes or leave a pending Apply behind. A custom callback that directly
calls a model setter is outside this barrier.

`TFlashTrackedHandle.SetRootElement` (`0x84ed10`) returns for the same root
pointer. Its `Update` (`0x84ed88`) also skips the current-element notification
when the current pointer remains identical. This prevents treating every
parent-object notification as a changed scalar sibling value.

## Exact remaining list/message boundary

`TFlashTrackedHandle.DoRootElementChanged` (`0x84e7b0`) still calls
`DoListChanged` (`0x84e6f0`) for collection/enum roots even when the current
pointer is unchanged. For `TFlashComboBox`, the immediate list callbacks
`FlashHandleListChanged` (`0xae61a0`) and `FlashHandleListRootChanged`
(`0xae61c4`) only set dirty byte `+0x320` and call `UpdateEnableState`
(`0xae6244`). The latter only reads acceptance and calls the original Enabled
setter. Neither callback calls `PopulateList` or assigns the model.

Population is deferred: `PopulateList` (`0xae5fa4`) has callers in `DropDown`
(`0xae5f70`), `DoMouseWheelDown` (`0xae680c`), `DoMouseWheelUp` (`0xae6918`)
and `KeyDown` (`0xae6ac0`). Those additional user gestures are outside the
isolated quick-checkbox candidate. This narrows the gap but does not prove
all native message or queued callback behavior absent.

The Plant DFM contains one event, `cmbInternalPlantType.OnChange`, unlike the
three zone checkboxes. Its original handler
`CIS_TfrmThermostatPlant.TfrmThermostatPlant.cmbInternalPlantTypeChange`
(`0x11221fc`) posts message `0x423`; `HandlePlantTypeChange` (`0x11221c8`)
dispatches callback `+0x460/+0x464`. Plant setup binds this callback to
`TcdThermostatPlant.HandleInternalPlantTypeAfterChange` (`0x112947c`), which
can invoke `UpdateParametersToMatchPlantType` (`0x1129508`). That path must
not be silently omitted or confused with the locked same-controller Apply.
Likewise custom range/minimum/cycle callbacks may invoke model setters
directly. Initial binding state, other control families, pending messages and
project-object provenance remain separate prerequisites for a full-form claim.

No production code or callable action is introduced by this evidence slice.
