# eDLT scene-table authoring

`EdltSceneTable` authors an explicit table of up to **8 scenes and 64 total output items** on **5055EDL / KEYGL5 firmware 5.5.00**. It uses the original Toolkit `EDLTUnit.SaveScenes` layout, shared text allocation and all five configuration CRCs. The workflow stages a database PP session, verifies the full result, and leaves saving explicit. It does not invoke, learn or transfer scenes on physical hardware.

The ordered scene list is the complete replacement table. List position defines the scene's fixed human slot number, starting at 1. Read an existing table, change its definitions, inspect the plan, then apply it:

```python
from dataclasses import replace
from cbus_toolkit.edlt_scenes import EdltSceneTable, SceneDefinition, SceneItem

editor = EdltSceneTable(spec)
scenes = editor.read(session.values())
new_table = [
    SceneDefinition("primary", trigger_group=42, action_selector=77,
                    items=(SceneItem(group=9, level=127, ramp_seconds=20),),
                    name_text="Evening"),
    SceneDefinition("secondary", trigger_group=42, action_selector=88,
                    items=(), name_text="Reading"),
]
plan = editor.plan(session.values(), scenes=new_table)
print(plan.as_dict())
result = editor.apply(session, plan)  # verified=True, saved=False
session.save_to_source()
```

`SceneDefinition.from_dict()` and `SceneItem.from_dict()` accept the equivalent JSON objects and reject unknown keys. `configure(session, scenes=...)` checks source identity before reading PP values, then plans and applies. `.read()` returns a tuple of `SceneDefinition` values, which can be planned again without introducing changes once a canonical table has been saved.

Fields and limits:

| Scene field | Meaning |
|---|---|
| `application` | Existing `primary` or `secondary` Lighting application, assigned in 48..95 |
| `trigger_group` | Assigned Trigger Control group in 0..254 |
| `action_selector` | Action selector in 0..255 |
| `items` | Explicit output items; an empty list is a trigger-only scene |
| `name_index` | Existing shared text slot in 0..63, or `None` for no name |
| `name_text` | Nonblank text of at most 63 UTF-8 bytes, without NUL; mutually exclusive with `name_index` |
| `editable` | Scene editability flag, a boolean; defaults to true |

An item has `group` in 0..254, `level` in 0..255, `ramp_seconds`, and an `editable` boolean. Duplicate groups within one scene are rejected. Supported ramp times are 0, 4, 8, 12, 20, 30, 40, 60, 90, 120, 180, 300, 420, 600, 900 and 1020 seconds. Level and ramp values are explicit; no network levels are sampled.

This first authoring workflow requires assigned trigger bindings in both existing and replacement records. It rejects malformed, truncated or overlapping records, middle holes, unsupported record bits and unknown Scene widget macro combinations. It does not silently compact holes or convert unassigned-trigger records. Unused trailing pointer sentinels 255 and 65535 are accepted. `SceneCount` is not used to hide records: original `LoadScenes` inspects all eight pointers.

Existing Scene widgets are preserved byte for byte. Off/On, ramp and nudge modes reference the single scene at byte 6; cycle mode references the active list at bytes 13..21. A referenced slot must remain configured and retain its primary/secondary application selection, trigger group and action selector. Reordering or replacing a middle entry that changes that identity is rejected. Items and scene names can be edited while retaining the identity; a widget displaying the scene name also requires a name to remain assigned. No widget is automatically rebound to another slot. Unreferenced trailing scenes can be removed, and an empty table is allowed when no widget references it.

Name allocation follows the original model's property order: install the explicit replacement scene list, reserve all direct name references and unrelated unit references, then allocate and bind requested names in scene order. Exact text matches reuse the first matching slot; new names use the highest unused slot. Equal new names deduplicate, different names reserve their allocations before the next name is processed, and table exhaustion is an error. The plan exposes `name_allocations`, `referenced_slots`, all eight pointers and the complete bucket bytes.

The helper requires a complete snapshot and exact profile/schema. It rejects stale or forged plans before mutation. Failed writes attempt to restore and verify original PP state. If the connection loses synchronization, no further recovery I/O is sent; the error includes attempted parameters, rollback uncertainty and `saved=False`.

## Original serialization and the 64-item boundary

