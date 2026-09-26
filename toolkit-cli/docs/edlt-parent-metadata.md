# eDLT parent metadata resolution

The automatic metadata path extends the ordered
[eDLT parent transaction](edlt-parent-transaction.md) for one **KEYGL5 / 5055EDL
firmware 5.5.00** database unit. It reads one exact native `DBGETXML` project
snapshot and derives the applications, groups, dynamic-variant facts, complete
scene-action address sets and 64 static-label records that the retained parent
load and admitted operations consume.
Missing applications and groups are planned in deterministic address order.
The same parent transaction then performs its one load, ordered control phase,
terminal normalization and five-CRC projection.

Preview with saved inputs and no connection:

```sh
cbus-toolkit edlt parent-transaction-plan snapshot.json \
  --project-xml project.xml \
  --unit //PROJECT/254/p/20 \
  --operations operations.json
```

The PP snapshot must exactly match the selected unit's PP records in the
project XML. This guard prevents an old PP export from being combined with a
new application/group inventory. The returned
`cbus-native-edlt-parent-metadata-plan-v1` document includes:

- the project XML and canonical PP SHA-256 values;
- the original lifecycle requirements and the derived projected cache;
- every planned Application, Group or Enable `NetVar` creation;
- a complete, indexed inventory of all 64 static-label slots;
- the nested ordered parent transaction and its ownership/save phases; and
- the native persistence and evidence boundaries.

Preview the current closed database project through C-Gate:

```sh
cbus-toolkit cgate unit \
  --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 \
  --dry-run edlt-parent-transaction \
  --auto-metadata --exclusive-project \
  --operations operations.json
```

Review the project identity, hashes, `planned_creations`, `metadata_cache`,
static-label inventory and nested parent transaction before applying. To apply
with an explicit new backup name, omit `--dry-run` and add:

```sh
  --backup-project PARENTBK
```

The project must remain exclusively owned by the caller and every project
network must be closed with synchronization idle. The implementation does not
acquire a server-wide project edit lock, so `--exclusive-project` is an
explicit operational precondition rather than a lock command. `--lock-address`
must exactly name the network containing the selected source unit.

## Admitted native facts

The XML must contain exactly the selected project, unique byte-addressed
networks and units, and one selected unit with the exact profile identity.
PP names, application addresses, group addresses, level addresses and native
object IDs must be unique. Object IDs must be canonical UUIDs. Ambiguity or a
stale PP snapshot stops before backup or mutation.

The original `EDLTUnit.AfterLoadPPData` resolves the primary application,
loads `StaticTextString0` through `StaticTextString63`, loads scenes and
widgets, constructs dependent group controls, and finishes with group checks.
The original `CBusNetwork.GetApplicationByAddress` and
`CBusApplication.GetGroupByAddress` invoke their add callbacks when the
referenced object is absent. This path implements the database-only,
deterministic subset of those callbacks:

- missing applications use `Lighting`, `Air Conditioning`, `Trigger Control`
  and `Enable Control` for addresses 56, 172, 202 and 203; another admitted address uses
  `Application N`;
- missing ordinary groups use `Group N`;
- application 203 groups are created as native `NetVar` records;
- applications are created first by address, then groups by application and
  address; and
- group 255 is the original in-memory `<Unused>` record and is never created
  in the database.

Existing group level children supply the complete action-address set needed by
retained scene loading. A missing consumed scene trigger group is rejected,
because creating an empty group would discard its action while reproducing the
original level auto-add would require a separate evidenced naming/value policy.
This feature does not synthesize missing scene levels.
The 64 static labels are PP arrays in the selected unit, not application/group
objects. The parent transaction's existing allocator remains their only
writer.

The operation resolver adds the exact groups introduced by Lighting, Enable,
Fan, HVAC, Multi Level, Room Courtesy, Shutter, Timer, activation, Colours,
Navigation, Quick Status and Page Control operations before the nested parent
plan runs. This includes application 172 HVAC groups and application 203
`NetVar` records. Scene widget operations select retained scenes, so their
trigger/output dependencies remain owned by the retained scene load.

`CBusGroup.PopulateDynamicAll` always constructs four default-language
variants. Empty and `TEXT` variants have no image, so their four false image
facts are derivable from project XML. `DYNAMIC` and `FONT` variants depend on
downloaded project image files; `ICON` depends on Toolkit's local DLTP image
index. Those files are not part of `DBGETXML`. If the retained parent load or
an effective dynamic widget/navigation binding would consume one of those
image states, automatic resolution fails closed instead of guessing. Known
text/icon facts must agree with the effective dynamic display type. The
caller-cache path remains available when separately obtained image facts are
required.

## Save and rollback boundary

C-Gate does not expose one commit primitive spanning database object creation,
PP SAVE and PROJECT SAVE. Output therefore always reports
`batch_atomic=false`. An apply performs this sequence once:

1. re-read the exact project XML and closed-network state;
2. `PROJECT SAVE` the source and create a distinct project backup;
3. recheck the admitted semantic source;
4. create the planned metadata in memory and verify returned object IDs;
5. open one database-only PP session and apply the issued parent plan;
6. verify complete PP readback and issue one `PP SAVE` to the source unit;
7. issue one target `PROJECT SAVE`;
8. close/load the target project and verify the exact application/group
   address inventory, created identities, existing application/group metadata,
   unrelated project/unit/network metadata and all PP values.

If creation or PP staging fails before PP SAVE starts, the manager deletes the
created object IDs in reverse order, saves the inverse operations, closes and
reloads the target project, then verifies the admitted source. Evidence records `rollback_attempted` and
`rollback_verified` separately.

Once PP SAVE starts, a failed or interrupted reply can mean the unit record was
already written. The manager does not retry, delete metadata, restore the
backup or close/reload the project. Evidence keeps
`pp_state_uncertain=true`, `database_state_uncertain=true`, the backup name,
save-attempt flags and `automatic_retries=0`. A later PROJECT SAVE or reload
failure is also reported as a potentially partial operation. A confirmed PP
SAVE followed by a lost PROJECT SAVE reply keeps `pp_state_uncertain=false`
while marking database persistence uncertain. Every failed apply returns
`saved=false`; only complete post-reload verification returns `saved=true`.
Recovery is a separate operator decision after inspecting the target and
backup.

## Evidence boundary

[`edlt-parent-metadata-evidence.json`](../research/fixtures/edlt-parent-metadata-evidence.json)
pins the inspected Toolkit 1.18 source hashes and the exact original methods
that establish application/group auto-resolution, virtual group 255, level and
TagDLT population, and static-label load ordering. Portable tests use a native
command-shaped project simulator to verify planning, preservation, creation,
save/reload, rollback and lost-reply evidence. An optional native gate requires
an explicitly provisioned disposable closed project:

```sh
CBUS_EDLT_PARENT_METADATA_ACCEPTANCE=1 \
CBUS_EDLT_PARENT_METADATA_UNIT=//PROJECT/254/p/20 \
CBUS_EDLT_PARENT_METADATA_BACKUP=PARENTBK \
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_UNITSPEC_DIR=/path/to/specs \
PYTHONPATH=src:. python3.13 -m unittest \
  tests.test_edlt_parent_metadata.ParentMetadataTests.test_optional_native_database_metadata_parent_transaction -v
```

That optional gate was not run for the committed portable acceptance. The
original WinForms parent form, add dialog, refresh timing, project image
download and a combined transaction against Schneider C-Gate remain
unexecuted for this slice. No physical unit is opened or programmed, and
physical display, label and event behavior remain unverified.
