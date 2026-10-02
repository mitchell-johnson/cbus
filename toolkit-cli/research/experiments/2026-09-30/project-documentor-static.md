# Toolkit 1.18 Document Project: static review

Scope: issue #57 (P8.03), project documentation. This records the initial static review;
the bounded recovery below supersedes its original unrecovered-item inventory.
No vendor code was executed, no project was opened, and no C-Gate, CNI or PCI
endpoint was used.

## Inputs

| Input | Identity |
| --- | --- |
| `CBusToolkit.exe` 1.18.0.2754 | SHA-256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab` |
| `CBusToolkit.map` | SHA-256 `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb` |

Reproduce the verification with the following command. It requires the
private original files, `capstone` and `pefile`:

```sh
python research/project_documentor_static.py --exe CBusToolkit.exe --map CBusToolkit.map
```

The script checks that the extracted literals, factory registrations, VMT
slots, level names, resource strings and branch constants match the
constants in `cbus_toolkit.project_documentation`. It fails otherwise. The
receipt is [`project-documentor-static.json`](project-documentor-static.json).
It holds the method spans (MAP symbols with byte-span hashes), the 223
registrations, each documentor's ancestry and effective methods, and a string
inventory of every per-type documentor method, including the unrecovered
ones. At this checkpoint, `tests/test_project_documentation.py` compared the
receipt with the model offline and regenerated it with `CBUS_TOOLKIT_EXE`.
The current suite uses the separately derived
[`project-documentor-current-static.json`](../../fixtures/project-documentor-current-static.json),
which binds the current renderer and supporting modules. This historical
receipt remains unchanged; neither static extraction executes the original.

## Findings

**Entry point.** `TProjectNodeHelper.DocumentProject` creates a
`TProjectDocumentor`, a `TStringList` and the `TfrmProjectDocumentor` dialog.
A timer on the dialog calls `OnDocumentHTMLnew`. Unless the user cancels, the
list is saved as `GetAppPath + '\' + <project TagName> + '.html'` with
`TEncoding.UTF8` and opened with `ShellExecute`. The file is not named
`results.html`. Errors raise Toolkit error 13148 (`0x335C`). The dialog shows
`Generating Documentation` (resource 62347) and `Network %d of %d` (62346).

**Page.** `OnDocumentHTMLnew` first calls `GetAllProjectInfo`, which runs
`LoadAndSort` on the network, application, group and level managers. It then
writes the lines recorded in `ORIGINAL_LITERALS`: head, style, `h1`, the
header block with `DateTimeToString('dd mmm yyyy hh:mm')` (62345), `<hr />`,
`InsertHTMLContents`, `<hr />`, `InsertHTMLNetworksNEW`, `</body>` and
`</html>`. If an error flag is set, Toolkit error 21217 (`0x52E1`) is raised.
Its text was not mapped. Resource 63389, the Document Project error text, is
pinned as a string only.

**Contents and sections.** `InsertHTMLContents` uses `<li \>` for network,
application and group items. It skips the application that
`GetUnassignedApplication` returns (`FindOrCreateApplicationByAddress(255)`)
and every group for which `IsUnused` holds (address 255). The network, application and group
routines write the anchors `N`, `N_A` and `N_A_G`. Level anchors are
`N_A_G_L` and unit anchors are `N_unit_U`. Addresses use `IntToStr`. The hex
form is `Format('%.2x')`. An application equal to
`GetTriggerControlApplication` (202) uses `InsertHTMLTriggerGroup`.

**Groups.** `InsertHTMLGroupInput`, `…Output` and `…Other` iterate the
network's units. They call `TCBUSUnit` virtual methods (VMT `+0x128` for
inputs) that return `|`-terminated text. That text is trimmed by one
character, `|` is replaced with `<br/>`, and it is written under the unit
link. Those per-unit-class methods were **not recovered**. The level header is
`TLevelManager.GetDisplayName`, which is `TStandardCBusApplications`:
202 `Action Selectors`, 203 `Values`, default `Levels` (62334).

**Trigger groups.** For each action selector, every unit's documentor
`ActionSelectorUse` (VMT `+0x80`) is called. A nonempty result writes the
unit link, `<ul>`, the text and `</ul>`. The flag that produces
`Action Selector is not used` is reset per level. The base returns an empty
string. Fourteen documentor classes override it. With inheritance, 18 classes
use a non-base implementation. Their bodies were **not
recovered**, although their strings are inventoried.

**Units.** `InsertHTMLUnit` writes the heading. For `BURDEN`, `XC100B` and
`XC305B`, which `StrIsOneOf` matches from a three-element list, nothing more
is written. Otherwise, if the programming-loaded flag (`+0x16D`) is clear,
it writes the scan-error `<h4>`. If the flag is set, it calls
`GetDocumentor(UpperCase(type), firmware).DocumentHTML`.
`GetAllUnitProgramming` sets that flag before it loads each unit's
programming.

