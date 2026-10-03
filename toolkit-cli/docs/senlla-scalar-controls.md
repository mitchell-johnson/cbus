# Internal SENLLA scalar controls

`SENLLAScalarControls(late_unit)` binds persistent controllers to the **same**
Unit and bank attributes constructed before PP loading. It does not import a
final scalar dictionary, replace managers, apply every control, or admit a
complete Toolkit save. The source fixture is
[senlla-scalar-controls-source.json](../research/fixtures/senlla-scalar-controls-source.json).

The owning director invokes these separate source positions:

| Source position | Concrete method |
| --- | --- |
| Base Light target raw track, then margin track | `bind_light_target()`, `bind_light_margin()` |
| Maintenance checkbox, then its group combo | `bind_boolean('LightLevelMaintActive', checked_changed=...)`, followed by the owning group provider |
| PEC polarity, then broadcast checkbox/list | `bind_pec_polarity()`, `bind_boolean('LightLevelBroadcastActive', checked_changed=...)`, followed by the owning list provider |
| Target hook or ST7 SetupNonFlash, before maintenance OnChange installation | `initialize_light_target_text()` |
| Ascending Surface Bank scalar bindings, before that row's group bindings | `bind_bank(index)` |
| Same row after low/high group binding | `refresh_bank_enabled(index)` |
| Global bank group checkbox threshold setter slice | `bank_group_checks()` |
| Base/Surface Restore enum radio and preset positions | `bind_power_state(name, descriptions=...)`, `bind_power_preset(name)` |
| Restore UpdateEnables prefix, with actual getter refusal | `refresh_power_enabled()` |
| Global indicator radio, with excluded ordinal3 | `bind_indicator_control(descriptions=...)` |
| Global nonflash status Setup/Populate | `initialize_global_status(resources, text=...)` |
| Actual focused controller exit | `exit_control(name)` |
| Actual controller Apply call | `apply_controller(name)` |

The `checked_changed` function synchronizes the actual owning form's Checked
view. It is not a model setter or substitute for a Click handler. Native
CheckBox render sets ReadLock before SetChecked, suppressing its dynamic Click.
The source's manual maintenance/broadcast handlers, and bank low/high group
combo bindings, remain concrete owning form operations between these methods.
No omitted operation is acknowledged as a completed callback.

## Render and write behavior

An integer controller renders its current representation while locked, then
reads the **current** attribute again to restore the cache. Margin Position
clamps to1..100; custom bank lux tracks clamp/round to0..255 positions. Render
feedback can leave the controller dirty while its pending cache still contains
the original scalar. `umExit` commits that pending cache only through an actual
control exit. The direct target helper caps values above200 through the real
setter; its edit text uses the captured200 even if BeforeChange cancels or
transforms that write. Logical margin percent is not recomputed by the cap.

Apply retains the native dirty/read-only/active/render-lock gates, actual
BeforeChange validation, exception refresh and base dirty clearing. Boolean
SetAsBoolean marks dirty even for an equal cache value; the actual Boolean
attribute still suppresses equal writes. Radio Click writes its Boolean or
enum attribute directly. Bank polarity becomes inverted only after its initial
radio binding, matching the source setter order.

Each inactive bank row clears its own low/high use flags before invoking one
ascending all-bank loop. That loop reads current Low use before setting High
to2550, then reads current High use before setting Low to0. Earlier inactive
rows can normalize later rows before those rows clear their flags. Actual live
bank setters deliver real block feedback and nested notifications.
This is the threshold model-setter slice. The complete native checkbox
handler also reads the managed bank collection and current use flags for
control visibility before and between those setters. Its full display and
getter route remains an owning boundary.

Global IndicatorControl excludes list ordinal3; a loaded3 clamps to radio
index2 and the direct radio setter writes2. Global status builds253 choices
for3..255, installs Properties.OnChange afterward, then selects the exact
current formatted label. Stored0..2 therefore selects3 and writes3 under the
combo's click lock;3..255 remain unchanged. Resource suffix/zero-label readers
must supply actual localized source strings. This component never supplies
English Toolkit captions. Power radio descriptions similarly require the
actual current EnumValues registration in ordinal order. The focused tests
provide explicitly authored resource doubles.

## Remaining composition boundaries

This checkpoint is a concrete scalar binding component, not full director
bootstrap or Show/Apply acceptance. Generic Global RampRate/Potentiometer
combos, object selectors, Surface target/margin `TargetLevel.Value` controls,
their current Network.InterfaceState/query handler, complete persistent frame hook/display
lifetimes, identification, actual focus/message delivery and normal save
orchestration remain separate owning work. Enum-list mutation/rebinding is not
inferred from the captured description rows. Typed inputs cover signed32
numeric controls and Boolean/ordinal controls; arbitrary Delphi numeric text
grammar is outside this internal API.

`refresh_power_enabled()` executes only the native prefix up to the first
unimplemented managed getter and raises `ScalarGetterRequired` with a frozen
`ScalarGetterRequest`. Margin Use and its current group precede Target Use
and its current group; a true use flag stops at that group's native
`IsUnused` call. With both use flags false, their radio Enabled values become
false before the low-bank-use function stops at actual collection Count.
There is no acknowledgment or detached-result executor. The later bank
GetItem, High-use branch, remaining IsUnused and preset Enabled effects must
be composed by their real owner. A numeric group identity cannot replace
native dirty/cached Address state, and a fixed bank tuple cannot replace
Count resolution or the reverse-reference resolution performed by GetItem.
The request records the source position and canonical identity without
inventing those effects.

The retained OnApply toggles ambient display off, processes actual messages,
executes base save, then restores the captured state on successful return. It
does not enumerate and apply all scalar controllers. This component therefore
exposes individual exits and never fabricates a bulk Apply schedule.

Source proofs come from static decoding of pinned method/DFM spans. Neither
the original application nor hardware was executed. Authored focused tests
exercise same-object callback/cache order; they do not establish native GUI,
Windows linguistic comparison, project notification or physical acceptance.
