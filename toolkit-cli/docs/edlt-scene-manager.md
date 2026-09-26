# Retained eDLT SceneManager model

`EdltSceneManager` edits the retained scene objects for KEYGL5 / 5055EDL firmware 5.5.00. This is an additive workflow beside the declarative scene-table helper. It loads once, applies ordered operations to the same logical scene and group references, then serializes and calculates the five configuration CRCs. Exports are review-only; resuming arbitrary exported model identities is unsupported.

The implemented scope is `model`. The original WinForms SceneManager was separately exercised for baseline binding, percent-cell synchronization and copy into an empty scene. Those three observations do not establish complete panel initialization or all UI interactions. This model editor itself performs no live I/O. One-shot capture and broadcast are provided by the separate [scene live coordinator](edlt-scene-live.md), and [retained scene trigger invocation](edlt-scene-trigger.md) composes the resolved group/action pair with native Trigger Control. Full control timing, confirmation dialogs, metadata creation and physical execution verification remain excluded. Static scene-name allocation is a database PP edit restricted to this exact KEYGL5 / 5055EDL / 5.5.00 profile.

```python
from cbus_toolkit.edlt_scene_manager import EdltSceneManager, SceneManagerCache

manager = EdltSceneManager(spec)
state = manager.load(values, metadata=SceneManagerCache.from_dict(cache_document))
outcome = manager.edit(state, operations=[
    {"op": "set-application", "scene": 1, "selector": 1},
    {"op": "add-groups", "scene": 1, "groups": [7, 12]},
])
validation = manager.validate(outcome.state)
plan = manager.prepare_save(validation.state)
result = manager.apply(session, plan)  # verified PP staging; saved=False
session.save_to_source()              # explicit database persistence
```

Scenes use fixed slots 1–8. Existing scene/widget references keep those slot identities. Items expose engine-issued integer `item_id` values; matching only a numeric group cannot distinguish the original model's cross-application references. The first numeric bounds are level 0–255, percent 0–100 and ramp code 0–15. These do not claim the original UI's complete text-entry behavior or arbitrary signed-integer overflow behavior.

Supported operation dictionaries all contain `op` and `scene`:

| Operation | Additional fields | Effect |
|---|---|---|
| `set-application` | `selector`: 0 or 1 | Changes the selected primary/secondary application while retaining existing item group objects. Disabled secondary selection is rejected. |
| `add-groups` | `groups`: ordered group list | Adds currently available group objects with level/ramp zero and editable true. Excludes group 255 and already used identical group objects. |
| `remove-items` | `item_ids` | Removes the specified existing item identities. |
| `clear-items` | none | Clears items while retaining scene metadata. |
| `copy`, `paste` | none | Uses one detached retained clipboard; pasted/copied items receive new identities and editable true. |
| `clear-scene` | none | Copies the original empty-scene fields while retaining destination dynamic-label cache and selected-label index. |
| `set-level` | `item_id`, `level` | Sets one item level. |
| `set-percent` | `item_id`, `percent` | Sets level using integer `percent * 255 / 100`. The original getter is integer `100 * (level + 2) / 255`, including level 253 displaying 100%. |
| `set-ramp` | `item_id`, `ramp_rate` | Sets one raw ramp code. |
| `sync-levels` | `item_id` | Copies the explicitly selected current item's level to every item in that scene. |
| `set-trigger` | `group` | Sets the numeric trigger reference without implicitly resolving other fields. |
| `set-action` | `action` | Invokes original-style action lookup and dynamic-label refresh; a known missing action becomes -1. Disabled trigger ignores the assignment. |
| `set-name-index` | `index`: 0–63 or 255 | Selects an existing static slot or unused name. No allocation or reindexing occurs. |
| `set-name-text` | `text`: nonblank, at most 63 UTF-8 bytes, no NUL | Releases this scene's old name reference, reuses an exact existing string or allocates the highest unreferenced static slot, then binds the scene to it. |
| `get-trigger`, `get-action` | none | Explicitly observes the original potentially mutating getter. |

`available_groups(state, scene=...)` returns the ordered choices from the declared cache. Changing a scene from primary to secondary leaves its old group objects attached. A new secondary object with the same numeric group is therefore available. Serialization emits only the numeric group under the selected scene application, exactly as observed in the original model; the result reports the retained references so callers can review that distinction.

Copy/Paste copies the scene application, scene editability, trigger/action/name and items. Item editability becomes true, while group object references are retained. It does not copy the source dynamic-label list or selected-label index into the destination. Clear Scene likewise leaves a stale destination dynamic-label cache intact. The model API does not add a UI refresh to clear it.

