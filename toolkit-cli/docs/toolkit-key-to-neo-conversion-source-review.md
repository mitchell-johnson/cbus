# Classic key to Neo Toolkit conversion source review

This review independently pins the original Toolkit 1.18.0.2754 constructor,
tweaker and conversion-hook behavior for 93 registered classic-key to Neo
directions. It proposes the bounded fresh conversion lifecycle from source
firmware `1.2.67` to target firmware `2.5.00`. Other registry firmware ranges
are source facts, not permission to broaden that lifecycle.

The [source receipt](../research/fixtures/toolkit-key-to-neo-conversion-source-proof.json)
contains executable and MAP hashes, method hashes, original registration
call addresses, all 35 source and 63 target constructor attributes, their
initial mutable flags and the relevant setter/flag-store addresses. Fresh
PE bytes were inspected independently of the production conversion module.
The [literal vectors](../research/fixtures/toolkit-key-to-neo-conversion-literal-vectors.json)
cover group boundaries, nondefault values, exact formatting, repeated setter
order and preservation obligations. Neither artifact executes the original
GUI or establishes native persistence or physical programming acceptance.

## Registered scope and classes

The initializer at `0x0139DAE8` registers 98 `TTweakerKeyToNeo` directions.
The selected 93 consist of:

- Each of `KEY1`, `KEY2`, `KEY4`, `KEYIR1`, `KEYIR4` to each of
  `KEYB2`, `KEYB4`, `KEYB6`, `KEYH1`, `KEYH2`, `KEYH3`, `KEYH4`,
  `KEYM2`, `KEYM4`, `KEYM8`, `KEYA1`, `KEYA3`, `KEYA6`, `KEYA8`,
  `KEYAV2`, `KEYAV4` (80).
- Each of `KEY1`, `KEY2`, `KEY4` to each of `KEYC1`, `KEYC2`, `KEYC4` (9).
- Each of `KEYIR1`, `KEYIR4` to each of `KEYCIR1`, `KEYCIR4` (4).

The four coupler directions and `DINAUX4` to `BCI4A` are outside this
profile. So are reverse `TTweakerNeoToKey` and plain `TTweakerInputUnit`
conversions. Every admitted pair was rechecked at its original registration
call; membership in the lists alone does not authorize any other pair.

All five classic sources register `TCBusKeyInputCGateAgent`. All 21 selected
targets at `2.5.00` register `TCBusNeoProInputCGateAgent`. Their class and
agent registration operands were rechecked for each of the 26 types.
Fresh VMT reads resolve target constructor slot `+0x0c` to
`TCBusNeoProInputCGateAgent.InternalCreate` (`0x012168A4`), and conversion
hook slot `+0xa8` to `TCoreNeoProInputCGateAgent.BeforeUnitConversionSave`
(`0x00CEDC88`). Sources do not inherit `TCBusNeoInputUnit`; targets do.

## Constructor order and flags

Classic construction proceeds through the common unit, Learn, InputUnit
and CoreKey agent constructors, then adds `GAVBroadcastFlag`. The inherited
InputUnit constructor adds AreaGroupAddress before StatusReportInterval.
CoreKey calls its EEPROM helper immediately after LongPressTime, adding
EEPROMLevelStore, LightIndex, LightLevel, LightLevelStore1 and
LightLevelStore2 before RampRate. TimerHighByte, TimerLowByte and
TimerExpiryCommand are its final three helper calls.

NeoPro construction inherits that 34-attribute CoreKey inventory, then adds
12 CoreNeo, four Neo, 12 CoreNeoPro and one NeoPro attribute, for 63 total.
It does not add the classic-only GAVBroadcastFlag. CoreNeo renames the
existing InfraRedBank attribute to `IRBank` at `0x00CC9EE9`; its constructor
position remains unchanged. The complete receipt preserves exact order,
including constructor JoinPrimaryApplication, JoinSecondaryApplication,
DualJoinPrimaryApplication and DualJoinSecondaryApplication order.

The initial immutable common attributes are FirmwareVersion, SerialNo,
State and UnitType. CoreKey also constructs IndicatorBrightness immutable;
classic GAVBroadcastFlag is immutable. All other listed attributes start
mutable. In particular LearnedFlag is initially mutable: the last of its
three pushed flags is zero, but the mutable argument is the **second**
flag, which is one. `TFlashAttribute.Create` stores this argument at
attribute offset `+0x58`.

