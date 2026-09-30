# Project documentation ("Document Project")

`cbus-toolkit project document` reconstructs the recovered parts of the Toolkit's
**Document Project** HTML from a saved legacy XML/CBZ project or an explicitly
selected native XML snapshot. It does not yet reproduce every device body.
It reads one bounded regular-file snapshot, binds it by SHA-256, and never
writes the project or opens an endpoint.

```sh
cbus-toolkit project document house.cbz
cbus-toolkit project document saved-dbgetxml.xml --native-xml --output native.html
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
recovery status, every unrecovered item, status-report projection details, and
the parity status.

The output is deterministic. The same snapshot and options give the same bytes.
`Generated on:` uses `--generated-at` or, by default, the project file's
modification time in UTC. `--network N` documents one network. The original
always documents every network.

## Toolkit rules reproduced

The rules come from static disassembly of Toolkit 1.18.0.2754
(`TProjectDocumentor`, `TDocumentorCommon`, the per-type documentors,
`TfrmProjectDocumentor` and `TProjectNodeHelper.DocumentProject`). The complete
original workflow has not been executed. Separate bounded instruction probes
cover admitted action methods and trigger-group traversal. See the
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
  Stored secondary application 255 remains present; its default application
  name is the original raw `<Unused>` string.
- **Escaping.** `FormatHTMLString` replaces only `<` and `>` with `&#60;` and
  `&#62;`. It is applied to descriptions, notes and the text of group 255.
  Names in headings and links are written unescaped, as in the original.

## Per-type documentors

| Documentor | Unit types | Status |
| --- | --- | --- |
| `TUnitTypeDocumentor` (base) | every unregistered type, including `PCI`, `CNI` and `KEYGL5` | Recovered |
| `TClockDocumentor`, `TGeneralInputDocumentor`, `TCustomSceneKeyUnitDocumentor` | `CLK2`, `PC_GIM`, `KEYSCEN4` | Recovered (base body) |
| `TOutputDocumentor` | `RELDN4`, `RELDN8`, `RELDN8B`, `RELDN12`, `DIMDN4`, `DIMDN4F`, `DIMDN8`, `DIMDN8F` | Recovered: channel/groups/logic-function table |
| `TOutputDocumentor` | `ANODN4`, `DIMDS8`, `DIMPR1/2/4`, `RELDB1`, `RELDC4` | Recovered table when the explicit firmware selects the pinned native class |
| `TOutputDocumentor` | `DIMDH4`, `RELDN4A/8A/16A`; `DIMDD4/4F/8/8F` at firmware `1.3.0–9` | Recovered base-only body: native NCC classes fail this documentor's dimmer-class check |
| `TOutputDocumentor`, `TErrorReportOutputDocumentor` | remaining output classes, including earlier `DIMDD` firmware | Partial: base block, channel table marked |
| `TBridgeDocumentor` | `BRIDGE1N/1F/2N/2F`, `GATEWLS/N/F` | Recovered: adjacent network, application connections, adjacent/remote forwarding and destination |
| `TClassicOutputDocumentor` | `RELAY1`, `RELAY2`, `RELAY4`, `DIMMER4`, `AN_OUT4` | Recovered: associated groups and logic function per channel |
| `TDMXGatewayDocumentor` | `DMXDO12` | Recovered: groups and 512 DMX slots |
| `TClassicKeyInputDocumentor` | `KEY1`, `KEY2`, `KEY4` | Recovered: timing, macro/micro functions, group controls, preset levels and timer expiry |
| `TClassicKeyInputDocumentor` | other classic key types | Partial: base block and a marker |
| every other documentor | Neo key inputs, PIR, light-level and ST7 sensors, multisensor, thermostat, SENTEMP, WHAA, DALI, fan, architectural and Bytecraft dimmers, remote controls, wireless inputs and gateways, DLT | Unrecovered: base block and a marker |

The output table follows the original row format: `<tr><td>channel</td><td>groups</td>[<td>Max|Min|&nbsp;</td>]</tr>`.
Channel groups come from `GroupAddress`. Logic groups 1–4 sit at
`GroupAddress[12..15]`. A channel adds a logic group when its
`LogicGA13..16Associations` bit is set and that group is not 255. `RELDN8`
channels read PP indexes `1, 2, 3, 4, 7, 8, 9, 10`, which are the same
marshalling indexes that `din-output-settings` uses. The `Logic Function`
column appears only when a channel is associated with a used logic group. It
reads `Max` when `LogicFunction` is set and `Min` otherwise, but only for rows
with more than one group. The original writes `Max`/`Min` for relays as well.
All consumed PP arrays and displayed group records must be present. Missing
logic programming cannot silently become disabled logic.

The seven additional direct output profiles use the same pinned basic DIN
loader and report methods, with their native channel counts and four logic
groups. This only expands documentation and group usage; it does not admit
new devices to the programming editor. Firmware identity is required for
these additions. Native NCC units intentionally receive only the base body
from `TOutputDocumentor`, while their group usage remains independently unknown.
The [output receipt](../research/experiments/2026-09-30/project-documentor-outputs-static.json)
binds factory classes, firmware boundaries, channel counts and PP mappings.

Classic outputs consume six group slots and `LogicGA0..5Associations`; the low
bit of `LogicFunctionAndPowerUpDelay` selects Min/Max. The original GA5 branch
tests slot 5 but displays slot 0. Repeated groups remain repeated. The DMX
body maps sixteen 32-slot `DMXSlotMapping` banks to twelve channel groups;
shared groups produce duplicate rows. It preserves the original malformed
`</td></tr>` prefix rather than silently correcting the source output.