## Static scene names

`set-name-text` uses the same `EdltLighting.allocate_static_text` implementation as the accepted widget and declarative scene-table workflows. Matching is ordinal, case-sensitive and scans slots 0 through 63. An exact match is reused even when no spare slot exists. A new string uses the highest slot not referenced anywhere in the retained after-load unit model. Reservations include all eight current scene names, navigation page names and every supported static widget label/status reference described in [eDLT shared static text allocation](edlt.md#shared-static-text-allocation). The operation never edits another reference or renames a shared slot in place.

Operations are applied in array order. A `set-name-text` first changes the selected scene's name index to 255 in the staged view, so its old slot can be reused when no other field refers to it. The allocated string and new scene reference are then visible to the next operation. Equal later text reuses the earlier slot; a later `set-name-index` can add or clear a reservation. `set-name-index` with 255 clears only the reference and leaves stored static text intact. Clipboard contents are detached and do not reserve a unit slot until pasted into a scene.

Each retained state and final plan contains `static_text.overlay_changes`, the ordered allocation records and a SHA-256 `fingerprint` of that evidence. Every record includes its scene, operation number, chosen index, exact-reuse flag, used indexes and proposed string write. The overlay is part of the issued-state integrity receipt, so an exported or modified state cannot be resumed. Capacity and text validation finish while planning; failure causes no PP SET or SAVE. The plan exposes the eight final `scene_pointers`, includes the bound name byte in `SceneBucket`, and recalculates `StaticTextCRC`, `ScenesCheckSum` and `OverallCRC` together with the other configuration CRCs.

## CLI

```sh
cbus-toolkit edlt scene-manager-state source.json --metadata cache.json --operations edits.json --validate --list-groups 1
cbus-toolkit edlt scene-manager-plan source.json --metadata cache.json --operations edits.json --validate
cbus-toolkit cgate unit --lock-address //OWNED/254 --source /db//OWNED/254/p/20 --dry-run edlt-scene-manager --metadata cache.json --operations edits.json --validate
```

The native command requires a database destination. Removing `--dry-run` stages, verifies and explicitly saves the requested complete result. The state command can successfully return `complete=false` for a capacity-stopped review. Plan and native commands reject that same partial result with its retained-state evidence and zero PP writes/SAVE attempts. JSON loaders reject duplicate keys, nonfinite numbers, unknown operation fields and oversized input before a programming session.

When the native project snapshot is authoritative, the
[automatic scene metadata](edlt-scene-metadata.md) path replaces the manual
cache file:

```sh
cbus-toolkit edlt scene-manager-plan source.json \
  --project-xml project.xml --unit //OWNED/254/p/20 \
  --operations edits.json --validate
cbus-toolkit cgate unit --lock-address //OWNED/254 \
  --source /db//OWNED/254/p/20 --dry-run edlt-scene-manager \
  --auto-metadata --exclusive-project --operations edits.json --validate
```

It resolves complete application/group lists, consumed trigger-level addresses
and safe default-language action labels from one exact `DBGETXML` snapshot.
It creates no application, group or level. Image-dependent action labels fail
closed. Native apply rechecks the exact project and PP snapshot, uses the
existing connected staging rollback, issues one PP SAVE, and verifies that all
non-PP project metadata was preserved. A lost save reply is never retried.

## Declared cache

`SceneManagerCache` wraps the existing `ApplicationCache` and adds per-level `DynamicAll` facts:

```json
{
  "format": "cbus-edlt-scene-manager-cache-v1",
  "application_cache": {"format": "cbus-edlt-application-cache-v1", "...": "existing complete cache document"},
  "level_labels": [
    {"group": 42, "action": 1, "labels": [
      {"value": "0", "name": "Owned action 1", "image_present": false}
    ]}
  ]
}
```

The abbreviated application cache above is illustrative, not a valid complete document. It uses `ApplicationCache`'s ordered group lists, explicit completeness and lifecycle presence/level facts. A missing required fact differs from an explicitly absent group, empty label list or missing action. Each dynamic label retains the observed DataStore string value, name and image-presence fields; image pixels and live label transports are outside this workflow. There are at most four labels per action and 8,192 action records. Cache facts are copied into immutable records and do not assert database existence or freshness. Updating cache contents after load is not currently an API operation. The automatic path supplies these records from one guarded project snapshot, but does not broaden the retained model into a complete WinForms binding claim.

## Capacity and validation

The original storage percentage is integer `100 * item_count * 3 / 191`; 63 items display 98% and 64 display 100%. Ordered add and paste can apply one item and then encounter capacity. The API returns `complete=false`, exact requested/applied counts and the retained partial state. That state is review-only and cannot be edited further or prepared for persistence. To choose another result, branch explicitly from the last complete issued state. No retry, automatic rollback or silent clipping occurs.

Eight headers plus 64 items occupy the native 232-byte SceneBucket. The original serializer also emits an extra trailing `0xff` token in that exact-capacity case; the native PP array stores the first 232 bytes. The dedicated native acceptance submits the original 233-token value, verifies that C-Gate retains all 232 data bytes, and saves/reloads the complete result.

There is an additional original-model CRC distinction at exactly 64 items. `PPHelper.SetMemoryFromParamStringValue` consumes the extra trailing token into the temporary CRC image at logical address `0x21fa`, despite the declared array size. The retained helper reproduces this byte for `ScenesCheckSum` and `OverallCRC`; it does not write an extra physical/PP byte. The plan's `crc_projection` exposes original233/native232, the temporary address, and `native_pp_only_crc_matches_original=false`. Recalculating solely from the normalized native PP array would yield different CRCs. All five saved CRC fields are compared with the original model and preserved through native reload.

`validate(state)` follows the original `ValidateScenes` getter order, including its shortcut after finding both a populated scene with no name and one with no trigger/action. It separately reports duplicate trigger/action, populated missing trigger/action, populated missing name and duplicate name. Empty scenes can participate in duplicate checks. The validation outcome contains its normalized state because getters can change retained fields. These warnings do not automatically block original model serialization, and successful serialization does not imply full-form validity or an accepted UI override.

`prepare_save` also records validation on an independent branch for review; it does not insert those getter side effects before the actual save sequence. It projects the already loaded lifecycle's non-scene save behavior once, serializes the retained edited scenes, then calculates CRCs. Unrelated lifecycle normalization is included in the plan's phase deltas. No second model load loses copied group references or dynamic-cache state.

## Database staging and evidence

`apply` accepts only an intact issued plan, canonically rederives serialization and its static-text fingerprint, verifies the exact profile and database destination, and checks the complete source PP snapshot before the first write. It stages each string, scene/pointer and CRC change once and compares complete PP readback. A connected ordinary failure attempts rollback and verifies the source, including a static string already written before a later failure; a lost connection stops recovery I/O. Interruptions retain attempted parameter details under `edlt_scene_manager_evidence`, with `saved=false` and explicit uncertainty. `manager.last_evidence` is a fallback when an exception rejects attribute attachment; secondary evidence-export or attachment errors cannot replace the original interruption. Each apply clears previous outcome evidence before validation, and ordinary failures retain rollback evidence as well. Native SAVE remains an explicit caller operation.

The original probes are owned source in `research/NativeEdltSceneManagerProbe.cs`; vendor assemblies are supplied separately and remain unchanged. Literal observations are frozen in `research/fixtures/edlt-scene-manager-vectors.json`. The research pilot includes 10 retained-model and 3 bounded actual-control cases; a second matrix adds 13 original validation and 8 getter/cache-removal cases. Cache removal after load is research evidence only, since the public retained cache is immutable. Tests compare retained private fields, object relationships, full native PP, scene bytes, five CRCs and explicit save/close/load. The frozen acceptance runs execute 17 fresh original Windows model/control cases and eight native C-Gate cases per interpreter, including full capacity. Exact per-run source and report hashes are recorded in `research/fixtures/edlt-scene-manager-acceptance.json`.

The additive `set-name-text` tests reuse the independently original-DLL-tested whole-unit allocator documented in `edlt.md`. Focused module/CLI cases cover exact reuse, descending allocation, unrelated reservations, ordered release/rebind, exhaustion before writes, evidence fingerprints, pointer/name bytes, affected CRCs, complete readback and connected rollback. The environment-gated CLI case combines a 64-item retained scene with a new static name, then previews, stages, saves, closes and reloads all 874 PP values. The older frozen SceneManager acceptance fixture still describes its historical boundary as “existing static name indices only”; no new SceneManager WinForms label-control execution or physical eDLT display acceptance is claimed by this additive slice.

The declarative `EdltSceneTable` helper remains a separate normalized-PP authoring scope. At full capacity its normalized232-byte CRC projection is distinct from this retained original SaveScenes233-token projection; this implementation does not silently change that existing API.

This capacity-CRC finding qualifies the earlier [declarative SceneTable acceptance](edlt-scenes.md#original-serialization-and-the-64-item-boundary). Its historical fixture and report remain unchanged: those runs established full-capacity packing/native normalization, then checked original CRCs on a subsequent smaller edited table. The new acceptance fixture records this correction explicitly.
