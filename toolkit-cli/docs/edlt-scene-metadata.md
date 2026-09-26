# Automatic eDLT SceneManager metadata

The automatic metadata path extends the retained
[eDLT SceneManager](edlt-scene-manager.md) editor for one **KEYGL5 / 5055EDL
firmware 5.5.00** database unit. It derives complete application and group
lists, required lifecycle group facts, Trigger Control level inventories, and
consumed action `DynamicAll` rows from one exact native `DBGETXML` project
snapshot. When retained trigger/action getters reach missing metadata, the plan
projects the exact Trigger Control application, group, and `Level` objects that
the original model requests. A guarded native apply creates them.

Preview a saved PP/project pair without connecting:

```sh
cbus-toolkit edlt scene-manager-plan snapshot.json \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --operations scene-operations.json --validate

cbus-toolkit edlt scene-manager-state snapshot.json \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --operations scene-operations.json --list-groups 1
```

The PP file must exactly equal the selected unit's decoded PP records. The plan
uses `cbus-native-edlt-scene-metadata-plan-v3`; automatic state uses
`cbus-native-edlt-scene-metadata-state-v1`. The plan contains
`planned_creations`, the projected cache, the retained SceneManager PP plan,
and the separate persistence boundaries. Offline planning never writes.

Preview the current closed database project through C-Gate:

```sh
cbus-toolkit cgate unit \
  --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 \
  --dry-run edlt-scene-manager \
  --auto-metadata --exclusive-project \
  --operations scene-operations.json --validate
```

Apply with a reviewed backup name:

```sh
cbus-toolkit cgate unit \
  --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 \
  edlt-scene-manager --auto-metadata --exclusive-project \
  --backup-project SCBACKUP \
  --operations scene-operations.json --validate
```

When creation is required and `--backup-project` is omitted, the command
chooses a `Bxxxxxxx` name. A supplied backup name is valid only on apply.
Automatic mode rejects a physical source, a destination, or a lock address
other than the selected source network. Every project network must remain
closed with synchronization idle. C-Gate has no server-wide project edit lock,
so `--exclusive-project` records an operational precondition the caller must
enforce.

## Exact Trigger Control object creation

The original retained `EDLTScene.TriggerGroup` getter first calls
`CBusNetwork.GetApplicationByAddress(202)` and then
`CBusApplication.GetGroupByAddress(storedTrigger)`. Both use their default
`create=true`; the group call uses `bShowDialog=false`. The nonblank native
branches create these records when needed:

- application address `202`, named `Trigger Control` from the native
  application definition;
- the exact non-255 trigger-group address, named `Group N` in ordinary
  decimal; and
- no stored group for address 255, which remains the managed virtual
  `<Unused>` group.

A fresh original `CBusNetwork` constructor resets the static group auto-add
state to `AutoAddGroupsMessageShown=false` and `bAdd=true`. The automatic
CLI admits that fresh-model state; it does not import a prior Toolkit process
session in which a user declined an unrelated auto-add prompt.

The original retained `EDLTScene.ActionSelector` getter and setter then call
`CBusGroup.GetLevelByAddress` with its default `create=true`. For a missing
nonnegative action, that method sends the requested decimal address through
`AddLevelRequest`. The KEYGL5 native handler calls
`TLevelManager.FindLevelByAddress` with its action-selector naming flag. The
resulting object has:

- application `202` and the selected trigger group;
- `Address` equal to the exact requested action byte;
- `Value` equal to that address;
- `TagName` equal to `Action Selector N`, using ordinary decimal `N`; and
- four default-language blank, image-free variants in the managed model.

The chain can be reached during initial scene load, `get-trigger`, an explicit
`set-action` or `get-action`, copy/validation getters, or the terminal save
getter/fallback. Creations are deduplicated and ordered as application 202,
trigger groups by address, then levels by trigger group and action address.
Later operations in the same plan see every projected object and the level's
four blank `DynamicAll` rows. The planner does not infer text, font, icon, or
image content.

The SceneManager **Add** buttons use different paths. The action button passes
a blank level, scans from address 0 for the first free address, limits that
dialog allocation to 0..254 because address 255 is reserved, seeds editable
`Level N`, and creates only after dialog acceptance. The trigger-group Add
button likewise enters its separate dialog branch. This command does not
emulate either dialog. Exact-address action creation can address 255 because
the original `FindLevelByAddress` path bypasses the blank-dialog allocator.

This automatic creation boundary applies only to Trigger Control objects
reached by retained scene model accesses. A missing required primary or Enable
Control application, a missing scene output group, and broader parent-form
metadata remain unsupported here. A duplicate address/OID, native conflict or
capacity refusal, ambiguous add receipt, or readback mismatch stops the
transaction. Existing applications, groups, levels, and labels are preserved
exactly in the admitted XML model.

## Admitted metadata and image facts

