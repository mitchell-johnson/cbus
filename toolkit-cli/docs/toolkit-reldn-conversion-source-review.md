# RELDN Toolkit conversion source review

The relay conversion rules and constructor/hook chain were independently
checked against Toolkit 1.18.0.2754 on 2026-09-30. This is static source
evidence. No original Toolkit GUI, device or household project was used.
The sanitized [source receipt](../research/fixtures/toolkit-reldn-conversion-source-proof.json)
contains source hashes, method interval hashes, original call addresses,
constructor order and flags. The [literal vectors](../research/fixtures/toolkit-reldn-conversion-literal-vectors.json)
are independent expected strings, with byte boundaries, different logic
fields, preservation obligations and short-input refusal cases.

## Registered rules

The original initializer at VA `0x0139C510` registers RELDN8 in both directions
with RELDN12, RELDN4, RELDN8B and RELSM8. The four forward calls are at
`0x0139C534`, `0x0139C550`, `0x0139C56C` and `0x0139C588`; the four reverse
calls are at `0x0139C5A4`, `0x0139C5C0`, `0x0139C5DC` and `0x0139C5F8`.

Using zero-based source indices and half-open slices:

| Direction | GroupAddress | Each LogicGA13–16Associations |
| --- | --- | --- |
| RELDN8 → X | `s[1:5] + s[7:11] + [255]*4 + s[12:16]` | `s[1:5] + s[7:11] + [0]*4` |
| X → RELDN8 | `[255] + s[0:4] + [255]*2 + s[4:8] + [255] + s[12:16]` | `[0] + s[0:4] + [0]*2 + s[4:8] + [0]` |

The actual routines are `TTweakerRELDN8_TO_X.TweakParameters` at
`0x012EDE28` and `TTweakerRELDNX_TO_8.TweakParameters` at `0x012EF138`.
Each field reads its own aligned string. Both setters execute in the order
GroupAddress, LogicGA13Associations, LogicGA14Associations,
LogicGA15Associations, LogicGA16Associations. `IntToStr` and immediate
space fragments produce decimal values separated by single spaces, without
a trailing space. Group output has 16 entries; each logic output has 12.

That setter order is distinct from PP SET order. The original alignment and
PP SET passes enumerate the target agent's constructor order, which places
the four logic attributes before GroupAddress.

## Agent construction and conversion hook

| Types | Registered agent | Constructor inherited at VMT +0x0c |
| --- | --- | --- |
| RELDN8 | TMarshallingBoxCGateAgent | TDinRailOutputCGateAgent.InternalCreate |
| RELDN12, RELDN4, RELDN8B | TDinRailOutputCGateAgent | TDinRailOutputCGateAgent.InternalCreate |
| RELSM8 | TBusPoweredDinRailOutputCGateAgent | TBasicDinRailOutputCGateAgent.InternalCreate |

The complete constructor inventory has 32 attributes for full DIN and 29
for the basic DIN agent. RELSM8 therefore has no InterLockingChannel,
RestrikeChannel or RestrikeDelay attributes. Their presence in a PP
specification would not make them source agent attributes.

The common constructor starts FirmwareVersion, SerialNo, State and UnitType
immutable. The basic DIN constructor explicitly clears Burden's mutable flag
at `0x0122CC7C`, after constructing that attribute. All other listed agent
attributes start mutable. `TFlashAttribute.Create` at `0x007EC504` stores its
mutable argument at attribute offset `+0x58`; this establishes the flag's
meaning independently of its use by the conversion planner.

The three agent VMTs all resolve `+0xA8` to
`TCGateAgent.BeforeUnitConversionSave` at `0x00CAC4F8`. That method is empty.
The ordinary DIN `BeforeSaveProgrammingInformation` routine is a different
hook. `AlignUnit` calls AlignUnitNoSave, PP load, PP SetAll and PP save
directly; it does not dispatch the ordinary before-save hook. Burden's
ordinary before-save mutability assignment is therefore not evidence that
conversion makes Burden writable.

## No source-array padding

There is no supported basis for inventing missing source logic entries:

1. `TcgcPPGet.ProcessParameter` at `0x00CB25B4` extracts the name and value
   and passes the value to `TCBusUnitCGateAgent.SetParameter`.
2. `SetParameter` at `0x00CBEA94` selects the same-named attribute and passes
   the value to its string setter. The GroupAddress and logic attributes are
   `TCGateAttribute`, whose getter/setter inherit `TStringAttribute`.
3. `TStringAttribute.InternalSetAsString` at `0x007F37D4` stores the string
   at offset `+0x70`. These constructors install no per-array padding callback.
4. `AlignUnitNoSave` at `0x00CC04A4` copies each same-named source string to
   the target attribute and invokes the tweaker before the target PP load.
5. `StrToIntArray` at `0x007F1228` sizes its int32 array to the token count.
   The tweakers then index it directly without local bounds checks.

GroupAddress therefore needs at least 16 actual source tokens in both
directions. Forward logic reads through index 10; reverse logic reads
through index 7. These are direct-read minima, not permission to use an
arbitrary short vendor specification. A RELDN4 source with four actual
logic entries cannot execute the recovered reverse mapping safely. Refuse
that shape rather than supply guessed zeroes or model undefined memory
contents as original behavior. Target PP truncation occurs later and cannot
repair a short source input.

The review proves constructor order, flag handling, string flow and the
repacking algorithm. Native database acceptance, original GUI behavior and
physical programming are separate obligations. The user-facing conversion
documentation and test receipts record which of those obligations have
subsequently been completed.
