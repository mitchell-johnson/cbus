# SENLLA fresh PEC and PIR handler components

`senlla_fresh_forms.py` is an internal prerequisite for the eight-key SENLLA
owner. It computes complete existing-object maintenance and broadcast choices
and emits the native form handlers' ordered setter and control requests. It
does not issue PP writes or claim a complete unit save, original GUI execution
or hardware acceptance.

The path-free source receipt in
`research/fixtures/senlla-fresh-forms-source.json` contains 190 freshly reopened
method spans, the pinned EXE/MAP hashes and 17 numeric/request literals. It
incorporates the corrected parent-key update-depth and bank feedback contracts.
Original executable instructions were never executed.

## Current owning context

`FreshFormContext` is immutable. Supply the owning model's canonical application
and group object IDs, complete ordered application group inventories, all eight
block groups/display strings, bank Active values, current key Scene status,
template types, ordered key references and Light/Dark/Any/Sunset flags. Also
bind PEC/PIR/Join/DualJoin/Corridor references, Corridor Active, both maintenance
and broadcast references/Active values and current native control facts.

An identical address in two applications identifies two different group
objects. The inventory must describe actual manager-owned objects. Missing
identities are refused when a handler dereferences them. A PEC collision needs
the already-existing primary unused255 object; the helper never fabricates a
group creation or dialog decision.

The source GroupByAddress route looks up255 by looping the same manager Items;
it has no special detached unused object. Create=true adds a manager entry when
absent, while the fresh collision uses create=false. A nil secondary application
is valid for the allocation pointer comparison, which selects False. Choice
population dereferences its address only after the free probe succeeds and
refuses that native nil-dereference outcome.

`maintenance_choices(context)` returns source order: accepted blocks0..7,
then unallocated used groups in primary manager order and secondary manager
order when its application address is not255. A free accepted block enables
those extra choices only when its group is unused and its **same-index** key
is not a Scene key. This test does not examine key allocation. Active banks
are omitted; the current broadcast block is omitted only while both features
are active.

`broadcast_choices(context)` retains blocks0..7 except the current maintenance
block while both features are active and blocks shared by a Scene key or a key
with any occupancy flag. Bank Active, group use and free allocation are not
additional broadcast filters.

## Request executor protocol

Start a handler generator with one current context. Each yielded `FormRequest`
has a method, target kind/index, immutable value, native source position and
callback contract. Execute that exact operation in the owning engine, finish
all synchronous callbacks and then resume with `generator.send(new_context)`.
Calling `next()` after the first request refuses the missing updated context.
The generator returns its last context through `StopIteration.value`.

```python
handler = broadcast_after_change(current_context)
request = next(handler)
while True:
    current_context = owner.execute_request(request)
    try:
        request = handler.send(current_context)
    except StopIteration as completed:
        current_context = completed.value
        break
```

Native object-reference setters retain attribute-manager parent Begin/EndUpdate
around generic publication, dedicated AfterChange and nested callbacks. Equal
references still invoke dedicated callbacks. Equal Boolean assignments return
without any callback. For unequal template references, tracked-root Smart
notification precedes the dedicated key template handler, while the key remains
updating. The executor must retain that timing and the bank-owned feedback guard.
Use the owning `senlla_lifecycle` substrate for its reference attribute's own
CanDoChange guard, BeforeChange changed flag, nonnil-to-nil reset notifications
and callback exception unwinding. A reference setter refused while its attribute
is already updating has no dedicated callback.
This component does not substitute a naked field assignment for that chain.

Control requests also require a real owning executor. `Populate*Choices` carries
the source list for the supplied context; execute the native population and its
installed control callbacks in their order. Return the actual resulting
`broadcast_items` collection before a broadcast fallback. The fallback reads
candidate0 from that retained collection, rather than rebuilding a list from a
later graph. The native Count<0 guard admits Count0; an empty list therefore
refuses as the native index-error outcome.

`IndexOfAndSetItemIndex` preserves the source control operation. Native
TStringList comparison invokes Windows CompareString with LCID0x400 and
NORM_IGNORECASE. The executor must bind its resulting index/selected object and
installed OnChange facts. Python casefold or the current host locale is not an
equivalent substitute. An actual selection can be passed to
`maintenance_combo_changed`: Block selects MaintBlock; Group invokes the native
allocation scan; nil or another object type invokes no model setter.

## Handler order and normalization

