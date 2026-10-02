# Multisensor and thermostat Document Project reports

The offline `project document` command and the live read-only `cgate database-document` snapshot workflow recover seven multisensor factory profiles and four thermostat profiles. They require complete saved parameters for every displayed or queried value. They never open the bus, load a programming session, create missing objects or save a project.

| Unit | Firmware factory bounds | Model / agent |
| --- | --- | --- |
| SENPILL | 1.6.00–2.0.00 | TSENPILL / TCBusMultisensorCGateAgent |
| SENPILL | 2.0.01–2.3.9 | TST7SENPILL / TCBusST7MultisensorCGateAgent |
| SENPILL | 2.4–9 | TSENPILLA / TCBusSurfaceMountMultisensorCGateAgent |
| SENPILLA | 0–9 | TSENPILLA / TCBusSurfaceMountMultisensorCGateAgent |
| SENPIRIC, SENPIRIB | 0–9, 2.4–9 respectively | TSENPIRIC / TCBusSurfaceMountPIRSensorCGateAgent |
| SENLLA | 0–9 | TSENLLA / TCBusSurfaceMountLightLevelSensorCGateAgent |
| PC_TSA, PC_TSA5 | 0–9 | TPC_TSA / TPC_TSA5, programmable thermostat agent |
| PC_TSB, PC_TSB5 | 0–9 | TPC_TSB / TPC_TSB5, basic thermostat agent |

Bounds use the original case-sensitive lexical firmware comparisons, not semantic version ordering. Earlier SENPIRIB factories belong to the existing PIR documentors.

## Multisensors

The selected original documentor delegates the entire body to the Neo input documentor: timing table, eight physical key rows, macro and micro functions, controls and the scene appendix. Pro model ancestry alone does not choose the NeoPro action documentor. Secondary application blocks appear in the body and group dependencies, while the inherited ActionSelectorUse chain describes primary recalls and Trigger scenes only.

The SENPILL override recovers Day Move, Night Move, Any Move and Sunset. Assigning those templates sets a zero timer on the first allocated block to 300 seconds before the macro lock check. SENLLA has a different subset: Day/Night/Any movement and raw Trigger templates become Custom. Its default subset also applies to Application 255, unlike SENPILL's explicit unused-only subset. Ordinary keys retain their fresh Scene 1 object; this affects whether the dependency text calls a scene used or unused. The original scene appendix indexes the ramp through the scene number, and that behavior is retained.

Input dependency order is block-major key labels, then Light Level Maintenance for an active maintenance block, then scene references. A maintained block with no ordinary key does not receive a Block (Unused) label. Other dependencies retain the inherited Area/Pro entries, maintenance and occupancy enable groups, Corridor and the broadcast block's actual application/group. BroadcastActive does not suppress its dependency. Pro models deliberately retain both Corridor Link Group and Corridor Link for the same object. Unsupported KeyDisable loads the Enable application255 group; the saved raw KeyDisableGroup is not substituted.

Surface profiles append target, margin, low and high threshold groups. A used target forces the model's margin group to 255 before it is loaded. Threshold behavior 1 selects the low group; other values select the high group, with the opposite reference255. These comparisons are independent of the UI's usage flags.

This is a fresh model projection with no GUI listener that rewrites occupancy macro functions. Active joins, noncanonical scene arrays and missing consumed fields remain explicit refusals. Scene storage requires an exact 80-byte table and eight canonical pointers. Displayed groups and Trigger levels must already exist in the saved snapshot.

## Thermostats

The full body reports Master/Slave, resolved master unit, plant type, programmable UI temperature zone, six flags for every installed zone, guard enable and converted thresholds, fan mode, Heating/Cooling fan operation, direct speed control, speeds/default, delays, programmable schedule flags/groups and five internal relays on the relay models. The original fan table's missing opening row is retained.

Guard thresholds are signed bytes passed through the recovered thermostat temperature conversion with an explicit Celsius or Fahrenheit preference. Fan delays are five-second ticks divided by six and rounded to nearest/even before minute/30-second formatting. Invalid programmable Evap and NonEvap flags normalize to 0 and 1 respectively. Basic scheduling uses RemoteScheduleEnable. The output application comes from inherited Application[0]; ApplicationNumber belongs to a separate C-Bus parameter model and is not an alias.

Input use describes all 14 plant outputs and programmable dampers; basic dampers are unused. Output use describes all five internal relay objects even for a model whose body omits the relay table. Other use follows the HVAC Zone group, setback source routing and schedule Enable application references. The selected thermostat ActionSelectorUse method is the empty base implementation.

Thermostat plant-output loading can allocate or remap missing or generated groups. Input dependencies therefore require Network context and existing ordinary output groups. A group beginning with this thermostat's `[CGnn]` prefix, where nn is the ZoneGroup formatted with at least two digits, remains an explicit refusal. This renderer does not reproduce those allocation side effects or borrow prior model state. Displayed relay/schedule groups must also resolve from the saved snapshot.

A MasterNetworkAddress of 255 selects the current network. A foreign master requires exactly one network with the explicit matching NetworkNumber, independent of its report Address, and an admitted thermostat at MasterAddress. Missing or duplicate numbers, missing units and MasterAddress 255 remain refusals.

The saved native adapter also resolves consumed physical Numbers independently
from exact database Address identity and the source integer report projection.
Distinct values are admitted; ambiguous consumed Numbers and unresolved unknowns
remain marked. See [native report identities](native-project-documentation.md).

## Evidence and remaining acceptance

`research/project_documentor_sensors_static.py` reads the pinned Toolkit 1.18.0.2754 EXE/MAP without executing original instructions. Its receipt, `research/fixtures/project-documentor-sensors-static.json`, binds factory rows, native method spans/hashes, documentor slots, loader guards and current runtime modules. `project-documentor-sensors-literal.json` contains invented complete consumed parameters with independently transcribed body lines, dependencies and action descriptions for all eleven profiles. The focused test module also compares all 65,536 micro-function vectors in six application/subset contexts with independently extracted source registrations.

These are source-derived saved-snapshot reports. Complete original generated-page comparison, full original loader behavior and hardware/device acceptance remain open. The acceptance and protected scopes in issues 72–75 remain open. A recovered body does not establish full Toolkit workflow parity or remove an explicit missing-data refusal.
