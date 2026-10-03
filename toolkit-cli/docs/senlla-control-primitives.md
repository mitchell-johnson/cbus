# SENLLA persistent control primitives

`senlla_control_primitives.py` implements the internal programmatic Proflat key
control path using the same live key engine and canonical objects. It retains
lookup keys, display keys, Text, EditValue variant kind, Items, selection, update
and click counters, controller activity, roots, final reference subscriptions,
and actual collection notification order. It supplies the primitive requests
issued by `senlla_key_controls.py` and the initial Group/Scene/function binding
phase before M8 hooks.

The entry profile is a live, unmasked, unfocused, single-line control before
its inner HWND exists. The scope covers source programmatic normal-load/save
events. It excludes manual popup input, destruction, focus transitions,
replacement of the owner, arbitrary expression parsing, visual hint/menu
layout, and a complete 93-field owner. Actual late light/PEC/PIR/global controls
and backend creation are supplied by their owning components.

## Initial source binding

Create `SourceControlStrings` from the actual loaded template Description
catalogue and resource strings. `group_modify` is the scalar nil representation;
`modify_display` is the separate resource written by Clear/SetSelText. Supply a
lazy object adapter:

```python
provider = PersistentControlPrimitives(
    SourceControlStrings(descriptions, group_nil, group_multiple,
                         group_modify, modify_display),
    text=NativeText(),
    group_objects=current_object_collection,
)
controls = provider.initial_controls(engine)
engine.install_m8_hooks(control_dispatch=controls)
controls.finish_m8_guard()
```

`engine` must be at `fresh_function_bindings`, before hooks and before calling
the engine's isolated `fresh_function_bindings()` helper. Initial binding runs
all eight Group/Scene preparations, then each row's current function root,
actual unsupported-template reset, final Template attribute binding and scalar
render. It leaves the engine at `m8_hooks`.

The object adapter receives `(engine, key, kind)`, where kind is `group` or
`scene`. Return `SourceObjectCollection(actual_collection, get_count, get_item,
describe, get_object)`. Count and ordinal reads use the current collection and
its actual manager order. `get_item` executes actual ToString and returns a
canonical `SourceObjectChoice`; `get_object` rereads only the pointer after
Items.AddObject. `describe` executes CURRENT ToString for a selected object,
including an object outside the current list. These inputs are source object
reads; they do not supply completed Text, Items or selection outcomes.

Group and Scene bindings stay distinct. Their scalar handles watch the final
PrimaryGroup or ExtensionNeo.Scene reference attribute and subscribe to the
current target. Function bindings watch the final Template attribute. They can
render during attribute publication while the parent key is still updating.
RootKeyLink and RootUnitLink followers retain actual binding positions and use
captured counts with CURRENT ordinal rereads. Source Group preparation has a
final RenderDisplay; Scene preparation omits that call, so initial nil Scene
Text remains empty. Initial Modify prepares a disabled, inactive Group control
before the later function subset check can reset model template25 to16.

Function collections preserve Clear's descending per-row notifications and
each Append notification. The root handle rebuilds its index list before
delivering Link followers, then handle followers. Group order comes from its
actual manager; Scene sort uses the source TStringList moving-pivot QuickSort.
The later broadcast frame owns a real `ProgrammaticCollection`; its current
subscribers run at the actual managed EndUpdate publication.

## Cache and synchronous events

SetItemIndex writes the current lookup key and EditValue before its inner text
write. Duplicate labels preserve the requested ordinal. Equal actual Text
skips the outer Text setter and preserves its prior variant cache. Lookup text
uses the source uppercase prefix scan from ordinal0 and UTF16 unit counts.
Style0 validates nonempty text against complete lookup labels; style1 accepts
free text. Clear writes a null variant and updates the lookup key through the
inner text route. SetSelText validates before its inner display write.

`ProgrammaticCombo.property_on_change` optionally holds the actual synchronous
`callback(current_combo)`. The no-HWND inner SetTextBuf sends WM_SETTEXT then
CM_TEXTCHANGED. TCustomEdit.CMTextChanged explicitly invokes Change without a
handle. The combo's inherited change-event catcher updates lookup data and
delivers Properties.OnChange before the outer setter resumes. Outer click
locking does not suppress this property event. SetIndex callbacks see the new
EditValue; SetText callbacks see the old cache before later synchronization
from CURRENT post-callback Text. Nested setters and failures preserve native
counter unwinding and final CURRENT-index comparison. Fresh key-control
property callbacks and Click/actions remain nil.

Programmatic SetItemIndex does not invoke FlashCx DoIndexChange. The provider
records actual WM0x426 posts and requires explicit delivery; it does not drain
messages automatically or acknowledge the unresolved manual selection handler.

## Windows text boundary and evidence

`WindowsTextPrimitives` calls actual CompareStringW with LCID_USERDEFAULT0x400,
NORM_IGNORECASE1 and explicit UTF16 lengths, then subtracts2 exactly as source
AnsiCompareText does. Every comparison calls the API, including identical or
empty inputs; API failure remains -2. Lookup/validation uses actual
CharUpperBuffW. Exact buffer equality and unequal unit lengths prove only the
uppercase-equality results used on that separate route. Host casefold and
Unicode sort order are not native comparison authorities.

A non-Windows host refuses an unresolved comparison at its actual source call.
The focused tests use an explicitly authored API double to verify conditional
cache/order vectors; they do not establish Windows NLS or original-application
acceptance. Missing metadata, resource catalogue, canonical manager order,
manual handler or current object prerequisites also refuse at the source site.
Interrupted owning callbacks invalidate the live control/engine pair.

The sanitized fixture contains exact method digests/counts, numeric VMT slots,
Proflat DFM digest/selected properties and resource digests/identifiers. It
contains no vendor unit specifications, UI captions or help text. No original
application or hardware was executed, and no full test suite was needed for
this component.
