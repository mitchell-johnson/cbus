# IOPE retained scene command levels

`cbus_toolkit.iope_scene_levels.IopeSceneLevels` projects one original fresh
SceneManager command level selection onto a stable IOPE PP scene table. It
supports IOPE1R1, IOPE2R2 and IOPE2C4 firmware **1.0.00..1.2.99**, with the
same specification/catalogue intersection as the existing IOPE workflows.
An explicit `(unit_type, firmware, catalog_number)` identity is required;
`catalog_number=None` is permitted, but a supplied catalogue must match.

Select exactly one `raw_level` integer 0..255 or `percent` integer 0..100,
with `scene` 1..4 and `command` 1..8. A percentage that differs from
the stored display value converts using the original truncation
`percent * 255 // 100`: selecting 50% converts a different displayed value
to raw 127. The integer attribute setter skips its callback when the display
already equals the selection, preserving raw 126, 127 or 128 at 50%. A raw
selection retains its exact byte. The callback updates the displayed percentage under a guard; it does
not convert that percentage back into the raw level. Unselected raw levels
also retain their exact bytes.

`sync_levels=False` selects one command. The explicit synchronization action
`sync_levels=True` assigns the selected control value to all eight commands
in that selected scene. Each percentage assignment independently observes
the display equality guard: matching rows preserve their exact raw byte.
For example, levels 125,126,127,128,129 with synchronized 50% become
127,126,127,128,127. Raw synchronization assigns the same raw byte to every
row. It does not change another scene. `level_writes` records
all selected and derived level assignments, their original/final values,
indices, byte addresses, display values, callback conversions and setter
call counts. Calls include equality skips; they are not callback counts. The original numeric row
handler sets the selected command twice; with synchronization it sets that
command once more while iterating all eight rows.

## Graph and initialization admission

The component reuses the existing scene-selector graph validator through a
retained selector no-op. `group_cache` has format
`cbus-iope-scene-selector-groups-v1` and supplies a nonblank evidence source,
positive existing primary Lighting application/group objects, the existing
application202 Trigger group, and its complete positive LevelManager action
inventory. Every retained command group must resolve; each scene must have
eight distinct non-255 group addresses. All eight retained normal/all-off
selectors must be distinct addresses 1..254 and positively resolved.

`SceneIndex` must be `[0,1,2,3]`; `SceneTablePointer` must be
`[178,194,210,226]` (B2 C2 D2 E2). These conditions describe exactly four
complete ordered eight-command scenes in the 64-byte table. They exclude
null commands, duplicate collapse, short scenes, repacking, alternate
pointers and the original external-table sentinel 0x9D. No objects are
created. Cache freshness against a live database remains caller evidence.

The admitted lifecycle is a fresh SceneManager loaded from this canonical
PP graph, before any Live selection. Source-pinned constructor state sets
`SyncLevels=False` and `UsePercent=False`. The original `Execute` resets
the Use Percent action and invokes it, giving the entry state
`UsePercent=True`. A raw selection performs one mode toggle after entry;
a percent selection retains that mode. The optional synchronization action
performs one toggle from the fresh false state. These transitions are
recorded in `initialization` and `control_state`.

Fresh scene objects begin with `LiveGroups=False`. Loading copies that
false state, and selecting a scene clears live state and consumes the
unchecked fresh Live action. The component fixes Live to false, so the
level callback cannot update the network group's target-level model. A
prior original Toolkit session with Live already selected is outside this
component lifecycle. These are reconstructed source states, not an
observation or execution of an original VCL form.

## Python entry point

```python
from cbus_toolkit.iope_scene_levels import IopeSceneLevels, plan_from_dict

editor = IopeSceneLevels(spec)
plan = editor.plan(
    current_values,
    identity=("IOPE2R2", "1.2.00", "5752PP/2R"),
    scene=2, command=3, percent=40, sync_levels=True,
    group_cache=complete_existing_graph_cache,
)
result = editor.apply(pp_session, plan)
assert result["saved"] is False
```

