# Native thermostat scheduling

Two commands expose the accepted native scheduling layers. `cgate thermostat-schedule-levels` previews or creates missing levels in one existing Enable Control network variable. `cgate thermostat-schedule-compose` starts at an existing programmable thermostat unit, reads its six scheduling parameters and the complete application/group/level collection from one project XML snapshot, then composes the captured unit-load, outer-selection and level-creation rules.

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20033 thermostat-schedule-levels \
  //TEST/254/203/1 --action Enable --exclusive-project

cbus-toolkit cgate --host 127.0.0.1 --port 20033 thermostat-schedule-levels \
  //TEST/254/203/1 --action Enable --exclusive-project --apply --backup-project THBAK1

cbus-toolkit cgate --host 127.0.0.1 --port 20033 thermostat-schedule-compose \
  //TEST/254/p/4 --exclusive-project

cbus-toolkit cgate --host 127.0.0.1 --port 20033 thermostat-schedule-compose \
  //TEST/254/p/4 --exclusive-project --apply --backup-project THBAK2
```

The first command reads a preview. `--apply` performs the changes. The fixed actions are `Enable`, `Disable` and the original spelling `Overrd`. A supplied backup name must be a different project and is valid only with `--apply`; otherwise a new random name is generated when applying. `--exclusive-project` declares that the caller controls all editing and reloading of this project. The CLI does not acquire a server-wide edit lock.

The composition command uses `--policy button` by default; `--policy direct` enters the retained outer operation unconditionally. `--application-name`, `--group-name` and `--unused-name` supply bounded native tags for objects that must be created. Preview is read-only. It reports the normalized flags, resolved role identities, missing application/groups/levels, and whether apply would issue a target project save.

## Unit-to-level composition

The unit path is `//PROJECT/network/p/unit`. The selected unit must contain exactly one value for each captured scheduling parameter: `RemoteScheduleOnGroup`, `RemoteScheduleOffGroup`, `RemoteScheduleOverrideGroup`, `RemoteScheduleEnable`, `EvapProgramEnabled` and `NonEvapProgramEnabled`. Application 203 may be absent. Existing NetVars are resolved by byte address; shared role addresses create one group, and all existing groups and levels retain their identities, tags and opaque XML metadata.

Apply repeats the exact project snapshot check before any backup. When mutation is required, it saves the current source, creates a retained backup, rechecks the normalized snapshot, creates the missing Application/NetVar/Level records, and issues exactly one target `PROJECT SAVE`. Close/load verification checks the complete thermostat unit XML shape, all six raw bytes, existing application/group/level metadata, created OIDs, level values and generated labels. The source save used to make the backup is reported separately from the one target save. If the plan is already complete, apply performs no backup or write.

This workflow does not invoke the original inherited unit loader, acquire a server edit lock, open a network or program a physical thermostat. C-Gate collection order is still not claimed equivalent to Toolkit order.

## Behavior

The selected object must already be a NetVar under application 203, at `//PROJECT/network/203/group`. Project names contain 1–8 letters, digits or underscores; network addresses are 0–255 and group addresses 0–254. Every network in the project must be closed with an idle synchronization state. The command does not open a network or create the project, network, application or group.

Existing levels are matched by **Address**, independently of Value. Addresses 1–31 already present retain their values, labels and OIDs; other existing byte addresses are also retained. Missing addresses receive Value equal to Address and the exact original generated scheduling label. For example, address 1 becomes `Sched Enable Zone:unsw`, address 2 becomes `Sched Enable Zone:1`, and address 3 becomes `Sched Enable Zones:unsw,1`. Changing the requested action later preserves labels already present.

Apply rechecks the preview's group identity, metadata, levels and closed-network inventory. If all 31 scheduling addresses already exist, it returns `already_present` without a backup, write or project save. It does not claim fresh persistence verification in this case.

When levels are missing, apply first saves the **whole current project**, including existing pending edits, and copies it to a new backup. It rechecks the source, explicitly selects the project for OID commands, then creates and identifies each missing level before separately setting Value and TagName. A final project save, close and reload precede verification of address membership, values, labels, OIDs and existing metadata. The backup is retained for the caller. A pre-existing backup name is rejected before target level creation.

