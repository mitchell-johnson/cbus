# Thermostat optional remote Level source review

The [static receipt](../research/fixtures/thermostat-remote-levels-source-review.json)
and [reproducer](../research/thermostat_remote_levels_static.py) pin the
accepted and declined missing-Level branches in the thermostat parent
validators. They extend the
[remote-reference source review](thermostat-remote-references-source.md):
the same raw candidate, family, firmware, application binding, ordered group
getters and remote validation remain prerequisites.

The reproducer reads the pinned original EXE/MAP. It publishes hashes, method
bounds and checked instructions, without committing original bytes or private
paths. It executes no original instructions, emulator, GUI, C-Gate or hardware.

## Optional parent outcomes

The base `TddThermostat.ValidateProgramming` at `0x11320c0` reaches the setback
prompt only while its current validation result is true, the setback source
is positive, and `RemoteSetbackLevelsRequired` reports missing addresses.
It calls error/dialog ID 2688 (`0xa80`) at `0x1132556`. Only return value **1**
calls `CreateRemoteSetbackLevels` at `0x11325d0`. Every other result skips the
additions and preserves the current validation result. Declining these
additions does not cancel the settings save.

The programmable validator at `0x11334c0` first calls the whole base validator
at `0x11334cc`. If that succeeds, it checks schedule group uniqueness,
non-unused schedule roles and all five remote identities. Only then does it
check derived schedule enable and `RemoteScheduleLevelsRequired`. Error/dialog
ID 2687 (`0xa7f`) is called at `0x1133608`; only result **1** invokes scheduling
creation at `0x1133619`. Other results again preserve the validation result.
The basic thermostat has no programmable scheduling prompt.

For an admitted final state, the optional operations therefore run in this
order:

1. Setback prompt, then accepted On and Off Level additions.
2. Schedule prompt, then accepted On, Off and Override Level additions.

The original base validator can already create setback Levels before a later
base or derived validation fails. The owned settings transaction validates the
complete admitted plan before mutation. Its prompt receipts describe explicit
outcomes within that bounded transaction; they do not claim the original
invalid-form mutation history, complete validation, displayed dialog buttons,
or control callbacks.

## Detection, reuse and names

Both required predicates call `ZoneLevelsExist` (`0xfda7a4`), which tests
addresses **1 through 31** in ascending order using
`FindLevelByAddress(address, false, false)`. The first absent address makes the
role incomplete; the first incomplete eligible role makes the family require
additions. A complete address set suppresses the prompt even when the stored
Values and names differ from the generated defaults.

The outer helpers skip nil references and groups for which `IsUnused`
(`0xf27e14`) returns true. That method checks only group Address **255**.
Group **0** is an ordinary actionable target. An existing or newly resolved
real `<Unused>` group receives no Levels from these helpers; all of its stored
Levels and other metadata are preserved.

| Role | Exact generated tag prefix |
| --- | --- |
| Setback On | `Setbk Enable ` |
| Setback Off | `Setbk Disable ` |
| Schedule On | `Sched Enable ` |
| Schedule Off | `Sched Disable ` |
| Schedule Override | `Sched Overrd ` |

The trailing space is followed by `LevelToZones(address)` (`0xfda610`). Its
bit order is 1=`unsw`, 2=`1`, 4=`2`, 8=`3`, 16=`4`. A single selected bit uses
`Zone:`, otherwise `Zones:`; selected labels are comma-separated with no
spaces. Examples are `Zone:unsw`, `Zone:1`, `Zones:unsw,1` and
`Zones:unsw,1,2,3,4` at addresses 1, 2, 3 and 31 respectively. `Overrd` is the
original literal spelling.

Each accepted family visits every eligible role in order. Within each role it
visits 1–31 in ascending order and creates only missing addresses. Existing
objects keep their identity, Value, tag, order and complete metadata. Addresses
0 and 32–255 in the Level collection are untouched and do not satisfy any of
the required 1–31 addresses.

Setback source 1 uses the group already resolved under `ApplicationNumber`;
source 2 uses application 203. Neither the setback creation helper nor the
Level constructor has a Lighting-specific branch. Lighting groups therefore
receive the same `Setbk` labels and address/value projection. Application 56
is not a hardcoded substitute for another admitted Lighting application.

The existing parent remote checks still apply. One unused setback role is
allowed, but two non-unused setback roles must differ. All three enabled
schedule roles must be non-unused and distinct. A non-unused group cannot be
shared by setback and schedule within the same application. The same numeric
group address in two different applications identifies different objects and
can receive different labels. The standalone scheduling engine's ability to
revisit shared roles does not make those roles an admissible parent save.

## Original creation and the owning transaction

`TLevelManager.FindLevelByAddress` (`0xf2742c`) returns the first existing
address match before any mutation. For a missing address with creation enabled,
it performs `Add`, sets **Address=N**, sets **Value=N**, assigns `Level N`, saves
the Level and requests a project save. Both thermostat callers pass the final
Boolean argument as false; this selects `Level N`, not `Action Selector N`.
No existing Level is renamed or assigned a new Value.

The caller then replaces the new tag with the role/zone label and saves that
Level again. The setback inner method at `0xfeb130` and the schedule inner
method at `0x1130944` each hold a project save lock around their 1–31 loop,
request a project save if anything was added, and release the lock afterwards.
`EndSaveLock` (`0xf2d384`) flushes a pending request only when the lock depth
reaches zero. These are original object/storage callbacks, not an atomic
database transaction or a guarantee of one native wire command.

The original Level agent (`0x1213a58`) creates kind `Level` for a blank OID,
sets its address, can create a `TagsDLT` child, updates Value and delegates
ordinary attribute saving. The adapter's XML spelling and empty `TagsDLT`
normalization remain separate backend contracts.

The settings workflow must own the resulting graph and PP changes together.
It can use the existing native Level materialization sequence—`DBADDSAFE`
with `Level N`, then `DBSETSAFE Value`, then `DBSETSAFE TagName`—inside that
owner. It must not invoke the separate native scheduling workflow's `apply`
and then invoke settings `apply`. Full source and graph freshness, new OID
verification, complete preservation checks and post-reload verification belong
to the one issued plan. With only missing Levels and no PP delta, the owned
policy remains zero PP saves and one final target-project save. A Level-creation
plan must not be mistaken for a no-op.

The source catches some creation/lock-release exceptions and displays an
error. This review does not reproduce Delphi exception unwinding or authorize
continuation after an uncertain backend operation. Owned failure evidence,
separate save boundaries and the existing no-replay policy remain in force.

## Evidence and focused validation

The new receipt checks the predicates, parent branches, role order, both inner
loops, constructor assignments, exact labels and save-lock transitions. The
earlier retained
[inner scheduling vectors](../research/fixtures/thermostat-schedule-levels-vectors.json)
cover all 31 zone labels, preservation, intermediate `Level N` saves, final
retagging, extra addresses and deferred-save failures. The
[outer vectors](../research/fixtures/thermostat-scheduling-outer-vectors.json)
cover schedule role order and retained shared references. Those historical
captures used declared providers; they do not establish execution of this
combined parent transaction. This work reads them and performs static checks;
it does not rerun original instructions.

Focused implementation checks should cover all four accepted/declined choice
combinations, missing and complete address sets, source 1 on a non-56 Lighting
application, source 2, one unused setback role, real group 0, differing existing
Values/names and unrelated metadata. Repeated valid plans should add nothing
after a completed fill. Invalid remote associations must refuse before writes.
Owned backend checks should bind exact ordered additions, zero-or-one PP save,
one final target-project save, fresh reload, stale/tampered-plan refusal and
no replay after lost save replies.