Planning snapshots all eight scene parameters: applications, Trigger group,
index/ramp fields, normal/all-off selectors, pointers and the complete table.
Only a changed `SceneTable` parameter is staged. Every group byte, every
unselected level byte and all bytes outside the selected level set are
preserved. Schema, profile, canonical controls, source metadata, graph,
initialization, derived writes and every consumed PP value are checked again
before application. Saved plan arrays require exact integers; false and zero
are distinct in canonical metadata. `plan_from_dict` loads an exact unsaved
plan document; `apply` reconstructs and compares it before staging. A failed
write or readback restores attempted parameters and never saves. The caller
owns any separate save and persistence evidence.

## Source chain and boundary

`research/fixtures/iope-scene-levels-source-review.json` pins the original
Toolkit 1.18 EXE/MAP hashes, four decoded UnitSpecs, SceneManager resource,
method ranges and reconstructed initialized states. Key virtual addresses:

| Original method | Address | Established behavior |
| --- | --- | --- |
| `TIOPECGateAgent.LoadScenes` | 0x12D7B44 | positive groups/actions; duplicate group collapse; 0x9D external-table branch |
| `TNeoScene.AfterConstruction` / `InternalCreate` | 0xC99F68 / 0xC9A38C | fresh scene construction leaves LiveGroups zero |
| `TCommandsDataSource.Create` | 0xF8CF2C | explicit false mode/synchronization defaults |
| `TfrmSceneManager.LoadNeoScenes` | 0xF88F34 | ordered temporary graph and retained Live state |
| `TfrmSceneManager.Execute` | 0xF87C40 | selects scene and enables percentage entry mode |
| `SetSelectedScene` / `UpdateLiveScene` | 0xF88508 / 0xF8AE10 | clears Live states and consumes unchecked Live action |
| `TCommandsDataSource.SetValue` | 0xF8D1C8 | numeric level control and optional all-eight synchronization |
| `actSyncSlidersExecute` / `actUsePercentExecute` | 0xF8C1DC / 0xF8C27C | explicit control-state toggles |
| `TSceneCommand.HandleLevelAfterChange` | 0xD16084 | guarded display conversion and Live-dependent target-level update |
| `TSceneCommand.HandleLevelAsPercentAfterChange` | 0xD16170 | guarded percent-to-raw conversion |
| `TIntegerAttribute.SetAsInteger` | 0x8508D0 | equality skips callback, preserving same-display raw bytes |
| `GetSceneTableAsString` | 0x12DBE80 | ordered group/level packing of all 32 resolved commands |
| `GetSceneTablePointersAsString` | 0x12DC104 | unchanged B2 C2 D2 E2 for the admitted counts |
| `TIOPECGateAgent.SaveScenes` | 0x12DC430 | identifies table/header serialization and external-table session dependency |

The callable workflow models the temporary `TScene` control transition and
its stable table projection. It does **not** invoke or reproduce accepted
`SaveNeoScenes` graph replacement, its parent/deep scene-change notifications
or dependent input microfunction callbacks. Whole SceneManager save, whole
IOPE save, input template recoding, selector changes, scene/group addition or
removal, live scene testing and physical operations remain excluded. Original
packing formulas establish the projection; copying the complete parent graph
and executing its callbacks is a separate unresolved transaction boundary.

Focused verification:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m unittest -v test_iope_scene_levels
```

Tests cover all three profiles and every retained row, all integer percent
selections, exact raw levels, synchronized hidden writes, full 256-byte
preservation, metadata and graph refusals, stale dependencies, canonical
replay/tampering, schema/profile admission, rollback and no save. Static
source review and portable tests do not establish original GUI execution,
physical effects, lamp behavior or power-cycle persistence. Native database
save/reload acceptance, if obtained by the caller, is separate evidence.
