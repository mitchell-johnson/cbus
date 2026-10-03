# Thermostat output Add source evidence

The typed output Add history extends the existing ordinary output loader and
ordered selectors. It models an accepted Add dialog or a direct cancellation for
one enabled output, damper or internal-relay selector. Both outcomes use the same
evolving application inventory and the same owning settings transaction. It does
not execute the original form, invoke a vendor service or program hardware.

The source is Toolkit 1.18.0.2754. The EXE SHA-256 is
`9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`; the MAP SHA-256 is
`f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb`.
The [sanitized receipt](../research/fixtures/thermostat-output-add-source-review.json)
records 211 checked facts, 120 method spans, five DFM resources and the absence of
direct optional handler/address-limit assignments across 67 thermostat panel
methods. It contains hashes and derived facts, not original instruction bytes,
full disassembly, decoded unit specifications or private file coordinates.

Reproduce the receipt using explicit local source inputs:

```sh
.venv/bin/python research/thermostat_output_add_static.py \
  --exe "$TOOLKIT_EXE" --map "$TOOLKIT_MAP"
```

This command reads, hashes, decodes and checks bytes. It never loads the EXE as a
program or invokes its instructions. The optional source test requires those
inputs; its absence is a reported source-input skip, not executed vendor proof.

## Ordered inputs and load boundary

The new `output_operations` history contains either an existing selector outcome
or an Add outcome:

```json
[
  {"op":"add-output-group","parameter":"CoolStage1Output","outcome":"accept","address":12,"name":"Study cooling"},
  {"op":"select-output-group","parameter":"CoolStage1Output","address":255},
  {"op":"add-output-group","parameter":"CoolStage2Output","outcome":"cancel"}
]
```

The accepted record permits omitted `address` and `name`. The source constructs
a first-free address and default name before the dialog opens. The typed input
order is that seed, an optional integer address selection, then optional final
shown name text. This describes a reachable dialog result without claiming an
arbitrary text-entry history. Cancel permits only `op`, `parameter` and `outcome`:
it models a direct cancellation and does not run OK-only validation.

The existing `output_selections` input remains unchanged and is mutually
exclusive with `output_operations`. Both start after the complete ordinary load,
including its group creations, generated-name reuse and renames. Later selection
of a different group retains every earlier accepted Add. The existing role gates,
per-step selector exclusions and final form validation still apply; see
[ordinary output source evidence](thermostat-output-groups-source.md).

## Dialog wrapper and assignment

`TFlashCxGroupComboBox.DoButtonAddClick` spans `0xbc58e8..0xbc5cbc`.
`GetCBusApplication` at `0xbc5f50` resolves the selected group's application or the
prepared application/list binding. It creates a `TfrmGroupAssign`, obtains a
first-free address at `0xbc5954`, and refuses capacity exhaustion before showing
a modal dialog. This also prevents a direct-cancel history when no address is
available.

The provisional object is a `TCBusGroup`, constructed at `0xbc5980` in the bound
application's workspace. Its address is first-free. Its initial name is
`GetDefaultGroupName` plus `" %d"`. In the admitted applications this is `Group N`
for 48–95 and `Enable Network Variable N` for 203. The dialog receives the
application, provisional group, catalogue noun, blank old name and new-object mode.
The semantic creation kind is `Group`, including application 203; actual exported
Group/NetVar shape is a separate backend preservation contract.

Only modal result 1 accepts (`0xbc5b1b`). The wrapper calls the optional before-change
hook, adds the object to the manager at `0xbc5b3d`, saves it at `0xbc5b52`, then
assigns the clicked combo's bound reference at `0xbc5b83`. It refreshes the list
and posts the change notification. A nonaccept result frees the provisional
object at `0xbc5b9e` without manager insertion, group save or reference assignment.
No new field mapping is inferred: the clicked selector uses the same model
attribute as its existing ordered selection.

## Address and name rules

`TCBusGroupManager.GetNextAvailableAddress` (`0xf289fc`) scans numeric addresses
from zero. It does not allocate according to XML order. `GetMaximumPossibleAddress`
(`0xf28a58`) uses `GetHasReservedGroupAddress255` (`0xf261dc`), which returns true,
so the last Add address is 254. An occupied address is refused by OK validation;
255 remains a selectable existing unused identity but is not an Add address.

Fresh combo minimum/maximum fields are zero. `SetValues` (`0xbc356c`) changes the
zero maximum to 254 and offers free addresses in that range. `SelectedAddress`
(`0xbc34b0`) also has an editable-text fallback that parses and clamps text; the
public typed profile deliberately admits an integer outcome instead of this raw
text coercion path.

`cmbGroupAddressChange` (`0xbc31fc`) compares the first catalogue-noun-length
UTF-16 units of the current name using `SysUtils.UpperCase`. If that prefix
matches, or the name is empty, changing the address rewrites the name to the noun,
a space and the selected decimal address. The comparison does not require a word
boundary after the noun. In the canonical typed order, an explicit final `name`
follows and therefore overrides this rewrite.

`TFRMGROUPASSIGN.edtGroupName` is a Unicode `TEdit` with `MaxLength=32`.
`TCustomEdit.SetMaxLength` (`0x68540c`) and `DoSetMaxLength` (`0x6852f0`) pass that
limit to the edit control. The typed profile checks 32 UTF-16 code units before
trimming; it does not silently truncate input. Sixteen supplementary characters
use 32 units; seventeen use 34. Python's code-point count is not this limit.

