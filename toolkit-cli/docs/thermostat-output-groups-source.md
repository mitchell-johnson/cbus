# Thermostat ordinary output groups: static source contract

This annex supports ordinary agent loading followed by explicit, ordered group
selections and one owning settings save. It covers fourteen plant outputs, four
dampers and five internal relay assignments. It does not apply a template, run a
new-group allocator, simulate application changes, or execute the original GUI.

[Typed output Add](thermostat-output-add.md) is a separate admitted post-load
operation that can now interleave with these selections. Its direct dialog
wrapper, numeric allocation and name rules are pinned in
[the Add source annex](thermostat-output-add-source.md). The ordinary getter
rules below are unchanged and run before that explicit history.

The source is Toolkit `1.18.0.2754`. The EXE SHA-256 is
`9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`; the MAP SHA-256 is
`f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb`.
[The reproducer](../research/thermostat_output_groups_static.py) reads those files
as static data, checks instruction locations and DFM bindings, and emits
[the sanitized receipt](../research/fixtures/thermostat-output-groups-source-review.json).
The receipt includes method bounds and hashes, source-derived default-label
branches and published control fields. It contains no executable body or private
paths. Neither the reproducer nor the owned tests execute vendor instructions.

```sh
python research/thermostat_output_groups_static.py --exe /private/input/CBusToolkit.exe --map /private/input/CBusToolkit.map
```

## One ordinary load, then selections

The base `TCBusThermostatCGateAgent.AfterLoadProgrammingInformation` starts at
`0x128e06c`. Its ordinary fresh-model path uses the false template-event flag;
it does not call the template `GetGroup`/`GetNewGroup` allocation workflow.
The consumed dependency order is:

1. Resolve application 172 and the `ZoneGroup` object in it.
2. Bind `ApplicationNumber` and resolve inherited setback references.
3. Load the fourteen outputs in the order below.
4. Load four dampers, then five internal relay references.
5. The derived programmable agent loads schedule references.
6. Apply the ordered explicit output selections against that complete graph.
7. Validate the role identities and project their addresses during the one owner save.

| Family | Exact PP parameters, in ordinary load order |
| --- | --- |
| Cooling | `CoolActivationOutput`, `CoolStage1Output`, `CoolStage2Output`, `CoolStage3Output`, `CoolFanLowOutput`, `CoolFanMediumOutput`, `CoolFanHighOutput` |
| Heating | `HeatActivationOutput`, `HeatStage1Output`, `HeatStage2Output`, `HeatStage3Output`, `HeatFanLowOutput`, `HeatFanMediumOutput`, `HeatFanHighOutput` |
| Dampers | `DamperZone1Output`, `DamperZone2Output`, `DamperZone3Output`, `DamperZone4Output` |
| Relays | `InternalRelay1GroupNumber` through `InternalRelay5GroupNumber` |

The output getter calls occupy `0x128f11f`–`0x128f41e`, programmable damper
getters `0x128f474`–`0x128f525`, and ordinary relay lookups
`0x128f685`–`0x128f795`. The template flag at `0x128f654` skips the raw relay
load only on the separate template path. Derived AfterLoad `0x12994d0` invokes
the base at `0x12994f5`; its schedule lookups follow at
`0x1299912`–`0x1299a7e`. A single shared object ledger is therefore necessary:
source-1 setback, outputs and schedule can share application 203 and object
identities. Concatenating independently generated graphs loses causal reuse.

The ordinary PP edits retain their existing pre-load meaning. Explicit output
selections occur after the complete load. A load-created or renamed group stays
in the resulting graph even when a later selection chooses a different object.
This lifecycle distinction is intentional and visible in the plan.

## Application and prefix dependencies

`CreateSpecialApplications` (`0x128df98`) first looks up application 172 without
creation (`0x128dfcf`). If absent it requests creation (`0x128dff7`), assigns
`Air Conditioning` from resource `0x128b218`, and saves. An existing application
retains its name. The ensuing `ZoneGroup` lookup is
`GroupByAddress(raw ZoneGroup, true)` at `0x128e0fc`–`0x128e113` in that
application. Missing ordinary addresses are named `Communication Group N`;
255 is a real `<Unused>` group. No virtual group is synthesized.

