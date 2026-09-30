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
| TTweakerKeyToNeo | 98 | as above, plus five attributes and an IndicatorFunction 1→2, 3→1 remap | refused: same reason |
| TTweakerDLT, TTweakerKeyToDLT | 117, 15 | eight (or 13) attributes stay at defaults; LabelFlavourLSB/MSB=0; KeyToDLT also remaps IndicatorFunction | refused: DLT agent conversion hook not recovered |
| TTweakerSENPIR, TTweakerSENLL | 16, 2 | renames between EnableGroupAddress/Logic and PIR/PEC enabler groups | refused: sensor agent conversion hook not recovered |
| TTweakerPC_DAL2, TTweakerPC_DAL2B | 2, 2 | swaps the two Application values | refused: no native acceptance yet |
| TTweakerRELDN8_TO_X, TTweakerRELDNX_TO_8 | 4, 4 | repacks GroupAddress and LogicGA13–16; element rule not recovered | refused: value rule not recovered |

The refused hooks rewrite values from the Toolkit's in-memory unit model, for
example key blocks, group applications and sensor settings. Pure PP data
cannot reproduce them.

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
2. Leave `FirmwareVersion`, `SerialNo`, `State` and `UnitType` unwritten,
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
source, readdress, save the project file or contact a physical unit. Every
other registered pair, and every pair without a tweaker, raises
`TweakerRefused` with the receipt reason before any C-Gate I/O.

Native C-Gate 3.4.0.2001 PP SET truncates an over-long array. A short array
replaces only its leading elements, and sixbit text is upper-cased and padded.
The model relies on this behaviour, and the native test checks it directly.

## Verification

```sh
PYTHONPATH=src:tests .venv/bin/python -m pytest tests/test_toolkit_conversion_tweakers.py -q
CBUS_CGATE_JAVA=... CBUS_LOCAL_CGATE_VENDOR=... CBUS_UNITSPEC_DIR=... \
  PYTHONPATH=src:tests:. .venv/bin/python -m pytest tests/test_toolkit_conversion_tweakers.py -q
```

Owned native C-Gate acceptance ran all eight admitted pairs on synthetic
units with generated non-default values. Each PP list matched the model with
no PP SET failures, and spot checks confirmed the recovered rules
independently. The source stayed unchanged, and the targets were identical
after project save, close and load. This is database-level evidence only. It
does not execute the original Toolkit GUI and does not program hardware.