**Factory.** `RegisterUnitType(type, class, Min, Max)` calls are recovered
from the `.itext` initialization sections in address order. There are 223
registrations for 31 documentor classes. `FirmwareWithinLimits` returns
`not (VersionStringCompare(Min, fw) > 0) and VersionStringCompare(Max, fw) >= 0`.
`GetDocumentor` returns the first match and otherwise creates the base
`TUnitTypeDocumentor`. No type has overlapping ranges, so registration
order does not change the result.

**Class slots.** The effective `DocumentHTML` of `TClockDocumentor` and
`TGeneralInputDocumentor` is the base. `TCustomSceneKeyUnitDocumentor` only
calls the base. `TErrorReportOutputDocumentor` inherits
`TOutputDocumentor.DocumentHTML`. `TMultisensorDocumentor` and
`TNeoProInputDocumentor` call `TNeoInputDocumentor.DocumentHTML`. The receipt
records all 32 classes.

**Base documentor.** The base writes the fixed lines listed in the receipt.
`Part name` is the `UnitName` attribute. The application lines appear only
when the virtual application getters are non-nil. The clock and burden lines
come from the `ClockGenEnable` and `Burden` attributes.
`DisplayHTMLApplication` writes plain text for application 255.
`DisplayHTMLGroup` escapes the text of group 255 with `FormatHTMLString`,
whose `StringReplace` flags byte is 3 (`[rfReplaceAll, rfIgnoreCase]`).

**TOutputDocumentor.** This documentor requires the unit to be a
`TCBusDimmerUnit`. The unit-factory registrations resolve every admitted DIN
profile (RELDN4/8/8B/12, DIMDN4/4F/8/8F) to such a class. The channel table,
`UsesLogicGroups`, the logic-group order 13–16, the 255 exclusions and the
`Max`/`Min` rule for more than one group are recovered.

**TBridgeDocumentor.** The documentor calls
`NetworkByNetworkNumber(unit address)`. If no network matches, it writes
`WARNING: <DisplayUnitType> has no far side Network.` The connection lines
read `TBridge` attributes (`Application1`, `Application2`, `AdjacentNetwork`,
`RemoteNetwork`, `DestinationNetwork`), whose PP mapping was not recovered.

## Not established

The following were not captured or compared:

- original execution or a generated original page
- the `TCBUSUnit` group-usage methods, the status-report interface, 25
  unrecovered `DocumentHTML` bodies and all 14 `ActionSelectorUse` overrides
- the `LoadAndSort` sort key, which the CLI assumes is ascending address
- locale month names
- the progress dialog and printing

Every one of these parity dimensions remains `unassessed` or `not implemented`.


## Bounded recovery update

The renderer now integrates the separately pinned bridge, classic-output, DMX,
group-usage, action-use and status-report evidence. See
[`project-documentation.md`](../../../docs/project-documentation.md) for current
supported families and gaps. The core static receipt now binds all five
supporting runtime modules as well as the main renderer.

- `project-documentor-bridge-static.json`: forwarding PP bindings, route-prefix
  destination, private application names and base secondary-255 handling.
- `project-documentor-devices-static.json`: classic-output and DMX body branches,
  channel counts, loader mappings and the original output quirks.
- `research/fixtures/project-documentor-usage-static.json`: per-unit dependency descriptions and
  classic key ActionSelectorUse mappings. The separate
  `research/fixtures/project-documentor-action-original.json` executes ten
  synthetic cases of the pinned original action routine in bounded emulation
  with stubbed object/string dependencies. It is not an application/page run.
- `project-documentor-status-static.json`: input-interface membership and
  stored-PP minimum projection. Saved XML cannot establish scan-load success.
- `project-documentor-ordering-static.json`: original registry-dependent
  name/address sort and Windows-locale comparison. The CLI chooses a
  deterministic address profile and admits no original sort-parity claim.

The explicit saved-native-XML adapter has independent fixture-inventory and
original C-Gate readback comparisons, but it does not read SQL repositories or
initialize missing programming. NetVar and unsupported typed collections are
refused. No original generated HTML page has been captured; byte/visual parity,
printing, progress/cancellation and the remaining per-device bodies stay open.

## Second bounded recovery slice

The next separate implementation adds classic KEY1/2/4 device bodies, seven
direct DIN output profiles and the native NCC base-only report path. The
classic body has independent source-table comparison across every four-nibble
micro-function vector in 27 application/stored-level contexts (1,769,472
comparisons). This checks macro labels against independently extracted
registrations; it is not original method or page execution.

Fan/temperature action and group mappings add 33 source checks and eight
bounded original ActionSelectorUse execution cases. Six separate original
InsertHTMLTriggerGroup cases produce 99 matching lines and callback traces,
with explicit getter/factory/action/string providers. The new receipts retain
their distinct source-only and original-instruction acceptance boundaries.

See `project-documentor-page-feasibility.md` for the original entry-chain
dependencies and concrete capture prerequisites. The existing Windows guest
readiness could not be verified, and private process/preferences/C-Gate
isolation and the synthetic-project invocation route remain unproved. No
normal Toolkit launch or complete generated-page claim was substituted.