Constructor flags are not final conversion flags. Alignment can clear the
mutable flag for an empty same-named source value; the conversion hooks
then explicitly override the learning flags and IndicatorBrightness.

## Tweaker and hook sequence

The original order is target same-name alignment, `TTweakerKeyToNeo`,
then the target conversion hook. The NeoPro hook calls CoreKey first;
CoreKey calls the Learn hook first. Target PP hydration follows this
alignment/hook phase. See the separate
[learning-state review](toolkit-key-conversion-learning-source-review.md)
for fresh-target construction, scalar-only metadata loading and learned
history evidence.

`TTweakerKeyToNeo.TweakParameters` at `0x012F16C8` first calls inherited
`TTweakerInputUnit.TweakParameters` at `0x012F134C`. The inherited routine
clears 13 mutable flags, and the derived routine clears five more. The
receipt records their exact order. Both helpers look up the name and skip
missing attributes. Thus an InfraRedBank suppression lookup is harmless
on the renamed Neo target; it is not evidence that IRBank was suppressed.

The derived tweaker then reads IndicatorFunction, maps `1` to `2` and `3`
to `1`, and leaves other parsed integers unchanged. It calls the setter
with an empty string, then once per element with the accumulated decimal
text and one trailing space. Four admitted entries therefore cause five
original setter calls. For example, `0 1 2 3` becomes `0 2 2 1 `, including
the final space. The production PP write may be coalesced, but a receipt
must not confuse that with the number of original attribute setter calls.

The Learn hook sets LearnMode and LearnAnyApp mutable for target `2.5.00`.
Fresh model LearnedFlag and LearnedFlagOriginal are both false, making
LearnedFlag immutable. Later target PP values do not change which model
state the original hook read. Reused target/editor history is excluded.

CoreKey at `0x00CC9180` has a secondary-application scrub branch, but every
admitted classic source resolves HasApplication2 to the constant-false
method at `0x00F344FC`, so that branch is inactive. The classic-to-Neo
branch reads the aligned GroupAddress and constructs this nine-entry array:

```text
[source[0], source[1], source[2], source[3], 255, 255, 255, 255, source[4]]
```

Each source read uses `IntArrayElementWithDefault` (`0x007F0F30`) with a
255 fallback. Its explicit length check is source evidence for missing
indices; the selected portable PP profile nevertheless requires the
complete eight-entry classic source shape. This is different from an
unchecked relay tweaker array read.

The group string uses uppercase hexadecimal, a `0x` prefix, minimum width
two, single separating spaces and no trailing space. Original source
indices 5–7 are discarded. The variant setter executes at `0x00CC9577`.
The core hook then sets IndicatorBrightness mutable from unit slot
`+0x1a8`. All selected targets resolve that slot to
`TCoreKeyInputUnit.IndicatorBrightnessPropertyEnabled` (`0x00C9E124`),
which returns true unconditionally. There is no firmware comparison in
this resolved brightness method.

Finally, because a classic source does not inherit TCoreNeoProInputUnit,
the NeoPro tail clears these 13 mutable flags, in order:

```text
DisableIR, DisableIRNEC, KeyDisableGroup, KeyDisableGroupInvert,
CorridorLinkEnable, CorridorMasterGroup, CorridorGroupBlock,
CorridorOfficeGroupBlock, JoinPrimaryApplication,
DualJoinPrimaryApplication, JoinSecondaryApplication,
DualJoinSecondaryApplication, SecondApplicationBlocks
```

The join order in this hook differs from constructor order. NightlightColour
is initially mutable and is not explicitly cleared by these routines;
alignment, available target values and changed-value checks remain relevant
to whether it is written. Unknown PP fields, metadata and suppressed target
values retain the existing conversion workflow's preservation rules.

## Acceptance boundary

The recovered behavior supports a source-pinned implementation with exact
constructor metadata and hooks. It does not substitute C-Gate CONVERTUNIT
for Toolkit conversion, execute original GUI controls, prove historical
firmware variants, or program hardware. Portable tests and owned synthetic
C-Gate plan/apply/raw PP/save-close-reload results must be reported separately.
The algorithm-only short-array and out-of-range vectors explicitly remain
outside the selected PP schema admission.
