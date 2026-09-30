# Toolkit client-side conversion tweakers

Toolkit 1.18 does not use C-Gate `CONVERTUNIT` when it converts a unit. It
creates the replacement unit and copies every same-named agent attribute from
the source. It then applies the tweaker registered for the (source type,
target type) pair and calls the target agent's own conversion hook. Finally,
it issues PP SET only for attributes that are still writable. A failed PP SET
is caught and ignored. This is separate from the native engine described in
[conversion.md](conversion.md).

## Registry receipt

`research/fixtures/toolkit-conversion-tweaker-registry.json` is the
denominator for Toolkit-side conversions. It lists all 292 `RegisterTweaker`
registrations: source type, target type, tweaker class and call site. It
also records each of the 13 classes' recovered rules and the decision for
every pair. The facts come from static inspection of the pinned Toolkit EXE
and MAP, whose hashes are in the receipt. No original code was executed, and
the receipt contains no instruction bytes or specification data.
`research/toolkit_conversion_tweaker_registry.py --validate` checks the
receipt's counts, uniqueness, class coverage and decisions.

| Class | Registrations | Recovered rule | Decision |
| --- | --- | --- | --- |
| TTweakerDIMDN_TO_DIMDU4 | 4 | InterLockingChannel=4; PowerUpDelay takes the aligned MaxDimmingLevel; MaxDimmingLevel=`0 0 0 0` | admitted |
| TTweakerDIMDU4_TO_DIMDN | 4 | InterLockingChannel=0; MaxDimmingLevel takes the aligned PowerUpDelay; PowerUpDelay=`0 0 0 0` | admitted |
| TTweakerInputUnit, TTweakerNeoToKey | 11, 13 | 13 Neo/IR attributes stay at target defaults | refused: target key-input conversion hook not recovered |
| TTweakerKeyToNeo | 98 | as above, plus five attributes, IndicatorFunction 1→2/3→1 and the inherited Learn/CoreKey/NeoPro hooks | 93 classic-source pairs admitted for the fresh 1.2.67→2.5.00 profile; five coupler/auxiliary pairs refused |
| TTweakerDLT, TTweakerKeyToDLT | 117, 15 | eight (or 13) attributes stay at defaults; LabelFlavourLSB/MSB=0; KeyToDLT also remaps IndicatorFunction | refused: DLT agent conversion hook not recovered |
| TTweakerSENPIR, TTweakerSENLL | 16, 2 | renames between EnableGroupAddress/Logic and PIR/PEC enabler groups | refused: sensor agent conversion hook not recovered |
| TTweakerPC_DAL2, TTweakerPC_DAL2B | 2, 2 | swaps the two Application values | refused: no native acceptance yet |
| TTweakerRELDN8_TO_X, TTweakerRELDNX_TO_8 | 4, 4 | source-pinned GroupAddress and LogicGA13–16 repacking | seven pairs admitted; RELDN4 → RELDN8 refused because its four-element source logic cannot satisfy the original eight-element reads |

The refused hooks rewrite values from the Toolkit's in-memory unit model, for
example key blocks, group applications and sensor settings. Pure PP data
cannot reproduce them.

The classic-to-Neo exception below has an independently recovered fresh-target
model lifecycle. It does not generalize to retained/editor targets or to
Neo-to-classic conversion with secondary-application group identity.

## Admitted DIMDN/DIMDU4 conversion

`cbus_toolkit.toolkit_conversion_tweakers` supports the eight pairs of DIMDN8,
DIMDN8F, DIMDN4 or DIMDN4F with DIMDU4, in both directions:

```python
from cbus_toolkit.toolkit_conversion_tweakers import ToolkitTweakerConversion

converter = ToolkitTweakerConversion(client, "DIMDN8", source_spec, "DIMDU4", target_spec)
result = converter.apply("//TEST/254/p/20", 40, target_firmware="2.7.00", target_catalog="L5504D2U")
```

The source unit is only read. The replacement is created at the given unused
database address with native defaults. The model then applies these steps:

1. Walk the target agent's constructor-order attributes. Copy each attribute
   that the source agent also has.
