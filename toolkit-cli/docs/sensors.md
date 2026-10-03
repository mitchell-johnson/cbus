# ST7 multisensor setup

`Multisensor` implements a bounded Toolkit sensor setup workflow for unit
type **SENPILL**, firmware **2.0.01** through **2.3.9**, catalog **5753PEIRL**
or **SLC5753PEIRL**, using the user's `SENPILL_ST7.xml` and its includes.
Native application and offline snapshots reject other unit types, revisions
and catalog numbers before any write. This is one Toolkit sensor class, not
full sensor-dialog or hardware parity. See [Profile admission](#profile-admission).
The ST7 PIR types SENPIROA, SENPIRIA and SENPIRIB use a separate workflow; see
[ST7 PIR sensor dialog](#st7-pir-sensor-dialog). The ST7 light-level sensor
SENLL has its own workflow; see
[ST7 SENLL light-level dialog](#st7-senll-light-level-dialog). All three have
[CLI commands](#cli-commands).

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
`ROUND(target_byte * ext(margin_percent / 100))`, the original x87 save
arithmetic ([Margin arithmetic](#margin-arithmetic)). For example 550 lux and
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

## Margin arithmetic

The SENPILL, PIR and SENLL agents inherit one multisensor load and save.
AfterLoad converts the stored margin to the dialog percentage as
`ROUND(ext(margin / target) * 100)` (0 for target 0), and BeforeSave converts
it back as `ROUND(target * ext(percent / 100))`. `ext` is the x87 80-bit value
(64-bit significand, ties to even) and `ROUND` is Delphi's round half to even.
`cbus_toolkit.sensors.margin_percent` and `saved_margin` implement both.

`research/sensor_margin_original.py` runs the original instructions
(0xcf49ee..0xcf4a1f and 0xcf5704..0xcf5743 with `System.@ROUND`) under Unicorn
with the Delphi control word 0x1332 and fixture getters. It covers every
target byte with every dialog percentage 0..100, every stored target/margin
pair, and each pair's load/save round trip. The frozen tables are in
`research/fixtures/sensor-margin-original-vectors.json`. `tests/test_sensors.py`
compares the model with all 157,184 values and regenerates them when
`CBUS_TOOLKIT_EXE` names the pinned executable.

**Behaviour change.** The SENPILL workflow previously rounded the exact
rational `target * percent / 100` half to even. The original differs for nine
target/percent pairs, where `ext(percent / 100)` lies just below or above an
exact .5 tie: (50, 59) → 29, (75, 42) → 31, (95, 30) → 29, (150, 21) → 31,
(150, 53) → 79, (175, 30) → 53, (190, 15) → 29, (190, 65) → 123 and
(195, 30) → 59. `sensors.py` now writes the original values. A stored margin of
255 with a target byte of 136 or more round-trips to 256, which the native
byte cannot hold; the PIR and SENLL workflows refuse such a plan.

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
| SENPIROA, SENPIRIA | 2.0.01..2.4.99 (`_ST7`, `_ST7_2`) | identical | `TST7SENPIROA` / `TST7SENPIRSS`, ST7 PIR agent | refused (own workflow) |
| SENPIRIB | 2.0.01..2.3.9 (`SENPIRIB_ST7`) | identical | `TST7SENPIRSS`, ST7 PIR agent | refused (own workflow) |
| SENLL | 2.0.01..2.4.99 (`SENLL_ST7`) | identical | `TST7SENLL`, light-level agent | refused (own workflow) |
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
Toolkit overwrites on its next save. The workflow therefore refuses them, and
`PIRSensor` below models that class instead. `SENLL` is a light-level sensor
class with no occupancy workflow, whose save forces every occupancy mask to 0;
`LightLevelSensor` below models it.

## ST7 PIR sensor dialog

`cbus_toolkit.pir_sensors.PIRSensor` models the Toolkit dialog of class
`TST7SENPIROA` (SENPIROA) and `TST7SENPIRSS` (SENPIRIA, SENPIRIB) with agent
`TCBusST7PIRSensorCGateAgent`, followed by that agent's complete save. The
values it writes are the values the Toolkit would leave after pressing OK
with the same dialog edits. Admission is the intersection of the Toolkit
registration and C-Gate's catalogue:

| Unit type | Firmware | Catalogue | Specification |
|---|---|---|---|
| SENPIROA | 2.0.01..2.3.99, 2.4.00..2.4.99 | 5750WPL, SLC5750WPL,GY | `SENPIROA_ST7.xml`, `SENPIROA_ST7_2.xml` |
| SENPIRIA | 2.0.01..2.3.99, 2.4.00..2.4.99 | 5751L, SLC5751L,WE | `SENPIRIA_ST7.xml`, `SENPIRIA_ST7_2.xml` |
| SENPIRIB | 2.0.01..2.3.9 | 5753L, SLC5753L | `SENPIRIB_ST7.xml` |

Catalogue bands are `2.0.01..2.0.99`, `2.1.00..2.1.99` and so on; firmware
between bands is refused. SENPIRIB 2.3.10..2.3.99 has no Toolkit ST7 class
and SENPIRIB 2.4 uses the SENPIRIC layout, so both are refused. The loaded
specification must be the one the catalogue selects for the session firmware.

```python
from cbus_toolkit.pir_sensors import PIRSensor

sensor = PIRSensor(UnitSpecStore(spec_directory).load("SENPIRIA_ST7.xml"))
plan = sensor.plan(
    session.values(),
    keys={1: {"block": 1, "group": 41, "timer_seconds": 300, "expiry": "ramp_off"},
          4: {"group": 44}},
    restore_functions=True, darkness_same_as_light=False,
    enable_group=23, enabled_when="off", power_up="enabled",
)
sensor.apply(session, plan)   # profile, schema, stale and readback checks
session.save_to_source()      # separate, explicit persistence operation
```

`plan(current)` with no options is the Toolkit's save of an unchanged dialog.
The recovered dialog has these controls; the Light Level, Bank Switch,
Environment and Scenes tabs are hidden and their subforms are empty:

* Four fixed virtual keys: 1 Motion in Light, 2 Motion in Darkness, 3 Sunset,
  4 Any Motion. Their function combos are disabled; the dialog's templates
  `0x1F`, `0x20`, `0x22` and `0x21` resolve to the day, night, sunset and any
  vectors in the table above. `keys` edits a key's block (1..4), Lighting group
  (0..254, 255 for none), timer and expiry. Keys and blocks 5..8 are not
  editable (grid columns 5..8 are disabled) and are preserved.
* When an edited key's function is not its fixed template, the Toolkit asks
  whether to restore it. `restore_functions=True` writes the template and
  `False` keeps the custom function. Without a choice the plan is refused.
* `darkness_same_as_light` is the "same response as Motion in Light" link.
  The dialog loads it checked when keys 1 and 2 have equal blocks. While set,
  key 2's blocks are replaced by key 1's and key 2's block cannot be edited
  separately. Copying key 1 onto key 2 also triggers key 2's template check.
* `enable_group` / `enabled_when` are the Occupancy Enable/Disable group
  and polarity, as for SENPILL.
* `power_up` is the Power Fail occupancy state: `disabled`, `enabled` or
  `resume`.

A shared block, a non-Lighting application, a key allocation that is not a
single block 1..4, and other invalid values are refused before any write.

### Toolkit save model

The save runs the multisensor save and then `PrepareForcedParameters`. The
plan applies, in this order:

* Occupancy power-up. On load the state is `resume` when `PIRLevelStore` is
  set; otherwise it is `disabled` when `(LightLevel[8] == 255)` equals
  `PIREnablerGroupLogic`, else `enabled`. On save `resume` sets
  `PIRLevelStore`=1; `disabled` stores `LightLevel[8]`=255 if the logic is set
  (else 0), `enabled` the inverse, and both clear `PIRLevelStore`. A polarity
  change therefore rewrites `LightLevel[8]`.
* `BroadcastActive` becomes 4 when the loaded value is 1..6, otherwise 0.
* `PECMarginLux` is recomputed through the hidden percentage:
  `percent = ROUND(ext(margin / target) * 100)` (0 when target is 0), then
  `margin = ROUND(target * ext(percent / 100))`. `ext` rounds to the x87
  64-bit significand and `ROUND` rounds ties to even. This changes the margin
  for many target/margin pairs and differs from exact rational rounding for
  nine target/percent pairs, for example 50 lux-bytes at 59% gives 29.
  `PECTargetLux` is preserved.
* `PotentiometerBBankSwitchEnable`=0 (multisensor save, unconditional).
* Forced: `PIRLightMovement`=9, `PIRDarkMovement`=10, `PIRDark`=4,
  `PotentiometerAFunction`=1, `PotentiometerBFunction`=0, both
  potentiometer timer blocks 0, `IRBank`=0, `DisableIR`=1, `IRBankKeyOffset`=0,
  corridor office/link blocks 0, `CorridorLinkActive`=0,
  `CorridorLinkEnablerGroup`=255, `BroadcastBlock`=0, `IndicatorControl`=0,
  `PECEnablerGroup`=255, both join enabler and control groups 255,
  `ControlAppGroupAddress`=255, `PECFunctionBlock`/`Active`=0, the PEC and PIR
  infrared key/active fields 0, `PECLevelStore`=0 and `PECEnablerGroupLogic`=0.
* `LightLevel` elements 4, 5, 6, 7 and 9 are set to 0.
* `SceneKeySelector` is set to the one-value string `0`. Native C-Gate then
  changes only element 0; elements 1..7 are preserved.
* When the loaded `IndicatorBlockAssignment[0]` is 7 (the Blocks tab's
  Disable Indicator state), the whole array becomes `7 0 0 0 0 0 0 0`.

The Toolkit sends a PP SET only for programmable, changed attributes;
`IndicatorFunction` and `PrimaryColour` are marked non-programmable and are
absent from these specifications. Writing the final values is therefore
equivalent. The plan is idempotent: planning again after apply changes nothing.

Unmodelled: the base Neo/NeoPro key, block, timer and scale serialization is
assumed to round-trip loaded values, and the Toolkit's
`ApplyMicroFunctionDefaults` reset path (key 4 defaults to On/Off/Idle/Off
below 2.4.00) is not a dialog edit here. `sensors pir-plan` and
`unit sensor-pir` expose the workflow; see [CLI commands](#cli-commands).

### PIR evidence

`research/pir_sensor_review.py` disassembles the pinned Toolkit EXE with its
MAP and parses its DFM resources. Its sanitized receipt,
[`pir-sensor-review.json`](pir-sensor-review.json), holds method digests,
parameter names, constants and control component names only. It resolves
agent member `0x13C` to `LightLevel` through
`TCoreKeyInputCGateAgent.CreateEEPROMLevelAttributes`, and it checks the
`ParameterProgrammingSetSingle` gate on attribute flags `+0x58` and `+0x38`.

`tests/test_pir_sensors.py` holds independent literal vectors for the forced
save, normalizations, x87 margin arithmetic, dialog controls and refusals. It
checks every catalogue decision against the profile gate, checks the receipt
against the model, and regenerates the receipt from the private EXE. Native
acceptance on owned loopback C-Gate 3.4.0 build 2001 covers six profiles:
SENPIROA 2.0.01/5750WPL and 2.4.99/SLC5750WPL,GY, SENPIRIA 2.2.00/SLC5751L,WE
and 2.4.00/5751L, and SENPIRIB 2.1.00/SLC5753L and 2.3.9/5753L. Each starts from
a non-default value in every forced field. It checks 41 raw-byte assertions,
six dialog cases, idempotence, 31 unrelated parameters and keys/blocks 5..8
unchanged, and an explicit database save/reload. Five identities are refused
with values unchanged: SENPIRIB 2.3.10 and 2.4.00, SENPIRIA 2.0.00, SENPILL and
SENLL. `pir-sensor-acceptance-summary.json` records the source hashes.

```sh
CBUS_NATIVE_SERVICE_BACKEND=local CBUS_LOCAL_CGATE_VENDOR="$VENDOR/cgate/app" \
CBUS_CGATE_JAVA=/path/to/jdk-11/bin/java CBUS_UNITSPEC_DIR="$VENDOR/unitspec-plain" \
CBUS_TOOLKIT_EXE="$VENDOR/toolkit/app/CBusToolkit.exe" \
CBUS_PIR_SENSOR_REPORT=research/runtime/pir-sensor-acceptance.json \
  .venv/bin/python -m pytest tests/test_pir_sensors.py -v
```

This is static-source plus native C-Gate evidence. The original Toolkit
dialog was not executed, and no physical PIR, lux or power-fail behavior was
observed.

## ST7 SENLL light-level dialog

`cbus_toolkit.light_level_sensors.LightLevelSensor` models the Toolkit dialog
`TddST7LightLevelSensor` for class `TST7SENLL` with agent
`TCBusST7LightLevelSensorCGateAgent`, followed by that agent's complete save.
The Toolkit registers `TST7SENLL` for SENLL 2.0.01 and later; the admitted
profile is its intersection with C-Gate's catalogue:

| Unit type | Firmware | Catalogue | Specification |
|---|---|---|---|
| SENLL | 2.0.01..2.0.99, 2.1.00..2.1.99, 2.2.00..2.2.99, 2.3.00..2.3.99, 2.4.00..2.4.99 | 5031PE, 5031PEWP, SLC5031PE, SLC5031PEWP,GY | `SENLL_ST7.xml` |

`SENLL_ST7.xml` declares the SENPILL type and the SENPILL_ST7 layout; the
workflow is selected by the SENLL identity. SENLL 1.x (`TSENLL`, `SENLL.xml`),
SENLL between or above the bands, SENLLA (`TSENLLA`) and other catalogue
numbers are refused.

```python
from cbus_toolkit.light_level_sensors import LightLevelSensor

sensor = LightLevelSensor(UnitSpecStore(spec_directory).load("SENLL_ST7.xml"))
plan = sensor.plan(session.values(), level_group=40, on_off_group=41,
                   broadcast_group=42, enable_group=43, indicator="on_off",
                   target_lux=500, margin_percent=59,
                   broadcast_interval_seconds=300, power_up="enabled",
                   status_report_interval=13)
sensor.apply(session, plan)   # profile, schema, stale and readback checks
session.save_to_source()      # separate, explicit persistence operation
```

`plan(current)` with no options is the Toolkit's save of an unchanged dialog.
The dialog hides the Occupancy, Blocks, Indicators, Key Functions, Light
Level, Bank Switch, Environment and Scenes tabs. The recovered controls are:

* `level_group`, `on_off_group` and `broadcast_group` are the group combos
  bound to blocks 2, 3 and 5 (`Blocks[1..4].Group`); `enable_group` is the
  maintenance enable group (`PECEnablerGroup`). Each is 0..254, or 255 for none.
  A combo omits a group other than 255 that another block or the enable group
  already uses, except its own current group, and the enable combo omits
  groups used by any block. Groups are compared per application. Such a
  selection is refused.
* `on_off_application` switches block 3 between the primary and secondary
  application. When the unit has no application 2 (address 255), the dialog
  clears block 3's secondary application on load and the switch is disabled.
  A change that collides with another block's destination group is refused,
  whether the preserved group is implicit or explicitly supplied. The native
  callback can migrate shared key allocations and clear the selected group
  to 255; those additional effects are not modelled by this workflow.
  The separate [ordered SENLL control history](senll-application-controls.md)
  admits explicit application/group callbacks on a fresh zero-key graph,
  including collision clearing and the all-eight-block refresh when application
  2 is absent. It preserves raw `BlockAllocation` and refuses missing destination
  group creation/decline decisions. The flat interface retains its existing
  numeric profile and collision refusal.
* `indicator` is the LED radio: `light_level`, `on_off` or `enable`.
  `IndicatorBlockAssignment[0]` loads 5 as `enable`, 2 as `on_off` and any
  other value as `light_level`.
* `target_lux` is 0..2000 lux, stored as `Ceil(lux / 10)`
  (`CIS_CBus.Lux2550ToByte`). On load a stored target above 200 (2000 lux) is
  clamped to 200. `margin_percent` is 0..100; without it the loaded
  percentage is kept, and a plan whose margin would exceed 255 is refused.
* `broadcast_interval_seconds` is the block 5 broadcast timer, 10..65535
  seconds. It writes only element 4 of `TimerHighByte` and `TimerLowByte`;
  the other timers and expiry functions are preserved. The original timer
  model clamps a loaded interval below 10 seconds even when the dialog is
  saved without edits. This minimum does not apply to other blocks.
* `power_up` selects the Power Fail light-level maintenance state:
  `disabled`, `enabled`, or `resume`. The receipt shows `power_up_loaded`,
  the selected `power_up`, and `power_up_after_reload` separately because
  the original SENLL save resets the maintenance polarity after encoding
  this setting. This describes configured bytes rather than an observed
  physical power-failure outcome.
* `status_report_interval` is the Global selector's native integer, 3..255
  seconds, written to `StatusReportInterval` at byte 66. The learn-mode
  controls are hidden for SENLL, while this selector remains available.
  Fresh Global initialization changes stored values 0..2 to 3 before any
  explicit valid selection; values 3..255 remain unchanged. The original
  raw byte remains in the plan's expected map, so two different raw values
  that both initialize to 3 still produce a stale-plan refusal. The source
  [callback review](senll-global-status-source-review.json) and
  [Global interval notes](senll-global-status.md) explain this behavior.

### SENLL Toolkit save model

The save runs the multisensor save, then the light-level
`PrepareForcedParameters`, then two conditional writes:

* The margin round trip of [Margin arithmetic](#margin-arithmetic), using the
  dialog's target and percentage. `PotentiometerBBankSwitchEnable`=0.
* The inherited Power Fail save uses the loaded `PECEnablerGroupLogic`.
  `resume` sets `PECLevelStore` and preserves `LightLevel[9]`. The other
  states clear `PECLevelStore`: `disabled` stores 255 for polarity 1 or 0
  for polarity 0; `enabled` stores the inverse. The later forced save clears
  the polarity. A loaded polarity of 1 therefore reverses the state shown
  on reload after an explicit disabled/enabled selection, matching the
  original ordering. No-edit saves normalize non-resume levels to 0/255.
* Forced: `PIRLightMovement`, `PIRDarkMovement` and `PIRDark`=0, `DisableIR`=1,
  `IRBankKeyOffset`=0, corridor office/link blocks 0, `CorridorLinkActive`=0,
  `CorridorLinkEnablerGroup`=255, `BroadcastBlock`=4, `PIREnablerGroup`=255,
  both join enabler and control groups 255, `PECFunctionActive`=1,
  `PECFunctionBlock`=1, the PEC and PIR infrared key/active fields 0,
  `PIRLevelStore`=0, `PECEnablerGroupLogic` and `PIREnablerGroupLogic`=0, both
  potentiometer functions and timer blocks 0, `RampRate`=`7 7` and
  `LightLevel[8]`=0.
* `JPCommand`, `SRCommand`, `LPCommand`, `LRCommand`, `BlockAllocation`,
  `IndicatorFunction`, `SceneKeySelector` and `PrimaryColour` are marked
  non-programmable, so the Toolkit never sends them. Their stored values are
  preserved.
* `BroadcastActive` becomes 1 when block 5 has a group, otherwise 0.
* `IndicatorBlockAssignment` becomes `1 0 0 0 0 0 0 0`, `2 0 …` or `5 0 …` for
  the level, on/off and enable LEDs.

Other fields, including `IRBank`, `IndicatorControl`, `PECScaleFactor`,
`ControlAppGroupAddress`, other block timers and bank switching,
are preserved. The plan is idempotent after the loaded values have passed
through the original save normalization.

Unmodelled: the remaining base block, bank and scale serialization is assumed
to round-trip loaded values. The live ambient light reading and physical
broadcast timing and power-failure behavior remain unverified. The source
review and native database checks do not establish the original GUI lifecycle.

### SENLL evidence

`research/light_level_sensor_review.py` disassembles the pinned Toolkit EXE
with its MAP. Its sanitized receipt,
[`light-level-sensor-review.json`](light-level-sensor-review.json), holds
method digests, parameter names, constants, control names and flash binding
expressions only. `tests/test_light_level_sensors.py` holds independent
literal vectors for the forced save, load normalizations, dialog controls,
combo exclusions and refusals. It checks every catalogue decision against the
profile gate and the receipt against the model, and regenerates the receipt
from the private EXE.

Native acceptance on owned loopback C-Gate 3.4.0 build 2001 covers one
profile per catalogue band and all four catalogue numbers: 2.0.01/5031PE,
2.1.00/SLC5031PE, 2.2.99/5031PEWP, 2.3.00/SLC5031PEWP,GY and 2.4.99/5031PE.
Each starts from a non-default value in every forced field and a stored
target above 200. It checks 57 raw-byte assertions and 27 dialog cases
(unchanged save, indicators, groups, target/margin, both applications,
broadcast interval boundaries and loaded minimum, all power-up/polarity
combinations, and Global interval selections/invalid loaded values),
idempotence, 39 unrelated
parameters and the non-programmable fields unchanged, and an explicit database
save/reload. Six identities are refused with values unchanged: SENLL 1.2.68 and
1.9.99, SENLL with catalogue 5754PE, SENLLA, SENPILL and SENPIRIA. C-Gate
cannot create SENLL 2.0.00 or 2.5.00 units, so those gaps are refused offline
only. `light-level-sensor-acceptance-summary.json` records the source hashes.

```sh
CBUS_NATIVE_SERVICE_BACKEND=local CBUS_LOCAL_CGATE_VENDOR="$VENDOR/cgate/app" \
CBUS_CGATE_JAVA=/path/to/jdk-11/bin/java CBUS_UNITSPEC_DIR="$VENDOR/unitspec-plain" \
CBUS_TOOLKIT_EXE="$VENDOR/toolkit/app/CBusToolkit.exe" \
CBUS_LIGHT_LEVEL_SENSOR_REPORT=research/runtime/light-level-sensor-acceptance.json \
  .venv/bin/python -m pytest tests/test_light_level_sensors.py tests/test_cli_sensors.py -v
```

This is static-source plus native C-Gate evidence. The original Toolkit
dialog was not executed, and no physical light-level, broadcast or indicator
behavior was observed.

## SENLLA surface component view

`sensors surface-light-level-view` inspects the separate surface-mount
SENLLA / 5754PE / 2.4.00..2.4.99 profile offline. It reports thirteen consumed
surface fields and their source-derived component overlay, preserves its
identified export and specification inputs, and has no edit or native save
action. This eight-key class is kept separate from the zero-key SENLL dialog.
Read [the component guide](senlla-surface.md) for the admitted fields and
remaining ordinary-save lifecycle work.

## CLI commands

Offline plans read a PP export snapshot (`cgate … unit … export`) or a bare
parameter mapping and never contact C-Gate:

```sh
cbus-toolkit sensors pir-plan snapshot.json \
  --key 1:block=1,group=41,timer_seconds=300,expiry=ramp_off --key 4:group=44 \
  --restore-functions --separate-darkness --enable-group 23 --enabled-when off --power-up enabled
cbus-toolkit sensors light-level-plan snapshot.json --level-group 40 --on-off-group 41 \
  --broadcast-group 42 --enable-group 43 --indicator on-off --target-lux 500 --margin-percent 59 \
  --broadcast-interval-seconds 300 --power-up enabled --status-report-interval 13
```

A bare mapping for `pir-plan` needs `--spec` (for example
`SENPIRIA_ST7.xml`); a snapshot selects the catalogue specification from its
firmware. Online, `cgate … unit --lock-address NETWORK --source PATH` accepts
`sensor-pir` and `sensor-light-level` with the same options. `--dry-run`
previews the verified PP changes and parameters without saving;
otherwise the edited session is saved to `--source` or `--destination`.
`--key KEY:FIELD=VALUE[,…]` repeats per key; its fields are `block`, `group`,
`timer_seconds` and `expiry`. `--restore-functions`/`--keep-functions` answer
the template prompt and `--darkness-same-as-light`/`--separate-darkness` set
the link. Groups accept `none` for 255. With no edit options, each command
applies the Toolkit save of an unchanged dialog. The identity gate runs
before a specification is loaded.

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
maintenance/broadcast programming. Custom macros, SENLLA/SENPILLA
dialogs and complete GUI before/after parity are also outside it. The PIR and
SENLL dialogs have their own evidence above.
