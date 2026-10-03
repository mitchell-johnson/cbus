# SENLLA inherited scalar save component

`cbus_toolkit.senlla_st7_save.ST7SaveState.load` captures inherited light-level
and occupancy power-up states from the original ten LightLevel bytes, store
flags and enable-group logic. The immutable state preserves the raw bytes.
`parameters` then serializes those captured states using explicit current
enable-group logic supplied by the owning lifecycle. The owning save passes
`current_light_levels` from the preceding CoreKey serializer. Omitting it keeps
the isolated component's original baseline for the earlier source literals.

This distinction matters when a fresh frame clears enable-off for an unused
group after power state was loaded. Recomputing power state from the changed
logic would give a different result. Resume skips an indexed write, preserving
the corresponding **current serializer byte**, and sets its store flag.
Disabled/enabled clears that flag and writes zero or255 at fixed index9 for
light level and8 for occupancy. Every other current LightLevel slot is retained.

CoreKey rebuilds the array using LightIndex: a255 prefix, eight current block
levels and a255 suffix to the loaded length. For index0 its two tail slots
are255 before ST7, even when the original power bytes differ. Index1/2 overlaps
those power slots; index3..255 grows the rebuilt array to11..263 bytes. ST7
accepts that current array without truncation and applies its two fixed indices.
Whole-unit PP schema/programming admission for a grown array remains owned.

The component also captures raw BroadcastActive 1..6 as active, with 0 and 7
inactive. Normal ST7 save serializes active as 4 and inactive as 0, and clears
PotentiometerBBankSwitchEnable unconditionally. These writes belong to ordinary
ST7 save. The SENLL conversion/forced-save helper is outside this component.

The [static inherited source handoff](../research/fixtures/senlla-inherited-scalars-source.json)
pins 50 methods and records 93 effective numeric layouts, eight power literals
and eight broadcast literals. It retains no vendor XML or specification
defaults. Independent review verified every method pin, the inherited scalar
conclusions and this component's code. `save_off` in the literals is supplied
current logic; the power serializer does not write the enable-off field.

Focused source checks with the bank, ordinary-key and retained surface
components pass 54 parents and 375 separate subtests, without skips. The
complete byte/flag power loop is one parent test. No original instructions,
forms, vendor services or hardware execute. This is an internal component
with no public CLI save action or installed-wheel release. The owning
93-parameter initialization/save lifecycle and Windows Toolkit parity remain
open in issue41.

The [combined frozen source check](../research/fixtures/senlla-foundation-source-check-20261004.json)
covers six SENLLA modules at authored commit `3316b13e`: 89 parent tests,
794 separate subtests, zero failures or skips. All 4,047 tracked inputs
remain unchanged. This records source components, without an installed
wheel, public whole-unit save, original runtime or physical acceptance.

The [frozen indexed-block source check](../research/fixtures/senlla-indexed-block-source-check-20261004.json)
covers fourteen SENLLA modules at authored commit `3acca689`: 247 parents,
3,846 separate subtests and zero failures, errors or skips. All 4,086 tracked
inputs remain unchanged in the frozen checkout. Independent reviews clear
the eighteen block method pins, final request component and current-array
ST7 overlay. The 135-pin pre-key schedule is static design evidence. The
key engine, complete owning save/public CLI and installed-wheel/original/
native/hardware acceptance remain open. Full suites are deferred for speed.
