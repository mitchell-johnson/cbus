# Plain InputUnit Toolkit conversion source review

This review pins ten non-sensor `TTweakerInputUnit` directions with source
and target firmware `1.2.67`, using a fresh conversion target before target
PP hydration. It independently checks original Toolkit 1.18.0.2754 PE/MAP
registration operands, constructor order and flags, model ancestry and
conversion-hook dispatch. No original CPU execution or GUI was used.

The [source receipt](../research/fixtures/toolkit-input-unit-conversion-source-proof.json)
contains hashes and original addresses. The
[independent literal vectors](../research/fixtures/toolkit-input-unit-conversion-literal-vectors.json)
cover byte boundaries, nondefault groups, unchanged indicator codes,
exact already-aligned strings, immutable target preservation and BCNC
ordinary-editor-hook exclusions. These artifacts do not modify the
previous relay, classic-to-Neo or classic-to-CouplerPro packages.

## Registered scope

The original initializer at `0x0139DAE8` registers 11 plain InputUnit
conversions. The selected ten are:

- KEY1 to KEY2 and KEY4; KEY2 to KEY1 and KEY4; KEY4 to KEY1 and KEY2.
- KEYBC2 to KEYBC4 and KEYBC4 to KEYBC2.
- BCNC4A to BCNC4B and BCNC4B to BCNC4A.

The eleventh, SENPILL to SENPILL, remains refused and belongs to the sensor
owner. No other pair becomes admitted merely because its names appear in
this list. The receipt rechecks all ten actual registration calls and
records the excluded sensor call separately.

All seven selected model classes register firmware bounds `0` through `9`.
Those source ranges do not broaden the exact `1.2.67` profile. Native
catalogue evidence separately supplies the BCNC4B alias to `BCNC4A.xml`
and specification type BCNC4A, on either source or target. BCNC4B still
uses its own original model class and registered pair; arbitrary aliases
remain outside this profile.

## Shared constructor graph

KEY1, KEY2, KEY4, KEYBC2 and KEYBC4 use TCBusKeyInputCGateAgent. BCNC4A and
BCNC4B use TBCNC4CGateAgent, which inherits that same constructor. All seven
source and target agent VMTs resolve constructor slot `+0x0c` to
`TCBusKeyInputCGateAgent.InternalCreate` at `0x01215B0C`.

The result is the same ordered inventory of 35 attributes for every
selected source and target. The full receipt expands every inherited
constructor and helper call, including EEPROM fields and the final three
timer helpers. BCNC adds no agent attributes. There is no InfraRedBank to
IRBank rename in this graph.

FirmwareVersion, SerialNo, State, UnitType, IndicatorBrightness and
GAVBroadcastFlag initially have mutable=false; every other listed
attribute initially has mutable=true. LearnedFlag initially is mutable,
but the fresh conversion hook changes that flag later. A native PP
specification can omit IndicatorBrightness or InfraRedBank while the
original agent still constructs the corresponding attribute. PP presence
and constructor presence must remain separate facts.

## Plain tweaker behavior

`TTweakerInputUnit.TweakParameters` at `0x012F134C` makes exactly 13 calls
to its missing-name-safe flag helper at `0x012F12A4`, in this order:

```text
InfraRedBank, EnableNightlight, EnableNightlightControl,
DisableTimerFlash, FirstKeyThrowAway, IndicatorPressedLevel,
TimerDuration, IDBacklightIllumination, PrimaryColour,
EnableNightlightOnPCx, EnableNightlightOnPA6, DisableIR, DisableIRNEC
```

Only InfraRedBank exists in the selected 35-attribute constructor graph.
Its mutable flag becomes false. The other twelve names produce no-ops;
the helper does not create missing attributes.

This method has no value setter calls. It does not invoke the derived
KeyToNeo implementation, remap IndicatorFunction, pad or rearrange
GroupAddress, or append a trailing space. For example, already-aligned
IndicatorFunction `0 1 2 3` remains exactly `0 1 2 3` through this phase.

## Actual target hooks

Every selected target agent resolves conversion-hook slot `+0xa8` to
`TCoreKeyInputCGateAgent.BeforeUnitConversionSave` at `0x00CC9180`.
Neither the NeoPro nor CouplerPro conversion hook runs.

CoreKey first invokes the Learn hook. The separately reviewed
[fresh model lifecycle](toolkit-input-unit-learning-source-review.md)
establishes LearnedFlag=false and LearnedFlagOriginal=false; at firmware
`1.2.67`, the resulting learning mutable flags are LearnMode=true,
LearnAnyApp=true and LearnedFlag=false. That decision uses model state
before target PP hydration, not a later target PP flag.

Every selected source's HasApplication2 resolves to the constant-false
method at `0x00F344FC`; the secondary-application scrub is therefore
inactive. Every selected source and target is outside the TCBusNeoInputUnit
ancestry, so both the classic-to-Neo and Neo-to-classic group rewrite
branches are inactive. GroupAddress and IndicatorFunction remain unchanged
by this hook as well as the plain tweaker.

The final CoreKey action assigns IndicatorBrightness.mutable from the
actual target model's virtual property:

| Target | Resolved method | Result |
| --- | --- | --- |
| KEY1, KEY2, KEY4 | CoreKey method at `0x00C9E124` | true |
| KEYBC2 | TKEYBC2 method at `0x00F72FB4` | false |
| KEYBC4 | TKEYBC4 method at `0x00F7336C` | false |
| BCNC4A, BCNC4B | TBCNC method at `0x00FB4140` | false |

Each reviewed method is a constant return with no firmware comparison.
The constructor's initial false brightness flag is therefore re-enabled
only for the three ordinary key targets.

## BCNC ordinary save hook is outside conversion

TBCNC4CGateAgent has an ordinary `BeforeSaveProgrammingInformation` hook
at `0x0129A594`. It calls ApplyMicroFunctionDefaults at `0x0129A5A3`,
ApplyLearnModeDefaults at `0x0129A5B0`, and the inherited ordinary save
hook afterward. That routine is distinct from the conversion hook.

The recovered AlignUnit path invokes AlignUnitNoSave and its conversion
hook, then directly performs target PP load, set and save. It does not
dispatch the ordinary before-save hook. Consequently neither BCNC default
application belongs in conversion, and BCNC group, indicator and other
source-aligned programming values must not be rewritten by those routines.

## Preservation and acceptance

InfraRedBank and GAVBroadcastFlag retain the target PP baseline under their
final immutable flags. Coupler brightness remains immutable. Unknown PP
fields, metadata and other unrelated values retain the existing workflow's
preservation behavior. No constructor graph change can be inferred solely
from a native PP field's presence or absence.

Static source facts and literal preservation vectors do not prove native
C-Gate persistence, original GUI behavior or physical programming. The [separate native acceptance receipt](../research/fixtures/input-tweaker-native.json)
records owned plan/apply/raw PP/save-close-reload tests; it does not execute
original Toolkit CPU code or its GUI. Other firmware, retained/editor target state, unsupported schema
shapes, unregistered pairs and SENPILL remain outside this profile.
