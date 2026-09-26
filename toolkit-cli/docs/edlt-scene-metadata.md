# Automatic eDLT SceneManager metadata

The automatic metadata path extends the retained
[eDLT SceneManager](edlt-scene-manager.md) editor for one **KEYGL5 / 5055EDL
firmware 5.5.00** database unit. It derives complete application and group
lists, required lifecycle group facts, Trigger Control level inventories, and
consumed action `DynamicAll` rows from one exact native `DBGETXML` project
snapshot. When the retained action getter or setter reaches a missing action,
the plan also projects the exact Trigger Control `Level` that the original
model requests and a guarded native apply creates it.

Preview a saved PP/project pair without connecting:

```sh
cbus-toolkit edlt scene-manager-plan snapshot.json \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --operations scene-operations.json --validate

cbus-toolkit edlt scene-manager-state snapshot.json \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --operations scene-operations.json --list-groups 1
```

The PP file must exactly equal the selected unit's decoded PP records. The
plan uses `cbus-native-edlt-scene-metadata-plan-v2`; automatic state uses
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

## Exact action-level creation

The original retained `EDLTScene.ActionSelector` getter and setter call
`CBusGroup.GetLevelByAddress` with its default `create=true`. For a missing
nonnegative action, that method sends the requested decimal address through
`AddLevelRequest`. The KEYGL5 native handler calls
`TLevelManager.FindLevelByAddress` with its action-selector naming flag. The
resulting object has:

- application `202` and the already existing selected trigger group;
- `Address` equal to the exact requested action byte;
- `Value` equal to that address;
- `TagName` equal to `Action Selector N`, using ordinary decimal `N`; and
- four default-language blank, image-free variants in the managed model.

The same side effect can be reached by an explicit `set-action`, `get-action`,
copy/validation getters, or the terminal save getter/fallback. Creations are
deduplicated and ordered by trigger group then action address. Later operations
in the same plan see the projected level and its four blank `DynamicAll` rows.
The planner does not infer text, font, icon, or image content.

The SceneManager **Add** button is a different path. It passes a blank level,
scans from address 0 for the first free address, limits that dialog allocation
to 0..254 because address 255 is reserved, seeds `Level N`, and waits for the
interactive dialog. This command does not emulate that dialog. Exact-address
action creation can address 255 because the original `FindLevelByAddress`
path bypasses the blank-dialog allocator.

Missing applications and trigger groups remain unsupported. A missing trigger
continues to follow the bounded retained fallback instead of being created.
A duplicate level/address/OID, a native conflict or capacity refusal, an
ambiguous add receipt, or a readback mismatch stops the transaction. Existing
levels and their labels are preserved byte-for-byte in the admitted XML model.

## Admitted metadata and image facts

The project and selected-network addresses must be unambiguous. The unit and
every selected-network application, group and level must have a unique native
OID. Existing `Level` records require canonical byte `Address` and `Value`
fields. The unit identity and all decoded PP values must match the supported
profile. Group 255 exists only as the original in-memory `<Unused>` object when
a consumed lookup needs it.

Empty and `TEXT` `TagDLT` variants produce their exact text with
`image_present=false`. Existing `DYNAMIC` and `FONT` variants depend on
project images; `ICON` depends on Toolkit's local DLTP index. Neither source is
present in `DBGETXML`, so consuming such an existing action fails closed. Use a
separately established caller cache when those image facts are required.

The cache limits remain 256 applications, 4,096 listed groups, 512 lifecycle
group facts, and 8,192 level addresses. Scene operations retain the existing
eight-scene and 64-item boundary. A scene-capacity-stopped edit is review-only
and cannot reach metadata or PP mutation.

## Backup, save ordering, and failure evidence

Apply accepts one unchanged plan issued by the same transaction. It first
rechecks the exact XML bytes, semantic metadata, PP snapshot, and closed/idle
network inventory. When levels are planned, it then performs this order:

1. `PROJECT SAVE` the unchanged source and `PROJECT COPY` it to the retained
   backup;
2. repeat the semantic stale check and select the source project;
3. issue each `DBADDSAFE ... Level ... Action Selector N`, resolve its one new
   OID, and `DBSETSAFE !OID/Value N`;
4. read back every created OID, address, value, name, blank-label default and
   all existing metadata;
5. when PP edits exist, stage and verify them, then attempt one `PP SAVE`;
6. attempt one target `PROJECT SAVE`, then close/load the project; and
7. verify created objects, expected PP, unrelated units/networks, and all
   pre-existing metadata after reload.

`DBADDSAFE`/`DBSETSAFE`, `PP SAVE`, and `PROJECT SAVE` are separate native
operations. There is no cross-operation commit. Before the first applicable
persistence save starts (`PP SAVE` when PP changes exist, otherwise the target
`PROJECT SAVE`), a staging or metadata failure reverses known created OIDs,
persists the inverse, reloads, and requires the complete admitted source
snapshot. If an add receipt is ambiguous, the command avoids saving an
unidentified object and reloads the source saved before backup. A failed
rollback is reported as uncertain.

After either `PP SAVE` or the target `PROJECT SAVE` is attempted, the command
performs no rollback or automatic retry. A lost save reply, an interruption,
or a post-save verification failure can leave a partial result. Inspect
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
and post-backup stale checks, conflicts, preservation, pre-save rollback, lost
PP/project save replies, and interruption evidence. An optional disposable
Schneider C-Gate gate requires all `CBUS_EDLT_SCENE_LEVEL_*` opt-in variables,
the native host, and the exact unit-spec directory.

```sh
CBUS_EDLT_SCENE_LEVEL_ACCEPTANCE=1 \
CBUS_EDLT_SCENE_LEVEL_UNIT=//PROJECT/254/p/20 \
CBUS_EDLT_SCENE_LEVEL_BACKUP=SCENEBK \
CBUS_EDLT_SCENE_LEVEL_GROUP=42 \
CBUS_EDLT_SCENE_LEVEL_ACTION=13 \
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_UNITSPEC_DIR=/path/to/specs \
PYTHONPATH=src:tests python3.13 -m unittest \
  tests.test_edlt_scene_metadata.SceneMetadataTests.test_optional_native_missing_action_level_transaction -v
```

The selected group must already exist and the selected action must be absent.
The gate deliberately leaves the changed disposable source and retained backup
for inspection.

The optional native gate was not enabled for the recorded offline acceptance.
No fresh complete WinForms SceneManager or interactive add dialog was run for
this slice. Full control binding, missing trigger-group creation, project-image
download, physical display behavior, scene learning, and physical trigger
execution remain outside this boundary.
