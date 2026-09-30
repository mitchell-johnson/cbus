# IOPE occupancy-controller settings

`cbus_toolkit.iope_settings` edits part of the Toolkit 1.18 `TfrmIOPE` dialog
for the ultrasonic occupancy controllers:

| Unit type | Catalogue | Sensors | Aux inputs | Output channels | Relay channels |
| --- | --- | --- | --- | --- | --- |
| IOPE1R1 | 5752PP/1R | 1 | 1 | 1 | 1 |
| IOPE2R2 | 5752PP/2R | 2 | 2 | 2 | 1, 2 |
| IOPE2C4 | 5752PP/2R/2D | 2 | 2 | 4 | 1, 2 (3, 4 dim) |

All three types have eight input blocks. The editor admits the catalogued
firmware revisions 1.0.00..1.2.99; other revisions are refused. Toolkit
registers one class for 0.0.0..9. Owned native C-Gate 3.4.0.2001 has no IOPE
specification outside the catalogued revisions.

## How Toolkit binds the dialog

IOPE has no `TUnitNodeManagerFactory` registration, so the dialog map records
it as having no static node manager. The `CIS_TfrmIOPE` initialization calls
`TUnitDialogFactory.RegisterUnitDialog('IOPE1R1' | 'IOPE2R2' | 'IOPE2C4',
TfrmIOPE)`. `TddCommonCBusUnit.Initialise` looks the unit type up
case-insensitively with `TUnitDialogFactory.GetUnitDialog`. Load and save go
through `TIOPECGateAgent`, registered with `CGateAgentFactory.RegisterAgent`
for the three unit classes. The same unit-dialog factory also serves
TfrmArchitecturalDimmer, TfrmDMXGateway, TfrmKEYGL5, TfrmPC_RDTS, TfrmSENCT4
and TfrmHydraExample.

## Controls and parameters

| Tab | Control | Parameter | Domain and rule |
| --- | --- | --- | --- |
| Global | Long Press | `LongPressTime` | Ordinal 6..63, *n* × 16 ms. The combo drops 0..5. |
| Global | Global 1/2/3 and Scene ramp rates | `RampRateA/B/C/S` | Ordinal 0..15 (Instant … 1020 secs) |
| Global | Status Report | `StatusReportInterval` | 3..255 |
| Global | Sensor Debounce | `SensorOccupancyDebounce` | Ordinal 0..6 (3 Counts, 0.010 … 0.500 sec) |
| Global | Global 1..4 Recall Level (%) | `Memory1..4` | PercentToLevel of 0..100, or a raw byte |
| Global | Clock generator, Burden | `ClockGenEnable`, `Burden` | Boolean |
| Global | Sensor *n* "Disabled when" On/Off | `Sensor{n}Enabled` | On = 1, Off = 0. The agent inverts the bit on load and save. |
| Global | Sensor *n* enable group | `Sensor{n}EnableGroup` | 0..254, or none (255) |
| Global | Sensor *n* enable application | `Sensor{n}EnableGroupInEnableControlApp` | primary = 0, enable-control = 1 |
| Power Failure | Sensor *n* Enabled/Disabled Recovery | `Sensor{n}EnableStateStoreEnabled`, `Sensor{n}EnabledStartup` | Enabled = (0, 1), Disabled = (0, 0), Restore = (1, 0) |
| Power Failure | Broadcast on power-up, per block | `GroupAssertOnPowerup` bit *b* | Only blocks with a group that a bistable auxiliary input references |
| Power Failure | Channel recovery | `LevelStoreEnable[c]`, `LightLevelOutput[c]` | Level store forces level 255. Level 0..255 or a percentage. |
| Block timer | Expiry Time | `TimerHighByte[b]`, `TimerLowByte[b]` | 0..65535 s (18:12:15), h×3600 + m×60 + s |

Rules reproduced from the original agent:

- **Sensor state recovery.** The load reads Restore when the store bit is
  set, otherwise Enabled when the startup bit is set, otherwise Disabled. A
  save writes both bits from that choice. A stored (1, 1) pair is therefore
  rewritten as Restore, and `show` flags it.
