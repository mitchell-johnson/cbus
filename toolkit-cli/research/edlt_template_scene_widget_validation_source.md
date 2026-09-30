# Scene widget Save validation: static source contract

Recovered 2026-09-30 from the private managed-pass disassembly; no vendor
execution, hardware, network, build, or GUI observation. No vendor IL copied.
The existing `edlt_template_terminal_evidence.json` pins FrmBaseUnit method
token `0x06000320`, RVA `0x0001bea4`, size 1062, IL SHA-256
`5faecbd46b710e7284107a751b5675835af7213a60bef700c1746c24d4ebdb9c`.
This is source-derived behavior, not original executable acceptance.

## Save boundary and options

Save validates serial first, obtains Widgets once, lazily filters each widget
with `WidgetType == 6`, and passes the ordered enumerable to this validator.
False stops before unit IsValid and SaveDialog. Exceptions propagate.
The validator returns true for null unit, null PPAttributes, or null widgetList
in that short-circuit order. Its widget enumerator and cycle enumerator have
finally disposal, including on early return and exceptions.

GetLabelStatusOpt initializes all flags and variants to zero, obtains WidgetData
and casts to SceneData. An unsuccessful cast leaves zero options. For SceneData
it reads WidgetByte(1).ValueAsInt, uses the first BitConverter byte, and splits
high/low nibbles. High nibble 1 means dynamic label text; 2 means dynamic label
icon. Low nibble 6 means dynamic status text; 7 means dynamic status icon.
It then reads raw integer variants WidgetByte(11) and WidgetByte(12), without
range normalization. These three byte reads occur even with no dynamic flags.

## Checks and their exact short circuits

For each widget with any dynamic flag:

1. Obtain unit.Network.GetApplicationByAddress(202, true). Null returns true
   immediately, discarding all accumulated inconsistencies and skipping later
   widgets. This is not a validation failure.
2. Obtain SceneData.SceneCycle (mutation described below).
3. For each picked PPAttribute, find the FIRST unit.Scenes element with
   SceneIndex == picked.ValueAsInt + 1. Missing scene skips this cycle entry.
   The predicate rereads picked.ValueAsInt for every candidate scene.
4. Evaluate scene.TriggerGroup (side effects below), then use the application
   captured in step 1 to GetGroupByAddress(result, false, false). Missing group
   skips the entry. Evaluate scene.ActionSelector, then use that outer group to
   GetLevelByAddress(result, false). Missing level does not skip checks.
5. If a level exists, access DynamicAll[labelVariant].Name; exactly null skips
   BOTH label and status checks. An empty string does not skip. This access is
   unconditional even for status-only options. A bad labelVariant therefore
   throws even if only status is dynamic.
6. A dynamic text side is inconsistent when level is absent OR its variant
   Image is nonnull. A dynamic icon side is inconsistent when level is absent
   OR its variant Image is null. Label uses labelVariant, status uses
   statusVariant. Image access occurs only for the respective active option
   and a present level. Status Name is never inspected.
7. Collect inconsistent scene OBJECT identities in separate per-widget
   HashSets for label/status. Repeated cycle references deduplicate. Nonempty
   sets are Dictionary.Add-ed by widget identity after the complete cycle.
   Repeated widget identity can therefore throw on dictionary Add.

No catch converts malformed PP, null nested collections, bad variant indices,
lookup exceptions, or notification exceptions into false. Partial getter
mutations remain when an exception or later validation failure occurs.

## Getter mutation and external requests

SceneCycle disables its binding list change events, clears it, and scans
WidgetByte(13)..WidgetByte(21). SceneCycleAddScene accepts values 0..8 inclusive,
retaining the PPAttribute objects. The first rejected value ends the scan;
the rejected byte itself is retained unchanged, but every LATER byte through
21 is written to 255 using ValueAsInt, rendering exact `0xFF`. PPAttribute
SetValue compares raw strings; decimal `255` and lowercase `0xff` therefore
still require a write and can set dirty/notify, despite numerical equality.
An offline raw fixed point requires exact `0xFF` for these trailing bytes.
It then reenables events and returns the list. No
finally restores event enablement if a read/write fails.