2. Leave `FirmwareVersion`, `SerialNo`, `State`, `UnitType` and `Burden` unwritten,
   because they start immutable. An empty source value also makes its
   attribute immutable.
3. Apply the tweaker's assignments.
4. PP SET the remaining writable attributes that exist in the target
   specification, in attribute order.

The unit is saved with PP `SAVE_TO_SOURCE` and checked in a fresh PP session
against expectations computed from the native target defaults.

Like Toolkit before it readdresses, the copied `UnitAddress` PP is the
source address. The result reports `parameter_address_matches_database`.
This module does not copy tag, description or serial metadata, delete the
source, readdress, save the project file or contact a physical unit. Unsupported
registered pairs, and every pair without a tweaker, raise
`TweakerRefused` with the receipt reason before any C-Gate I/O.

Complete native PP SET rejection replies are recorded and ignored, matching
the original parameter setter. A transport failure stops immediately without
further PP SET or save attempts; an uncertain write is never retried.

Native C-Gate 3.4.0.2001 PP SET truncates an over-long array. A short array
replaces only its leading elements, and sixbit text is upper-cased and padded.
The model relies on this behaviour, and the native test checks it directly.

## Verification

```sh
PYTHONPATH=src:tests .venv/bin/python -m pytest tests/test_toolkit_conversion_tweakers.py -q
CBUS_CGATE_JAVA=... CBUS_LOCAL_CGATE_VENDOR=... CBUS_UNITSPEC_DIR=... \
  PYTHONPATH=src:tests:. .venv/bin/python -m pytest tests/test_toolkit_conversion_tweakers.py -q
```

Owned native C-Gate acceptance ran all eight DIMDN/DIMDU4 pairs on synthetic
units with generated non-default values. Each PP list matched the model with
no PP SET failures, and spot checks confirmed the recovered rules
independently. The source stayed unchanged, and the targets were identical
after project save, close and load. This is database-level evidence only. It
does not execute the original Toolkit GUI and does not program hardware.

## RELDN relay conversion

The same API supports RELDN8 → RELDN12/RELDN4/RELDN8B/RELSM8 and
RELDN12/RELDN8B/RELSM8 → RELDN8. Both original routines have been recovered,
including the eighth registered direction RELDN4 → RELDN8, but that direction
is refused before I/O: native RELDN4 supplies four logic elements while the
original routine unconditionally reads eight. The original string load and
alignment path does not pad them. Fabricating four zeroes would conceal this
undefined original behavior.

For each field's own source array `s`, the zero-based rules are:

| Direction | GroupAddress | Each LogicGA13–16Associations |
| --- | --- | --- |
| RELDN8 → X | `s[1:5] + s[7:11] + [255]*4 + s[12:16]` | `s[1:5] + s[7:11] + [0]*4` |
| X → RELDN8 | `[255] + s[0:4] + [255]*2 + s[4:8] + [255] + s[12:16]` | `[0] + s[0:4] + [0]*2 + s[4:8] + [0]` |

The tweaker assigns GroupAddress then logic 13, 14, 15, 16, rendering decimal
elements with single spaces and no trailing space. PP SET still uses agent
constructor order, in which the logic arrays precede GroupAddress. RELDN4
targets retain the native PP SET truncation to four logic elements; the plan
records the original twelve-element string before native normalization.

RELDN8 uses the marshalling-box agent and RELDN12/4/8B use the full DIN agent.
RELSM8 uses the basic bus-powered agent and has no `InterLockingChannel`,
`RestrikeChannel` or `RestrikeDelay` attributes. Converting from RELSM8 retains
those target defaults. These agents all inherit the empty base
`BeforeUnitConversionSave` hook. The basic constructor makes `Burden`
immutable; this also corrects the inherited DIMDN/DIMDU4 flag.

Relay construction checks the supplied source and target PP shapes before any
I/O, including the explicit RELDN8B → RELDN8 specification alias. Planning
requires complete GroupAddress (16 byte values) and logic (12 Boolean values)
strings and rejects malformed, partial or oversized input. Apply validates the
source values before creating a replacement. These are deliberate safe bounds;
the original unchecked reads and malformed-token fallback are not reproduced.

