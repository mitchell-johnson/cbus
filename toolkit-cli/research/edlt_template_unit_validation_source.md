# eDLT unit validation: static source contract

Evidence class: **source proof only**. Recovered by reading private managed IL; no original runtime, CPU, GUI, native I/O, build, or device execution was performed. This document contains a sanitized behavioral summary, not vendor IL. Private source: `CBusLogicModel.dll.il`, methods and line anchors below.

## Callable boundary

`EDLTUnit.IsValid(ref List<string> errors)` (38970–38997) first calls the virtual `GetKeyFunctionGroups`, then `ValidateCorridorLinking(groups, ref errors)`, then `ValidateScenes(ref errors)`. Both validators execute even if the corridor result is false. Return is corridor-valid AND scenes-valid. The existing list is preserved and messages append in corridor-then-scenes order; neither validator clears or replaces it. Unexpected getter/list errors propagate: there is no catch or defensive null handling.

Minimal offline equivalent requires an issued intact AfterLoad model before terminal BeforeSave projection, its ordered widget group results, primary-application PP value, corridor-link PP value, ordered retained scenes with item counts/name indices and trigger/action getter behavior, and a caller-owned mutable error list. Plain raw PP bytes do not establish those getter results or their effects. The original Save wrapper supplies an initially empty error list.

## Key-function group acquisition and corridor predicate

`EDLTUnit.GetKeyFunctionGroups` (38481–38530) iterates `Widgets` in collection order, calls every widget's `WidgetData.GetGroup()`, and appends non-null results without deduplication. The base method returns null (23159–23168). The sole override in this IL is `StatusLabelAppGroupData.GetGroup` (43305–43337): resolve selected application using `Network.GetApplicationByAddress(selectedApplication.ValueAsInt, true)`, then `GetGroupByAddress(WidgetByte(6).ValueAsInt, true, true)`. Thus acquiring groups is itself a model/cache operation even when corridor link is 255.

`ValidateCorridorLinking` (40830–40891) reads `CorridorLinkingLinkGroup.PPAttributeValue`. If 255, return true without enumerating its supplied groups. Otherwise filter by `group.AddressAsInt == link` and `group.Application.AddressAsInt == PrimaryApplication.PPAttributeValue` (predicate 33879–33901). `Any()` decides conflict; on conflict `ElementAt(0)` re-enumerates the filtered sequence to format the first match. Append one message and return false. Group `ToString()` inherits `CBusBaseObject.ToString` (1369–1377), which returns `TagName`.

Exact message (including original apostrophe):

```
The selected Corridor Link Group "{tag_name}" is also being used in at least one key function. To resolve this error, either change the Corridor Link Group or remove it's associated key functions.
```

## Scene scan

`ValidateScenes` (40005–40204) initializes four false flags: duplicate trigger/action, duplicate name, populated missing trigger/action, populated missing name. It loops `i = 0 .. Scenes.Count-1`, not a literal eight. At each outer iteration, if BOTH missing-name and missing-trigger flags are already true, skip all remaining work for that `i`.

Otherwise, when scene `i` has at least one item, set missing-name if `NameIndex == 255`; set missing-trigger if `TriggerGroup == 255 OR ActionSelector < 0`, with normal short-circuit getter order. Then for every later scene `j`, including empty scenes:

- Set duplicate-name if `i.NameIndex != 255` and name indices equal.
- Set duplicate-trigger/action if `i.TriggerGroup != 255`, trigger groups equal, `i.ActionSelector != 255`, and action selectors equal, with left-to-right short-circuit getter evaluation. The duplicate condition deliberately excludes 255, not negative action values.

If any flag is true, append exactly ONE composed string. Prefix: `The following problems were detected with the scene configurations: ` (trailing space). Append present clauses in this order, each prefixed by two LF newlines:

1. `Multiple scenes have been assigned with identical Trigger Group and Action Selector combinations.`
2. `One or more scenes have been populated with items but have not been assigned a Trigger Group and/or Action Selector.`
3. `One or more scenes have been populated with items but have not been assigned a scene label.`
4. `Multiple scenes have been assigned identical scene labels.`

Return false if the composed string is nonempty, otherwise true. There are no extra item capacity, label text, scene-widget reference, or cross-panel checks in this method.

## Scene getters and effects

`Scenes`, `Items`, and `NameIndex` are direct backing-field getters. `TriggerGroup` (32629–32665) obtains Trigger Control application 202 with add=true and stored group with `GetGroupByAddress(raw,true,false)`. Missing group calls `set_TriggerGroup(255)` and returns 255; present group returns its address. The setter only changes a differing stored value and notifies `TriggerGroup`, `TriggerGroupName`, and `AvailableActionSelectors` (32668–32690).

`TriggerGroupEditable` (32716–32735) calls TriggerGroup, rejects 255, then calls TriggerGroup again and requires >=0. `ActionSelector` (32738–32793) first checks that property. False returns -1 without updating raw action. Otherwise it resolves non--1 raw action using application202/add=true, TriggerGroup, group(true,false), and `GetLevelByAddress(raw,true)`. Missing level or raw -1 calls `set_ActionSelector(-1)` then returns -1; existing level returns address. The action setter (32796–32847) checks editable again, resolves its supplied level with add=true, stores resolved address or -1, refreshes dynamic labels, and notifies `ActionSelector` and `ActionSelectorName`. `RefreshDynamicLables` (32849 onward) clears current dynamic labels and may copy existing level.DynamicAll, making complete level and dynamic-label facts relevant.

## Existing implementation comparison and data gaps

`edlt_scene_manager.py:577` mirrors flag order, short-circuit predicate order, getter-driven state updates, and outer skips for its established eight-scene profile. Its outcome exposes warning identifiers, skips, issued state and `save_blocking=false`, rather than the native composed error string. Unit validation must aggregate messages and carry the returned retained state; using only its boolean loses getter effects. Existing vectors retain component validation evidence; they do not prove the unit wrapper or complete parent Save ran.

`edlt_corridor.py:199` derives groups for seven known families, requires matching metadata/cache presence, filters on app/address and throws `CorridorConflictError`. Its accepted projection does not call ValidateScenes, does not provide exact native TagName-formatted error text, and is scoped to unchanged loaded models. Unit validation needs final model groups after model changes, complete declared group/cache facts, and first matching TagName. Native `GetGroup` uses add-enabled lookup; an offline refusal for unknown facts is a boundary choice, not native missing-object behavior.

No full-form, hardware, persistence, original parent Save, or runtime parity claim follows from this source recovery.
