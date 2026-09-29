# ST7 multisensor setup

`Multisensor` implements a bounded Toolkit sensor setup workflow for unit
type **SENPILL**, firmware **2.0.01** through **2.3.9**, catalog **5753PEIRL**
or **SLC5753PEIRL**, using the user's `SENPILL_ST7.xml` and its includes.
Native application and offline snapshots reject other unit types, revisions
and catalog numbers before any write. This is one Toolkit sensor class, not
full sensor-dialog or hardware parity. See [Profile admission](#profile-admission).

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

`configure(session, **options)` combines `plan` and `apply`. A plan made from
a PP export snapshot, or by `configure`, is bound to that unit identity and
`apply` refuses a session with another firmware or catalog number. A plan
made from a bare parameter mapping reports `firmware` and `catalog_number` as
`null`; `firmware_range` and `catalog_numbers` always state the admitted
profile. Global threshold
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

## Profile admission

`research/sensor_profile_review.py` compares every decoded `SEN*` sensor
specification with `SENPILL_ST7.xml` and reads C-Gate's `cbusunits.xml` and
the Toolkit 1.18 EXE/MAP. Its committed receipt,
[`sensor-profile-review.json`](sensor-profile-review.json), holds only input
SHA-256 values, per-specification layout digests and counts, Toolkit class
names and derived verdicts. Layout equality covers every parameter name with
its type, address, array/bit geometry, protection and min/max bounds.

| Unit type | Firmware (catalogue) | Layout vs `SENPILL_ST7` | Toolkit class | Decision |
|---|---|---|---|---|
| SENPILL | 2.0.01..2.3.9 (5753PEIRL, SLC5753PEIRL) | identical | `TST7SENPILL` / `TCBusST7MultisensorCGateAgent` | admitted |
| SENPILL | 2.3.10..2.3.99 | identical | none registered | refused |
| SENPIROA, SENPIRIA | 2.0.01..2.4.99 (`_ST7`, `_ST7_2`) | identical | `TST7SENPIROA` / `TST7SENPIRSS`, ST7 PIR agent | refused |
| SENPIRIB | 2.0.01..2.3.9 (`SENPIRIB_ST7`) | identical | `TST7SENPIRSS`, ST7 PIR agent | refused |
| SENLL | 2.0.01..2.4.99 (`SENLL_ST7`) | identical | `TST7SENLL`, light-level agent | refused |
| SENPILL 2.4, SENPILLA, SENPIRIC, SENPIRIB 2.4 | `SENPILLA` / `SENPIRIC` | 11 parameters added | `TSENPILLA` / `TSENPIRIC` | refused |
| SENPILL | 1.6.00..2.0.00 (`SENPILL_1/2/3`) | 6 removed, 8 changed | `TSENPILL` | refused |
| SENPIR, SENPIRSS, SENSOR | 1.x (`SENPIR`, `SENPIRSS`) | different | `TSENPIR` / `TSENPIRSS` | refused |

Toolkit selects a unit class by unit type and firmware in numeric
`.`-token order (`VersionStringCompare`), independently of the catalog
number. It registers `TST7SENPILL` for SENPILL 2.0.01..2.3.9, while C-Gate's
catalogue maps 2.0.01..2.3.99 to `SENPILL_ST7.xml`, so only their
intersection is admitted. Within the admitted class and agent ancestry, the
two direct firmware comparisons are overridden by constant
`TCBusST7MultisensorUnit` methods, so the scanned class methods behave the same
throughout the range.

The ST7 PIR types have the same PP layout, and native C-Gate accepts it, but
the Toolkit does not handle them like SENPILL. `TCBusST7PIRSensorCGateAgent`
inherits the multisensor save and then runs `PrepareForcedParameters`. That
step forces `PIRLightMovement`=9, `PIRDarkMovement`=10, `PIRDark`=4 and
`PotentiometerAFunction`=1. It also clears the join, corridor, IR,
maintenance and scene-selector fields. The PIR unit also limits blocks to four.
Editing their event masks with this workflow would produce a state that the
Toolkit overwrites on its next save. The workflow therefore refuses them.
`SENLL` is a light-level sensor class with no occupancy workflow. Modelling
the PIR and light-level dialogs is still open.

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
and EXE bytes. It also checks that every catalogue decision in the receipt
matches the profile gate, and that the receipt regenerates from the private
inputs. Native acceptance runs against an owned loopback C-Gate 3.4.0 build
2001 (`research/local_cgate.py`) or an explicitly supplied host. It covers
five admitted profiles: 2.0.01, 2.2.00 and 2.3.00 with 5753PEIRL, and 2.1.00
and 2.3.9 with SLC5753PEIRL. Each profile runs five events across all eight
virtual keys (40 cases, 200 in total) with 210 raw-byte assertions (1,050 in
total). Each profile also checks packed-neighbor preservation and that all 52
parameters outside the workflow stay unchanged. An explicit database
save/reload must then return the complete PP parameter set.

The same run creates 12 refused units: SENPIROA and SENPIRIA at 2.3.00 and
2.4.00, SENPIRIB 2.3.00, SENLL 2.3.00, SENPILL 2.3.10, SENPILL 2.0.00 and
2.4.00, SENPILLA, SENPIRIC and SENPIRIB 2.4.00. The first seven have the
native 82-parameter `SENPILL_ST7` layout and pass the native schema check.
All 12 are rejected before any write, and their values stay unchanged.
`tests/test_cli_sensors.py` repeats the CLI preview/apply/save/reload flow for
2.3.00/5753PEIRL and 2.1.00/SLC5753PEIRL, and checks KEY4 and SENPIRIA
refusals. Each test creates and deletes its own closed disposable project. No
physical endpoint is opened. The compact report in
`sensor-acceptance-summary.json` records source hashes and the local
full-report hash.

```sh
VENDOR=/path/to/toolkit-cli-research-vendor
research/sensor_profile_review.py --unitspec-dir "$VENDOR/unitspec-plain" \
  --catalogue "$VENDOR/cgate/app/unitspec/cbusunits.xml" \
  --exe "$VENDOR/toolkit/app/CBusToolkit.exe" --map "$VENDOR/toolkit/app/CBusToolkit.map" \
  --output docs/sensor-profile-review.json
CBUS_NATIVE_SERVICE_BACKEND=local CBUS_LOCAL_CGATE_VENDOR="$VENDOR/cgate/app" \
CBUS_CGATE_JAVA=/path/to/jdk-11/bin/java \
CBUS_UNITSPEC_DIR="$VENDOR/unitspec-plain" \
CBUS_TOOLKIT_EXE="$VENDOR/toolkit/app/CBusToolkit.exe" \
CBUS_TOOLKIT_HELP_DIR="$VENDOR/toolkit-help" \
CBUS_SENSOR_REPORT=research/runtime/sensor-acceptance.json \
  .venv/bin/python -m pytest tests/test_sensors.py tests/test_cli_sensors.py -v
```

The following remain outside this acceptance scope: physical movement
detection, lux calibration, sensitivity, occupancy power-up state, infrared
controls, corridor linking, join mode, bank-switch editing and light
maintenance/broadcast programming. Custom macros, PIR/light-level/SENPILLA
dialogs and their Toolkit forced-parameter behavior, and complete GUI
before/after parity are also outside it.
