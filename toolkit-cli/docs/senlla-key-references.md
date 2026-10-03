# SENLLA ordered key references

`cbus_toolkit.senlla_key_references.SENLLAKeyReferences` retains eight ordered
block-reference lists. `from_masks` establishes direct raw ascending order;
`from_ordered` preserves and validates existing order against optional masks.
The first retained reference supplies the primary block. A saved allocation
mask records membership and cannot reconstruct reference order after moves.

An established collision appends its destination before extracting its source.
For example, references `[1, 2]` become `[2, 0]` when block1 moves to block0.
The saved mask becomes 5, but the primary block remains 2. The ordinary-key
component accepts these ordered rows for timer and recall-store lookups.

Add/remove/transfer/swap return immutable state and ordered mutation records.
Records include intermediate rows, direct refresh requests and conditional
indicator remap requests. Duplicate additions and absent removals have no
refresh requests. The key-updating flag suppresses direct refreshes without
suppressing list mutation. Returned parameter arrays and exported views are
detached.

The [source handoff](../research/fixtures/senlla-key-references-source.json)
pins 64 methods and provides eight association literals plus three qualified
application/collision literals. Independent review reopened all 64 method
pins with zero mismatches and checked the component's ordering and guards.

This is a direct association projection. The owning lifecycle must replay
nested macro, application, bank and Scene callbacks at each event and may need
to re-evaluate later operations if those callbacks change mappings. The
component does not infer a collision destination, group-creation decision,
complete callback replay or whole-unit save. It adds no public CLI action.
Original/native/hardware acceptance and full Windows Toolkit parity remain
open in issue41.