Literal independent tests cover both transformations, boundaries, constructor
ordering and preserved values. The separate owned native acceptance helper
exercises seven directions, raw PP, source/default preservation, no-op plan
repetition, and project save/close/reload. It also verifies the four-element
RELDN4 source and its refusal before I/O. Static derived vectors are not native
execution evidence. Original Toolkit GUI and physical acceptance remain open.

Evidence and reproduction:

- [Original constructor and array review](toolkit-reldn-conversion-source-review.md)
- [Owned native receipt](../research/fixtures/reldn-tweaker-native.json): seven conversions,
  one refusal, 15 units reloaded, no PP SET rejection and confirmed process cleanup.
- Portable tests: `.venv/bin/python -m pytest -q tests/test_toolkit_conversion_tweakers.py tests/test_toolkit_conversion_reldn.py`
- Native tests: set `CBUS_CGATE_JAVA`, `CBUS_LOCAL_CGATE_VENDOR` and
  `CBUS_UNITSPEC_DIR`, then run `.venv/bin/python -m pytest -q tests/test_reldn_tweaker_native.py`.

The native helper's `NOOP` check sends the C-Gate `NOOP` command and confirms
the target is unchanged. Repeated planning is also unchanged. Applying a
conversion again creates a different replacement; this API does not claim
idempotent replacement or register any self-conversion pair.

## Classic key to fresh Neo conversion

The existing API now admits 93 registered `TTweakerKeyToNeo` directions from
KEY1, KEY2, KEY4, KEYIR1 and KEYIR4. The initial profile requires an actual
source firmware of `1.2.67`, target firmware `2.5.00` and a freshly created
target. The five KEYBC/DINAUX registrations remain refused. Historical Neo
firmware, Neo-to-classic conversion and an existing edited target are outside
this profile.

```python
plan = plan_writes("KEY4", "KEYB4", source_values, set(target_spec.parameters),
                   target_firmware="2.5.00")
converter = ToolkitTweakerConversion(client, "KEY4", source_spec, "KEYB4", target_spec)
result = converter.apply("//TEST/254/p/20", 40,
                         target_firmware="2.5.00", target_catalog="5084NL")
```

Use the target's actual catalogue number. Planning describes the exact fresh
profile in `model_context`; apply checks the database source firmware before
PP loading or target creation. Constructor checks reject mismatched types,
historical `_A` specifications and unsupported array shapes before I/O.

The 35-attribute classic source and 63-attribute NeoPro target preserve original
constructor order. The inherited `InfraRedBank` target attribute is renamed
`IRBank`; it therefore has no same-name classic source and retains its target
default. The tweaker suppresses its original 18 named fields and maps each of
the four IndicatorFunction entries `1→2`, `3→1`, retaining other values. Its
output uses decimal tokens with one trailing space.

The inherited hook chain then runs in original order:

1. **Learn:** the target firmware enables LearnAnyApp and LearnMode. The fresh
   model's current/original learned flags are both false, so LearnedFlag is
   immutable. This is a model initialization fact, distinct from the native
   PP LearnedFlag default of 1.
2. **CoreKey:** a classic source has no second application capability, so the
   dual-to-single rewrite is skipped. GroupAddress becomes source entries
   0–3, four 255 entries, then source entry 4. The output is uppercase,
   two-digit hexadecimal with `0x` prefixes, single spaces and no trailing
   space. IndicatorBrightness becomes writable even though its constructor
   flag was false.
3. **NeoPro:** the non-NeoPro source causes the original 13 IR, disable,
   corridor and application-join fields to retain target defaults.

PP SET follows constructor order. Four-entry key, command and timer arrays
replace only the corresponding target prefix; the remaining target entries
retain native defaults. Unsupported or malformed transformation arrays fail
before creating a replacement.

The [source review](toolkit-key-to-neo-conversion-source-review.md),
[fresh-model lifecycle proof](toolkit-key-conversion-learning-source-review.md)
and [native acceptance](toolkit-key-to-neo-native-acceptance.md) keep original
static evidence separate from the executed C-Gate checks. All 93 directions
passed native acceptance, including raw PP and 98 source/target units after
save/close/reload. Original GUI replacement, retained target history, source
deletion, final readdressing and hardware programming remain separate.