`actOKExecute` (`0xbc2dc4`) validates in this order:

1. Apply `SysUtils.Trim` and refuse an empty name (message 2202).
2. Refuse exact equality with the containing **Project.TagName** (message 2204).
3. Refuse another object at the selected address (message 2201).
4. Refuse another group with the same ASCII-uppercase name (message 2203).
5. Set the provisional Address and trimmed TagName, then set modal result 1.

`Trim` (`0x618f9c`) removes leading and trailing UTF-16 units at or below `0x20`.
It does not remove NBSP or other Unicode whitespace. `UpperCase` (`0x6186e4`)
transforms only ASCII `a`–`z`, using XOR `0x20`; other UTF-16 units remain unchanged.
Python `strip`, `upper` and `casefold` are therefore not substitutes. For example,
`é` and `É`, or `straße` and `STRASSE`, are distinct under this source comparison.
No additional blanket reserved-name test appears in this dialog; `<Unused>` can
still collide with an existing name, while address 255 is independently reserved.

The Project dependency is exact and acceptance-only: the validator follows
application.GetNetwork (`0xbc2eb0`), network.Project (`0xbc2eb5`) and inherited
attribute `+0x9c` (`0xbc2eba`) before exact string equality (`0xbc2ecc`).
`TProject.InternalCreate` (`0xf2d200`) calls `TCGateObject.InternalCreate`
(`0xf47718`), which constructs the literal `TagName` attribute into that field.
Project Address is not a substitute. The wrapper and `SetValues` read only the
provisional group's name, so cancelled and selection-only histories do not
consume Project.TagName.

## Control gates and callbacks

The action-combo constructor writes `ActionButtons=3`, making Add and Edit
visible. Fresh instances are zero-filled by `TObject.InitInstance` (`0x60620c`).
The receipt resolves the published BeforeAdd/AfterAdd, before-change, change,
can-change and button-enabled handler fields; none are assigned for these 23
thermostat selectors in their DFMs or in the 67 scanned panel methods. The scan
is a syntactic direct-write check composed with the constructor and DFM evidence,
not a general proof about arbitrary external code.

`PrepareFlashCxGroupComboBox` (`0xc103a4`) explicitly activates both controllers;
`Loaded` (`0xbbc2b0`) also activates them. `GetActive` (`0x84dcac`) requires the
active flag and an owner outside its loading state. `UpdateEnableState`
(`0xbc54fc`) requires a bound non-255 application, `GetCanAddGroups`, the bound
active controller and the existing role's enabled control. The cooling/heating
DFMs explicitly disallow the inactive override. The profile does not assume a
published default value proves the state of an unprepared control.

OK's `IsSiteOpen` (`0xbc3168`) checks that the project installation's workspace
communicator is connected. It does not require an open C-Bus network or physical
bus access. Offline plans represent this as the connected database-owner profile;
they do not claim an original dialog was enabled on a host.

`DoIndexChange` (`0xbbbee8`) posts message `0x426`, whose dynamic method entry is
`HandleComboChange` (`0xbbc158`). It renders and invokes an optional custom
`OnChange`, absent here. DevExpress `Properties.OnChange` is a separate event:
existing cooling/heating warning behavior and the damper's last-non255 cache
remain as documented for ordinary selectors. No extra PP mutation or automatic
relay reassignment is inferred from accepted Add.

## Source wire representation and owning save

The original group save is not a final-name-only `DBADDSAFE`. The recovered chain
is `TCBusGroupCGateAgent.AgentSave` (`0x1210d28`) → `CreateGroup` (`0x1210f3c`) →
`TCGateAgent.CGateAdd` (`0xcac698`). It creates an unaddressed Group under the
application OID with `DBAdd`, binds the returned OID, and writes its Address.
Generic `AgentSave` (`0xcac354`) calls `UpdateTag` (`0xcac614`) and
`UpdateCGateValue` (`0xcac504`), which writes `TagName` through the new object's
`!OID` path. The group agent then requests `ProjectSave`.

`TcgcDBSet.GenerateCommandText` (`0xcab1d4`) calls
`TagStringToCgateString` (`0x7b8cd8`). That formatter escapes double quote and
backslash, then, if the escaped text contains two consecutive ASCII spaces,
escapes **every** ASCII space. It always wraps the result in double quotes.
Other UTF-16 units, including NBSP, are copied unchanged. The receipt pins the
escape bitmap, literals, loops and caller. This establishes the original static
formatter; it does not establish new native-server acceptance for every Unicode
name. Collapsing repeated spaces or NBSP on an owned command path would change
the requested TagName and must not be presented as successful preservation.

The CLI performs complete preflight before materializing reviewed graph effects
and uses one owning settings save, followed by its project-save boundary. This
is a storage projection of the successful source path. It does not reproduce
original partial-failure prefixes or the original per-object project saves.
Fresh OID/parent/address checks, exact-name readback, full graph preservation and
no retry after uncertain writes remain necessary. Native command framing and
XML admission can add explicit product limits; they must not be described as
source dialog rules or hidden by silently rewriting names.