- **Power-up broadcast.** `SaveGroupAssertOnPowerupAttribute` rebuilds the
  byte. It sets bit *b* only when the block is flagged, has a group, and
  `IsBlockAssociatedWithBistableKey(b)` holds: some auxiliary input with
  `BistableAuxiliary{n}` set has block *b* in `Auxiliary{n}BlockAllocation`.
  Enabling an ineligible block is refused. A plan also clears ineligible bits
  that are already set, as a Toolkit save would, and lists this in `derived`.
  An `InputGroupAddress` of 255 is treated as "no group".
- **Output recovery.** `SaveOutputs` writes 255 for each level-store channel.
  Enabling level store sets the level to 255. A level edit is refused while
  level store is on. Channels that share an output group are coupled by the
  recovery frame, so their recovery edits are refused.

The editor changes only the parameters named in a plan. It does not
reproduce these whole-dialog save effects, which `show` reports where
relevant:

- `LightStateMachine` is written false on every save;
- `Pot1/2TimerExpiryCommand` are rewritten from unit state;
- output, logic, block, scene, join and corridor arrays are rewritten.

Not covered by this editor:

- the Scenes, Input Blocks, Sensor Functions, Aux Functions, Environment,
  Output, Status and simplified Zone tabs;
- Join Mode Recovery and Logic Recovery;
- the dimmer recovery delay;
- timer expiry functions;
- `EEPROMLevelStore`, for which no dialog control was found.

## Commands

Offline, from a PP export or a bare mapping with `--unit-type`:

```sh
cbus-toolkit iope-settings show iope.json
cbus-toolkit iope-settings plan iope.json --long-press 40 --ramp-rate scene=2 \
  --sensor 1 --disabled-when on --enable-group 12 --state-recovery restore \
  --output 3 --recovery-percent 50 --block-timer 2=0:10:00 > plan.json
```

Against a native C-Gate PP session. The editor plans, applies, reads back and
verifies. `--dry-run` skips the save:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/30 \
  --dry-run iope-settings --status-report 10 --enable-broadcast-block 1
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/30 iope-settings --plan plan.json
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/30 iope-settings --show
```

Other options are `--status-report`, `--debounce`, `--recall-percent G=P`,
`--recall-level G=RAW`, `--clock-gen`, `--burden`, `--enable-application`,
`--disable-broadcast-block`, `--level-store` and `--recovery-level`.

A saved plan is stale-checked against all owned parameters before any write.
A failed write restores the attempted parameters and nothing is saved. Use
`CBUS_UNITSPEC_DIR` for the decoded specifications.

## Evidence

| Evidence | What it pins |
| --- | --- |
| `research/fixtures/iope-settings-source-review.json` | Sanitized static receipt: the dialog binding, per-class counts, control-to-parameter bindings with original addresses, transforms, unreproduced save effects, exclusions and open points. It records hashes for the executable, map, form resources and specifications. |
| `research/fixtures/iope-settings-native-acceptance.json` | Owned C-Gate 3.4.0.2001 acceptance on loopback |
| `tests/test_iope_settings.py` | Offline rule and CLI tests, and the native test |

The native acceptance covers all three types at firmware 1.2.00, with no CNI
or physical access:

- 27 verified edits and 105 raw PP byte assertions;
- boundary and invalid edits for each control group;
- read-modify-write of shared bytes 0x30, 0x3E, 0x6C and 0x6E, preserving
  neighbour bits;
- preservation of the 87 unrelated parameters;
- save, project save and reload;
- a refusal of an IOPE2R2 unit loaded against the IOPE2C4 schema, leaving
  its values unchanged;
- CLI dry-run preview equal to the offline plan, saved-plan apply and a
  stale-plan refusal.

Open items:

- The On/Off item order of the "Disabled when" radio group is inferred from
  `BooleanInverse = False` and the specification description, not executed.
- Clock generator and burden enable rules.
- Original Toolkit GUI execution and physical controller behaviour.
- Firmware outside 1.0.00..1.2.99, and the tabs listed as not covered.
