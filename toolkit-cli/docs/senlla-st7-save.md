# SENLLA inherited scalar save component

`cbus_toolkit.senlla_st7_save.ST7SaveState.load` captures inherited light-level
and occupancy power-up states from the original ten LightLevel bytes, store
flags and enable-group logic. The immutable state preserves the raw bytes.
`parameters` then serializes those captured states using explicit current
enable-group logic supplied by the owning lifecycle.

This distinction matters when a fresh frame clears enable-off for an unused
group after power state was loaded. Recomputing power state from the changed
logic would give a different result. Resume preserves the corresponding raw
byte and sets its store flag. Disabled/enabled clears that flag and writes
zero or 255 according to the current logic. Other LightLevel slots are retained.

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
