# Classic coupler to CouplerPro Toolkit conversion source review

The five remaining `TTweakerKeyToNeo` directions use a distinct CouplerPro
constructor and final hook. This independent original-source review pins
source firmware `1.2.67` to target firmware `2.2.00` for a fresh conversion
target, before target programming-parameter hydration. The
[source receipt](../research/fixtures/toolkit-key-to-coupler-conversion-source-proof.json)
records original binary/MAP hashes, checked registration operands,
constructor flags/order, model and agent VMTs, method hashes and hook order.
The [literal vectors](../research/fixtures/toolkit-key-to-coupler-conversion-literal-vectors.json)
separate original assignment strings from the native PP array tail.

This is static source evidence. Original GUI execution, owned native
C-Gate persistence tests and physical programming are separate obligations.
The [separate native acceptance receipt](../research/fixtures/coupler-tweaker-native.json)
records the five-direction database tests; this does not mean every independent
literal vector was executed by the original program or the native server.
Neither the previously implemented relay package nor the 93 classic-to-Neo
profile is changed by this source review.

## Five exact directions

The original initializer at `0x0139DAE8` registers:

| Source | Target |
| --- | --- |
| KEYBC2 | BCN2B |
| KEYBC2 | BCN4B |
| KEYBC4 | BCN2B |
| KEYBC4 | BCN4B |
| DINAUX4 | BCI4A |

Every selected tweaker registration and each of the six class/agent
registration operands was checked against fresh original PE bytes. All six
model registrations have original firmware bounds `0` through `9`; this
wide registry does not broaden the selected lifecycle profile.

KEYBC2, KEYBC4 and DINAUX4 use `TCBusKeyInputCGateAgent`. BCN2B, BCN4B and
BCI4A use `TCBusCouplerProInputCGateAgent`. Their target constructor VMT
slot `+0x0c` resolves to `TCoreBusCouplerInputCGateAgent.InternalCreate`
at `0x0121EF00`; target hook slot `+0xa8` resolves to the concrete coupler
hook at `0x0121F6CC`. Sources do not inherit TCBusNeoInputUnit; targets
inherit TCoreBusCouplerInputUnit, TCoreNeoProInputUnit and TCBusNeoInputUnit.

Native catalogue acceptance separately identifies the target `BCI4A`
request with `BCN4B.xml` and specification type `BCN4B`. That PP alias does
not change the original model class `TBCI4A`, the registered conversion
pair, or its agent. Alias admission must be explicit and backed by the
native catalogue receipt; it must not admit arbitrary mismatched types.

## Constructor inventory

The source agent has the same 35-attribute classic constructor graph as
the prior classic-to-Neo review. An attribute's absence from a source PP
specification does not remove it from that graph. In particular, the
source constructors still have IndicatorBrightness and InfraRedBank even
where native PP has no corresponding parameter. FirmwareVersion, SerialNo,
State, UnitType, IndicatorBrightness and GAVBroadcastFlag start immutable;
the other listed source attributes start mutable.

The target agent contains 64 attributes. It calls the 62-attribute
CoreNeoPro constructor directly, then creates BistableSwitchBlock and
GroupAssertOnPowerup, in that order. Both additions start mutable. Their
create calls are at `0x0121EF43` and `0x0121EFA7`, and their agent offsets
are `+0x1d8` and `+0x1dc`. The target does not call the concrete NeoPro
constructor that adds NightlightColour, so NightlightColour is absent.
RetardationIndex is also absent from this agent constructor inventory,
even if a native PP specification exposes it.

The inherited CoreNeo constructor renames InfraRedBank to IRBank at
`0x00CC9EE9` without moving its constructor position. Classic InfraRedBank
therefore does not align by name to target IRBank. The complete source
receipt lists all 35/64 constructor names, mutable flags, creation addresses
and field offsets rather than inferring them from vendor PP names.

## Conversion hooks and exact strings

The selected pairs share the recovered `TTweakerKeyToNeo` implementation:
it first executes the inherited 13 flag suppressions, then five additional
suppressions, then remaps IndicatorFunction. Each `1` becomes `2`; each `3`
becomes `1`; other parsed integers are unchanged. It clears the attribute
string and appends each decimal token followed by a space, calling the
setter for each intermediate string. Thus `0 1 2 3` becomes `0 2 2 1 `,
including the final space.

CoreKey's secondary-application scrub is inactive because each selected
classic source resolves HasApplication2 to the original constant-false
method at `0x00F344FC`. CoreKey's classic-to-Neo GroupAddress branch is
active and produces:

```text
source[0], source[1], source[2], source[3], 255, 255, 255, 255, source[4]
```

Its reads use the bounds-checked 255-default helper; the selected portable
PP profile still requires the full eight-element source array. The group
setter uses `0x`-prefixed uppercase hexadecimal with minimum width two,
single spaces and no trailing space. Source indices 5–7 are discarded.

The target Learn property resolves to the CoreBusCoupler constant-true
method, and fresh model LearnedFlag and LearnedFlagOriginal both start
false. The resulting learning mutable flags are LearnMode=true,
LearnAnyApp=true and LearnedFlag=false. The
[companion lifecycle review](toolkit-key-coupler-learning-source-review.md)
pins that fresh state and the source/target model hierarchy independently.
Do not substitute a later PP LearnedFlag value for the pre-hydration model
state consumed by this hook.

CoreKey next re-enables IndicatorBrightness: target unit slot `+0x1a8`
resolves to the same original constant-true method at `0x00C9E124` used by
Neo targets. The inherited NeoPro tail then clears its 13 conversion flags.
Finally, the concrete CouplerPro hook calls the entire inherited chain at
`0x0121F6D6`, and explicitly clears IndicatorBrightness's mutable flag at
`0x0121F6E4`. **Final coupler brightness is immutable.** Omitting this last
store would incorrectly import the prior Neo profile's effective flags.

The ordinary CoreBusCoupler `BeforeSaveProgrammingInformation` at
`0x0121F4A8` serializes the BistableSwitchBlock and GroupAssertOnPowerup
model properties. Toolkit alignment calls the separate conversion hook;
that ordinary hook is not dispatched by the recovered conversion path.
There is no source basis for adding those ordinary model serialization
steps to conversion.

## PP and preservation boundary

The native selected source schemas have eight group entries and four
indicator entries; targets have nine group entries and eight indicator
entries. Original tweaker output still has only four indicator tokens.
Native PP applies that prefix and retains the target's four-entry tail;
for the selected target defaults that tail is `3 3 3 3`. This differs from
the earlier Neo defaults and must be checked against raw native PP, not
predicted by reusing the earlier profile's fixture.

BistableSwitchBlock, GroupAssertOnPowerup, RetardationIndex, unrelated PP
fields and unknown extensions retain the target baseline under their
applicable existing conversion rules. Their presence in PP is not an
instruction to synthesize missing source attributes. The two new target
agent attributes have no same-named classic source attributes, while
RetardationIndex is outside both conversion agent inventories.

The literal algorithm expectations and constructor source facts do not
widen firmware, schema, alias, metadata or lifecycle admission. Reused
models, editor history, other firmware and unregistered pairs remain
outside this bounded proposal. C-Gate CONVERTUNIT is a distinct workflow.
