# InputUnit conversion learning and hook source review

The ten reviewed non-sensor `TTweakerInputUnit` directions preserve the
aligned GroupAddress and IndicatorFunction strings. The original tweaker
changes writable flags only, and none of the inherited CoreKey group
rewrite branches applies to these models.

The bounded profile is `1.2.67` to a fresh `1.2.67` target for the six
directions between distinct `KEY1`, `KEY2` and `KEY4` types, both
directions between `KEYBC2` and `KEYBC4`, and both directions between
`BCNC4A` and `BCNC4B`. The `SENPILL` self-conversion remains outside
this proof.

The [learning and hook receipt](../research/fixtures/toolkit-input-unit-learning-source-proof.json)
contains seven concrete model VMTs, two agent VMTs and 46 method hashes
checked against original Toolkit 1.18.0.2754 bytes. The companion
[constructor and registration receipt](../research/fixtures/toolkit-input-unit-conversion-source-proof.json)
establishes the actual pair, model and agent registrations. These are static
source facts, separate from native persistence or original GUI acceptance.

## Model predicates and final flags

All seven models resolve HasApplication2 to the constant-false method
`0x00F344FC`. None inherits `TCBusNeoInputUnit` or
`TCoreNeoProInputUnit`. Their learning-property virtual resolves to
`TCoreKeyInputUnit.LearnModePropertiesEnabled` at `0x00C9E014`, which
compares firmware text lexically against `1.2.63`. The exact target
revision `1.2.67` passes.

Target brightness predicates differ:

| Targets | Brightness method | Final writable flag |
| --- | --- | --- |
| KEY1, KEY2, KEY4 | CoreKey `0x00C9E124`, constant true | true |
| KEYBC2 | `0x00F72FB4`, constant false | false |
| KEYBC4 | `0x00F7336C`, constant false | false |
| BCNC4A, BCNC4B | TBCNC `0x00FB4140`, constant false | false |

The target conversion hook is CoreKey `0x00CC9180` for both the classic
key agent and the distinct BCNC4 agent. It invokes Learn first. With a
fresh target, the final LearnMode and LearnAnyApp flags are true and
LearnedFlag is false. CoreKey then skips the secondary-application scrub
because the source HasApplication2 predicate is false. It skips both
Neo/non-Neo group reshapes because neither model is Neo. Its final
brightness flag store at `0x00CC97C5` uses the target predicate above.

The base InputUnit tweaker at `0x012F134C` suppresses 13 named
attributes, in its original order. Only InfraRedBank exists among those
names in the selected 35-attribute agent inventory; missing names are
ignored. There is no indicator remap, array reconstruction or string
reformatting in this tweaker. In particular, the derived KeyToNeo
indicator transformation must not be applied to these pairs.

## Fresh learning history

The seven concrete model constructors are short wrappers around
`TCBusKeyInputUnit.InternalCreate`; BCNC4A and BCNC4B resolve the
TBCNC wrapper. The inherited chain reaches Learn, whose constructor
allocates separate LearnedFlag and LearnedFlagOriginal Boolean
attributes, both false. The wrappers add no learning-state changes.

Both selected agents resolve AgentSave to `0x00CC9A34`, AgentLoad to
`0x00CC9A10` and LoadDatabaseUnitAttributes to `0x00CB8C44`. The
original fresh conversion creates a target, sets its firmware, loads source
programming, creates the target database identity, loads target scalar
attributes, and runs alignment followed by the tweaker and conversion
hook. Target programming hydration occurs later. The scalar load reads
TagName, UnitName, Description, SerialNumber and CatalogNumber; it does
not load learning attributes.

All seven model ResolveChange slots resolve to `0x0076A444`, which only
clears a change marker. It does not lazily load programming parameters.
Thus target LearnedFlag and LearnedFlagOriginal are still false/false
at the conversion hook. Source PP values and target native PP defaults
do not establish or replace this model history. The shared
[fresh-model lifecycle review](toolkit-key-conversion-learning-source-review.md)
details the common original call order; the new receipt rechecks its
method bytes and the concrete dispatch used here.

## Why BCNC ordinary-save defaults do not run

The BCNC4 agent has an additional ordinary
BeforeSaveProgrammingInformation override at `0x0129A594`. It calls
ApplyMicroFunctionDefaults at `0x00FB4214`, ApplyLearnModeDefaults at
`0x00FB44C0`, then the inherited ordinary-save hook. The learning-default
method sets model LearnMode and LearnAnyApplication false. Those actions
would matter for an ordinary editor save, so they cannot simply be
assumed harmless.

The original conversion bypasses that path. AgentSave tests explicitly
for the `ProgrammingParameters` verb at `0x00CB7668` before calling
SaveProgrammingInformation at `0x00CB767A`. That ordinary save method
dispatches the before-save virtual, slot `+0x9c`, at `0x00CBDD63`.
The conversion instead supplies `AlignUnit`, dispatched at
`0x00CB7BA6`.

AlignUnit calls AlignUnitNoSave, then directly calls
ParameterProgrammingLoad at `0x00CC032E`, ParameterProgrammingSetAll
at `0x00CC0338` and ParameterProgrammingSave at `0x00CC0349`.
This path does not invoke SaveProgrammingInformation or the ordinary
before-save virtual. CoreKey AgentSave also skips its subsequent
light-level save when the verb is AlignUnit. Consequently, neither BCNC
default-rewrite method runs during this conversion. The BCNC pair needs
no extra microfunction model context for the reviewed path.

The proof covers the exact fresh-target conversion lifecycle. It does not
generalize to an ordinary BCNC editor save, another firmware profile or
a reused target. Native schema aliasing and save/reload acceptance remain
separate evidence, and original GUI and physical execution are unclaimed.
