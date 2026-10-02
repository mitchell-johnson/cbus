# Light-level, WHAA and DALI project reports

`cbus-toolkit project document` now renders the complete source-derived device
bodies for the following explicit factory profiles. It also reports their
Input/Output/Other group references and action-selector references. These are
read-only projections of saved programming data; the report does not configure
units, read physical sensors, or operate an audio or DALI network.

| Device | Native class and agent | Factory firmware | Projection |
| --- | --- | --- | --- |
| `SENLL`, `PE_CELL` | `TSENLL`, `TSENLLCGateAgent` | `1.00–2.0.00` | Three group roles, exponential threshold conversion, Lux and foot-candle target/margin |
| `SENLL` | `TST7SENLL`, `TCBusST7LightLevelSensorCGateAgent` | `2.0.01–9` | Maintenance/on-off/enable/broadcast groups, zero-key fresh loader, broadcast timer minimum, Lux2550 target and percentage margin |
| `PC_WHAD`, `PC_WHAR`, `PC_WHARB` | Corresponding `TPC_*`, `TCBusPC_WHAACGateAgent` | `0–9` | Automatic/manual zone, matrix/relative zone, control application, both control-group tables |
| `PC_DAL2B`, `PC_DAL2C` | Corresponding `TPC_*`, `TCBusPC_DAL2BCGateAgent` | `0–9` | Both DALI network settings, levels/selectors, ramp/status controls and complete mapping table |

The firmware column records literal factory registrations. It is not a claim
that every firmware version has been exercised on original software or hardware.
The base report retains its existing fields and formatting. Each new body is
constructed as the original sequence of `TStringList` lines, including spelling,
duplicate references and disabled-field behavior.

## Old light-level sensors

The consumed programming fields are `Application`, `TargetLUX`, `Hystersis`
(the original spelling), `LevelGroupAddress`, `OnOffGroupAddress` and
`EnableGroupAddress`. Other usage separately consumes `AreaGroupAddress`.
Displayed groups must resolve in the selected network.

The old sensor scale is `ROUND(25 * e80 ** (byte / 52))`, where `e80` is the
original extended-precision constant, rather than a rounded host-language
constant. The documentor converts `target + hysteresis` and
`target - hysteresis`, then reports their rounded midpoint and full width. Its
margin percentage is capped at 100. Foot-candle values use the original
extended-precision `0.0929368` constant and nearest/even rounding.

The source receipt checks all 766 possible signed threshold exponents from
`-255` to `510` for rounding stability at 60 and 90 decimal digits. This
establishes a bounded formula projection; it is not original executable or
generated-page acceptance. Input usage is `Level Group`; Other usage keeps
`Area Group`, `On/Off Group`, `Enable Group` in order. Output and selector usage
are known empty.

## ST7 light-level sensors

ST7 uses eight loaded block groups. `SecondApplicationBlocks` independently
selects the primary or secondary application for each block. The maintenance
block is `PECFunctionBlock`; the on/off block is always index 2; the broadcast
block is `BroadcastBlock`. Both selected indices must identify one of the eight
loaded blocks. `PECEnablerGroup` remains in the primary application.

`PECTargetLux` is multiplied by 10. `PECMarginLux` is converted to a percentage
with the existing source-derived extended-precision margin calculation; a zero
target reports zero. `TimerHighByte` and `TimerLowByte` supply the broadcast
timer, written as `0h1m1s` without inserted spaces.

The selected class has zero physical and zero effective virtual keys. Its
fresh `InputKeys` collection is empty, so stored key commands and occupancy
masks cannot trigger the inherited five-minute key-template timer default.
Block 4 instead has its own ten-second `TimerMin`: stored values 0–9 load as
10 seconds. Other selected blocks retain zero, and larger values retain their
unsigned sixteen-bit timer. Explicit consumed timer bytes are required.

The selected class overrides the multisensor dependency methods. Input usage
is `Level Group`, then `On/Off Group`; Other usage is
`Light Level Broadcast Group`, then `Enable Group`. Complete application/group
identity controls these comparisons, including duplicate role matches and
unused objects. Active flags do not suppress them. This report does not
consume key, scene, area, corridor or occupancy dependencies. Output and
selector usage are known empty. A saved nonempty scene table is preserved and
does not add report dependencies. These corrections and their source evidence
are detailed in [the ST7 annex](project-documentation-st7-light-level.md).

The separate [multisensor recovery](project-documentation-sensors.md) now
admits seven exact profiles, including `SENLLA`, `SENPILL` and `SENPILLA`.
It binds their own loaded macros, fresh macro overrides and report dependencies;
active joins and unsupported scene states remain explicit refusals.

## WHAA audio units

`UsePnP > 0` selects automatic zone reporting. Otherwise `ZoneNumber` selects
matrix bands 0–7, 8–15 and 16 onward; the displayed matrix and relative zone
are one-based, and the last band's relative zone is capped at 8.

