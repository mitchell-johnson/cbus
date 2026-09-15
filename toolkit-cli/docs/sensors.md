# ST7 multisensor setup

`Multisensor` implements a bounded Toolkit sensor setup workflow for catalog
**5753PEIRL**, unit type **SENPILL**, firmware **2.3.00**, using the user's
`SENPILL_ST7.xml` and its includes. Native application rejects other catalog
numbers, unit types and revisions. This is one tested sensor profile, not full
sensor-dialog or hardware parity.

The helper combines the Occupancy tab's event selection, the standard sensor
macro, virtual-key/block assignment, timer settings, occupancy enable group,
and light threshold. It checks dependencies before editing an existing PP
session. It never implicitly saves, transfers to hardware, or opens a network.

```python
from cbus_toolkit.sensors import Multisensor
from cbus_toolkit.unitspec import UnitSpecStore

sensor = Multisensor(UnitSpecStore(spec_directory).load("SENPILL_ST7.xml"))
plan = sensor.plan(
    session.values(), key=2, event="night", group=17,
    timer_seconds=300, expiry="off", allow_shared_block=True,
    target_lux=550, margin_percent=10,
    disable_potentiometer_override=True,
    enable_group=23, enabled_when="off",
)
print(plan.as_dict())
sensor.apply(session, plan)  # checks native schema, stale data and readback
session.save_to_source()    # separate, explicit persistence operation
```

`configure(session, **options)` combines `plan` and `apply`. Global threshold
and occupancy-enable settings can be changed without `key` or `event`.
Key numbers and block numbers are 1..8. A selected event requires an assigned
Lighting Type group (0..254). The selected block's existing primary/secondary
application must be in 48..95. The helper preserves that application selection.

| Event | Day mask | Night mask | Sunset mask | Short press, short release, long press, long release |
|---|---|---|---|---|
| `day` | 1 | 0 | 0 | Retrigger timer, idle, idle, idle |
| `night` | 0 | 1 | 0 | On, retrigger timer, retrigger timer, idle |
| `any` | 1 | 1 | 0 | On, retrigger timer, idle, retrigger timer |
| `sunset` | 0 | 0 | 1 | On, off, retrigger timer, off |
| `disabled` | 0 | 0 | 0 | Idle, idle, idle, idle |

Each mask uses bit `key-1`. Other keys' masks and functions remain unchanged.
The ordinary sensor function clears that key's scene selector. A sensor event
disables bank switching on its selected block; the block's other packed bits
remain intact. `disabled` removes sensor event assignments and uses an unused
macro without erasing group or timer data.

The default day and night virtual keys share block 2. Editing that shared
group or timer requires `allow_shared_block=True`; the plan lists every other
key sharing it. A missing or multiple-block assignment requires an explicit
block. Join mode, a selected broadcast block, and a selected maintenance block
are rejected because their combined behavior is outside this workflow.

Timer seconds are 0..65535, split into high and low bytes. Expiry accepts
`idle`, `off`, `down`, `ramp_off`, `recall1`, `recall2`, or `ramp_recall1`;
recall expiry uses the block's existing recall setting. A zero timer is an
explicit native setting, not evidence of a useful physical timer action.

Thresholds use exact 10-lux steps in the native byte range 0..2550. Setting
`target_lux` requires `margin_percent` (0..100). Toolkit stores the target in
units of ten lux and stores the margin as
`round_to_even(target_byte * margin_percent / 100)`. For example 550 lux and
10% produce target byte 55 and margin byte 6. The stored margin is quantized;
the percentage displayed on a subsequent Toolkit load can differ. This range
describes supported native encoding, not a claim about every GUI slider limit.
The target and margin also affect the unit's other light-level functions.

When a potentiometer controls the light target, or controls the selected
block's timer, that setting requires `disable_potentiometer_override=True`.
The helper then changes only the conflicting potentiometer function to
unused. It preserves unrelated controls. This is an explicit choice of
software settings, not a claim that moving a Toolkit slider automatically
disables the potentiometer.