`ApplicationNumber` is bound through `ApplicationByAddress(..., true)` at
`0x128e518`. Generic creation obtains the catalogue name via
`GetApplicationName` (`0x85adc4`): start with the decimal address string, then
replace it with the matching catalogue name. Within the bounded selected-app
profile 48–95 and 203, 56 is `Lighting`, 95 is `DALI`, 203 is `Enable Control`,
and other addresses use decimal names such as `49`. Existing names are
preserved. The original output selector itself has no Lighting-family filter;
that selected-app range is an owned product admission boundary.

Generic application/group creation uses the existing application and Group
agent paths established by [the remote-reference annex](thermostat-remote-references-source.md).
The command kind is `Group`, including under 172 or 203. XML `NetVar` under 203
is a separately admitted serialized shape; it must not be inferred from the
application number. Actuator applications 115/116 do not supply the output
prefix or selector inventory and are outside this dependency projection.

`AutogeneratedPrefix` (`0xfe2a74`) reads the actual resolved ZoneGroup object's
address and formats `CG` with `[%s%2.2d]`. Thus address 5 gives `[CG05]`, and
address 123 gives `[CG123]`; two digits are a minimum, not truncation.

## Ordinary getter creation, reuse and rename

Every output getter receives its raw address and `cl=false`. The representative
`GetDefaultCoolActivationOutputGroupForPlantType` begins at `0xfe6140`.
The fourteen source-derived label tables are retained in the receipt; they are
also the tables used by the earlier post-load recovery.

* Address 255 returns `GetUnusedGroup` (`0xfe6008`), whose lookup requests real
  group 255 with creation enabled (`0xfe6028`–`0xfe602f`).
* Other addresses first perform an exact address lookup with creation disabled.
  An existing manually named group returns unchanged, even if the plant type
  would normally leave that output unused.
* A missing group or an existing group whose name starts with the exact,
  case-sensitive own prefix enters the plant-specific default-label branch.
  If that branch has no label, an existing group remains unchanged; a missing
  group becomes the real unused object.
* A label-bearing branch calls `CreateAndRenameGroup` (`0xfe2830`). With the
  ordinary false flag, an existing requested object is renamed directly, in
  place, to `prefix + ' ' + label` (`0xfe29be`–`0xfe29e9`).
* If the requested object is absent, that helper first calls
  `FindExistingGroup` (`0xfe2afc`) for the complete generated name. A match is
  reused; otherwise it creates at the requested address. It does not allocate
  a different free address.

`FindExistingGroup` scans manager order and compares `SysUtils.LowerCase`
results (`0xfe2b8b` and `0xfe2b9a`). XML order is not that manager order.
Ambiguous matching generated names must therefore be refused rather than
arbitrarily selected. The owned implementation also bounds case matching to
its explicitly documented character profile; it does not claim host-locale
Delphi lowercasing for arbitrary Unicode.

The damper helpers (`0xfe959c`, `0xfe969c`, `0xfe979c`, `0xfe989c`) differ:
an existing non255 group returns unchanged on the ordinary false-flag path,
including an own-prefix name. Missing groups use labels `Damper Zone 1` through
`Damper Zone 4`; missing generated-name peers can be reused before creation.
Basic thermostats instead look up group 255 four times with creation disabled
(`0x128f559`, `0x128f58f`, `0x128f5c5`, `0x128f5fb`); the model may contain nil.
The five relays use raw exact-address create-enabled lookups with generic
application group names, not plant-generated labels.

Default labels consume the loaded virtual plant type and current installation.
Raw type 8 virtualizes to 11 when one of the ten source-tested output bytes is
non255. The existing post-load table pins that exact set. Installation code 0
leaves the current installation nil in a fresh model; codes 1–9 bind their named
installation; higher codes take the code-1 fallback (`0x1293694`–`0x1293975`).
The profile restricts plant types to the documented admitted domain rather than
claiming the original unchecked high-bit enum behavior.

## Selector eligibility and callback effects

Cooling, heating and damper `SetupFlashComponents` bind the group references to
`ApplicationObject.Groups`; internal relays do the same in
`TcdThermostatPlant.SetupFlashComponents` (`0x1127424`). The DFM controls use
`FlashController.UpdateMode=umChange`. Explicit selections only choose actual
objects present after the whole load. Selecting absent address 255 does not
create it. [Accepted typed Add dialogs](thermostat-output-add-source.md) are a
separate operation on the same loaded graph; subsequent selections can use
their newly created identities.

