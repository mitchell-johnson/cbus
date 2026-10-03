# SENLLA explicit bank transitions

`cbus_toolkit.senlla_banks.BankState` models a preexisting bank in SENLLA's
native formula3 domain, with logical high/low lux, stored levels, Active,
Allowed and EnableGroupOff. Callers supply the owning unit's ordered events
and computed Allowed result. Values cover logical lux 0..2550 and raw bytes
0..255; the component neither constructs an owning unit nor imports a PP
snapshot as a complete loader.

Unequal Active changes can activate a bank even while Allowed is false.
Activation lowers an inverted Low threshold to High. An unequal Allowed
change to false clears Active, while a repeated false assignment has no
callback. High and Low changes write their corresponding stored byte using
ceiling division by ten; an active bank then adjusts the opposite threshold.
Equal integer assignments preserve the existing stored bytes.

A declared block refresh applies Allowed first, captures both raw levels,
then assigns High before Low. An active inverted refresh can therefore raise
High to the captured Low, while raw activation of an already loaded inactive
inverted bank lowers Low to High. These outcomes are distinct. The raw bank
loop assigns Active before EnableGroupOff. `bank_parameters` produces detached
eight-block arrays for these explicit states.

The [static source handoff](../research/fixtures/senlla-bank-transition-source.json)
records 22 method pins and twelve literal state transitions recovered before
implementation. Independent source review verified all 22 pins and the
component's callback order, byte rounding and equality guards. Focused source
checks with the ordinary key and retained
surface components pass 44 parents and 310 separate subtests, with no skips.
The 256-byte-domain loop is one parent test. Original instructions, forms,
vendor services and hardware do not execute in these checks.

This internal component is part of the ordinary-save foundation. Key reference
ordering after application collisions, occupancy and maintenance event scans,
fresh form initialization and the complete 93-parameter transaction remain
owning-lifecycle integration work. No public save action or installed-wheel
release is claimed for this foundation increment. Issue41 and Windows Toolkit
parity remain open.