Classic `KEY1/2/4` bodies require complete consumed PP and resolved displayed
groups. Timing labels use the native enums, including the stored ramp value
255 becoming `4 secs`. Macro detection reproduces registered command vectors,
application subsets and shutter aliases; custom functions retain the four
micro-function columns. Repeated controls remain repeated. Their stored
levels and timers come from the first unit block matching the group, even
when that block is assigned to another key. Named presets resolve by Level
Address, independently of Level Value. Other classic input models still need
their own native interface and programming-state mappings. Block order models
a freshly initialized native key collection loaded from ascending PP bits;
association history in an existing GUI session is not present in a saved PP
snapshot and is not reproduced.

Bridge bodies use `Application[0..1]`, `ApplicationConnectEnabled`,
`BridgeCount` and `BridgeAddress`. Their private application-255 names are
`All Applications` and `<Unused>`. A positive `BridgeCount` enables remote
forwarding, while the destination is the last existing network in the first
contiguous prefix of at most seven route entries. The first 255 or unknown
network terminates that prefix. Missing programming stays marked; a known
empty prefix displays the original `Unknown Network` text.

## Group usage and action selectors

Input/Output/Other lists now reproduce the original unit-link/description
layout for fifteen admitted DIN output types, five classic output types, and
nine classic key types (`KEY1/2/4`, `KEYIR1/4`, `KEYBC2/4`, `KEYAUX4`,
`DINAUX4`). Input descriptions retain block-major key ordering, duplicate key
uses and `Block (Unused)`. DIN output descriptions list channels then used or
unused logic groups; classic output descriptions list logic groups. Other
usage includes the recovered area and indicator-brightness group rules.
Known empty uses produce empty lists. Unsupported units and missing fields
produce individual markers in the list and summary.

Classic-key `ActionSelectorUse` retains key-major ordering, duplicates,
recall commands and timer-retrigger conditions. The original second stored
level comparison is nested under the first stored level's Address match.
Native Level Address and Value are retained separately. An action is reported
unused only when every participating documentor has a known empty result.
The bounded original instruction comparison uses synthetic object callbacks;
it is not an original generated-page capture.

Direct action usage also covers `RELDF1`, `SENTEMPB` and `SENTEMP4`. These
references use application 202 and selector Address; an unused trigger group
suppresses the reference. `SENTEMP4` preserves the native behavior in which a
broadcast match replaces an earlier error-report match. Fan master input and
digital-temperature enable/HVAC group descriptions are recovered separately.
Eight original-method cases and 33 additional source checks support this
extension; the [usage note](project-documentation-usage.md) lists exact fields
and the remaining per-family gaps.

Six additional original `InsertHTMLTriggerGroup` instruction cases match
99 rendered lines and their exact unit/level callback order, including empty
levels, empty units, unused selectors and interleaved multiple uses. These
cases supply explicit action strings and getter results; they independently
check the wrapper rather than complete native project loading or composition.
See the [comparison note](../research/experiments/2026-09-30/project-documentor-trigger-original.md).

## Status interval and ordering

`Status Report Interval` now projects the original strict minimum over units
with a recovered input-interface and PP mapping. Equal values keep the first
unit. There is no formatting clamp or multiplier; the original sentinel is
99999 and no qualifying value prints `None`. Missing PP, unknown factory
identity, and unrecovered mappings keep the entire network result unknown.
The report explicitly states its stored-PP basis: original programming-load
success/failure flags cannot be observed from saved XML.

The CLI uses a deterministic address-order profile. Networks, applications
and groups place address 255 first; units and levels use ordinary ascending
address order. Fresh Toolkit preferences actually default applications,
groups and levels to name order, and registry settings can select address
order. Original name comparison uses the Windows user locale. This CLI does
not claim to reproduce an unobserved registry/locale ordering.

## Saved native XML

`--native-xml` reads an explicit saved `DBGETXML` Installation snapshot, not a
SQL/SQLite repository or a live server. It preserves the stored interface
fields, unit PP strings and distinct Level Address/Value. Both direct network
interface fields and the nested Interface form have fixture support; mixed
forms are refused. The adapter checks unique addresses, scalar fields and PP
names, refuses DTDs and namespace shadows, and rejects unsupported NetVar or
typed group/level collections rather than omitting them. Eight native fixture
inventories and two committed original C-Gate readbacks provide independent
projection comparisons. No missing PP is initialized from an assumed default.

## Marked, never guessed

When a value's original data source or body was not recovered, the page writes
`… not documented (unrecovered)`. A final `Not documented (unrecovered)`
section, after the networks, lists each such item. The original page has no
such section. The following are marked:

- `Inputs:`, `Outputs:` and `Other:` usage outside the admitted families;
- `Status Report Interval` when any potential participant lacks a known mapping
  or consumed PP;
- `ActionSelectorUse` outside the base, classic-key and admitted fan/temperature implementations;
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
- The original process's registry/locale-dependent application/group/level order.
- `DateTimeToString` month names, which depend on the locale. The CLI uses
  English names.
- The scan-error branch (`An Error occurred while scanning this unit…`), which
  needs a failed live programming load.
- Base links to applications missing from the snapshot use the existing
  standard-title/address fallback; no complete native auto-creation is modeled.
- Native SQL repositories and unsupported XML collection variants.

The [original-page feasibility investigation](../research/experiments/2026-09-30/project-documentor-page-feasibility.md)
records the required native storage, manager, modal form and serialization
dependencies. Existing Windows-runner readiness could not be verified, and
the isolated synthetic project/process route remains unproved. A normal
Toolkit startup is therefore not used as a substitute for an isolated capture.
