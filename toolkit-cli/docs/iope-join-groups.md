# IOPE Environment JOIN GROUP component

`IopeJoinGroups` reproduces existing-application first and second JOIN GROUP
selections for IOPE1R1, IOPE2R2 and IOPE2C4 firmware 1.0.00..1.2.99. It stages
only the four group-address parameters at 0x63..0x66. `saved=false`,
`whole_dialog_save=false` and `device_verified=false` remain explicit.

The API is `plan(current, identity=(unit_type, firmware, catalogue),
group_cache=cache, first_group=..., second_group=...)`. At least one selection
is required. `first_group` admits 0..254; `second_group` admits 0..255, where 255
selects the original unused object. Selection order is first, then second.
Use `show(current)` for a read-only raw/effective projection, `apply(session,
plan)` for canonical staging or `configure(session, ...)` to plan and stage.
The CLI and database command use the same component contract.

The cache format is the existing `cbus-iope-environment-groups-v1`:

```json
{"format":"cbus-iope-environment-groups-v1","source":"synthetic declared same-network objects","applications":[{"address":56,"groups":[20,21,23]},{"address":203,"groups":[40,41]}]}
```

Every consumed non-255 group and every target needs positive same-network
object evidence. Object identity is the application/group pair; matching
numeric addresses in different applications do not collide. Source metadata
is caller supplied and is not an independent freshness observation.

Primary Application must be Lighting 48..95. The existing first JOIN GROUP
must be assigned. Each JOIN loads Enable Control application 203 before
Primary when its control field is non-255. Dual-populated raw fields are
refused rather than silently normalized. Assigned first/second groups must
have the same effective application. An unused second group is supported.
The group-save projection initializes all four fields to 255 and writes both
model group addresses into the pair selected by the **first** JoinApplication;
the independent SecJoinApplication does not determine the destination.

The original selectors reject a candidate already used by any of eight
InputBlocksB, the Area group, the opposite JOIN GROUP or the active corridor
link. Blocks are resolved through InputGroupAddress and SecondApplicationBlocks
under primary/secondary Application. AreaGroupAddress (0x68) resolves under
primary. The active corridor object is the CorridorGroupBlock role when
FirstCorridorLinkEnable is true. Both selector filters include that exclusion.
Unused second-group selection takes the original IsUnused fast path before
conflict checks. New group objects are never created by this component.

SetCBusUnit calls the inherited corridor initializer before editing. The
component evaluates the retained `IopeEnvironment` initialization and refuses
any state requiring a corridor change. It therefore needs every Environment
layout plus the AreaGroupAddress byte in its expected snapshot. The entire
snapshot is checked again before staging. Canonical saved plans are
re-derived from their options, so altered dependencies, details or unowned
changes cannot be applied. Staging restores attempted parameters on failure
through the shared PP editor and never calls SAVE.

The source proof covers InternalCreate's object attributes and installed
callback, the model group setters, Environment/IOPE SetCBusUnit expression
bindings, both include-item handlers, first group-change handlers, Area load,
and JOIN load/save group branches. First group-change handlers update UI
colors/enabled controls, including second-selector eligibility. In the admitted
already-assigned first-group state, they introduce no model writes. The excluded
unused-to-assigned path can reach the template-initialization virtual callback.
No separate secondary group-change method is registered.
The group attributes have no model callbacks installed in InternalCreate.
Changing JoinApplication invokes a callback that clears **both** groups; that
application-changing lifecycle is excluded.

This component excludes clearing the first group, changing either application,
complete Environment Save, recovery-bit normalization, input block allocations,
macro/scene setters, scene allocation and physical verification. The complete
SaveJoinModeAttributes writes those other families; preserving them here is
an explicit component projection, not a claim that the complete original
Save executed. Existing recovery and hidden raw allocations remain untouched.

Portable tests cover both applications and all three profiles, address
boundaries, exact object conflicts, ordered release/reselection, second unused,
initialization/identity refusals, stale staging and canonical-plan mutation.
An optional original-source test verifies pinned EXE/MAP bytes, model binding
strings and all vendor parameter layouts. The receipt is
`research/fixtures/iope-join-groups-source-review.json`; source binaries and
vendor specifications remain private and are not committed.
