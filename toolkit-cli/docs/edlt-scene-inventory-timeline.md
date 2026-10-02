# Causal SceneManager inventories

Native SceneManager metadata resolves the inventory at each admitted operation
and explicit selector callback. This allows missing Trigger Control groups and
action levels to be created after load, and allows accepted or cancelled
SceneManager Add dialogs to occur in a selector history. The same engine serves
standalone SceneManager edits and the single SceneManager sequence inside an
ordered parent transaction.

Use `--project-xml FILE --unit //PROJECT/network/p/unit` for an offline plan,
or `--auto-metadata --exclusive-project` with the database operation. Supply
explicit `--display-preferences FILE` when an address-sorted list is required.
The literal acceptance profile uses `SortModeGroups=1` and `SortModeLevels=1`;
existing no-preferences XML-order behavior remains separately admitted. The CLI
does not read or infer the operator's Toolkit registry.

Read the complete choice rows from `get-selector-view` and the callback
receipt before choosing an ordinal, identity and value. See
[selector callback schemas](edlt-scene-selector-control.md) and
[metadata/save rules](edlt-scene-selector-metadata.md).

## Creation order and retained collections

Initial scene getter reservations happen before the first user operation.
Later create-enabled getters reserve the exact requested address; Add dialogs
allocate the first available address from 0 through 254. Getter defaults are
`Group N` and `Action Selector N`, while editable Add seeds are
`Trigger Group N` and `Level N`. These names describe different creation paths.
Cancelled dialogs create nothing and do not reserve an address.

New native objects can omit `TagsDLT` or retain an empty collection. The model
initializes four blank dynamic-label defaults from that representation; this
does not mean four explicit TagDLT records were stored in XML.

The modeled source creation contract refreshes the whole Network model. Existing Group objects
are retained, but every loaded Group receives a replacement Levels collection
and replacement level/dynamic-label objects. A control already bound to the
old collection keeps those old rows until an explicit callback rebinds it.
Creation in another group also advances this refresh generation. A fresh
getter sees the current inventory; it does not silently change a retained
control binding. An explicit action setter or dynamic-label refresh adopts
the current label objects. A valid action getter retains its existing labels.

For example, a bound action list `[0, 1, 7]` stays `[0, 1, 7]` after an Add
creates action 2. Under the declared address-sort profile, a fresh list is
`[0, 1, 2, 7]`. The explicit `trigger-current-changed` callback rebinds the
control to that new list. Selecting action 2 from the stale binding refuses.

The action Add button consumes the explicitly selected trigger control row.
That selection can differ from a scene property changed through a direct
setter. The resolver requires an admitted target; it never infers an automatic
currency selection, notification cascade or GUI binding update.

## Validation, save and parent ownership

Validation and terminal `BeforeSave` follow their own getter order. A terminal
fallback action 0 cannot appear in an earlier control or validation view.
One issued timeline binds the exact source snapshot, owning editor and ordered
operation history. Exported cache or state JSON is review material and cannot
grant this capability. Foreign, modified or out-of-order continuation refuses.
Manual v1/v2 cache behavior remains separate from native creation history.

Earlier parent Add results are visible at the SceneManager's position. Later
parent application/group/action facts may appear in the complete outer parent
cache, but cannot enter an earlier SceneManager choice list. The parent still
admits one SceneManager operation, which must precede its Scene widget edits.
Reset starts fresh initialization and control state and retains its existing
ordering restrictions.
Earlier Network language mutations still refuse this initializer-backed
profile because original label ownership cannot be inferred from changed XML.

Native execution keeps the closed-project, exact network lock, freshness,
backup and full PP/project readback checks. Known objects can be rolled back
before a save attempt. PP SAVE and PROJECT SAVE are separate persistence
boundaries; an uncertain outcome is never automatically retried or deleted.

## Evidence boundary

The collection and callback rules are recovered from static original source
and tested with synthetic specifications and projects. Owned cmqttd and
cgate-mock transactions establish software behavior and persistence only.
Native apply materializes the reviewed objects before PP staging; it does not
execute the original COM/WinForms refresh or event schedule.
Automatic host scheduling, culture-dependent default sorting, implicit first
selection, null binding conversion, modal/async behavior, full original GUI
acceptance and physical display/power-cycle acceptance remain open. Native
selector actions still require matching numeric Address and Value. No original
instructions, VM or house devices execute for this profile.