Native XML stores Address as a child and Value as an attribute. Existing XML metadata and child ordering are compared, with the observed materialization of an empty Level TagsDLT element treated as equivalent. **Native collection order is not claimed:** C-Gate's returned level order may differ from the original retained model, and output reports `native_collection_order_verified: false`.

## Failures and recovery evidence

There is one apply attempt and no automatic retry, rollback, reverse write or backup deletion. A missing or interrupted reply can leave a partial result even when C-Gate applied a write. The result records backup creation, issued level OIDs, confirmed field writes, final-save confirmation and reload verification separately. Stop and inspect that evidence before issuing a new operation.

CLI errors include `thermostat_schedule_evidence`, with a separate CLI phase and nested `native_result`. A failed connection close or output write does not undo a confirmed database save. Native completion and CLI completion therefore have distinct fields. Interruption preserves the first error and available confirmed state; secondary cleanup or evidence errors do not authorize another write.

The group API is `NativeThermostatScheduleLevels(client).plan(path, action, exclusive_project=True)`. The composed API is `NativeThermostatScheduling(client).plan(unit, exclusive_project=True, policy=...)`. Each is followed by `apply(plan, backup_project=...)` on the same manager. Plans are immutable, issued to that manager, checked for tampering and usable for one apply attempt. The manager retains `last_result` and `last_error`. The caller owns the connection lifetime; the CLI supplies that connection handling.

## Verification and remaining scope

Native integration tests use a fresh owned C-Gate 3.4.0.2001 process with six verified loopback listeners and isolated project storage. A separate listening CNI sentinel detects any unintended network connection. Independent XML parsing checks all three actions, preservation of existing and extra addresses, backups, second-action no-ops, stale metadata rejection and actual native partial writes after injected lost Value/TagName receipts. Public CLI subprocess checks cover preview, invalid options, apply and no-op, with direct native XML observations afterward.

The first native adapter pilot failed because project close/reload cleared the command session's current project; the corrected second pilot passed 182 commands and verified backup and project cleanup. The first integration draft separately exposed duplicate sibling fixture tag names; that failed draft is preserved and the fixtures now use distinct names. These findings are separate from product acceptance.

The [combined acceptance fixture](../research/fixtures/thermostat-schedule-native-acceptance.json) records **67 tests passing on each of Python 3.13.14 and 3.10.20**, with zero failures, errors or skips. Each run includes five native integration methods covering eight project/group scenarios; process exit, isolated storage removal and zero CNI connections were verified. All 443 archived input files were hash-checked, with unchanged per-run inputs and actual loaded modules associated with the archive. The tests replay all 14 captured original scheduling outcomes; they perform no fresh original instruction execution. The earlier 17-test retained core and 29-test development checkpoint overlap this result. This is a focused source-tree acceptance, separate from the last complete installed wheel. Full thermostat dialog selection, original service factories, cursor/delay behavior, complete thermostat settings and physical devices are outside this command and remain outstanding in [implementation status](implementation-status.md).

The unit-to-level composition layer adds **14 focused Python 3.13 host tests**: eight manager methods and six public CLI methods. They cover missing and existing applications, shared and distinct groups, 93 missing levels, one target save, no-op apply, one-snapshot preview, stale project/unit/application rejection, input and plan tampering, lost replies, first-error preservation and public dispatch. Its [review record](../research/experiments/2026-09-24/thermostat-native-composition-review.json) pins the source and test files.

The [fresh integrated native acceptance](../research/experiments/2026-09-24/thermostat-native-composition-acceptance.json) adds two tests against one owned C-Gate 3.4.0.2001 process. The manager case created application 203, groups 12/13/14 and 93 levels, used one target save, verified the backup and preserved the exact unit record after save/close/load. The public CLI case created 31 levels in one shared group and then proved a second apply was a read-only no-op. Six loopback listeners belonged to the child process, its storage was removed after confirmed exit, and the CNI sentinel recorded no connections. The earlier seven-case unit read and 67-test level writer evidence remain separate.

Original inherited loading/service factories, complete settings, native collection-order equivalence and physical thermostat behavior remain outstanding.