The project and selected-network addresses must be unambiguous. The unit and
every selected-network application, group, and level must have a unique native
OID. Existing `Level` records require canonical byte `Address` and `Value`
fields. The unit identity and all decoded PP values must match the supported
profile. Group 255 exists only as the original in-memory `<Unused>` object when
a consumed lookup needs it.

Empty and `TEXT` `TagDLT` variants produce their exact text with
`image_present=false`. Existing `DYNAMIC` and `FONT` variants depend on project
images; `ICON` depends on Toolkit's local DLTP index. Neither source is present
in `DBGETXML`, so consuming such an existing action fails closed. Use a
separately established caller cache when those image facts are required.

The cache limits remain 256 applications, 4,096 listed groups, 512 lifecycle
group facts, and 8,192 level addresses. Scene operations retain the existing
eight-scene and 64-item boundary. A scene-capacity-stopped edit is review-only
and cannot reach metadata or PP mutation. The native inventory and projected
objects must remain within the 4,096-object transaction bound.

## Backup, save ordering, and failure evidence

Apply accepts one unchanged plan issued by the same transaction. It first
rechecks the exact XML bytes, semantic metadata, PP snapshot, and closed/idle
network inventory. When objects are planned, it performs this order:

1. `PROJECT SAVE` the unchanged source and `PROJECT COPY` it to the retained
   backup;
2. repeat the semantic stale check and select the source project;
3. issue `DBADDSAFE` for application 202, each `Group N`, then each exact
   `Level ... Action Selector N`; resolve one new OID per object and
   `DBSETSAFE !OID/Value N` for levels;
4. read back every created OID, kind, address, and name, each level value and
   blank-label default, and all existing metadata;
5. when PP edits exist, stage and verify them, then attempt one `PP SAVE`;
6. attempt one target `PROJECT SAVE`, then close/load the project; and
7. verify created objects, expected PP, unrelated units/networks, and all
   pre-existing metadata after reload.

`DBADDSAFE`/`DBSETSAFE`, `PP SAVE`, and `PROJECT SAVE` are separate native
operations. There is no cross-operation commit. Before the first applicable
persistence save starts (`PP SAVE` when PP changes exist, otherwise the target
`PROJECT SAVE`), a staging or metadata failure reverses known created OIDs in
level/group/application order, persists the inverse, reloads, and requires the
complete admitted source snapshot. If an add receipt is ambiguous, the command
avoids saving an unidentified object and reloads the source saved before
backup. A failed rollback is reported as uncertain.

After either `PP SAVE` or the target `PROJECT SAVE` is attempted, the command
performs no rollback or automatic retry. A lost save reply, interruption, or
post-save verification failure can leave a partial result. Inspect
`pp_save_attempted`, `pp_save_confirmed`,
`target_project_save_attempted`, `target_project_save_confirmed`, both
`*_outcome_uncertain` fields, `partial_failure_possible`, the per-object
receipts, and `database_persistence`. Only complete readback after any required
reload returns `saved=true`.

If the plan changes PP only, the existing single `PP SAVE` path remains and no
metadata backup or target `PROJECT SAVE` is needed. A true no-op performs no
save.

## Evidence boundary

[`edlt-scene-metadata-evidence.json`](../research/fixtures/edlt-scene-metadata-evidence.json)
pins the managed sources plus the Toolkit executable/map used to establish the
exact creation and allocator paths. Portable tests cover projected plans,
exact names/addresses/values/default labels, native command ordering, initial
and post-backup stale checks, conflicts, preservation, reverse pre-save
rollback, lost PP/project save replies, and interruption evidence. An optional
disposable Schneider C-Gate gate requires the native host, exact unit-spec
directory, and explicit `CBUS_EDLT_SCENE_METADATA_*` variables:

```sh
CBUS_EDLT_SCENE_METADATA_ACCEPTANCE=1 \
CBUS_EDLT_SCENE_METADATA_UNIT=//PROJECT/254/p/20 \
CBUS_EDLT_SCENE_METADATA_BACKUP=SCENEBK \
CBUS_EDLT_SCENE_METADATA_GROUP=42 \
CBUS_EDLT_SCENE_METADATA_ACTION=13 \
CBUS_EDLT_SCENE_METADATA_EXPECT_APPLICATION=1 \
CBUS_EDLT_SCENE_METADATA_EXPECT_GROUP=1 \
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_UNITSPEC_DIR=/path/to/specs \
PYTHONPATH=src:tests python3.13 -m unittest \
  tests.test_edlt_scene_metadata.SceneMetadataTests.test_optional_native_missing_scene_metadata_transaction -v
```

The selected action must be absent. Set either `EXPECT_*` flag only when the
disposable source also lacks that object; application absence implies the
selected group is absent. The gate deliberately leaves the changed disposable
source and retained backup for inspection.

The optional native gate was not enabled for the recorded offline acceptance.
No fresh complete WinForms SceneManager or interactive add dialog was run for
this slice. Full control binding, interactive blank-address creation,
project-image download, physical display behavior, scene learning, and
physical trigger execution remain outside this boundary.
