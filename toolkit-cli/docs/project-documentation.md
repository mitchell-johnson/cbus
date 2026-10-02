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

For one fresh loaded cmqttd/C-Gate snapshot, use
[`cgate database-document --project //PROJECT`](native-project-documentation.md).
The same renderer now also admits eight source-pinned light-level, WHAA and
DALI factory profiles; see [their exact saved-PP boundaries](project-documentation-remaining.md).
It also renders bounded [multisensor and thermostat](project-documentation-sensors.md)
and [wireless, gateway, remote and Bytecraft L1](project-documentation-wireless-l1.md)
profiles with independent group and action dependencies.

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
| `TErrorReportOutputDocumentor` | `DIMDU4`, `DIMPR3A/6A/12A` with an explicit registered firmware | Recovered channel/logic table, error-trigger actions and enable-group usage |
| `TOutputDocumentor` | remaining output classes, including earlier `DIMDD` firmware | Partial: base block, channel table marked |
| `TFanControllerDocumentor` | `RELDF1` at canonical `2.4.xx–2.6.xx` | Recovered single channel, controller role, speed labels and thresholds under the shared source mapping |
| `TBridgeDocumentor` | `BRIDGE1N/1F/2N/2F`, `GATEWLS/N/F` | Recovered: adjacent network, application connections, adjacent/remote forwarding and destination |
| `TClassicOutputDocumentor` | `RELAY1`, `RELAY2`, `RELAY4`, `DIMMER4`, `AN_OUT4` | Recovered: associated groups and logic function per channel |
| `TDMXGatewayDocumentor` | `DMXDO12` | Recovered: groups and 512 DMX slots |
| `TClassicKeyInputDocumentor` | `KEY1`, `KEY2`, `KEY4` | Recovered: timing, macro/micro functions, group controls, preset levels and timer expiry |
| `TClassicKeyInputDocumentor` | `KEYIR1/4`, `KEYBC2/4`, `KEYAUX4`, `DINAUX4`, `BCNC4A/B` with an explicit registered firmware | Recovered inherited tables, native physical key counts and AUX macro override |
| `TClassicKeyInputDocumentor` | `KEYC1/2/4`, `KEYCIR1/4` with an explicit registered firmware (`1.8.01–9`) | Recovered eight-key tables with physical/virtual/IR labels and canonical Scene24/Scene Modify controls; scene dependencies are decoded independently |
| `TBytecraftDimmerDocumentor` | exact old `DIMPR12` class/agent firmware `0–1.9.02` | Bounded channels, DMX/lock/restore and packed-scene tables plus independent group/action usage; complete explicit records and consumed body fields required |
| `TClassicKeyInputDocumentor` | other classic key types | Partial: base block and a marker |
| `TNeoInputDocumentor`, `TNeoProInputDocumentor` | `KEYA3`, `KEYB4`, `KEYM4`, `KEYM8` at `1.3.01–2.9.99`; `KEYE1` at `2.5.00` | Recovered ordinary controls and canonical scene bodies for complete admitted snapshots; other model states remain partial |
| `TDLTDocumentor` | `KEYBL5`, `KEYML5`, `KEYDL4` at `3.0.00` | Recovered inherited NeoPro tables and label mode, with the same snapshot restrictions |
| `TCustomSceneControllerDocumentor` | `SCNCTL5` with an explicit registered firmware | Recovered five-scene body, commands, trigger selectors and master-off fields for complete admitted snapshots |
| `TPIRDocumentor`, `TST7PIRSensorDocumentor` | registered `SENPIRSS`, `SENPIROA`, `SENPIRIA`, `SENPIRIB` classes | Recovered four-key ordinary controls, enable-group appendix and bounded group/action usage; surface multisensor and encoded scene keys excluded |
| `TSENTEMPDocumentor`, `TSENTEMPProDocumentor`, `TDigitalTemperatureSensorDocumentor` | registered `SENTEMP`, `SENTEMPB`, `SENTEMP4` classes | Recovered consumed control/broadcast fields and four-channel reports under explicit Celsius/period-decimal formatting |
| `TLightLevelSensorDocumentor`, `TST7LightLevelSensorDocumentor` | old `SENLL`, `PE_CELL`, ST7 `SENLL` under exact selected factory profiles | Recovered saved control/lux/broadcast bodies and selected usage; ST7 zero-key loader, block-4 timer minimum and direct roles are documented in the [ST7 annex](project-documentation-st7-light-level.md); consumed missing fields remain marked |
| `TWHAADocumentor`, `TDALI2BDocumentor` | `PC_WHAD/WHAR/WHARB`, `PC_DAL2B/C` under exact selected factory profiles | Recovered audio roles/zones and DALI mappings/error references; complete consumed programming required |
| `TMultisensorDocumentor` | Seven exact factory profiles for `SENPILL/A`, `SENPIRIC/IB` and `SENLLA` | Bounded eight-key/block loaders, sensor-specific macro overrides, occupancy/light-level controls and explicit canonical scenes; active joins and missing dependencies refused |
| `TThermostatDocumentor` | `PC_TSA`, `PC_TSA5`, `PC_TSB`, `PC_TSB5` | Bounded HVAC/plant/output/master reports; existing nongenerated plant groups and unambiguous explicit NetworkNumber required |
| `TCBusWirelessInputDocumentor`, `TWirelessGatewayDocumentor`, `TWirelessGatewayAdvancedDocumentor`, `TRemoteControlDocumentor` | 50 wireless input types, two gateways and seven remotes under exact source partitions | Bounded sixteen-block/decorator/remote-map and compacted-scene tables; missing receivers/consumed metadata refused |
| `TBytecraftDimmerDocumentor` | `DIMPR12` L1 partition at `1.9.03–9` | Bounded inherited body/scenes and one logic group, with per-channel enable and Min/Max attributes |
| `TArchitecturalDimmerDocumentor` | `DIMAR3`, `DIMAR6`, `DIMAR12`, `C12DIMAR` | Bounded fresh loaded channel/logic/DMX tables, fixed RMS voltage conversion, 128 sparse ordinary scenes and special scenes; consumed metadata required |
| every other documentor | other Neo key input profiles and unsupported loaded states | Unrecovered: base block and a marker |

