# SENLLA explicit occupancy transitions

`cbus_toolkit.senlla_occupancy.OccupancyState` retains the four per-key flags
and two Smart refresh decisions. Raw loading uses the pre-director nil
event-to-template handler. Macro refresh takes explicit handler-installation
and decision facts; a reached decision requires the caller's answer.
Later direct GUI flag edits with the event-to-template handler installed
remain a separate owning-lifecycle path.

Flag setters preserve native equality guards, nested mutually exclusive
movement clears and ordered bank-event snapshots. Equal writes emit no event.
Template34 can seed Sunset before raw banks load; an equal raw Sunset value
then produces no later refresh. Final flags alone therefore cannot reproduce
the bank effects of the load history.

`apply_bank_events` applies explicit snapshots in event/reference order to
eight existing bank states. It examines the current key's flags rather than
aggregating all keys. An occupied event clears Active directly before assigning
Allowed, even if Allowed is already false. A later empty snapshot can allow
the bank without reactivating it. The maintenance dependency is supplied as
explicit current state. `occupancy_parameters` serializes the eight states
into the three one-byte PIR masks.

The [transition source fixture](../research/fixtures/senlla-occupancy-transition-source.json)
records 27 method pins, sixteen ordered raw flag-event vectors and twenty
Smart macro vectors. This internal component introduces no public save action,
fresh form initialization or complete 93-parameter transaction. The owning
loader must replay all contexts, including changing key references and later
decision hooks. Original/native/hardware acceptance and Windows Toolkit parity
remain open in issue41.