TriggerGroup is not a plain field read: it obtains App202(create=true), then
GetGroupByAddress(_triggerGroup,true,false). Missing group calls
set_TriggerGroup(255), which updates the field only if changed and raises
TriggerGroup, TriggerGroupName, AvailableActionSelectors notifications in that
order. A present group returns its AddressAsInt.

ActionSelector first evaluates TriggerGroupEditable: TriggerGroup !=255 and
a second TriggerGroup >=0. False returns -1 without changing selector. When
editable and stored selector !=-1, it gets App202(create=true), evaluates
TriggerGroup again, gets Group(create=true,false), then Level(create=true).
A present level returns AddressAsInt. A missing level, or stored -1, calls
set_ActionSelector(-1) before returning -1. That setter reevaluates editable;
when editable it gets App/TriggerGroup/Group/Level with create=true, stores
the resolved address or -1, calls RefreshDynamicLables, and raises
ActionSelector then ActionSelectorName notifications (no equality guard).
RefreshDynamicLables first evaluates TriggerGroup; it clears
CurrentDynamicLabels and returns if that result is255. Otherwise it clears
the list, returns for addr outside0..255 or missing Unit/Network, resolves
App202(create=true), evaluates TriggerGroup again, then uses Group/Level
create=false and appends every resolved DynamicAll DataStore object to
CurrentDynamicLabels. Thus even setter(-1) can clear this list.

Network GetApplicationByAddress returns first exact address match. Missing
app with create=true and bContinue=true sets bContinue=false, invokes the
AddApplicationRequest("202") event (return ignored), waits/polls/refreshes,
then resets bContinue=true. It has no finally recovery for failure. Group
and Level create=true getters likewise can invoke AddGroupRequest or
AddLevelRequest and refresh; group creation depends on static bAdd. The
outer create=false lookups do not prevent these nested create=true calls.
Offline validation must explicitly resolve these outcomes or refuse them;
it must not silently substitute a read-only field lookup.

## Reporting and decision

After scanning ALL widgets it reports all label dictionary entries, then all
status dictionary entries. Dictionary/HashSet native enumeration is used;
IL does not promise a sorted order. Per entry it rereads GetLabelStatusOpt,
prefixes `Widget {WidgetNumber - 5}'s `, and appends
`{Label|Status} variant {rawVariant+1} of scenes are inconsistent with {Label|Status} Type({Dynamic Label|Dynamic Icon}) : `.
Scene names render as `"{SceneIndex} - {SceneName}"`, joined by ` , `, with
two Environment.NewLine strings after each entry. SceneName returns empty for
NameIndex outside 0..63; otherwise reads unit.StaticLabels[NameIndex].Name.

Nonempty error text constructs CustomMessageBox(title=`Error: Validation
Errors`, heading=`Scene widget configuration has errors`, details=text,
SystemIcons.Error, MessageBoxButtons.OK, true), attaches SceneWidgetErrorHelp,
calls ShowDialog, ignores its result, and returns false. Empty text returns
true. Help dispatches network.ShowHelpForContextId using Rinna context for
catalogue R5045ED, otherwise eDLT context. Dialog failure propagates.

## Synthetic source-derived vectors (not runtime observations)

| Case | Facts | Expected |
| --- | --- | --- |
| No dynamic modes | byte1=0; raw variants readable | true; no App lookup, cycle read, or cycle mutation |
| Text/image conflict | byte1=0x10; labelVar=0; existing level Name=""; Image present | false, Label Dynamic Label error |
| Null name gate | byte1=0x17; labelVar=0; statusVar=99; existing level label Name=null | true; no status variant access |
| Empty name is checked | Same as previous but Name="" and statusVar=99 | index exception during status Image access |
| Missing level | byte1=0x17; group exists; selector getter resolves absent level | label and status inconsistencies, subject to nested selector normalization |
| Cycle normalization | byte13..21=[0,9,2,3,4,5,6,7,8] | cycle=[byte13]; byte14 remains9; byte15..21 become255 |
| Missing application | First dynamic widget App lookup resolves null | true immediately; cycle getter never called |
| Duplicate cycle | picks=[0,0], same first scene | one scene identity in each applicable error set |

Open boundary: original GUI/dialog execution and external add-event outcomes
are unobserved. Native collection ordering should not be claimed from IL.
