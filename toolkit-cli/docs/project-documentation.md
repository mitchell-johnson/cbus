# Project documentation ("Document Project")

`cbus-toolkit project document` writes the HTML page that the Toolkit's
**Document Project** command produces, for a saved legacy XML or CBZ project.
It reads one bounded regular-file snapshot, binds it by SHA-256, and never
writes the project or opens an endpoint.

```sh
cbus-toolkit project document house.cbz
cbus-toolkit project document house.cbz --output results.html --network 254
cbus-toolkit project document house.cbz --output house.html \
    --generated-at 2026-09-30T07:05 --catalog /path/to/cbusunits.xml
```

The command never overwrites. If the output file exists, it fails with
`FileExistsError` and leaves the file unchanged. The default name is
`<project TagName>.html` in the current directory. The Toolkit uses the same
name, `TProjectNodeHelper.DocumentProject` saving `<AppPath>\<TagName>.html`.
A name containing a path or reserved character requires `--output`. The JSON
result reports the file, its SHA-256 and size, the per-unit documentor and
recovery status, every unrecovered item, and the parity status.

The output is deterministic. The same snapshot and options give the same bytes.
`Generated on:` uses `--generated-at` or, by default, the project file's
modification time in UTC. `--network N` documents one network. The original
always documents every network.

## Toolkit rules reproduced

The rules come from static disassembly of Toolkit 1.18.0.2754
(`TProjectDocumentor`, `TDocumentorCommon`, the per-type documentors,
`TfrmProjectDocumentor` and `TProjectNodeHelper.DocumentProject`). The
original was not executed. See the
[research note](../research/experiments/2026-09-30/project-documentor-static.md)
and its verified receipt.

- **File.** Each fragment is one `TStringList` line. The list is saved as UTF-8
  with a byte-order mark and CRLF line breaks, including after `</html>`.
- **Head and header.** `<title>` holds `CBus Project <name>`. The style block
  centres `h1`, `h2` and `div.header_info`. The header gives
  `Generated on:` (`dd mmm yyyy hh:mm`, resource 62345), `Number of Networks:`
  and `Number of Units:`. The last line has no `<br />`.
- **Contents.** A square list of networks. Each network has a disc list of
  applications and a `Units` entry. The original writes `<li \>`, with a
  backslash, for network, application and group items and `<li />` for units.
  Application 255 and group 255 are left out.
- **Network section.** `Network Number`, `Interface Type`, `Interface Address`,
  the three network calculator lines and `Status Report Interval`. Then each
  application except 255 is wrapped in `<ul>…</ul>`, followed by the `Units`
  section.
- **Application.** `Address: N ($HH)</br>`, with `%.2x` rendered as upper-case
  hex, and an escaped `Description`. Each group except 255 is wrapped in
  `<ul>…</ul>`.
- **Group.** `Group - <name>` heading, `Address: N ($HH) <br />`, and then
  `Inputs:`, `Outputs:` and `Other:` lists. The levels follow: a
  `<levels name>: ` line and one anchored item per level. The levels name is
  `Action Selectors` on application 202, `Values` on 203 and `Levels`
  elsewhere (resource 62334).
- **Trigger group (application 202).** The heading has no `Group -` prefix. The
  description ends `<br /><br />`, followed by `Events:<br />`. Each action
  selector lists every unit whose documentor reports a use. Otherwise it
  writes `<li />Action Selector is not used`.
- **Units.** Units are in ascending address order. Each has an anchored
  `<name> - <type>` heading. `BURDEN`, `XC100B` and `XC305B` get only the
  heading.
- **Documentor selection.** The documentor is the first factory registration
  whose type equals the upper-case unit type and whose firmware range contains
  the unit's firmware. The comparison is numeric per `.` token. With no match,
  the base documentor is used. All 223 registrations are pinned.
- **Base documentor.** `Unit Address`, `Tagname`, `Part name` (`UnitName`),
  `Application` and `Secondary Application` from the `Application` PP array,
  `Serial Number` (`GetDisplayableSerialNumber`), `Firmware Version`, escaped
  `Notes`, `Unit clock is enabled` and `Unit burden is enabled`, then `<br />`.