`AlternateApplication` supplies the control application. When it is 255 the
report writes the escaped `CBus Control Application: <Unused>` line and omits
the group tables. Otherwise the Audio Control table consumes volume, bass and
treble groups, and the Source/Dynamic table consumes next, previous, absolute,
Button A and Button B groups.

Other usage additionally consumes `AlternateLanguageGroup`, which does not
appear in the body. Its order is Volume, Bass, Treble, Next Source, Prev Source,
Button A, Button B, Language, Absolute Source. Multiple roles on one group
remain separate. Input, output and action-selector use are known empty from
their selected native base methods.

## DALI gateways

Both models consume two applications. The mapping table uses the secondary
application. Enable/disable error groups are in application 203; full-report
trigger groups and selector objects are in application 202. A used group
requires its stored level or selector **Address** and a matching network level
record; Level Value is retained separately and does not replace that identity.
Unused groups do not consume their hidden level/selector field.

Each network reports live error reporting, refresh minutes, enable/disable
groups and values, full-report group and selector, ramp matching and mapping.
The refresh loader caps stored values at 59 and the report adds one minute.
Stored 255 loads zero plus a separate disabled flag; the documentor ignores
that flag and reports one minute when live reporting is on. Live reporting off
writes `&nbsp; min` and does not consume the hidden refresh value.

Only `PC_DAL2C` uses the status-correction bit and restore-level row. A restore
level is `(raw + 2) * 100 // 255`. When correction is off the report writes its
Off row followed by the loaded DALI-to-C-Bus mapping mode. `PC_DAL2B` omits the
correction row and never consumes the hidden restore field.

`CBusToDali` and `DaliToCBus` must both be explicitly present. The native loader
reads all 256 slots with zero as the short-array default. Its setters clear
earlier duplicate non-255 destinations, so the last index wins independently
in each array, including the hidden index 255. An explicit empty string is a
known array; an absent field is not. The HTML table only enumerates C-Bus groups
0–254. Reciprocal mappings report `1:1 Mapping`; the original misspelling
`Diabled` is retained for other table rows.

The source registers these action addresses:

| DALI network | Unit | Group | Scene | Broadcast | Off |
| --- | --- | --- | --- | --- | --- |
| A | 0–63, displayed Unit 0–63 | 64–79, displayed Group 1–16 | 80–95, displayed Scene 1–16 | 96 | 97 |
| B | 128–191, displayed Unit 0–63 | 192–207, displayed Group 1–16 | 208–223, displayed Scene 1–16 | 224 | 225 |

255 is `Unused`. Unregistered action addresses 98–127 and 226–254 remain
explicitly unsupported rather than acquiring fabricated names.

Output usage follows forward mappings. Input usage requires a reciprocal
reverse mapping and retains the native possibility of an `Unused` action.
Other usage lists A Enable, B Enable, A Disable and B Disable roles in that
order. Action-selector usage can append both networks' full-error-report
descriptions for the same application/group/selector object. It ignores Level
Value and excludes unused trigger groups.

## Evidence and remaining work

The historical [literal vector](../../rust/testdata/vectors/project_documentation_remaining.json)
contains ten complete synthetic units and their independently authored body
lines, group-use results and selector results. It covers old exponential and
unused light-level states, ST7 secondary-application and explicit-idle zero
timers, all three manual WHAA models, automatic WHAA with an unused application,
and both two-network DALI models. Boundary tests cover zone clamping, all DALI
action ranges, mapping duplicate clearing, hidden fields, missing references,
firmware selection. Its bytes remain unchanged. The current ST7
[literal annex](../research/fixtures/project-documentor-st7-light-level.json)
explicitly supersedes its two ST7 expectations; the zero timer on block 4 now
reports ten seconds and usage follows the selected derived methods. Ten new
invented units cover all broadcast selectors, stored active keys and scenes,
coincident roles and unused objects. Current public journeys pin both receipts.

The historical [static receipt](../research/fixtures/project-documentor-remaining-static.json)
binds the exact Toolkit 1.18.0.2754 EXE/MAP hashes, eight factory profiles,
33 source methods and 40 checked facts. It records source method hashes and
derived literals/contracts, without publishing vendor instruction bytes or
private unit specifications. The verifier is
[`project_documentor_remaining_static.py`](../research/project_documentor_remaining_static.py).
It requires explicitly supplied pinned original files and reads them statically.
The current [ST7 source annex](../research/fixtures/project-documentor-st7-light-level-static.json)
checks the effective class slots, zero-key loader and timer callbacks. Historical
evidence is not presented as acceptance of the corrected current implementation.

No original executable, VM, live C-Bus network, audio device or DALI endpoint
was used for this extension. Original full-project loading, retained GUI state,
Windows preferences/locales and generated HTML comparisons remain unaccepted.
[Sensor and thermostat reports](project-documentation-sensors.md)
now have their own bounded loader and report contracts. Wireless, remote and
architectural dimmer recovery is tracked separately. These limits keep the
overall Document Project workflow partial.
