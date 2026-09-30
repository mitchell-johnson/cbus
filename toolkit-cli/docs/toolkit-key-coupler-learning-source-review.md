# Coupler conversion learning and hook source review

The five remaining `TTweakerKeyToNeo` directions have a coupler-specific
conversion hook. It explicitly makes **IndicatorBrightness immutable after
the inherited hook enables it**. Copying the classic-key-to-Neo final flags
would therefore be incorrect.

The reviewed directions are `KEYBC2` and `KEYBC4` to each of `BCN2B` and
`BCN4B`, and `DINAUX4` to `BCI4A`. The proposed bounded profile is source
firmware `1.2.67` to a fresh target at `2.2.00`. The
[source receipt](../research/fixtures/toolkit-key-coupler-learning-source-proof.json)
records six concrete model VMTs, the target agent VMT, ancestor references,
55 checked method hashes, constructor facts and hook addresses. It uses
original Toolkit 1.18.0.2754 PE bytes independently of the conversion
implementation. It does not execute the original GUI.

## Concrete models and branch selection

All three source models resolve `HasApplication2` to the constant-false
method `TCBUSUnit.HasApplication2` at `0x00F344FC`. None inherits
`TCBusNeoInputUnit` or `TCoreNeoProInputUnit`. `KEYBC2` and `KEYBC4`
construct through `TCBusKeyInputUnit`; `DINAUX4` passes through the
20-byte `TCBusKeyAuxInputUnit.InternalCreate` wrapper before the same
constructor. Their brightness property virtuals return false, but these
source virtuals are not what the target conversion hook consults.

All three target models inherit `TCoreNeoProInputUnit` and
`TCBusNeoInputUnit`. Their concrete constructors directly call
`TCoreBusCouplerInputUnit.InternalCreate` at `0x00CE6424`.
Their relevant virtuals resolve as follows:

| Target model virtual | Original method | Result |
| --- | --- | --- |
| HasApplication2, slot `+0xf4` | `0x00D066F0` | Constant true |
| LearnModePropertiesEnabled, slot `+0x160` | `0x00CE64F0` | Constant true |
| IndicatorBrightnessPropertyEnabled, slot `+0x1a8` | `0x00C9E124` | Constant true |
| ResolveChange, slot `+0x24` | `0x0076A444` | Clears the change marker only |

The learning predicate is the coupler override. It performs no firmware
comparison. That fact does not by itself admit any firmware outside the
bounded profile.

These class and virtual facts select the inherited CoreKey
classic-to-Neo branch: the secondary-application scrub is skipped, and
GroupAddress becomes source indices `0, 1, 2, 3`, four `255` entries, then
source index `4`. Its format remains nine uppercase `0xNN` tokens with
single spaces and no trailing space. The inherited KeyToNeo indicator
remap and the NeoPro tail of 13 immutable flags are also active.

## Fresh learned-state lifecycle

Target construction follows CoreBusCoupler, CoreNeoPro, Neo, Key,
CoreKey, CustomKey, Input and Learn. The Learn constructor allocates
separate LearnedFlag and LearnedFlagOriginal Boolean attributes, both
initially false. The additional CoreBusCoupler constructor work creates
KeyCouplers and BlockCouplers collections and references existing model
keys and blocks. It does not change those learning attributes.

The concrete coupler agent VMT resolves AgentSave to `0x00CC9A34`,
AgentLoad to `0x00CEBBE4`, and LoadDatabaseUnitAttributes to `0x00CB8C44`.
These are the same independently recovered methods used by the original
fresh conversion lifecycle. The
[common lifecycle review](toolkit-key-conversion-learning-source-review.md)
and the new receipt record the precise calls: factory construction,
target firmware assignment, source-only PP loading, target UnitCreate,
target UnitAttributes loading, same-name agent alignment, tweaker, then
conversion hooks. The target UnitAttributes load reads scalar identity
and descriptive fields, not learning or programming attributes.

Target programming loading and model hydration occur after the conversion
hook. The coupler AfterLoadProgrammingInformation extension at
`0x0121F46C` loads its additional coupler fields after inherited hydration;
it is not invoked by the earlier UnitAttributes-only load. The concrete
target ResolveChange method does not lazily load PP data. Consequently,
the fresh target still has LearnedFlag=false and
LearnedFlagOriginal=false when the Learn hook runs.

Source PP values and later native target defaults are separate from this
model history. A native LearnedFlag value must not replace either fresh
Boolean input. A retained or edited target is outside this proof.

## Final hook order and writable flags

After KeyToNeo tweaking, `TCBusCouplerProInputCGateAgent` dispatches its
BeforeUnitConversionSave at `0x0121F6CC`. It calls the NeoPro hook at
`0x0121F6D6`; NeoPro calls CoreKey, which first calls Learn.

Learn enables LearnMode and LearnAnyApp and disables LearnedFlag for the
fresh false/false history. CoreKey reshapes the group array and temporarily
sets IndicatorBrightness mutable=true from the target virtual. NeoPro
applies its 13 suppression flags because the source is not CoreNeoPro.
Finally, at `0x0121F6E4`, the coupler hook writes zero to the mutable byte
`+0x58` of agent attribute `+0x108`, IndicatorBrightness.

| Attribute | Final mutable flag |
| --- | --- |
| LearnMode | true |
| LearnAnyApp | true |
| LearnedFlag | false |
| IndicatorBrightness | false |

The final brightness suppression preserves the freshly created target's
native value. Missing source PP names, target PP defaults, `BCI4A` schema
aliasing and save/reload persistence need separate native checks; the
source receipt makes no native or physical acceptance claim.
