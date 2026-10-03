# SENLLA fresh surface bank frame

`cbus_toolkit.senlla_surface_banks.fresh_surface_banks` accepts eight existing
`BankState` values and eight logical Low/High usage flags. These inputs must
already incorporate the owning raw-load callbacks, including the surface
loader's LowLux=0 assignment for a Low-group bank. The component accepts lux
in multiples of ten within 0..2550 and does not establish that earlier history.

Fresh binding visits the banks in order. Each inactive bank clears its own
Low and High usage flags, then runs the global handler over all eight banks.
For each row still using Low, that handler sets HighLux to 2550; then for that
same row still using High, it sets LowLux to zero. After binding all eight
rows, initialization runs the handler once more.

This order matters for inactive banks. An earlier inactive bank can normalize
a later inactive bank's thresholds before the later bank clears its flags.
The result retains Active, Allowed and EnableGroupOff. Allowed=false with
Active=true disables the checkbox while preserving its active state and usage
flags. Exact lux equality retains independently supplied stored bytes.

The immutable result's `parameters` returns detached post-frame bank arrays
and eight one-bit `BankSwitchGroupUsed` elements. `save_overlay` separately
returns the source surface serializer's indexed writes: a Low-group bank
writes Store2 from its logical **HighLux** divided by ten; a High-group bank
writes Store1=255. The owning save applies that overlay after frame parameters.
Unused indices have no overlay. Global threshold group and behavior remain
owned by the separate surface serializer.

The [source handoff](../research/fixtures/senlla-surface-bank-source.json)
records 60 unique method pins, two DFM hashes, numeric layouts and four ordered
component vectors. Independent review verified every method pin and the code.
Focused checks pass 19 parent tests and 56 separate subtests without skips.
The whole 93-parameter loader/save, public CLI admission, original/native form
execution and hardware acceptance remain open in issue41.