The unchanged Toolkit 1.18 `CBusLogicModel.dll` has SHA256 `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`. `research/NativeEdltScenesProbe.cs` calls its actual `EDLTUnit.SaveScenes`, `GetSceneStartAddress` through serialization, scene-name allocation and storage percentage methods. The sources are the decompiled `EDLTUnit`, `EDLTScene` and `EDLTSceneItem` classes in the ignored vendor directory.

Each scene contains a five-byte header:

```text
(editable << 1) | secondary, item_count, trigger_group, action_selector, name_index
```

Each item contains three bytes:

```text
(editable << 4) | ramp_index, group, level
```

Records are packed in scene order. Pointers are cumulative record lengths; unused pointers are 255. `SceneCount` is the list length. In PP raw memory, pointers are 16-bit **little-endian** integers beginning at logical address `0x2102`. The 232-byte `SceneBucket` begins at `0x2112`. Replacing a table deliberately rewrites its packed records and unused padding, matching the original serializer; unrelated PP fields and text slots are preserved.

The exact boundary needs both the original serializer and the native PP writer:

| Fixture | Original `SaveScenes` tokens | Native PP bytes | Result |
|---|---:|---:|---|
| 8 scenes, 63 items | 232 | 232 | Data plus unused padding |
| 8 scenes, 64 items | 233 | 232 | All 232 data bytes persist; only the extra final `FF` is discarded |

The serializer always appends a final `FF`. At 64 items, eight headers plus 192 item bytes already fill the 232-byte array. Exact C-Gate 3.4.0.2001 accepts the 233-token original value, normalizes it to the declared 232 elements and returns the full record data unchanged. The helper therefore writes the effective 232 bytes explicitly. It does not drop scene data or rely on an unchecked truncation assumption. The original UI storage percentage is 98 at 63 items and 100 at 64; its AddGroup guard stops further additions at 100. The helper rejects a 65th item.

The historical full-capacity check establishes packing and native 232-byte normalization. Its separate original five-CRC comparison and final save/reload apply to the subsequent smaller edited table, after replacing the capacity fixture. It does not establish the retained original 64-item `SaveScenes` CRC path. This declarative helper calculates CRCs from normalized PP values. The original retained serializer consumes its extra 233rd `FF` in the temporary CRC image, changing `ScenesCheckSum` and `OverallCRC`; that distinct behavior is now implemented and tested by [EdltSceneManager](edlt-scene-manager.md). Historical fixtures and raw report hashes remain unchanged.

Independent fixed digests:

```text
63-item original/effective232: 62e66a688391ab94ef61e70e7e6030226b95c33127e7f7881f9446d2c9bf4e54
64-item original233:           43add6166edea72dfe8d2075aad73a907c5ff1ad3afeb279c06d845d96bfff36
64-item native effective232:   8994edb0d1997390ceb455d21496c63e67b39f7a0bc117ff2dbe4b532a71e910
```

These are deliberately chosen synthetic scene records, not captured user settings or reserved hardware defaults.

## Acceptance

`tests/test_edlt_scenes.py` covers literal packing/digests, full capacity, input validation, duplicate groups, malformed sources, cycle references, slot identity, allocation ordering, preservation, stale/forged plans and rollback/disconnect behavior. The native test authors a full 64-item table, replaces it with two scenes, adds a referencing Scene widget, edits items/names, compares original DLL serialization, checks raw pointers/bucket/widget bytes, validates all five original-DLL CRCs for the subsequent normalized edited table, saves and reloads that project state, and compares the complete PP snapshot. It also exercises the original 233-token value directly against native PP SET. `tests/test_cli_edlt_scenes.py` covers offline/native previews, JSON input, inspection, save/reload and rejected slot swaps.

Run from `toolkit-cli`, with the same opt-in gates as the other eDLT tests:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_SCENES_REPORT=research/runtime/edlt-scenes-report.json \
PYTHONPATH=src python3 -m unittest discover -s tests -p '*edlt_scenes.py' -v
```

The test uses a marked disposable database project with an unopened CNI. Docker/Mono executes the unmodified DLL. Vendor files and private runtime reports remain ignored. A compact summary is recorded in `research/fixtures/edlt-scenes-acceptance.json`.
