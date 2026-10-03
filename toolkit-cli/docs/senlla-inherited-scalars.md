# SENLLA inherited scalar save ownership

The internal SENLLA scalar component projects eleven inherited fields from a
validated complete 93-parameter snapshot. It preserves the raw snapshot and
does not provide a public programming command or a complete ordinary save.

`load_inherited_scalars(snapshot)` loads debounce and long-press ordinals in
0..63, both ramp ordinals, EEPROM level-store and the NeoPro IR bank and enabled
flags. Ramp bytes 0..15 retain their ordinals; 16..254 become 15 and 255 becomes
1. NeoPro's final IR serializer preserves bank 0..3 and both disable bits. The
separate `initialize_global()` phase changes status intervals 0..2 to 3 and
preserves 3..255. Serialization before this phase retains the loaded interval;
the full fresh lifecycle must call the phase at its source position.

`parameters(metadata=ScalarSaveMetadata(...))` requires the actual final
Project.TagName, selected unit.Address and unit.CBusUnitName. The Project writer
does not use Project.Name or the unit.Project property loaded from PP. Both
text writers uppercase the supplied owning strings; address comes from the
supplied actual unit address. This bounded component requires representable
ASCII text of at most eight characters and preserves spaces and punctuation
before uppercasing. Fresh UnitName cleaning, tag fallback and framework control
casing are separate owning phases; these arguments do not prove their execution.

All 93 fields have explicit ownership in `CLASSIFICATION`. Thirteen fields are
outside this agent's changed, programmable PPSET writes: eight have no created
matching attribute, the three Learn fields are nonprogrammable for SENLLA,
SerialNo is protected, and PatchEnable is nonprogrammable. Their detached raw
baseline remains available through `non_sent_parameters()`. In particular,
EEPROMCheckSumActive is an unsigned byte without a created Boolean attribute;
values greater than one are not coerced. The canonical agent's CRC parameter
name is blank, so its optional CRC update does not target these checksum fields.
This describes the Toolkit PP projection, not device-maintained bytes after
physical persistence.

The remaining fields belong to application/group, eight-key, block/power,
Scene, occupancy, bank and Surface components. CoreNeo's key serializer owns
all eight IndicatorBlockAssignment entries; the later indicator hooks and ST7
and Surface tails do not overwrite index 0 or the array. Delegation does not
imply raw preservation: those owners must apply their established callback and
save order. Conversion-only forced parameters remain outside ordinary save.

The path-free source receipt is
`research/fixtures/senlla-baseline-scalars-source.json`. It retains numeric
classification, enum headers, method hashes and literal vectors from static
analysis of the pinned original. No original instructions, original GUI or
physical endpoint executed; full Toolkit parity remains open.