| Selectors | Original enabled/visible rule |
| --- | --- |
| All seven cooling selectors | Cooling action enabled for virtual plant types 2, 3, 5, 6, 7, 9, 10, 11 (`0x1128d74`) |
| Heating activation and stages | Heating action enabled except virtual types 0, 2, 5 (`0x1128dec`) |
| All three heating fan selectors | Heating action enabled, and type is neither 0 nor 8 (`0x1125a40`) |
| All four damper selectors | Programmable form, virtual type nonzero, at least one loaded `InternalPlantZones` bit 1–4 checked (`0x1129970`) |
| Five relay selectors | `GetUnitHasRelays` is true for TSA5/TSB5; loaded master state (`ControlledZones > 0`) enables the controls |

`SetupComponents` (`0x11289e4`) hides relays when the virtual getter is false
and hides the plant-zone/damper controls on basic thermostats. Base
`GetUnitHasRelays` is false (`0xfecc9c`); TSA5/TSB5 overrides are true
(`0xfeda5c`, `0xfeda48`). Master/slave control enabling is at `0x1129154`.
It disables zone checkboxes for a slave but does not clear their checked state
and does not disable the cooling/heating/damper action buttons. Consequently a
programmable slave can enter the damper dialog if its loaded zone/type gate
passes. Its later save still writes unused damper values. Admission uses loaded
state, not the slave-normalized final PP state.

Six fan `Handle...IncludeItem` callbacks always include unused and exclude the
other two same-side fan object identities. This rule is evaluated per selection,
so swapping fan groups requires an intermediate unused selection. Stage and
activation duplicates are checked by the parent validator after the history.

The 23 model setters assign their `TObjectReferenceAttribute`; equal identity
suppresses reference replacement (`SetFlashObject`, `0x7ddbf4`). Plant
`HookEvents` (`0xfe1664`) subscribes zones, modes and ventilation, not these
output references. Cooling `cmbGroupChange` (`0x1125174`) and heating
(`0x1126140`) only update an external-relay warning. Damper
`cmbGroupChange` (`0x1126ad4`) additionally stores the last non255 selection in
four UI cache fields, relevant to later zone histories but not this current
save. Internal relay combos have no explicit change callback.
`UpdateInternalRelayGroup` belongs to `RefreshThermostatGroups`/`UpdateGroup`
(application migration), not these selector assignments. Selecting an output
does not automatically reassign its internal relay.

## Validation and save

Base `ValidateProgramming` (`0x11320c0`) checks cooling, heating and damper
collections before inherited remote validation. `ValidateCoolingGroups`
(`0x1131b70`), `ValidateHeatingGroups` (`0x1131c28`) and
`ValidateDamperGroups` (`0x1131ce0`) pass all 7, 7 and 4 role objects to
`SameGroups` (`0x1131ad0`), regardless of plant stage count. Repeated non255
identities fail within each collection; repeated unused or nil values do not.
Sharing between cooling and heating, between outputs and dampers, or with
remote controls is not prohibited by these three validators. There is no
relay uniqueness check in this parent path.

Base `BeforeSaveProgrammingInformation` (`0x129471c`) writes the five relay
addresses first (`0x1295aee`–`0x1295bf0`), then all fourteen output addresses
(`0x1295d19`–`0x1296035`). Those references must be nonnil. Each damper stores
its address only when nonnil and master; otherwise it writes 255
(`0x1296045`–`0x129626d`). The existing scalar save also normalizes dependent
slave/plant and damper-modulation fields. It must compose with these group
addresses in the same candidate and one transaction.

Owned preflight deliberately completes validation before mutation. This does
not claim to reproduce partial original graph effects before a failed later
validation. Object creation, rename, PP save and project save are separate
backend operations. A graph-only change requires zero PP saves and one final
project save; a changed PP image uses the one owning PP save. Preserve complete
unrelated XML, all existing Level data and metadata, identity-fenced names and
load-created objects. Uncertain writes or saves must not be replayed.

## Focused acceptance obligations

Use literal expectations for ordinary rename retained after a later selection;
unique generated-peer reuse; missing unused, damper and relay creation;
application172 and ZoneGroup creation; selected application catalogue names;
ordered fan swap versus direct exclusion; all family/master/slave gates;
separate role duplicate validation; and shared application203 getter ordering.
Verify graph-only persistence, fresh PP readback, explicit project reload,
stale/tampered plan refusal, unrelated metadata preservation and uncertain-save
no replay on both owned backends. Those results establish the bounded owned
workflow, not executed Windows control binding, a native service or hardware.
