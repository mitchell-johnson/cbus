# SENLLA complete raw input guard

`cbus_toolkit.senlla_inputs.SENLLAInputs` verifies the canonical SENLLA.xml
provider type and all 93 source-derived effective numeric layouts. Its
`snapshot` binds the SENLLA / 5754PE / 2.4.00..2.4.99 identity and requires all
93 current PP values. This internal guard does not load the owning object
graph, initialize forms, calculate a complete save or open a programming
session.

Numeric values require exact array counts and unsigned effective bit widths,
followed by the provider's own value validation. Boolean and float values
cannot enter numeric arrays. All 21 Typebit fields use the native codec's
one-bit packing, including the original provider fields that omit BitSize and
ArraySkip. The three occupancy masks remain scalar bytes; packed per-bank and
key flags retain their distinct eight-element arrays.

Project and UnitName are representable ASCII sixbit strings. The snapshot
preserves their supplied lexical values; encoding validation does not assert
that a fresh Windows control or metadata callback leaves them unchanged.
That behavior belongs to the owning lifecycle's separately qualified metadata
path.

The immutable snapshot provides detached `parameters` and `as_dict` exports.
Its adapter rechecks mutable provider layouts before every snapshot. Extra
provider/current fields are excluded from this exact 93-field ownership
boundary and remain untouched. The schema contains derived types and numeric
layout facts only, without vendor XML, descriptions or defaults.

The [inherited source fixture](../research/fixtures/senlla-inherited-scalars-source.json)
records those 93 layouts separately from the code. Authored synthetic schemas
exercise missing fields, changed layouts/types, unsigned/count boundaries,
omitted bit metadata, sixbit text and detached exports. Complete ordinary
save, installed-wheel/original/native/physical acceptance and Windows Toolkit
parity remain open in issue41.

The [combined frozen source check](../research/fixtures/senlla-form-input-source-check-20261004.json)
covers nine SENLLA modules at authored commit `8ae5c6fe`: 133 parent
tests, 2,860 separate subtests, zero failures or skips. All 4,062 tracked
inputs remain unchanged. This is source-component evidence; public
whole-unit save and installed-wheel/original/native/physical acceptance
remain open.

The [provider-schema probe](../research/fixtures/senlla-inputs-provider-probe-20261004.json)
admits all 93 authored values against the actual decoded provider: 91
numeric and two sixbit round trips, including all 21 omitted-bit-size
fields. It retains only counts and hashes, without vendor definitions
or defaults, and performs no vendor execution or hardware access.
