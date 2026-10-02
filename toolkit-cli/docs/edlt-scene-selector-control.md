# Retained SceneManager selector callbacks

The `scene-selector-control` nested SceneManager operation projects explicit
application, Trigger Control group, action and dynamic-label callbacks. It uses
the scene model's observed choice objects and property setters. It does not
infer the event schedule of a WinForms host or replace existing direct
`set-application`, `set-trigger` and `set-action` operations.

The enclosing `scene` is 1..8. An explicit `scene-current-changed` with
`current: true` binds that scene. `current: false` disables the controls while
retaining the previous direct action, dynamic-label and SceneName bindings.
Application and trigger bindings follow the current scene. Null-current
application/trigger conversion is unqualified and refuses. A later
`level-current-changed` still calls the retained action binding's `WriteValue`
when present, even with controls disabled; it does not call `ReadValue`.

For example, this callback history binds scene 1, selects the exact observed
Trigger group and invokes the separate source current-change handler:

```json
{
  "op": "scene-selector-control",
  "scene": 1,
  "events": [
    {"event": "scene-current-changed", "current": true},
    {"event": "trigger-selected", "value": 42,
     "choice_index": 0, "choice_identity": "trigger:202/42"},
    {"event": "trigger-current-changed"},
    {"event": "level-current-changed", "value": 1,
     "choice_index": 0, "choice_identity": "action:202/42/1"},
    {"event": "label-selected", "index": 0,
     "choice_identity": "label:202/42/1/0"}
  ]
}
```

Those identities and ordinals are examples. Read the selected model's complete
ordered views before choosing them. The operation cannot supply Names, choices,
bindings, cached state or a resume token. Duplicate display Names remain valid;
the current ordinal, object identity and value must all match. Application
selector values are 0 for primary and 1 for secondary, rather than application
addresses. An absent secondary row cannot be selected. Trigger choices contain
only the real observed objects, including 255 only when explicitly present.
The coordinator does not prepend an unused row or choose a first row.

The admitted event records are:

| Event | Fields after `event` | Effect |
| --- | --- | --- |
| `scene-current-changed` | `current`: Boolean | Enable/disable; a real current scene rebinds action, label and Name controls in source order. |
| `trigger-current-changed` | None | With a current scene, resolve its AvailableActionSelectors, rebind action, then read ActionSelector and refresh dynamic labels. No current is a no-op. |
| `level-current-changed` | Selection triple when an action binding exists | Call only the retained action binding's WriteValue. An absent binding is a no-op. |
| `application-selected` | `value`, `choice_index`, `choice_identity` | Write the current scene's primary/secondary selector. |
| `trigger-selected` | Selection triple | Write TriggerGroup; this does not infer a subsequent current-change callback. |
| `action-selected` | Selection triple | Write the retained direct action binding, preserving the model setter's own refresh behavior. |
| `label-selected` | `index`, plus `choice_identity` when index is nonnegative | Write LabelValueIndex through SelectedIndex. Explicit -1 has no selected object. |

A selection triple has an integer value -1..255, nonnegative ordinal and
nonempty identity. Values outside the current source list refuse. This does not
qualify null SelectedValue-to-integer parsing. Label indexes are -1..3, and a
nonnegative index must match the exact current dynamic-label row. Image presence
is an observed metadata fact; this operation does not render or edit pixels.
Each history has at most 512 events. Unknown keys or injected binding state
refuse during shape normalization before a model read.

The pure API is `run_scene_selector_control`, with owner-supplied property
callbacks. It returns an immutable `SceneSelectorControlState` and a detached
review receipt. The state represents one retained form binding, with separate
`current_scene`, `bound_scene` and `action_source_trigger`. Typed continuation
is internal to the owning SceneManager. A fresh owner or Reset starts unbound;
the engine has no module-global mutable state. SceneName pending text is owned
by its separate control engine and is neither committed nor discarded here.

The owning model's optional bound-list observer checks the actual collection
generation when a selection consumes it. It is not Binding.ReadValue and does
not run an automatic PropertyChanged or currency callback. Native creation
refreshes the whole Network and replaces every loaded Group's Levels list.
An old control binding retains its old rows until explicit rebinding, including
when a getter creates an action after the trigger-current handler bound its
list. A TriggerGroup setter alone cannot rebind the action list. Declared
manual caches and snapshot-only pure suppliers retain their separately supplied
inventory behavior. Read [native creation/collection rules](edlt-scene-inventory-timeline.md).

The callback journal distinguishes source handler binding operations from
setter WriteValue calls. A failed callback stops immediately: the engine does
not replay a setter, run a following handler, issue a save or clean up a remote
object. Native backup, fresh readback, one parent PP save, project persistence
and uncertain-send handling remain the outer transaction owner's responsibility.

The static recovery binds SceneManager's three CurrentChanged methods and
InitializeComponent, EDLTScene property/list methods, and complete original input
hashes in the selector source proof. These are static source facts. No original
instructions, WinForms host, Framework event loop, VM, vendor service or physical
C-Bus device executed for this engine. Culture ordering, implicit currency
first-selection, null parsing, asynchronous callbacks, automatic notification
cascades, scene-switch Name refresh, queued invocations and modal close remain
outside this explicit profile. Complete Toolkit/GUI parity and issues 72–75
remain open.
