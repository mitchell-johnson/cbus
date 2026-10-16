# SENLLA block values

This internal component consumes an immutable `SENLLAInputSnapshot` containing
all 93 guarded raw parameters. It describes the pre-key block stage and the
CoreKey indexed LightLevel serializer. It does not create a unit, program PP
values or admit a complete Toolkit save.

`block_load_plan(snapshot)` returns a detached `BlockLoadPlan`. Its `requests()`
contains all eight secondary Boolean assignments first, then LightIndex and
the original ten-entry count, then each block in ascending order: indexed
LightLevel, Store1, Store2, unsigned timer word, canonical expiry object,
current expiry membership check and current application/group getter.

The owning executor must complete each request's setter, publication and
callbacks before advancing. It must establish the fresh constructor and
native application/Area objects before this stage. Unit updating does not
suppress block or bank notifications. Raw allocations, later application
normalization and Scene/key/form callbacks occur at later owning positions.

The request protocol is explicit:

- `set` invokes the actual field setter at its source position. Retain that
  field's BeforeChange, equality, publication and callback rules. Equal Boolean
  writes return immediately; Integer BeforeChange still runs and can force a
  write or replace its candidate before validation.
- `get_indexed_level_and_set` rereads the owner's current LightIndex and calls
  `plan.level_for_block(block, light_index=current_index)`, then invokes the
  LightLevel setter. The request's value is the initial guarded projection.
- `set_microfunction` resolves the byte using the native canonical registered
  factory, then invokes the reference setter. Byte 0 is a nonnil type 0 object.
- `check_expiry` reads the current object/function type after the preceding
  setter at `0xcc8357`. It checks the ordered types `[0,15,4,9,12,6,10]` and
  invokes the second canonical type 15 setter at `0xcc83a9` only if unsupported.
  An unexpectedly nil current object is a native invalid-access boundary;
  the executor must not replace it with a guessed type. `loaded_expiry_type`
  provides only the qualified raw-to-membership scalar projection.
- `get_group` rereads the current Secondary flag. True selects the actual unit
  Application2 reference; actual nil selects nil Group, while real app 255
  remains an object. False selects current ApplicationForBlock. The executor
  performs the source create=true getter and group setter using canonical
  manager-owned objects. The request carries no invented application identity.
- `capture` retains the loaded count for the later indexed serializer.

TimerMin, TimerCached and expiry override have constructor values 0, 0 and nil.
They are not additional PP loading writes in this stage. Loaded timer bytes
form unsigned seconds `(high << 8) | low`, so 1/44 means 300 seconds.

`plan.parameters(current_levels, light_index=current_index)` serializes only
LightIndex and LightLevel before ST7 power serialization. Current levels must
contain exactly eight unsigned bytes. The native array is an unused-255 prefix
of current LightIndex entries, the eight current levels, then enough unused-255
tail entries to reach the captured ten entries. Original prefix/tail bytes are
replaced. Indices 0, 1 and 2 produce ten entries; 3 produces eleven, and 255
produces 263. Out-of-range indexed raw reads return 0. The owner must handle or
explicitly refuse this exact growth when enforcing a ten-entry PP schema.

The later ST7 serializer receives this rebuilt array. Fixed power states
overwrite slots 9/8; previous-state branches retain the current rebuilt slots.
Those writes, other block fields, metadata creation and complete lifecycle
orchestration remain separately owned.

The numeric source fixture records the exact method hashes, request positions
and independent indexed literals. Static fidelity and focused Python tests do
not establish original GUI, native persistence or physical-device acceptance.

The [frozen indexed-block source check](../research/fixtures/senlla-indexed-block-source-check-20261004.json)
covers fourteen SENLLA modules at authored commit `3acca689`: 247 parents,
3,846 separate subtests and zero failures, errors or skips. All 4,086 tracked
inputs remain unchanged in the frozen checkout. Independent reviews clear
the eighteen block method pins, final request component and current-array
ST7 overlay. The 135-pin pre-key schedule is static design evidence. The
key engine, complete owning save/public CLI and installed-wheel/original/
native/hardware acceptance remain open. Full suites are deferred for speed.