The [Neo body note](project-documentation-neo.md) records physical and virtual
key labels, secondary applications, the native scene-ramp indexing quirk and
the fresh-model limits. The original Timer template changes a zero primary
block timer to 300 seconds during loading; the classic and Neo adapters both
apply this default while retaining an explicit Idle expiry. Other Neo/DLT Scene Modify,
configured joins, block relocation and noncanonical scene tables remain open.

[DLT](project-documentation-dlt.md) adds the exact `Labels: Static` or
`Labels: Dynamic` suffix after the inherited body. Its separate programming and
label editor is not invoked. [SCNCTL5](project-documentation-scene-controller.md)
keeps five scenes with three shared primary and six secondary commands each,
including the original distinction between custom and Dragan ramp fields.
Its master-off selector uses the original fresh default
`DisplayAddressValue=false`; saved display preferences are not loaded.

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
levels and timers come from the first unit block matching the application/group pair, even
when that block is assigned to another key. Named presets resolve by Level
Address, independently of Level Value. The [additional classic profiles](project-documentation-classic-profiles.md)
use the same report with their native physical key counts. AUX units replace
Bell Press with Aux On/Off; BCNC units preserve stored commands because their
forced defaults apply only before saving. [KEYC and KEYCIR](project-documentation-neoclassic.md)
use eight keys and blocks, with the original physical/virtual/IR labels. Their
Classic documentor does not append a Scenes table. It admits ordinary selectors
and canonical JP14 Scene24 keys with unshared linear primary unused-group blocks;
Canonical Scene Modify preserves template 25, raw stages and Scene 1 / Instant
controls; it does not initialize a timer. The loader consumes encoded scene selectors even
though the model reports scenes disabled. Block order models
a freshly initialized native key collection loaded from ascending PP bits;
association history in an existing GUI session is not present in a saved PP
snapshot and is not reproduced.

The [PIR projection](project-documentation-pir.md) preserves four ordinary keys,
SENPIR macro overrides, mixed block applications and the opposite enable-group
polarity of the old and ST7 classes. ST7 scene keys remain partial, and its scene
dependency list requires positive evidence that the scene table is empty.

