# IOPE Environment corridor controls

`cbus_toolkit.iope_environment.IopeEnvironment` implements the corridor part
of Toolkit 1.18's `TfrmIOPEEnvironment` for IOPE1R1, IOPE2R2 and IOPE2C4.
It admits exact type/schema identity and catalogued firmware 1.0.00 through
1.2.99. A present catalogue number must match the type. This is a bounded
component workflow, not execution of the complete original parent dialog.

The editor exposes `show`, `plan`, `apply` and `configure`. It stages and
verifies PP changes but never saves, programs hardware, or creates groups.
`show` displays raw fields and unresolved metadata warnings. `plan` requires
`identity=(unit_type, firmware, catalog_number)` and caller group evidence:

```python
cache = {
    "format": "cbus-iope-environment-groups-v1",
    "source": "owned disposable project snapshot",
    "applications": [{"address": 56, "groups": [10, 11, 20]}],
}
plan = editor.plan(current, identity=("IOPE2R2", "1.2.00", "5752PP/2R"),
                   group_cache=cache, enabled=True, master_group=20,
                   second_office_enabled=True)
```

The source string identifies caller evidence; it does not verify freshness.
Every consumed non-255 input-block, master or effective join group must have
positive presence in the same-network cache. Omitted groups are refused,
never auto-created. Primary and referenced secondary input applications are
bounded to Lighting 48..95. The primary application must appear even when
its group list is empty. Join loading chooses a non-255 Enable Control (203)
group before its primary-application field. Object comparisons therefore use
application and group identity together. Equal numeric addresses on different
applications do not conflict. Unused group 255 is represented separately.

## Defined edit sequence

A plan performs dialog initialization, then these optional controls in order:

1. `enabled`: main linking checkbox.
2. `corridor_block`: public block number 1..8.
3. `first_office_block`: public block number 1..8.
4. `second_office_enabled`: second-office checkbox.
5. `second_office_block`: public block number 1..8.
6. `master_group`: primary Lighting group 0..254, or 255 for unused.

`None` and omitted options preserve the explicit control; source-derived
initialization and checkbox effects still apply. Disabled controls reject
edits. Changing roles in an order excluded by the original selectors is
refused; this API does not invent a simultaneous role swap.

Original dependent effects are retained:

- Initialization captures the original enabled state and runs the enable
  handler even when linking is disabled.
- On the first enable of an initially disabled dialog, stored corridor and
  first-office indices 0/1 move to 2/3 respectively; second-office indices
  0..3 move to 4. These are public blocks 3/4/5.
- An enable event clears a non-unused master already used by any input block
  or effective join group. All comparisons retain application identity.
- Duplicate active second-office roles are repaired first, followed by a
  duplicated first-office role. The first unused role is the lowest index
  0..7 not equal to any of the three currently selected role indices.
- Disabling linking also disables the second office. The second-office
  click handler runs afterward, even when disabled: it clears a master
  matching the second-office block group and repairs a duplicated second
  role. A direct second-office toggle has the same effects.
- Block selectors exclude other active roles and a block whose non-unused
  group equals the master. The master selector excludes all input-block
  groups and both effective joins. Unused 255 remains selectable.

Only six PP parameters are writable: `CorridorMasterGroup`,
`CorridorGroupBlock`, `FirstCorridorOfficeGroupBlock`,
`SecondCorridorOfficeGroupBlock`, `FirstCorridorLinkEnable`, and
`SecondCorridorLinkEnable`. Stored block indices are zero-based. The masks
are 0xBF at 0x6B and 0x0F at 0x6C; bit 6 of 0x6B and the high nibble of 0x6C
are preserved. Input groups, application selection and join fields are
read-only stale-check dependencies.

Saved plans carry canonical options and are re-planned from their expected
snapshot before application. Altered changes, identity, metadata or derived
claims are refused unless they exactly reproduce a newly valid plan.
Application checks fresh PP values and native schema, verifies readback and
restores attempted staged fields after an error. The enclosing caller owns
metadata freshness and the distinct PP/project save boundary; uncertain
saves must never be replayed automatically.

## Evidence and limits

`research/fixtures/iope-environment-source-review.json` pins fresh original
EXE/MAP and UnitSpec hashes plus method byte-range hashes. The private
method disassembly is retained in the isolated task research directory.
`tests/test_iope_environment.py` provides independent synthetic vectors,
profile and metadata refusal, canonical replay, stale-plan, rollback and
shared-bit preservation checks. Native save/reload evidence is recorded
separately by the owned native workflow test.

Join editing, group creation, timer/function dialogs, block-group edits,
registry/list ordering, original GUI execution and physical controller
acceptance remain outside this slice. Other original whole-form save
normalizations, including LightStateMachine clearing, are not applied.
