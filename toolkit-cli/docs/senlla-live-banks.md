# SENLLA live bank stage

`SENLLALiveBanks` is an internal source-owned stage for the SENLLA shared
constructor and normal loading path. It provides eight real bank objects,
their managers and their actual attributes before PP loading. It does not
install a Windows form or establish complete unit-save acceptance.

Construct it while `runtime.phase == 'fresh_constructor'`, before PP loading:

```python
banks = SENLLALiveBanks(
    runtime,
    maintenance_active=late.attribute('LightLevelMaintActive'),
    maintenance_block=late.attribute('LightLevelMaintBlock'),
)
```

Both maintenance attributes must belong to `runtime.unit_manager`. The late
Unit owner and persistent controls use the same objects under `banks.banks`;
they must not construct replacements. Each bank exposes `object`, `manager`,
`block`, `active`, `allowed`, `off`, `high_lux`, `low_lux`, `use_low` and
`use_high`. Its `attributes` mapping uses the retained native property names.
Direct attribute subscribers receive the normal source publication route.
The UseLow/UseHigh attributes have no dedicated callback.

`set_block` assigns the actual reference before activating its tracked
expression. That expression follows the canonical shared block object's
publisher. A block notification first refreshes Allowed from current
maintenance and all current keys, then captures both Store1 and Store2,
then assigns High and Low in that order. Native ByteToLux2550 clamps signed
stored inputs below0 to0 and above255 to2550. If the resulting lux equals the
current attribute, no setter runs, so an original out-of-range stored value can
remain unchanged. Unit updating does not suppress the notification.
Bank updating does suppress it; the same-pointer expression reevaluation on
Bank.EndUpdate does not manufacture a later refresh.

High and Low dedicated handlers hold their bank and current block updating
while setting the corresponding stored byte. They reread the current Block
for each native access, including EndUpdate, then perform the current Active
and opposite-lux clamp. Native integer attributes accept signed32 values.
Formula3 converts lux below zero to byte0, lux above2550 to byte255, and the
remaining values with `ceil(lux / 10)`. The adapter does not invent a tighter
attribute range.

The key kernel calls the attached `runtime.live_bank_dispatch` synchronously:

* `block_changed(index, runtime)` is observation only, because the actual
  tracked bank expression has already delivered the native setter route.
* `occupancy_bank_event(key, runtime)` executes one unequal flag event. The
  kernel must commit that event's current flags before this call, and must
  continue nested and outer flag assignments only after it returns. The bank
  loop reads the actual occupancy InputKey reference before captured Count,
  then reads it again before the current reference item at each ordinal.
  It finds the first current bank Block pointer match, rereads the
  flags before clearing Active, and rereads them again before SetAllowed.
  The aggregate tests Dark, Light, Any, Sunset. The event tests Light, Dark,
  Any, Sunset before Active and Light, Any, Dark, Sunset before Allowed.

The runtime supplies `get_occupancy_flag(key, flag)` for each individual
short-circuit operand and `occupancy_input_key(key)` for those two reference
getter sites. With live occupancy attached, these are the SAME Boolean and
reference attributes created before the banks and before PP loading. The
Boolean getter rearms only its actual attribute and owning occupancy object;
an earlier true operand leaves later flag publication guards untouched.
`current_occupancy_flags` is detached inspection and never supplies a native
predicate. The historical projected runtime retains its explicit stored flag
profile through the same single-flag API. The current live occupancy adapter
admits stable constructor-bound InputKey references; arbitrary rebinding
requires the actual lifetime owner and is explicitly refused there.

The kernel bypasses its older numerical bank transition and feedback route
when this dispatcher is attached. A callback may change flags, references,
stores or subscriptions while another native setter is on the stack. An
unavailable current ordinal or an unbalanced current Block EndUpdate refuses
at that source boundary; the adapter does not replay or replace the callback.

`sync_graph_observation()` updates the older bounded graph without callbacks
only when each bank still points to its corresponding block, both lux
values fit0..2550, and stored values fit0..255. Otherwise it returns false and sets
`graph_observation_available` false. The actual signed32 attributes and
current stored bytes remain available in `snapshot()`. A full owner must
consume those actual objects and must not mistake a stale bounded graph for
native state. Snapshots and graph observation read storage without rearming
native Boolean/reference publication guards.

The numeric source receipt is
[`senlla-live-banks-source.json`](../research/fixtures/senlla-live-banks-source.json).
It records the pinned source methods, constructor facts, source order and
literal vectors. Focused tests use authored shared objects and causal
executors; they do not prove original GUI binding, vendor runtime behavior,
native metadata storage or physical acceptance.

This stage admits the source-established initialized, nondestroying shared
bank/block constructor objects. It does not compose arbitrary target
destruction or external native object-state transitions. Those require their
actual lifetime owner, in addition to the counter and pointer behavior here.