[Temperature bodies](project-documentation-temperature.md) retain native
control and broadcast modes, loader clamps and disabled-value defaults. SENTEMP
uses the ceiling of the high/low average. SENTEMP4 preserves the original
unclosed table and its absolute Fahrenheit threshold conversion. The project
renderer explicitly uses Celsius and a period decimal separator; stored Toolkit
preferences and Windows locale are not loaded.

[Specialized outputs](project-documentation-special-outputs.md) add the four
error-report output classes and RELDF1. Fan reports consume one scalar channel
group, resolve Master/Stand Alone/Slave roles and retain native speed ranges,
including reversed ranges. Canonical `2.4.xx`, `2.5.xx` and `2.6.xx` share the
same unconditional mapping; this is software projection coverage, not native
or hardware firmware-continuum acceptance. Other firmware and non-BMP label
copying remain partial. Architectural and Bytecraft L1 bodies still need separate loaders.

Bridge bodies use `Application[0..1]`, `ApplicationConnectEnabled`,
`BridgeCount` and `BridgeAddress`. Their private application-255 names are
`All Applications` and `<Unused>`. A positive `BridgeCount` enables remote
forwarding, while the destination is the last existing network in the first
contiguous prefix of at most seven route entries. The first 255 or unknown
network terminates that prefix. Missing programming stays marked; a known
empty prefix displays the original `Unknown Network` text.

## Group usage and action selectors

Input/Output/Other lists now reproduce the original unit-link/description
layout for fifteen admitted DIN output types, four error-report output types,
five classic output types, and eleven classic key types (`KEY1/2/4`, `KEYIR1/4`,
`KEYBC2/4`, `KEYAUX4`, `DINAUX4`, `BCNC4A/B`). Input descriptions retain block-major key ordering, duplicate key
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

The admitted Neo/NeoPro and DLT families also report
[group and action uses](project-documentation-neo-usage.md). They retain the
native primary-recall, scene-overwrite, secondary-recall order and duplicate
uses. Neo scene dependencies distinguish unused scenes; DLT reports retained
scenes through its own override. SCNCTL5 preserves repeated `Scene N` command
dependencies and combines matching master-off and scene selector descriptions.
Bounded instruction comparisons execute the original methods with synthetic
objects; they do not establish complete native project loading or page parity.

PIR action usage retains its inherited primary-application-only Classic method,
including on ST7 units with secondary-application blocks. PIR group usage keeps
native corridor and broadcast dependencies even when the corresponding active
flag is false. Temperature usage follows the selected control/broadcast mode;
fan output usage identifies its scalar Channel 1. Error-report outputs append
both matching error and clear actions and preserve the Enable group reference.
Each method refuses missing consumed data independently of body recovery.

KEYC/CIR input usage counts physical keys and separately scans loaded scene
commands. Ordinary keys reference Scene 1; encoded Scene24 keys reference their
decoded indicator index. Any of the eight key objects can make a scene used.
Missing or noncanonical scene data preserves known block
uses with a partial marker. Their Classic action method scans all eight keys,
including virtual/IR keys, only for the primary application. Unsupported join
capabilities suppress join descriptions; the inherited corridor group reference
is still reported when it matches. These distinctions are source-derived and do
not establish original loader or generated-page acceptance.

Old [Bytecraft DIMPR12 usage](project-documentation-bytecraft-usage.md)
admits the exact original class/agent through firmware `1.9.02`. It reports
matching channels in order, including repeated groups and address 255, without
consuming packed scenes or DMX data in that output pass. The separate packed
record model supplies ordered input/action consumers, while Other reads Area
and application-203 control groups. Its [bounded body](project-documentation-bytecraft.md)
adds exact lock/DMX/restore and scene tables. L1 firmware, incomplete snapshots,
history and original whole-loader/page acceptance retain explicit gaps.

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
- `ActionSelectorUse` outside the base and admitted classic-key, Neo/DLT,
  scene-controller and fan/temperature implementations;
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
- Saved `DisplayAddressValue` formatting for the SCNCTL5 master-off selector;
  the report uses the original fresh default and records that basis.
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