- **Escaping.** `FormatHTMLString` replaces only `<` and `>` with `&#60;` and
  `&#62;`. It is applied to descriptions, notes and the text of group 255.
  Names in headings and links are written unescaped, as in the original.

## Per-type documentors

| Documentor | Unit types | Status |
| --- | --- | --- |
| `TUnitTypeDocumentor` (base) | every unregistered type, including `PCI`, `CNI` and `KEYGL5` | Recovered |
| `TClockDocumentor`, `TGeneralInputDocumentor`, `TCustomSceneKeyUnitDocumentor` | `CLK2`, `PC_GIM`, `KEYSCEN4` | Recovered (base body) |
| `TOutputDocumentor` | `RELDN4`, `RELDN8`, `RELDN8B`, `RELDN12`, `DIMDN4`, `DIMDN4F`, `DIMDN8`, `DIMDN8F` | Recovered: channel/groups/logic-function table |
| `TOutputDocumentor`, `TErrorReportOutputDocumentor` | the other 24 output types | Partial: base block, channel table marked |
| `TBridgeDocumentor` | `BRIDGE1N/1F/2N/2F`, `GATEWLS/N/F` | Partial: `Adjacent Network` and the missing-far-side `WARNING`; connection settings marked |
| every other documentor | classic and Neo key inputs, PIR, light-level and ST7 sensors, multisensor, thermostat, SENTEMP, WHAA, DALI, DMX, fan, architectural and Bytecraft dimmers, classic outputs, remote controls, wireless inputs and gateways, DLT | Unrecovered: base block and a marker |

The output table follows the original row format: `<tr><td>channel</td><td>groups</td>[<td>Max|Min|&nbsp;</td>]</tr>`.
Channel groups come from `GroupAddress`. Logic groups 1–4 sit at
`GroupAddress[12..15]`. A channel adds a logic group when its
`LogicGA13..16Associations` bit is set and that group is not 255. `RELDN8`
channels read PP indexes `1, 2, 3, 4, 7, 8, 9, 10`, which are the same
marshalling indexes that `din-output-settings` uses. The `Logic Function`
column appears only when a channel is associated with a used logic group. It
reads `Max` when `LogicFunction` is set and `Min` otherwise, but only for rows
with more than one group. The original writes `Max`/`Min` for relays as well.

## Marked, never guessed

When a value's original data source or body was not recovered, the page writes
`… not documented (unrecovered)`. A final `Not documented (unrecovered)`
section, after the networks, lists each such item. The original page has no
such section. The following are marked:

- the `Inputs:`, `Outputs:` and `Other:` unit-usage lists, which come from
  `TCBUSUnit` virtual methods;
- `Status Report Interval`, which comes from the status-report unit interface;
- `ActionSelectorUse` for every documentor that overrides it;
- unrecovered per-type `DocumentHTML` bodies and the partial data listed above.

Without `--catalog`, the three calculator lines read `not calculated`. With a
user-supplied `cbusunits.xml`, they use the [offline calculator](calculator.md)
with each unit's `CatalogNumber`, `Burden` and
`SwitchablePowerSupplyEnabled`. A zero-conductance network is also marked.

## Not established

- Byte and visual parity with an original page. No original `Document Project`
  output has been captured, so the comparison is **unassessed**.
- Printing. The Toolkit opens the saved page in the browser. Printing is **not
  implemented**.
- The `TfrmProjectDocumentor` progress dialog (`Network %d of %d`,
  `Generating Documentation`) and cancellation. These are **not implemented**.
- `LoadAndSort` order. The sort key is not recovered, so the CLI assumes
  ascending address.
- `DateTimeToString` month names, which depend on the locale. The CLI uses
  English names.
- The scan-error branch (`An Error occurred while scanning this unit…`), which
  needs a failed live programming load.
- Secondary application 255, which the CLI treats as absent.
- Links to groups or applications that are missing from the project. The CLI
  uses the address, or the standard application title, as the link text.
- Native C-Gate 3 projects.
