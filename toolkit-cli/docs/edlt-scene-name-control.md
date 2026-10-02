# Explicit eDLT SceneName control callbacks

The typed `scene-name-control` operation models the source-established
`ComboBoxStaticText` callbacks for one retained scene. The SceneManager owns
the SceneName getter, static-name inventory and property allocator; the pure
event engine never sends C-Gate commands or saves PP. It does not run WinForms,
infer keyboard-generated selection order or establish physical rendering.

Use this nested operation within a SceneManager sequence:

```json
{
  "op": "scene-name-control",
  "scene": 1,
  "events": [
    {"event": "input", "text": "Kitchen"},
    {"event": "enter"},
    {"event": "close"}
  ]
}
```

Input is bounded by 64 UTF-16 units, so 64 ordinary BMP characters or 32
supplementary characters fit. An unpaired surrogate refuses. Embedded NUL in
input or known-name selection also refuses because host TextBox/WM_SETTEXT
behavior is unaccepted. This does not alter the separate property getter or
raw PP string semantics. Loaded names and
binding readback are not revalidated against the input length: the cached
SceneName can differ from the truncated saved PP image. The property allocator
owns the source-pinned .NET whitespace policy; the engine does not use Python
`strip()` or otherwise trim the submitted text.

| Event | Fields | Binding effect |
| --- | --- | --- |
| `input` | `text` | Changes display text and marks it pending; no property write. |
| `enter`, `leave` | Optional `binding_present` boolean, default true | Calls `WriteValue` then `ReadValue` if a binding is present. The read displays the actual getter result. |
| `arrow-preview` | `key`: `left`, `right`, `up` or `down` | Suppresses the next selection callback's write, once. |
| `selected-name` | Explicit `selected_index`; `name` for an active selection; optional `data_source_present`, `data_manager_present`, `binding_present` booleans | The known name is matched ordinally. A suppressed callback consumes suppression without writing. Otherwise an existing data source, nonnegative selected index and binding cause write then read. |
| `list-refresh` | `change_type`, `new_index`, `old_index`, `selected_index`; optional flags described below | A qualifying callback only reads the binding, discarding pending display text without committing it. |
| `close` | None | Marks an explicit end; unresolved pending text refuses. No automatic commit is inferred. |

`selected_index=-1`, no data source or no binding preserves the source callback's
no-write behavior. The supplied index is a callback fact, not a culture-sorted
position derived from the name table. Selection identity must be an exact member
of the owning model's current known names; earlier property writes can update
that collection. Data-manager presence records the source's listener rebind,
without claiming that a host listener was installed.

For `list-refresh`, the relevant change types are `item-added`, `item-changed`
and `reset`. A read requires visibility and either `new_index < selected_index`
or `old_index < selected_index` with `old_index != -1`. Other admitted .NET
change types are no-ops. Optional flags default to `visible=true`,
`list_updates_disabled=false`, `invoke_required=false` and
`binding_present=true`. Disabled updates return before the asynchronous branch.
Otherwise `invoke_required=true` refuses: the host's queued `BeginInvoke`
execution is outside this synchronous callback profile.

End of an events array is not an implicit close. Input-only histories return
`pending=true`, with the binding and PP unchanged. The owning SceneManager can
continue that history using its immutable internal control state; a later Enter,
Leave or qualifying list refresh resolves it. Composition/save must reject
unresolved pending text. JSON cannot supply or resume the internal state. Arrow
suppression likewise survives the next operation until a selection callback
consumes it. A setter failure stops immediately, with no following read or retry.

Each scene retains its explicitly modeled control display between operations.
A direct model edit or scene switch does not infer a host `PropertyChanged`
callback that refreshes that display. The model getters and exported views read
the current names; a control's later Enter writes its retained display unless
an explicit read callback refreshed it first. Automatic host notification and
scene-switch rebinding require separate original acceptance.

Receipts separate display text, the actual bound name, pending/suppression state
and ordered `WriteValue`/`ReadValue` actions. They are detached review output,
not accepted cache or state inputs. Known-name selection does not reproduce the
source's culture-sensitive suggestion sorting, autocomplete or equal-name
survivor rules. Pending modal-close ordering and asynchronous framework dispatch
remain explicit acceptance gaps.

The source-faithful SceneName property allocator retains its old name reference
while allocating the replacement. This differs from the historical additive
`set-name-text` operation, which releases the old reference first. Keep that
existing operation's vectors and strict new-text policy separate. Read
[the SceneManager guide](edlt-scene-manager.md) and
[retained grid/language histories](edlt-static-language-add.md) for their owning
model and parent save boundaries.
