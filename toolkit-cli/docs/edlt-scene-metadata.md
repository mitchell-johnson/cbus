# Automatic eDLT SceneManager metadata

The automatic metadata path extends the retained
[eDLT SceneManager](edlt-scene-manager.md) editor for one **KEYGL5 / 5055EDL
firmware 5.5.00** database unit. It derives the complete application and group
lists, required lifecycle group facts, complete trigger-action address sets,
and consumed action `DynamicAll` rows from one exact native `DBGETXML` project
snapshot. A caller no longer needs to hand-author `scene-cache.json` when all
consumed labels are representable in that snapshot.

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
plan uses format `cbus-native-edlt-scene-metadata-plan-v1`; automatic state
uses `cbus-native-edlt-scene-metadata-state-v1`. Both include the immutable
derived cache and the ordinary retained SceneManager evidence.

Preview the current closed database project through C-Gate:

```sh
cbus-toolkit cgate unit \
  --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 \
  --dry-run edlt-scene-manager \
  --auto-metadata --exclusive-project \
  --operations scene-operations.json --validate
```

Remove `--dry-run` to stage, verify, and save the PP changes to that same
database unit. Automatic mode rejects a physical source, a destination, or a
lock address other than the selected source network. Every network in the
project must remain closed with synchronization idle. The command does not
acquire a server-wide project lock, so `--exclusive-project` declares an
operational precondition the caller must enforce.

## Admitted metadata

The selected project plus selected-network addresses must be unambiguous. The
selected unit and every selected-network application, group and level used by
the snapshot must also have a unique native object ID. The unit identity and
all decoded PP values must match the supported profile. Application and group
inventories are complete for the admitted selected-network snapshot; group 255
is represented only as the original in-memory `<Unused>` object when a
consumed lookup needs it.

The resolver evaluates the initial eight retained scenes and the ordered edit
sequence before constructing its cache. It supplies complete level addresses
for every consumed Trigger Control group and four default-language
`DynamicAll` rows for each consumed valid action. Empty and `TEXT` `TagDLT`
variants produce their exact text with `image_present=false`.
`DYNAMIC` and `FONT` variants depend on downloaded project images, while
`ICON` depends on Toolkit's local DLTP index. Neither image source is present
in `DBGETXML`, so consuming any such action fails closed. Use a separately
obtained caller cache when those image facts are required.

This path is read-only for database metadata. It never issues `DBADDSAFE` or
`DBDELETE`, and `metadata_mutation_planned` is always false. A missing trigger
group follows the retained getter's `<Unused>` fallback. A missing action is
normalized to `-1` by the original-style level lookup. The resolver does not
create groups or levels because the original add-dialog naming and missing
action creation policy have not been established. The separate
[automatic parent metadata](edlt-parent-metadata.md) workflow can create its
bounded required application/group set; it also deliberately does not invent
missing scene levels.

Complete application/group lists can be much larger than the facts consumed
by one scene edit. The existing cache limits still apply: 256 applications,
4,096 listed groups, 512 lifecycle group facts, and 8,192 level addresses.
Scene operations retain the existing eight-scene and 64-item boundary. A
capacity-stopped state is available for offline review, but planning or native
apply rejects it before a PP write or save.

## Stale checks, save, and rollback

Planning reads one project XML document and records its exact hash and semantic
source. Apply accepts only an unchanged, single-use plan issued by the same
transaction object. Before opening a PP session it re-reads `DBGETXML`, checks
the exact XML bytes, re-resolves the cache and plan, and confirms all project
networks are still closed and idle. The PP session then checks the complete
source snapshot again before its first write.

The retained SceneManager stages each changed PP value once and verifies the
complete readback. An ordinary connected staging failure restores and verifies
the original PP values. A disconnected rollback failure remains explicit.
After successful staging, native mode issues exactly one `PP SAVE`; no project
metadata is changed and no `PROJECT SAVE` is needed. A fresh `DBGETXML` must
then contain the exact expected PP values while preserving all non-PP project,
network, unit, application, group, level, tag, and object-identity data.

Once `PP SAVE` is attempted, a lost or interrupted reply is outcome-uncertain.
The command does not retry or claim rollback. Inspect
`pp_save_attempted`, `pp_save_confirmed`, `pp_save_outcome_uncertain`,
`pp_state_uncertain`, `database_state_uncertain`, and
`database_persistence` in the result or error evidence. Only complete
post-save `DBGETXML` verification returns `saved=true`.

## Evidence boundary

[`edlt-scene-metadata-evidence.json`](../research/fixtures/edlt-scene-metadata-evidence.json)
pins the original sources already used by the retained SceneManager and parent
metadata research. Portable tests cover exact text-label derivation, missing
object normalization, duplicate/stale/image-dependent rejection, capacity,
CLI guards, metadata preservation, connected staging rollback, and the lost
save-reply boundary.

No new original WinForms execution was performed for this additive resolver.
The retained SceneManager's earlier model and three bounded control probes
remain the original evidence. Complete control binding, the add-level dialog,
project image download, Schneider C-Gate acceptance for this combined path,
and physical device/display behavior remain unverified.