Initial PEC group binding installs its callback before activation. Unused255
invokes Off=false; a used group preserves Off. PIR binding does the same for its
own Off value. Both happen before later Surface visibility changes. Use
`pec_enable_changed` and `pir_enable_changed` at their actual binding positions.

ST7 initialization populates broadcast then maintenance choices before setting
up hooks and controls. Its `SetupNonFlashComponents` runs the separate owner's
target-lux clamp before installing maintenance OnChange and selecting by the
current maintenance block display string; `setup_maintenance_selection` models
that tail. Initial linked maintenance-block callbacks can already repopulate and
select0 while the features share an active block. Use
`maintenance_block_changed` at each actual expression callback position.

The final explicit fresh calls run `maintenance_checked` before
`broadcast_checked`. The PEC collision check runs even when maintenance is
inactive. A used PEC group identical to Join, DualJoin, PIR, any block group or
an active Corridor group clears to the primary unused object. It then rereads
both Active values and block references before any same-block fallback, manually
invokes the PEC enable callback even without a group change, and refreshes
broadcast choices. PEC and PIR IncludeItem filters are intentionally distinct:
PIR excludes PEC only while maintenance is active and has no block-group filter.

`set_maintenance_group` scans all eight blocks for the first unused group and
same-index non-Scene key, then requests Secondary, Group and MaintBlock in that
order. This allocation scan does not repeat the choice list's bank-active or
broadcast exclusions. The selected group and chosen block stay captured while
their setters' callbacks run.

`broadcast_after_change` skips timer/function refresh only when both features
are active and their block objects are identical. Otherwise it invokes all
eight timer-override setters before scanning keys. Current active broadcast
block gets microfunction8; all other blocks get nil. The later key scan resets
templates29/30/33/34 sharing the **current** broadcast block to16. It rereads that
block and each template after earlier callbacks.

The manual fresh broadcast handler clears each sharing key's Light, Dark, Any
and Sunset flags in that order, then rereads Scene status and resets a remaining
Scene key to16. A row admitted before a callback still completes all four flag
setters; later rows use current references. `input_key_blocks_changed` retains
the inherited callback, all-key flag clearing, broadcast reassignment and the
changed key's direct non-Smart flag refresh order.

Native IsSceneKey is true for current template types23,24,25 and false for a nil
template. The context validates the supplied Scene status against those current
types rather than accepting an independent caller Boolean.

## Unit identification metadata

`clean_unit_name_text` computes the logical SetText target from actual control
text. It retains codepoints33..59,61,63..96 in original order, removes all others
and uses NEWUNIT if nothing survives. It performs no Trim, uppercase or space
replacement.

`unit_name_exit` uses an immutable `IdentificationContext` with actual control
text, actual controller cache, actual model UnitName and actual unit TagName.
It first requests SetText, then requires the executor's current identification
context. It rereads TagName and actual control Text afterward and requests
immediate TagName assignment only for an empty name or exact NEWUNIT. An
unchanged SetText may deliver no Change event; the helper never infers a new
cache merely because displayed text differs from the model's text.

The TagName request targets the unit's managed `TCISTagAttribute` through
`TStringAttribute.SetValue`, rather than the separate `TUnitData.SetTagName`
method. Its BeforeChange runs before Begin even for equal requests and receives
the mutable candidate and changed flag. A false flag produces no update; a
changed candidate longer than 32 UTF16 code units raises before Begin. The
executor runs the native attribute/manager notification order, including
`HandleTagNameAfterChange`, its optional owner callback and conditional manager
timer. Reference updating guards and nil-reset rules do not apply to this
string writer.

The direct fresh form Exit handler does not itself run FlashEdit umExit Apply.
The context's `cached_text_differs` reports only the supplied actual cache versus
the actual model; it does not assert that an exit/apply occurred or is scheduled.
The scalar serializer still requires actual final UnitName and
Project.TagName metadata context. Raw PP text is not evidence of native
ecUpperCase or MaxLength window behavior; control rendering and a later actual
exit remain executor facts.

The [frozen callback-prerequisite source check](../research/fixtures/senlla-callback-prerequisite-source-check-20261004.json)
covers thirteen SENLLA modules at authored commit `25533098`: 232 parents,
3,694 separate subtests and zero failures, errors or skips. All 4,080 tracked
inputs remain unchanged in the frozen checkout. This source-only increment
adds reviewed synchronous lifecycle and fresh form request components.
The key event engine, complete owning save/public CLI and installed-wheel/
original/native/hardware acceptance remain open. Full suites are deferred
for speed; earlier check receipts retain their historical scopes.