`enable_group` accepts 0..254 or 255 to remove the group assignment.
`enabled_when="on"` stores polarity 0; `"off"` stores 1 and requires an
assigned group. This setting controls whether that group enables the
occupancy sensor; it does not claim the current sensor is enabled.

Application returns `verified=True`, `saved=False`, `device_verified=False`.
A failed write or readback raises `SensorApplyError` carrying the original
cause and attempted field names. No write is retried, no recovery I/O occurs,
and no automatic save follows a partial change. Inspect or reload the unsaved
PP session before continuing.

## Evidence

Toolkit Help topics 307 (Occupancy), 305 (Light Levels), 1000/11177 (sensor
events), and the independent micro-function tables in 10114, 10115, 17328,
and 10116 establish the controls and event functions. The original EXE/MAP
provides the following additional mappings; addresses below are EXE virtual
addresses with this build's image base.

* `CIS_TCBusST7SensorCGateAgent.SaveOccupancyKeys`, VA `0xCF4DAC`, builds
  independent day, night, and sunset masks. Any Movement enters both motion
  masks. Writes at `0xCF4EEC`, `0xCF4F0D`, and `0xCF4F2E` target agent members
  `0x21C`, `0x220`, and `0x1D8`. Constructor bindings at `0xCF6F5F` onward
  name those fields `PIRLightMovement`, `PIRDarkMovement`, and `PIRDark`.
* `TInputKeyOccupancy.RefreshMacroFunctionFromEventFlags`, VA `0xD01138`,
  selects factory templates `0x1D` (day), `0x1E` (night), `0x21` (any),
  `0x22` (sunset), and `0x10` (unused). The helper performs the explicit
  combined event-and-standard-function choice. It does not implement the GUI
  callback's optional retention of a custom function.
* `TInputKeyOccupancy.RefreshBlockBankSwitchFromEventFlags`, VA `0xD0120C`,
  disables selected blocks' bank switching when a sensor event is active.
* `TCBusST7MultisensorCGateAgent.BeforeSaveProgrammingInformation`, VA
  `0xCF5558`, writes target to member `0x224`; `0xCF56EE..0xCF5763` implements
  the percentage-to-margin calculation and Delphi `ROUND`. Member `0x228`
  is `PECMarginLux`; `0x240/0x244` bind occupancy group/polarity.
* `CIS_CBus.ByteToLux2550`, VA `0x7F2944`, multiplies the byte by 10.
  `TCBusST7MultisensorUnit.GetLightLevelTargetAsValue`, VA `0xCFB22C`, calls it.
* Sensor specifications locate the event masks at `0x32..0x34`, allocations
  at `0x36`, function nibble pairs at `0x68/0x69` with stride 2, bank enable
  at `0x48` bit 5, target/margin at `0x1B/0x1C`, and group/polarity at
  `0x58` / `0x63` bit 6. Timer and ordinary scene-selector serialization
  share the already-tested Neo-core programming path.

`tests/test_sensors.py` checks independent literal vectors and original help
and EXE bytes. Native acceptance exercises five events across all eight
virtual keys (40 cases), 210 raw-byte assertions, packed-neighbor preservation,
and explicit database save/reload against C-Gate 3.4.0 build 2001. It creates
and deletes its own closed disposable project. No physical endpoint is opened.
The compact report in `sensor-acceptance-summary.json` records source hashes
and the local full-report hash.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_TOOLKIT_HELP_DIR=research/vendor/toolkit-help \
CBUS_SENSOR_REPORT=research/runtime/sensor-acceptance.json \
  .venv/bin/python -m unittest discover -s tests -p test_sensors.py -v
```

Physical movement detection, lux calibration, sensitivity, occupancy power-up
state, infrared controls, corridor linking, join mode, bank-switch editing,
light maintenance/broadcast programming, custom macros, other sensor profiles
and firmware revisions, and complete GUI before/after parity remain outside
this acceptance scope.
