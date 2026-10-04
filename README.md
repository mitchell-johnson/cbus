# C-Bus Toolkit CLI and Rust tools

Manage Clipsal/Schneider C-Bus projects from the terminal and connect C-Bus lighting to MQTT and Home Assistant.

This repository has two main applications:

- **[`cbus-toolkit`](toolkit-cli/README.md)** — a Python CLI for Toolkit-style project editing, commissioning, unit configuration, scenes, and diagnostics. It works with project files offline and connects to C-Gate or a CNI for online operations. JSON output makes it usable from scripts and AI agents.
- **[`cmqttd`](docs/configuration.md)** — a Rust daemon providing MQTT/Home Assistant support and an embedded C-Gate service over one shared C-Bus connection. It runs without Schneider C-Gate, Windows, or the Toolkit application. Its [C-Gate replacement status](docs/cmqttd-cgate.md) distinguishes implemented hardware operations from outstanding compatibility work.

The Rust workspace also provides protocol tools, a PCI simulator, and a C-Gate compatibility server for development and testing. Install the application you need; the Python CLI and Rust bridge can be used independently.

## Compatibility at a glance

| Product | Compatibility measure | Current state |
| --- | --- | --- |
| `cbus-toolkit` | Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001 workflow parity | The evidence register has **22,103 provisional source records**, a scoped original-differential receipt and three source-bound physical-applicability decisions for `SESSION_ID`, and **zero fully accepted obligations**. Its functional denominator is incomplete, so the functionality percentage is unavailable. The 42-area ledger records 18 implemented, 22 in progress and 2 pending; **18/42 = 42.86%** measures only those broad rows. |
| `cmqttd --cgate-bind` | Primary routing for the maintained C-Gate command inventory | **431 paths: 230 physical, 199 local/session, 0 blanket fail-closed 502, and 2 native-obsolete.** All **429/429 non-obsolete** primary paths are routed (100% command-path routing) and `full_cgate_command_path_coverage` is `true`. `full_cgate_compatibility` remains `false` because selector-specific, vendor-format, device/topology/timing, and physical-acceptance boundaries remain. |
| `cgate-mock` | In-memory C-Gate command surface | All **431** maintained paths parse and dispatch with deterministic protocol-shaped behavior. It does not provide persistent vendor storage, physical C-Bus effects, or device timing. |

Raw `cgate exec` and `cgate run` can forward the command surface exposed by the selected server. That reach does not create a typed Toolkit workflow, reproduce Toolkit GUI state, prove native-server semantics, or verify a physical effect.

Thermostat settings combine supported quick-zone, plant, output and damper
histories through one database transaction. Its [temperature model](toolkit-cli/docs/thermostat-temperature-model.md)
keeps all 15 raw, live and saved fields distinct; broader initialization,
original GUI scheduling and physical thermostat acceptance remain open.

The Toolkit CLI also renders saved multisensor, thermostat, wireless input,
gateway and remote-control report tables from explicit supported snapshots.
Architectural dimmer reports include 128 sparse scenes, DMX mappings and
source-derived voltage conversion; Bytecraft L1 adds channel logic.
Use `project document` for a file or `cgate database-document` for one fresh
database read. Ordered eDLT `static-text-dialog` and `add-language-dialog`
operations compose with widget and SceneManager edits through the existing
parent transaction. cmqttd retains their Network language objects with stable
identities and save/reload. See [report profiles](toolkit-cli/docs/project-documentation.md),
[static text and languages](toolkit-cli/docs/edlt-static-language-add.md) and
[service language definitions](docs/cgate-network-languages.md) for the admitted
inputs, exact command behavior and remaining original/physical acceptance.
Static-text histories now also accept explicit cell commit, cancellation and
focus events. They retain row names across dialog opens and later widget edits,
including truncated UTF-8 text. ST7 light-level reports apply their own timer
minimum and exact group roles. Native reports select the exact database Network
Address separately from physical NetworkNumber; HTML follows the source integer
address projection, so distinct saved identities can share anchors. The
[current implementation report](toolkit-cli/docs/feature-batch-2026-10-03-grid-native-report-corrections.md)
records the fixes, focused tests and remaining acceptance boundaries.

eDLT SceneManager also supports explicit `scene-name-control` histories and
`get-name`: all 64 retained names and eight scene views remain available during
an ordered edit. Enter/Leave use the original property allocation order, so the
old reference stays reserved until replacement succeeds. Long cached names can
be reused by later widgets while saved PP keeps only its 63-byte text image.
Pending text refuses save. See [SceneName callbacks](toolkit-cli/docs/edlt-scene-name-control.md)
and [the implementation report](toolkit-cli/docs/feature-batch-2026-10-03-scene-name-control.md)
for exact limits and the separate original GUI/hardware acceptance work.

Explicit `scene-selector-control` histories now cover application, trigger,
action and dynamic-label selection. `get-selector-view` returns complete ordered
labels and object identities for choosing a value. The retained form keeps its
previous action binding when there is no current scene. Automatic metadata
supports create-enabled getters, accepted/cancelled SceneManager Add dialogs and
earlier parent controls through cmqttd and cgate-mock. A causal timeline keeps
later objects out of earlier views and preserves old bound collections until
an explicit rebind. Read [selector callbacks](toolkit-cli/docs/edlt-scene-selector-control.md),
[creation timelines](toolkit-cli/docs/edlt-scene-inventory-timeline.md) and
[native metadata limits](toolkit-cli/docs/edlt-scene-selector-metadata.md).

Explicit SceneManager Add-button histories now preserve the actual retained
control selection rules, including an action created outside an old bound
list. Text-only Language changes can precede the parent SceneManager sequence
while initial scenes retain their original labels until an ActionSelector setter
or explicit trigger-current refresh.
Read [buttons and Language ownership](toolkit-cli/docs/edlt-scene-buttons-language.md).
The [label controls and image workflow](toolkit-cli/docs/edlt-label-controls-images.md)
adds byte-backed project BMP exports, FONT/DYNAMIC/ICON lookup profiles and
explicit Lighting label/status callbacks inside the owning parent transaction.
Use `cgate edlt-project-images PROJECT --output FILE` to obtain the input,
then bind it by SHA-256 with automatic metadata. Earlier Language changes
also compose with image-dependent scene initialization in this bounded profile.
Original GUI scheduling, full image codecs and device rendering remain open.
Explicit label controls now also cover Enable, Timer, Shutter, MultiLevel, Fan
and Room Courtesy widgets. Scene widgets add observed selection, cycle and
status-text callbacks. Global Programming can derive its source lifecycle and
image facts from the current database before applying selected categories to
other units. Read [widget controls](toolkit-cli/docs/edlt-widget-control-adapters.md)
and [automatic bulk metadata](toolkit-cli/docs/edlt-global-image-metadata.md)
for usable schemas, commands and acceptance limits.
MRA Zone Control, Source Select and Source Control also accept explicit
`mra_controls` inside the parent transaction. These source-owned callbacks
retain hidden fields and static names; Zone macro repair occurs only on an
explicit getter. Read [MRA callbacks](toolkit-cli/docs/edlt-mra-controls.md).
Timer, Shutter and Room Courtesy add explicit `dual_key_controls` inside their
owning parent operation. Raw fields remain untouched until the selected
source-owned setter/getter is invoked; timer, level, colour and icon bindings
share one guarded parent save. Read [dual-key controls](toolkit-cli/docs/edlt-dual-key-controls.md).
Time/Date operations also accept explicit `time_date_controls`: retained
display/type bindings and shared format choices preserve stored values until
the declared callback writes them. Growth claims the actual next slice;
same-type and shrink callbacks preserve it. Read
[Time/Date controls](toolkit-cli/docs/edlt-time-date-controls.md) for the JSON
schema and one-save workflow.
Saved Neo/NeoPro reports now cover all 43 exact classes across 59 source factory
partitions, including the six couplers' Bistable column and distinct group usage.
Read [Neo report profiles](toolkit-cli/docs/project-documentation-neo-profiles.md) for
required snapshots and remaining original/physical acceptance.
DIN relay/dimmer settings also offer `--toolkit-save` for the source-owned
agent-save projection across all eight supported 2.7.00 profiles, including
RELDN8's ordered marshalling. Existing targeted plans remain usable. Read
[DIN settings](toolkit-cli/docs/din-output-settings.md).
The existing Reset initial-profile guards remain unchanged, and original
form dispatch, rendering and audio hardware acceptance remain open.
`coverage --reconciliation-bundle FILE --reconciliation-artifact-root DIR`
also diagnoses declared source/obligation mappings and evidence gaps. Its
bounded result leaves the global parity gate unchanged; see
[reconciliation](toolkit-cli/docs/toolkit-obligation-reconciliation.md).

The [network definition workflow](toolkit-cli/docs/network-definitions.md)
now carries closed runtime definitions into the project with `NET SAVE DB`.
The CLI and cmqttd preserve exact native tag addresses such as `0254`, `0xff`
and `CustomA`, independent of the NetworkNumber byte. The same rows can be
edited by name or OID, saved, reopened and exported as XML/CBZ. Project saving
and physical interface binding remain separate operations. The
[materialization report](toolkit-cli/docs/feature-batch-2026-10-01-net-save-db-materialization.md)
records the first candidate's software and original C-Gate acceptance boundaries.
The [integration corrections](toolkit-cli/docs/feature-batch-2026-10-01-net-save-db-integration.md)
also isolate DALI and PP patch traffic from independent database rows, preserve
existing duplicate-OID lookup rules and retain legacy programming fields during
unrelated tag edits. Whole-project XML preserves Network creation order; the
[export-order checkpoint](toolkit-cli/docs/feature-batch-2026-10-01-net-save-db-export-order.md)
binds that rule to fresh original-server evidence and preserves the export's
selection and model-state checks.

The [named database workflow](toolkit-cli/docs/feature-batch-2026-10-01-named-database-workflows.md)
adds Applications, Groups, NetVars and Levels to those independent named
Networks, with fresh identities on copies and explicit save/reload. Typed
`cgate database get`, `set`, `add`, `copy`, `delete` and `validate` now accept
`--project NAME` and select that project on the command's own connection.
The [operator guide](toolkit-cli/docs/network-definitions.md) explains Level
initialization, incomplete-object constraints and the remaining native limits.
The latest review fixes preserve raw scalar values and optional Interface
deletion in independent database graphs, while keeping the configured physical
Network's address and interface binding protected. Original Toolkit/C-Gate
acceptance is tracked separately in [the manual handoff](https://github.com/mitchell-johnson/cbus/issues/72).

The [associated Level workflow](toolkit-cli/docs/feature-batch-2026-10-02-associated-levels.md)
also lets the CLI create and copy admitted Levels after a secondary database
Network is renamed, following its original numeric owner through paths or OIDs.
Direct DBCOPYSAFE preserves an admitted byte source Value; typed CLI copy initializes the new
Level's Value to the caller's requested byte. Associated NULL semantics,
decorated copies and original acceptance remain unfinished. The feature report
records completed Rust, independent mock and source/wheel CLI checks, together
with the corrected evidence-format failures from the full Python run.

The [empty TagsDLT copy extension](toolkit-cli/docs/feature-batch-2026-10-02-empty-tags-copy.md)
also supports copying an admitted Level after save/reload has materialized its
empty label collection. The source keeps its Value and XML; typed CLI copy
explicitly initializes the destination Value. Nonempty labels and other retained
decorations remain outside this copy scope.

The [associated raw Value extension](toolkit-cli/docs/feature-batch-2026-10-02-associated-raw-level-values.md)
lets `cbus-toolkit cgate database set PATH/Value VALUE --project NAME` retain
non-byte strings on an existing Level under a Group or NetVar. For scalar Value
reads/writes, exact canonical numeric paths,
renamed paths and issued OIDs address the same owner. Existing independent
numeric-looking Networks keep lexical precedence for successfully resolved objects. Explicit project save/reload and cmqttd restart preserve the value and identity. Raw-value copy
and resynchronization remain controlled preservation refusals, and complete
external XML admission remains strict. Bare numeric object XML reads remain
unsupported; use a renamed lexical path or the issued OID. Numeric object XML
compatibility for raw/renamed profiles remains tracked in [issue #73](https://github.com/mitchell-johnson/cbus/issues/73).

Known numeric-copy and retained-XML LOAD bugs, plus an unverified missing-descendant
selector edge, are recorded in the [manual correction handoff](https://github.com/mitchell-johnson/cbus/issues/74).
These remain unfinished.

The [loaded-project barcode workflow](toolkit-cli/docs/barcode.md)
adds or selects a scanned Unit with `cbus-toolkit cgate database barcode-add`.
It previews against one exact project and private unit catalogue, selects
project-wide serial duplicates, and optionally creates and verifies a new
database Unit. cmqttd preserves unrelated labels, programming parameters and
incomplete Units while initializing the new object. Project saving and device
programming are explicit later steps; original GUI, physical scanner and
PICED/controller acceptance remain open in [issue #58](https://github.com/mitchell-johnson/cbus/issues/58).

The CLI now admits **288 of 292 registered conversion directions** and
**all 262 statically registered CSV unit types** at their documented firmware and input profiles.
[Conversion rules](toolkit-cli/docs/toolkit-remaining-conversions.md) cover
Neo-to-classic, DALI, older sensors and the verified KEYBIR catalogue aliases.
[CSV report profiles](toolkit-cli/docs/database-csv-last-profiles.md) cover
424 of 425 registration rows; the duplicate KEYGL5 row without an exact
agent remains refused. Ordered eDLT Application, Corridor,
Activation and Scene Add dialogs, including operation-1 Reset, can share one parent save; see
[eDLT parent Add histories](toolkit-cli/docs/edlt-parent-add-dialog.md).
These counts describe bounded software profiles. Original GUI, cold native
family acceptance and physical behavior remain tracked separately.

The [replacement, cached NeoPro CSV and bounded TCP batch](toolkit-cli/docs/feature-batch-2026-10-02-cached-csv-event-bounds.md)
introduced `cgate conversion tweak-replace` and read-only `tweak-recover` for
the 123 pairs admitted at that checkpoint. The database replacement stages a fresh Unit,
copies admitted metadata, verifies a backup, deletes/readdresses once and
saves/reopens with a durable journal. NeoPro cached v2 now binds Application
ownership explicitly. The mock bounds each peer's queued/active replies and
events to 512 batches and 32 MiB. Each feature has a separate software evidence
boundary; original Toolkit and physical acceptance remain open.

The preceding [conversion, NeoPro report and event-delivery batch](toolkit-cli/docs/feature-batch-2026-10-02-conversion-csv-liveness.md)
introduced `cgate conversion tweak` for all 123 Toolkit tweaker pairs
admitted at that checkpoint, with a reviewed plan digest and guarded creation of a database
replacement. That checkpoint added KEYB2/KEYB4/KEYB6 CSV at firmware 2.5.00,
including per-block secondary applications. cmqttd also delivers subscribed
events on the command connection while programming is running. These features
have bounded software acceptance; complete original Toolkit and hardware
acceptance remain outstanding.

The [classic DLT physical workflow](toolkit-cli/docs/classic-dlt-physical-workflow.md)
connects a saved KEYML5 2.1.00/5055DL Indicators plan to one physical save,
fresh field verification and read-only recovery through cmqttd. It checks the
identity observed by physical LOAD and the original two-byte baseline before
programming. Its software acceptance uses owned loopback PCI peers; original
Toolkit, display and power-cycle acceptance remain separate gates.

The latest [reviewed conversion workflow](toolkit-cli/docs/feature-batch-2026-10-01-conversion-workflow.md)
adds a backed-up RELDN4 → RELDN4A move through project save, reopen, full PP
verification and read-only recovery. Source and installed-wheel checks each
passed 180 focused tests and four public workflow cases, including uncertain
replies and stale group refusal. Its scope is a closed indexed database graph;
original Toolkit and physical acceptance remain open.

The preceding [database conversion and PP persistence batch](toolkit-cli/docs/feature-batch-2026-10-01-conversion-pp.md)
matches 30 original C-Gate conversion results in each Rust server, preserves
independent unit metadata and programming parameters across saves and daemon
restart, and fixes successful LOAD warning handling in the Python CLI.
Native memory readback, complete Toolkit conversion workflows and physical
acceptance remain open.

The [loaded-project commissioning workflow](toolkit-cli/docs/known-serial-commissioning-journey.md)
now carries a known-serial move through direct or routed physical evidence,
Python CLI database reconciliation in cmqttd, SAVE/CLOSE/LOAD and a verified
whole-project readback. It preserves unit identities, references and other
programming, and recovers uncertain saves without replaying the address command.
Use `--route-project` for a loaded routed project and `--exclusive-project` for
editing/reloading ownership. Its [source and installed-wheel acceptance](toolkit-cli/docs/feature-batch-2026-10-01-loaded-project-commissioning.md)
uses disposable software peers; original Toolkit and hardware acceptance remain open.

The preceding [routed commissioning and documentor batch](toolkit-cli/docs/feature-batch-2026-10-01-routed-commissioning-documentors.md)
adds Rust apply/verify through one to six bridges, independent Python journal
validation and offline project reconciliation, plus old Bytecraft DIMPR12 and
NeoClassic SceneModify reports. Its focused source and wheel runs each passed
**1,159 test nodes and 1,304 subtests**, with separate validation of
151 distinct Rust tests. It also corrects journal-parent aliases while retaining
strict attempt-marker checks. Original routed commissioning and complete report
GUI/physical acceptance remain open. A subsequent
[XML mapper receipt refresh](toolkit-cli/docs/feature-batch-2026-10-01-unit-mapper-receipts.md)
replays the retained original Unit and combined Network cases against both
current Rust servers, preserving strict source and exact-wire checks.
These results are separate from the preceding
[IOPE and template batch](toolkit-cli/docs/feature-batch-2026-10-01-iope-templates-recovery.md), which
adds eight IOPE controller components, local eDLT template export/inspection/
preview and guarded staging, plus firmware failure diagnostics. Its focused
source and installed-wheel runs each passed 642 test nodes and 1,951 subtests,
with separately qualified native database evidence. Template Apply, complete
original GUI workflows and physical acceptance remain open. The earlier
[Toolkit controls batch](toolkit-cli/docs/feature-batch-2026-09-30-toolkit-controls.md)
records conversion, wireless, DLT, thermostat, report and firmware codec work;
the
[conversion, DLT and temperature batch](toolkit-cli/docs/feature-batch-2026-09-30-conversions-dlt-temperature.md)
retains its separate validation record.
The earlier [DALI/SENLL batch](toolkit-cli/docs/feature-batch-2026-09-30.md)
retains its separate source-bound acceptance record.

cmqttd distinguishes a repository failure before replacement from a write
already applied whose directory-sync durability is unconfirmed. The latter
returns an explicit 500 and the CLI stops automatic recovery writes. Inspect
state through a fresh connection before any manual recovery; see
[repository recovery](docs/cgate-repository-capacity.md).

## Which program do I need?

| I want to… | Use |
| --- | --- |
| Create, inspect, edit, validate, or export Toolkit XML/CBZ projects | `cbus-toolkit project` |
| Generate project HTML with supported device tables, key macros and group/action usage from saved XML/CBZ or native XML | `cbus-toolkit project document` ([profiles and limits](toolkit-cli/docs/project-documentation.md)) |
| Generate the same HTML from one fresh cmqttd/C-Gate database snapshot | `cbus-toolkit cgate database-document` ([snapshot workflow](toolkit-cli/docs/native-project-documentation.md)) |
| Edit classic DLT label/display settings, ordered indicator controls, or existing-language project TEXT | `cbus-toolkit dlt labels`, `display`, `indicators`, `text`, `text-dialog` and `cgate unit ... dlt-labels` ([indicators](toolkit-cli/docs/classic-dlt-indicators.md), [TEXT dialog](toolkit-cli/docs/classic-dlt-language-dialog.md)) |
| Compile one classic DLT label broadcast and assess supplied outcomes offline | `cbus-toolkit dlt broadcast plan` / `assess` ([command and evidence boundary](toolkit-cli/docs/classic-dlt-broadcast.md)) |
| Plan or save SENLL groups, broadcast interval, power-up state and Global status interval | `cbus-toolkit sensors light-level-plan` and `cgate unit ... sensor-light-level` ([profiles and limits](toolkit-cli/docs/sensors.md)) |
| Extract or deploy supported DALI device and gateway settings | `cbus-toolkit cgate dali` through cmqttd, including its 133 advertised global gateway fields ([workflow](toolkit-cli/docs/dali-commissioning.md)) |
| Preview or save database thermostat settings, explicit Celsius/Fahrenheit form normalization and supported templates | `cbus-toolkit thermostat settings` and `thermostat template` ([settings](toolkit-cli/docs/thermostat-settings.md), [template allocation](toolkit-cli/docs/thermostat-templates.md)) |
| Manage native C-Gate projects, configure supported units, control groups, or commission a network | `cbus-toolkit cgate` |
| Create a closed database network, inspect runtime definitions, or save them into the project | `cbus-toolkit cgate database network-new` and `cgate network definition` ([setup and lifecycle](toolkit-cli/docs/network-definitions.md)) |
| Edit or copy a loaded project's named Applications, Groups, NetVars or Levels | `cbus-toolkit cgate database get`, `set`, `add`, `copy`, `delete`, `validate`, with `--project NAME` ([selected sessions and persistence](toolkit-cli/docs/network-definitions.md)) |
| Upload a local file for the server's FILE service and portable conversions | `cbus-toolkit cgate file-upload PATH SOURCE [--project PROJECT]`; cmqttd uses a virtual repository namespace |
| Review a supported database unit move, retain a backup, save/reopen and inspect an interrupted attempt | `cbus-toolkit cgate conversion plan-move`, `apply-move`, `recover` ([workflow and bounds](toolkit-cli/docs/conversion.md#reviewed-move-with-save-reopen-and-recovery)) |
| Replace a database Unit using an admitted Toolkit tweaker, copy metadata and save/reopen with a journal | `cbus-toolkit cgate conversion tweak-replace`, `tweak-recover` ([lifecycle and bounds](toolkit-cli/docs/toolkit-tweaker-lifecycle.md)) |
| Inspect or edit a supported physical unit through cmqttd, then verify it with a fresh physical load | `cbus-toolkit cgate physical-pp` ([workflow contract](toolkit-cli/docs/physical-programming.md)) |
| Deliver a reviewed KEYML5 Indicators plan to the physical unit and inspect an interrupted attempt | `cbus-toolkit cgate physical-pp dlt-indicators` and `recover` ([complete command sequence](toolkit-cli/docs/classic-dlt-physical-workflow.md)) |
| Plan supported keypad, sensor, eDLT, scene, or unit-conversion settings offline | `cbus-toolkit keys`, `sensors`, `edlt`, `scene`, and `unit-conversion` |
| Query a CNI directly or inspect routed PCI messages | `cbus-toolkit pci` and `pci-route` |
| Discover CNI2/Wiser interfaces without opening them | `cbus-toolkit interface discover-cni` or `cbus-tools cni-discover`; use `scan-cni` / `cni-scan` for multiple routes |
| Connect C-Bus lights to MQTT and Home Assistant | `cmqttd` |
| Inventory live eDLT labels without Windows, while MQTT keeps running | `cbus-toolkit cgate edlt-labels --network //PROJECT/NETWORK`, connected to `cmqttd` |
| Create or compare a serial-bound eDLT label baseline | `cbus-toolkit cgate edlt-label-audit //PROJECT/NETWORK` |
| Decode a frame, export project labels, or interrogate a unit | `cbus-tools` |
| Test a C-Gate client without a vendor server or hardware | `cgate-mock` |
| Test PCI/CNI protocol traffic without hardware | `cbus-simulator` |

## Toolkit CLI

### Install

Requires **Python 3.13 or newer**. From the repository root, on macOS or Linux:

```sh
python3.13 -m venv toolkit-cli/.venv
toolkit-cli/.venv/bin/python -m pip install -e ./toolkit-cli
source toolkit-cli/.venv/bin/activate
cbus-toolkit --help
```

On Windows, use `py -3.13 -m venv toolkit-cli/.venv`, then run `toolkit-cli\.venv\Scripts\python.exe -m pip install -e ./toolkit-cli` and `toolkit-cli\.venv\Scripts\cbus-toolkit.exe --help`.

The base package has no external Python dependencies. Optional serial and USB features have separate extras; see the [Toolkit CLI guide](toolkit-cli/README.md).

### Try it without hardware

Create a project, add a network and lighting group, then inspect it:

```sh
cbus-toolkit project new demo.cbz --name DEMO
cbus-toolkit project add demo.cbz --kind network --address 254 --name Local
cbus-toolkit project add demo.cbz --kind application --parent /254 --address 56 --name Lighting
cbus-toolkit project add demo.cbz --kind group --parent /254/56 --address 1 --name Lounge
cbus-toolkit project inspect demo.cbz
cbus-toolkit project export demo.cbz demo.xml --format xml
```

Project editing preserves unknown XML and opaque programming fields. Use `--output` on an edit to write a separate copy. Native C-Gate 3 SQLite projects are managed through `cbus-toolkit cgate project` instead of the offline XML/CBZ editor. The C-Gate `DBSETXML` mapper has its own compatibility boundary: the [original direct/combined Unit evidence](toolkit-cli/docs/native-cgate-dbsetxml-unit-mapper-vm.md) shows that the two captured unknown namespaced Unit additions are accepted but omitted on readback.

Generate a project page or edit existing classic DLT text from an explicitly
saved native XML snapshot:

```sh
cbus-toolkit project document saved-dbgetxml.xml --native-xml --output project.html
cbus-toolkit cgate --host HOST database-document --project //PROJECT --output database.html
cbus-toolkit dlt text plan --project-xml saved-dbgetxml.xml --target //PROJECT/254/56/20 \
  --edit '1:1=Kitchen' > text-plan.json
cbus-toolkit dlt text apply --project-xml saved-dbgetxml.xml --plan text-plan.json --output labelled.xml
```

These write new local files. Project HTML includes recovered output tables,
KEY1/2/4 macros and supported group/action usage, with explicit markers for
remaining bodies. Original full-page byte/visual parity is unassessed.

The separate classic TEXT dialog reproduces its selected existing language,
default-text and finalization rules. Ordered indicator controls operate on a
supported unit PP snapshot and require its separately supplied specification:

```sh
cbus-toolkit dlt text-dialog plan --project-xml saved-dbgetxml.xml \
  --target //PROJECT/254/56/20 --language 1 --variant 1 --text Kitchen > dialog-plan.json
cbus-toolkit dlt text-dialog apply --project-xml saved-dbgetxml.xml \
  --plan dialog-plan.json --output dialog-labelled.xml
cbus-toolkit dlt --spec-dir private/decoded/unitspec indicators plan \
  --project-xml saved-dbgetxml.xml --unit //PROJECT/254/p/1 \
  --indicator-control page_fallback=yes --indicator-control duration_seconds=5 > indicator-plan.json
```

Use a snapshot containing the selected admitted unit, language and group.
Indicator order matters; inspect enabled controls, initialization changes and
save/reopen normalization in the plan. These local workflows do not transfer
or render labels. The separate `dlt broadcast plan/assess` compiles supplied
label/bitmap facts and assesses supplied command outcomes; it sends no traffic
and provides no automatic retry.

Supported thermostat settings use a closed database unit, explicit exclusive
project ownership and separately supplied specifications. Preview shows
requested and dependent changes before one verified save/reload. Pass
`--temperature-preference celsius` or `fahrenheit` explicitly to include
the 15 recovered form temperature fields; this process preference is
independent of the device's `TemperatureUnits` setting. Template 9 allocation
requires its documented initially empty application and explicit
`--group-sort address-ascending` profile.
Ordered output controls now compose Select, accepted/cancelled Add and
[Edit](toolkit-cli/docs/thermostat-output-edit.md) in the same settings owner.
Edit renames the currently selected group while preserving its OID/address,
shared references and existing Level metadata. See the
[Edit acceptance](toolkit-cli/docs/feature-batch-2026-10-04-thermostat-output-edit-integration.md).
Missing ASCII output/damper defaults also work amid Unicode group names,
using the recovered ASCII-only comparison and retaining ambiguity refusal.
See the [default-name guide](toolkit-cli/docs/thermostat-default-names.md) and
[current focused acceptance](toolkit-cli/docs/feature-batch-2026-10-04-thermostat-unicode-defaults.md);
full thermostat GUI and hardware parity remain open.
Explicit [damper callbacks](toolkit-cli/docs/thermostat-damper-controls.md) share
that settings history, including cache restoration, InstalledZones updates and
modulation binding/Click with final plant-factor serialization. See the
[implementation and validation report](toolkit-cli/docs/feature-batch-2026-10-04-thermostat-damper-controls.md)
for the supported scope and test evidence.
The [fresh quick-zone owner](toolkit-cli/docs/thermostat-quick-zone-controls.md)
adds explicit checkbox edits and queued plant selection/dispatch to this same
settings transaction, with the documented Celsius/settled input profile.
Its [release report](toolkit-cli/docs/feature-batch-2026-10-04-thermostat-quick-zone-controls.md) records
separate source pure/model and backend epochs, and 199 passing installed-wheel
tests plus five passing subtest events. Broader initialization, automatic
Windows dispatch, full GUI and physical thermostat acceptance remain open.

The [Toolkit conversion API and CLI](toolkit-cli/docs/toolkit-conversion-tweakers.md)
admits 288 of 292 registered source/target pairs. The earlier 123 have historical
native database evidence; the additional 120 DLT-target pairs have source-backed
literal and owned-service tests. A further 45 directions cover verified KEYBIR aliases, Neo-to-classic, DALI and older sensor profiles; see [remaining conversion rules](toolkit-cli/docs/toolkit-remaining-conversions.md). Four registrations remain refused for absent factories or undefined original reads.
The earlier set includes seven relay, 93 classic-to-Neo, five coupler-to-Neo and ten non-sensor
InputUnit directions at the documented exact firmware profiles. Its
source-preservation and refusal rules also govern `cgate conversion tweak`.
Preview binds the closed project, private specifications and PP defaults;
apply requires `--exclusive-project --expect-plan-sha256 HASH`. It creates a
fresh replacement and verifies one PP save, preserving the source. For source
deletion/readdressing and save/reopen, use the separately guarded
`cgate conversion tweak-replace` workflow with a distinct backup and new
journal; `tweak-recover` observes an interrupted attempt without replay. Read
[its metadata, persistence and recovery boundaries](toolkit-cli/docs/toolkit-tweaker-lifecycle.md).
Physical programming remains separate work. The [firmware recovery contract](toolkit-cli/docs/firmware-update-recovery.md)
also separates image verification from USB cleanup and explains explicit
resume after a release failure. Full GUI and physical acceptance remain open
for these workflows.

Wireless workflows now include bounded Connection/Scenes database edits,
WTXU project metadata creation and typed cached status/statistics reads.
Physical unit actions require explicit opt-in; successful acknowledgements
remain separate from hardware effects. See the [wireless scope](toolkit-cli/docs/wireless.md)
and [conversion/wireless batch](toolkit-cli/docs/feature-batch-2026-09-30-conversions-wireless.md).

Bounded IOPE Environment, output, logic, join, timer and retained scene components
share the `iope-workflow` offline and closed-database CLI. Their nine-profile
native matrices establish synthetic database persistence; complete parent/scene
forms and hardware remain open. See [IOPE workflows](toolkit-cli/docs/iope-workflows.md).

The `edlt-templates` command inspects, exports and previews bounded templates.
Its separate local stages preserve assignment, second-model, Reset and terminal
normalization evidence; complete template Apply remains refused. See the
[template contract](toolkit-cli/docs/edlt-template-integration-boundaries.md).

Firmware execution also binds package metadata and selected images to a
bounded immutable snapshot. Resume checks that snapshot against the interrupted
journal before archive parsing, decryption or USB construction. See the
[package identity contract](toolkit-cli/docs/firmware-package-snapshot.md) for
substitution guards, offline NCC/payload models and the remaining acceptance work.

### Connect to C-Gate

Point the CLI at your C-Gate server. This example reads the project list:

```sh
cbus-toolkit cgate --host 192.168.1.20 --port 20023 project list
```

Replace the example address and port with your server's values. Use `cbus-toolkit cgate --help` for project, network, database, unit, addressing, scene, and control commands. The transport supports verified TLS and client certificates. Advanced parameter workflows may require vendor unit specifications; those files are supplied separately.

To edit a saved C-Gate object as XML, export it, review a separate edited file,
then submit it with the export hash as a stale-document guard:

```sh
cbus-toolkit cgate --host 192.168.1.20 database get-xml \
  //PROJECT/254/56/1 --project PROJECT --output group.xml
cbus-toolkit cgate --host 192.168.1.20 database set-xml \
  //PROJECT/254/56/1 edited-group.xml --project PROJECT \
  --expect-current-sha256 SHA256_FROM_EXPORT --readback
```

This changes the server's database object; save the project separately on
original C-Gate. The hash check is read-before-write, and native XML readback
may differ from the submitted file. See the [XML file workflow](toolkit-cli/docs/native-database-xml-files.md).

For an exact C-Gate command or a batch that must share one session, use:

```sh
cbus-toolkit cgate --host 192.168.1.20 --port 20023 exec 'PROJECT LIST'
cbus-toolkit cgate --host 192.168.1.20 --port 20023 run commands.txt
```

Command batches stop at the first failure. These raw routes expose the selected server's command surface; typed CLI commands add workflow-specific validation and evidence, so raw forwarding is not typed Toolkit parity.

Results are JSON on stdout; operation errors are JSON on stderr and return a nonzero exit status. Put `--compact` before the command for single-line JSON. Event monitoring emits JSON lines.

To find a CNI2 or Wiser endpoint first, run `cbus-toolkit interface
discover-cni`. It sends one bounded IPv4 UDP query and reports the source
address plus advertised TCP port without opening the interface. For several
adapters or subnets, `cbus-toolkit interface scan-cni --probe
LOCAL_IP@SUBNET_BROADCAST` records each chosen route independently. Install the
CLI's optional `network` extra to use `scan-cni --auto-adapters --plan-only`
for an OS-derived route preview, followed by `scan-cni --auto-adapters` to
query the derived routes. Automatic mode constrains each socket to its named
adapter and confirms the OS setting before sending; the report records this
constraint. Physical packet egress remains unobserved. A zero-reply result does not prove that no
interface exists. `cbus-tools cni-scan` supports explicit and OS-derived
multi-route scans with the same bounded result envelope; `cni-discover` exposes
the single-route wire codec and JSON boundary;
see the [discovery contract](toolkit-cli/docs/cni-discovery.md).

The CLI's `cgate cgl import` and `cgate cgl export` exchange CGL label graphs
with either Rust service. Applications retain recorded creation order across
edits, copies and durable reloads. See [CGL exchange and order](toolkit-cli/docs/cgl-application-order.md)
for commands, old-repository fallback and remaining native-order gaps.

### Toolkit compatibility and current status

The CLI targets **C-Bus Toolkit 1.18.0.2754 and C-Gate 3.4.0.2001**, with full Toolkit functionality as the goal. Implemented workflows include offline project editing, native project management, supported unit programming and addressing, keypad presets, scenes, CGL exchange, and substantial eDLT configuration. Device and firmware support is documented per workflow.

For the bounded KEYGL5 5.5.00 parent transaction, the CLI composes 15 admitted
widget operations—Measurement, Lighting, Enable, Fan, HVAC, Multi Level, Room
Courtesy, Scene, Shutter, Time/Date, Timer, all three MRA models and Blank—and
the activation, General, Display, Standby, Colours, Navigation,
Quick Status, Page Control, distributed MRA-global, Applications and Corridor
operations. Reset may be operation 1, where its accepted fresh widget/scene
graph becomes the baseline for later controls. Applications, Corridor and
Reset use a complete ordered cache; callers may supply it, or the automatic
resolver can derive existing DBGETXML lists and exact Reset PP strings without
projecting missing list objects.
The automatic metadata resolver validates
ordered editability, complete byte and shared MRA-bit
ownership and application/group/dynamic-label dependencies before one retained
terminal save. The CLI can derive those application/group/scene-level/dynamic-variant/
static-label facts from one exact native project snapshot and plan missing
database metadata before the retained multi-edit.
See the [automatic parent metadata contract](toolkit-cli/docs/edlt-parent-metadata.md)
for the closed-project guards and the non-atomic PP/project save boundary.
The retained SceneManager can also derive complete existing application/group
lists and safe Trigger action text directly from the same exact project
snapshot. See [automatic SceneManager metadata](toolkit-cli/docs/edlt-scene-metadata.md);
it plans and can create a missing Trigger Control application, exact trigger
groups, and exact action levels with a retained project backup, then records
the separate PP and project-save boundaries. Typed accepted and cancelled
[Trigger and Action Add operations](toolkit-cli/docs/edlt-scene-add-dialog.md)
now model first-free allocation and editable names. Without an explicit image
provider, image-dependent metadata still refuses. A SHA-bound project BMP
export and optional decoded DLTP input extend the admitted FONT/DYNAMIC/ICON
and Language profiles; see [label controls and images](toolkit-cli/docs/edlt-label-controls-images.md).
Complete original form binding remains outstanding. The ordered parent transaction can consume one complete
caller-supplied SceneManager cache, edit the retained or Reset-fresh scene
graph, and share its final PP/CRC/save path with widget/settings operations.
Its automatic project resolver also composes the exact SceneManager metadata
contract with Applications, Corridor and operation-1 Reset: existing list
objects retain DBGETXML child order, exact Reset PP strings feed the fresh
graph, and missing Trigger groups/actions join ordinary parent metadata
creation before the same one PP staging/save path. A contiguous Blank prefix
immediately after Reset binds engine-issued receipts to that fresh graph.
Missing objects required by the ordered list/Reset contract, registry
display/sort preferences, complete original combined
parent/SceneManager controls, original interactive Reset/multi-panel execution and
physical acceptance remain outstanding.

**Full Toolkit parity is not complete.** The feature ledger currently records 42 areas: 18 implemented, 22 in progress, and 2 pending. The simple implemented-row ratio is **18/42 = 42.86%**; it is not a percentage of Toolkit functionality. Check the current machine-readable status with:

```sh
cbus-toolkit coverage --require-complete
cbus-toolkit coverage --evidence-root toolkit-cli --require-complete
```

This intentionally returns exit status `1` while parity remains unfinished.
The second form checks every recorded evidence artifact against a trusted
Toolkit source checkout; the first reports packaged declarations and cannot
pass the final gate without that byte verification.
Completion is now derived from the packaged [functional parity register](toolkit-cli/docs/parity-register.md),
which accounts for 22,103 committed source-surface records, including 412
parsed Toolkit forms, 10,102 executable controls and 1,839 event bindings, but
keeps functional percentages unavailable until they are resolved into a
complete denominator. Its generated C-Gate contract inventory maps all 431
primary and 11 supplement paths across selector, session, target,
authorization, response/event, effect/routing and acceptance axes. Unresolved
subaxes stay explicit and prevent routed command coverage from being reported
as full compatibility.
The [completed functions and outstanding work](toolkit-cli/docs/implementation-status.md)
describe supported profiles, test evidence, and remaining work. The
[Toolkit CLI guide](toolkit-cli/README.md) contains detailed command examples.

The [implementation review and path to full parity](docs/parity-review-and-roadmap.md)
audits the current implementation and lays out 59 tracked work items across
12 packages, a concrete first delivery batch, and the acceptance gates for
reaching 100% across the Toolkit CLI, cmqttd and MQTT support.

## MQTT and Home Assistant bridge

Build the Rust tools with a current stable Rust toolchain, from the repository root:

```sh
cargo build --manifest-path rust/Cargo.toml --release --workspace
```

The binaries are written to `rust/target/release/`. Run the bridge against your MQTT broker and CNI, replacing these example addresses:

```sh
rust/target/release/cmqttd \
  --broker-address 192.168.1.20 \
  --broker-disable-tls \
  --tcp 192.168.1.10:10001
```

`cmqttd` publishes Home Assistant discovery and lighting state, and forwards MQTT light commands to C-Bus. `/set` commands remain FIFO until each command receives its correlated PCI confirmation. After positive confirmation, cmqttd publishes the compatibility state echo only when no newer physical observation for that application/group arrived while delivery was pending; observations for other groups do not suppress it. The echo's `cbus_source_addr: null` records requested state. Every confirmed command still queues a physical level report request and publishes its non-retained delivery/readback receipt on `cmqttd/cbus/command_result`; a source-bearing bus event or status report is the physical observation. The retained `homeassistant/binary_sensor/cbus_cmqttd/state` topic changes to `OFF` during C-Bus transport loss and `ON` after reconnect. Add `--project-file house.cbz` for names from your Toolkit project and `--cbus-network 'Main Network'` to select a network. TLS is enabled by default; omit `--broker-disable-tls` when using a TLS broker. Serial and ESP32 bridge connections are also supported.

For Docker, copy `.env.example` to `.env`, configure your broker and C-Bus endpoint, then run `docker compose up --build`. See [bridge configuration](docs/configuration.md) for authentication, certificates, project files, time synchronization, and status updates.

### Use cmqttd as the CLI's server

Enable `--cgate-bind 127.0.0.1:20023` together with `--project-file house.cbz`. The daemon imports your project into a persistent database and serves the Toolkit CLI while continuing MQTT on the same PCI/CNI connection. The default C-Gate event server listens separately on port 20024 and applies the command allowlist to each new event peer. If command TLS is enabled, the plaintext event port binds to loopback only. Saved `CONFIG event-mode=socket` sends events to a configured host and port after restart. Docker Compose publishes both default ports on host loopback and stores the database in the `cmqttd_data` volume.

```sh
cbus-toolkit cgate --host 127.0.0.1 project list
cbus-toolkit cgate --host 127.0.0.1 exec 'CMQTT CAPABILITIES'
cbus-toolkit cgate --host 127.0.0.1 exec 'HELP BROADCAST_EVENT'
cbus-toolkit cgate --host 127.0.0.1 exec 'BROADCAST_EVENT SP maintenance started'
cbus-toolkit cgate --host 127.0.0.1 exec 'CONFIG GET *'
cbus-toolkit cgate --host 127.0.0.1 exec 'CONFIG INFO sync-time'
cbus-toolkit cgate --host 127.0.0.1 exec 'FILE'
cbus-toolkit cgate --host 127.0.0.1 exec 'FILE DIR'
cbus-toolkit cgate --host 127.0.0.1 exec 'FILE SHA256 exports/project.cgl'
cbus-toolkit cgate --host 127.0.0.1 exec 'PORT ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'PORT LIST'
cbus-toolkit cgate --host 127.0.0.1 exec 'PORT IFLIST'
cbus-toolkit cgate --host 127.0.0.1 --timeout 15 exec 'PORT CNISCAN2 192.0.2.10 192.0.2.255 FAST'
cbus-toolkit cgate --host 127.0.0.1 --timeout 30 exec 'PORT PROBE cni 192.0.2.20:10001'
cbus-toolkit cgate --host 127.0.0.1 exec 'LOGIN'
cbus-toolkit cgate --host 127.0.0.1 exec 'ACCESS LIST'
cbus-toolkit cgate --host 127.0.0.1 exec 'ACCESS'
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 network sync-new //PROJECT/254 --unit 6
cbus-toolkit cgate --host 127.0.0.1 network set-project //PROJECT/254 PROJECT
cbus-toolkit cgate --host 127.0.0.1 edlt-labels --network //PROJECT/254
cbus-toolkit cgate --host 127.0.0.1 edlt-labels //PROJECT/254/p/5
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 edlt-widget-groups //PROJECT/254/p/5
cbus-toolkit cgate --host 127.0.0.1 edlt-label-audit //PROJECT/254 --write-baseline labels.json
cbus-toolkit cgate --host 127.0.0.1 edlt-label-audit //PROJECT/254 --baseline labels.json --mode configuration
cbus-toolkit cgate --host 127.0.0.1 label cache-clear //PROJECT/254/56 5 --key 2
cbus-toolkit cgate --host 127.0.0.1 exec 'AIRCON ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'AIRCON SET_ZONE_HVAC_MODE //PROJECT/254/172 1 0,1 3 0 1 0 1 255 230 64'
cbus-toolkit cgate --host 127.0.0.1 exec 'AUDIO ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'AUDIO REQUEST_CURRENT_FEED //PROJECT/254/205 1 2'
cbus-toolkit cgate --host 127.0.0.1 exec 'AUDIO SET_FEED //PROJECT/254/205 1 2 4 0'
cbus-toolkit cgate --host 127.0.0.1 exec 'SECURITY ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'SECURITY STATUS_REQUEST //PROJECT/254/208 1'
cbus-toolkit cgate --host 127.0.0.1 exec 'SECURITY ARM //PROJECT/254/208 away'
cbus-toolkit cgate --host 127.0.0.1 exec 'MEDIATRANSPORT ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'MEDIATRANSPORT STATUS_REQUEST //PROJECT/254/192 2'
cbus-toolkit cgate --host 127.0.0.1 exec 'MEDIATRANSPORT PLAY //PROJECT/254/192 2'
cbus-toolkit cgate --host 127.0.0.1 exec 'MEASUREMENT ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'MEASUREMENT DATA //PROJECT/254/228/1/1 10234 -2 2'
cbus-toolkit cgate --host 127.0.0.1 exec 'TELEPHONY ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'TELEPHONY RECALL_LAST_NUMBER_REQUEST //PROJECT/254/224 out'
cbus-toolkit cgate --host 127.0.0.1 exec 'TELEPHONY DIVERT //PROJECT/254/224 021234567'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI ?'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI KNOWN EXEC //PROJECT/254/p/20 A'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI EMERGENCY STATUS EXEC //PROJECT/254/p/20 A 3'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI ERROR_REPORTING STORE_OPTION //PROJECT/254/p/20'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI GATEWAY PAGED_RECALL //PROJECT/254/p/20 521 1'
cbus-toolkit cgate --host 127.0.0.1 exec 'DALI SESSION NEW commissioning'
```

Network-wide eDLT label inventory, audit, `serials refresh`, and
`serials populate --refresh` use a 300-second per-command timeout by default
to allow the full `NET SYNC` to finish. An explicit `cgate --timeout` overrides
it; other C-Gate commands retain the 10-second default.

The embedded endpoint implements the complete maintained C-Gate 3.4 CONFIG,
FILE, and ACCESS command families. CONFIG provides help, GET, INFO, SET, scoped
OBGET/OBSET/OBRESET and LOAD/SAVE over durable compatibility state. FILE
provides DIR/LS, recursive MKDIR, DELETE, SHA256, base64 DOWNLOAD and native
here-document UPLOAD, including the native `.0` replacement backup. FILE data
lives in a sandboxed virtual root inside cmqttd's atomic JSON repository; FILE
paths never access the host filesystem and `%PROJECT%` is a virtual namespace.
Mutating FILE commands require LOGIN when the optional command gate is armed.
ACCESS provides ADD/DELETE/LIST/LOAD/SAVE, native role filtering and
username/password LOGIN over durable rows. User passwords are digest-only and
LIST prints `<redacted>`. LOAD/SAVE use sandboxed repository snapshots rather
than host files; invalid hostnames and missing snapshots fail without changing
the active policy. Fresh and pre-ACCESS repositories preserve Docker-published
CLI access until an operator changes interface/remote policy. Thereafter an
unmatched peer receives 421, or a LOGIN/LOGOUT-only recovery session when the optional
token is configured. Mutating ACCESS commands require either that recovery-token
LOGIN or a Clipsal/Max ACCESS-user LOGIN when the gate is armed.
Query `CMQTT CAPABILITIES` for these explicit boundaries and see the
[C-Gate replacement guide](docs/cmqttd-cgate.md) for wire examples,
persistence, native evidence, and the remaining compatibility gaps.

`BROADCAST_EVENT` is local command-session traffic: it sends one native
timestamped level-three `703 cmdN - broadcast_event` line to clients subscribed
with `EVENT e3s0c0` (or a higher event level), without writing C-Bus, MQTT, or
the persistent database. The optional LOGIN gate protects event injection.

It also implements the complete maintained C-Gate 3.4 `PORT` command family.
`PORT LIST` and `PORT IFLIST` enumerate the cmqttd host, `CNISCAN` uses the
legacy UDP-30718 exchange, and `CNISCAN2` follows that with the native CNI2
CCP query on UDP 20050. `PORT PROBE` opens a separate temporary connection,
sends the retained DC1/`@2104` echo-and-serial exchange, reports the returned
PCI serial text, and always closes it. It refuses cmqttd's active endpoint with
431 so MQTT is not interrupted. C-Gate 3.4 automatically updates
serial devices, so `PORT REFRESH` retains its observed deterministic 408 reply.
When LOGIN is configured, scans, probe, and refresh require authentication;
help and local enumeration stay readable.

Replace the example project, network and unit with your actual addresses. The
network form performs one fresh `NET SYNC` plus `NET CHECKUNIT` serial refresh,
then reads every exact supported KEYGL5 5.5.00 record in numeric address order.
It brackets each selected memory snapshot with physical IDENTIFY4 reads and
attaches the fresh inventory identity only when both physical serials match the
fresh inventory serial. A mismatch remains a per-device read error; it never
attaches a stale inventory identity to the snapshot.
It reports unsupported, unknown or ambiguous identities and per-device read
failures alongside any successful static configurations. An incomplete report
is still emitted and the command exits nonzero.

Each selected device read verifies its live identity, stable configuration
header and static-text CRC, and includes the 64 stored strings plus widget,
page and scene references. Those physical snapshots are sequential, so the
inventory is not an atomic view of the network. After the device reads, the
CLI requests `CMQTT LABELS` once for the network. The resulting dynamic-label
observations are network-wide, transient, recipient-unverified and kept only at
the report's top level; they are never assigned to a device. A unit-shaped
`CMQTT LABELS` request is only a compatibility alias for that same network ring.
Physical dynamic-label cache readback remains unavailable, so the observation
view is always marked incomplete and `device_readback` remains false.

The embedded service also runs physical `NET CLOCKS` inspection, target-count
configuration, and gateway recovery after `NET SYNC`, using source-correlated
status reads and schema-backed writes with mandatory readback. It retains a
bounded current-connection history of incoming and confirmed outgoing dynamic
label traffic for Toolkit CLI inspection. Command connections also implement
native-shaped `SESSION_ID` enumeration and one-shot tags, the `EVENTS` alias,
and `QUIT`/`EXIT` reply-before-close behavior. It also exposes the exact
four-channel `EVENT_CHANNEL` catalogue with connection-local SUB/UNSUB state,
session-owned advisory `LOCK`/`UNLOCK`, the native `PROJECT` help and
`PROJECT DIRFULL` repository view, and the three read-only `DBGETJSON` NAC
projections. cmqttd does not retain vendor NAC object-list definitions, so its
object and routing JSON are explicitly empty; TAGMAP covers the durable local
network, application, group and level tags. Query `CMQTT CAPABILITIES` before
depending on that bounded JSON scope.

Programming sessions also implement specification-backed
`PP RESET_TO_DEFAULTS`: declared defaults replace only the staged session
values, with no database or PCI write until the caller explicitly saves.
Missing or malformed unit specifications fail unchanged.

Local C-Gate compatibility now includes PP catalogue/spec queries, lock and
session inventory/cancellation, staged raw-memory get/set/debug,
`LOAD_FROM_FILE`, and runtime PROGRAMMER queue creation, inspection and
cancellation. Catalogue files are confined to `--cgate-unitspec`, and these
administrative operations send no PCI traffic. `PROGRAMMER TRIGGER ... START`
acknowledges an INIT queue immediately, then runs TEST, PP_COPY, PP_SAVE,
PP_SET, PP_END, PP_UNLOCK, DALI_READ, DALI_PROGRAM and public DALI commands in
priority order through cmqttd's existing local or physical backends. STATUS
reports the active queue count and TEST countdown. The worker stops on the
first failed receipt and never automatically replays an uncertain bus command.
`PP WRITE_PATCH` executes a strict operator-supplied
`cmqttd.pp-patch/v1` manifest uploaded to
`%PROJECT%/patchsets/cmqttd-patches.json` through the controlled `FILE`
namespace. It checks the saved and live type/firmware, requires an admitted
current patch version for a normal run, then holds one physical programming
lane across the recovered disable, block-write, full second verification,
version and re-enable sequence. The live preflight requires exactly one type
and firmware reply. Firmware bounds use native case-sensitive lexical ordering,
an optional catalogue selector requires equal saved metadata, and non-overlapping
blocks may occupy at most the effective 136 bytes in ranges 114–241 and
247–254. The version parameter is native `0xF2`; target `FF` is reserved, while
`FF` may be deliberately admitted as a current version for manual recovery.
Ordinary blocks use STORE tag `0x73`; parameter `0xF7`
uses the returned unlock challenge as its tag. An already-target unit is
accepted only after every block and control `0x70` are verified, with enable
repaired only when necessary. A successful physical reply identifies one of
three dispositions: full pipeline, repaired enable only, or verified read only.
Every write is read back and an incomplete
transaction is never replayed automatically. `SIMULATE` validates and prints
the complete plan and its SHA-256 without PCI traffic; pass that digest as
`EXPECT_SHA256=<64hex>` on the physical command to bind the reviewed plan.
Successful completion persists the decimal patch version and manifest
provenance. The proprietary
Schneider `patchset.zip` container is not ingested; `CMQTT CAPABILITIES`
reports that boundary explicitly.

The five-command `DEPLOY_QUEUE` family is wired to that volatile PROGRAMMER
worker. LIST, DELETE and typed DELETE_ALL return the retained native JSON/status
envelopes. ADD registers an INIT task, returns immediately, and publishes the
native `updated-entries`, `started` and terminal `ended` channel envelopes.
The first instruction failure leaves the entry in ERROR and publishes a
structured `debug` receipt. RETRY is accepted only for a queued STOPPED or
ERROR task and is the sole operation that deliberately reinitializes and
re-executes it. Queue state and subscriptions disappear on restart; physical
PP/DALI commands share cmqttd's CNI and MQTT continues to use it throughout.

The embedded service also supports native physical `LABEL KFIGET` and
`LABEL KFISET`. The application token admits only a native
`LabelSupportingApplication`; it is a scope/class gate and is not encoded into
KFIGET's fixed selector `0x1c`. KFIGET first sends three volatile
parameter-`0xFF` writes, so it is a programming operation rather than a
dynamic-label cache read. Every KFI write and the GET IDENTIFY request is sent
exactly once with generation-safe confirmation handling and no transport
replay. Direct targets require source-correlated unit replies; targets on a
database-resolved route through one to six bridges require the exact Reply
Network, unit, parameter and PCI confirmation. A lost confirmation faults the
programming lane until reconnect.

Native `LABEL CLEAR //PROJECT/NETWORK/APPLICATION UNIT [KEY]` is also
hardware-backed. The Toolkit CLI exposes it as `cgate label cache-clear` so it
cannot be confused with `cgate label clear`, which broadcasts an empty group
label, or `cgate edlt-label-clear`, which runs the guarded KEYGL5
`CLEAREDLT` workflow. The no-key command clears all label keys with native CAL
`A3 FF 00 27`; a key from 1 through 8 uses `A4 FF 00 66 KEY`. cmqttd sends the
point-to-point command exactly once and waits only for its correlated PCI
confirmation. Native C-Gate treats either confirmation outcome as command
completion, and there is no unit ACK or cache readback, so a 200 response does
not prove erasure, rendering or persistence. The same command can target a
topology-resolved route through one to six bridges without clearing cmqttd's
configured-network observation cache. `CLEAREDLT` and `DO ... FactoryDefault`
also support those routes and additionally require the exact routed unit/tag
acknowledgement.

`NET SYNC` also populates the native KEYGL5 synchronization properties. A unit
must have non-error present MMI state one or two, exactly one raw IDENTIFY4
reply carrying a known serial, and KEYGL5 types
in both the configured database and fresh physical IDENTIFY1. Eligible units
follow retained C-Gate classfile order. Direct targets use the OEM `09 00`
route; bridged targets use the database-resolved one-to-six-bridge point-to-point
route and accept only the exact Reply Network. Parameter `0xFB` length 9
supplies the NUL-terminated `FirmwareVersion`, memory address
16 length 2 supplies decimal `Application` and `Application2`, and parameter
`0xFA` length 44 supplies `WidgetGroups` as opaque comma-separated decimal
bytes. `Version` remains the separate IDENTIFY2 value. Read the cached values
with `GET //PROJECT/NETWORK/p/UNIT PROPERTY`; these GETs issue no new bus I/O.
Repeated identical known replies and mixed known/unknown replies do not qualify
for metadata reads, even though the live serial cache keeps its established
distinct-known-serial representation.
The synchronization leaves persistent configuration unchanged, but the OEM
application read writes a volatile address-16 selector on the unit before its
recall. The typed `edlt-widget-groups` command reports that distinction in its
JSON evidence.
Each physical request is exact-once and source or Reply-Network/unit/parameter/
selector-tag/length correlated. An
optional failure does not fail an otherwise valid identity sync, but clears
that value and every later unrefreshed value and faults the programming lane
until reconnect. Ambiguous addresses receive no metadata traffic and expose no
stale values. A reconnect or transport loss invalidates an in-flight snapshot,
returns 408, and emits no sync-ok. These properties are separate from the unsupported dynamic
label-cache query.

`AIRCON ?` lists the complete C-Gate 3.4 AIRCON command family. The eleven
commands use application 172 on the configured network or a topology-resolved route through one to six bridges. With
`--cgate-auth-file`, the ten state-changing commands require `LOGIN`; `REFRESH`
remains open. A 200 response means the PCI confirmed the broadcast. It does not
establish controller acceptance or the resulting HVAC state. Incoming AIRCON
reports are available to C-Gate event clients; cmqttd does not expose an MQTT
HVAC state schema.

`AUDIO ?` lists all 19 maintained C-Gate 3.4 Audio commands for application
205. Both multiplexer/zone and `Z function` forms use the retained wire
encoding, including native low-bit transformations and the native 0..7 error
code range. Read/report requests remain open under the optional LOGIN gate;
amplifier, feed, ramp, mute and common-control operations require `LOGIN` when
the gate is armed. Success requires a correlated confirmation on the current
PCI generation. A topology-resolved one-to-six-bridge target uses the same SAL in one exact PPM send, accepts only its allocated confirmation, and has no invented device readback. Incoming Audio command traffic reaches C-Gate
event clients. C-Gate 3.4 advertises Audio `label` and `load_icon` events, but
the retained build silently drops valid standard frames because of a decoder
length bug; cmqttd decodes the intended retained A0 layout as an explicit
repair and does not claim byte-for-byte native event behavior for those two
events. No MQTT Audio state schema is invented.

`SECURITY ?` lists all seven maintained C-Gate 3.4 Security commands for
application 208 on the configured network or a topology-resolved route through one to six bridges. `STATUS_REQUEST` and
`REQUEST_ZONE_NAME` remain open under the optional LOGIN gate; arm, tamper,
alarm, keypad and display-message control require `LOGIN` when the gate is
armed. A 200 response means the shared PCI confirmed the broadcast; it does
not establish alarm-panel acceptance or resulting state. Incoming Security
events, zone names and packed status reports reach C-Gate event clients.
cmqttd publishes no invented MQTT alarm-panel state.

`MEASUREMENT ?` exposes the complete maintained C-Gate 3.4 Measurement
family. `MEASUREMENT DATA` sends the exact application-228 device/channel
sample and waits for PCI confirmation. Incoming samples reach C-Gate event
clients and populate native-shaped application/device/channel GET properties;
cmqttd does not publish them as MQTT state.

`MEDIATRANSPORT ?` lists all 21 maintained C-Gate 3.4 Media Transport
commands and reports for application 192 on the configured network or a topology-resolved route through one to six bridges.
Playback, navigation, enumeration, status, track totals and fragmented names
use exact native SAL, one send, and positive PCI confirmation. With
`--cgate-auth-file`, status and enumeration requests remain open while controls
and report injection require `LOGIN`. The typed decoder and canonical JSON
preserve raw name bytes, and incoming messages reach C-Gate event clients;
cmqttd publishes no invented MQTT player state. A 200 response does not prove
media-device acceptance or resulting state.

`TELEPHONY ?` exposes all five maintained C-Gate 3.4 Telephony commands for
application 224: clear diversion, divert, secondary-outlet isolation,
last-number recall, and incoming-call rejection. Exact native token grammar,
including the captured non-ASCII diversion defect, is retained. Incoming
line, call, ringing, number and Internet-request events reach C-Gate event
clients. A 200 proves active-generation PCI-confirmed broadcast delivery; it
does not prove telephone acceptance, call state or persistence. cmqttd does
not invent an MQTT Telephony state schema.

The maintained `IDENTIFY` control leaves (`OFF`, `ON`, `RAMP`, and
`TERMINATERAMP`) drive application 251 groups on the configured network or a topology-resolved route through one to six bridges. They use the native lighting-shaped SAL, including byte or percentage
levels, native duration suffixes, and optional `FORCE`. cmqttd accepts only
application 251: the retained native build falsely reports success without
sending a packet for other applications, so that unsafe behavior fails before
I/O. Incoming Identify traffic reaches C-Gate event clients and retains its
source unit; no MQTT Identify state is created.

`SHORTMESSAGE REFRESH` and `SHORTMESSAGE SEND` implement application 173.
Refresh retains the native 0..63 information-type field. Send validates the
fragment total/index, optional number and symbol, information type, and a
14-byte UTF-8 payload before I/O. C-Gate 3.4.0.2001 emits malformed SEND SAL:
it writes text as PCI hex characters, overstates the extended length, swaps
the number/symbol flags, and can still return 200. cmqttd deliberately repairs
SEND with real UTF-8 bytes, an exact extended length, and the layout accepted
by the native inbound decoder. This is protocol-compatible repaired behavior,
not byte-for-byte reproduction of the vendor defect.

`EREPORT MESSAGE` implements application 206 Error Reporting messages with
the native type aliases, category and `y`/`n` or `1`/`0` status flags,
severity, unit, and optional data bytes. Identify, Short Message, and Error Reporting commands are
sent once and require a correlated PCI confirmation on the active connection;
they are never replayed after an uncertain transport outcome. Mutating forms
require `LOGIN` when the optional gate is armed. Incoming Short Message and
Error Reporting SAL fans out to C-Gate event clients, while cmqttd defines no
MQTT state schema for either application.

`DALI ?` exposes all 128 maintained DALI paths. For a configured `SYS_DAL2`
gateway, 103 leaves have physical backends: 48 core, 14 emergency, and 41
specialized gateway, error-reporting, measurement, or session operations. The
remaining 25 paths are local: six exact retained group-help roots and 19
catalogue, gateway-view, and commissioning-session operations. Physical work
uses the shared PCI, source or programming-reply correlation, reconnect
generation guards, and no replay after an outcome-uncertain write. Paged
stores are read back before success; saved sessions use cmqttd's atomic JSON
repository. `EXT_ONLY` session extraction/deployment is physical. All four
source-pinned read-only typed extraction plans are implemented:
`DALI_ONLY`, `FULL`, `REFRESH_STATUS_INFO`, and `RETRIEVE_RECONCILE`. They
decode line discovery masks, device types, common parameters, all 16 scenes,
status, emergency, LED, GTIN, serial, and (for `FULL`) the complete extended
map, then commit one atomic snapshot only after the complete plan succeeds on
one PCI generation. `COND_QUICK`, `COND_EXTENDED`, and `RESCAN_FAULT` run the
recovered conditional plans, including a journaled, never-replayed
`ADDRESS_UNKNOWN` short-address assignment. Typed `DALI_ONLY`/`FULL`
deployment validates every payload before I/O, writes in native order, and
stops at the first fault without rollback or replay. Owned native C-Gate
transcripts against a scripted gateway confirm both. Downstream DALI device
state and hardware acceptance remain unverified, so
`dali_full_compatibility` remains false. There is no invented DALI MQTT state
contract. The Python CLI provides typed extraction, staged-edit deployment,
and read-only recovery through the same service:

```sh
cbus-toolkit cgate --host 127.0.0.1 dali extract //PROJECT/254/p/20 \
  --line A --extract-type DALI_ONLY --ecg 3
cbus-toolkit cgate --host 127.0.0.1 dali deploy //PROJECT/254/p/20 \
  --line A --ecg 3 --edits edits.json --journal /operator/dali-attempt.json
cbus-toolkit cgate --host 127.0.0.1 dali recover --journal /operator/dali-attempt.json
```

See the [typed CLI guide](toolkit-cli/docs/dali-commissioning.md) for edit
format, dry runs, address-assignment intent and uncertainty receipts, and the
[DALI command guide](docs/cgate-dali.md) for native wire evidence.

Command discovery also matches the retained parent envelopes for fourteen
application and administration families, including `CLOCK`, `LIGHTING`,
`TRIGGER`, `SHORTMESSAGE`, `CGL`, and `TRANSFORM`. Bare, literal `?`, and
`HELP` forms are local and do not touch the C-Bus network. Each listed child
still follows its own capability classification; showing native help does not
turn an unsupported child operation into a simulated success.

General C-Gate clients can use silent untagged `#`/`//` comments, 301 `OID`,
local `BROADCAST_EVENT`, native object discovery and reads through `SHOW`, and
native-shaped `REPORT`, `TREE`, `TREEXML`, and `TREEXMLDETAIL`. `SHOW`
implements ordered `?`/`??` property catalogues and `*`/named reads for
`cgate`, projects, project C-Bus, project, network, application, group, unit,
and output-terminal objects. The application and child-object schemas cover
the retained Temperature, Lighting, Air Conditioning, Media Transport,
Trigger, Enable, Audio, Security, Clock, Telephony, Measurement, and generic
application classes represented by application IDs 25, 48, 95, 172, 192,
202, 203, 205, 208, 223, 224, 228, and 238. Named fields are
case-insensitive while preserving the caller's field spelling in the reply;
foreign-project lookup, canonical terminal aliases, object errors, and the
captured GET/SHOW trailing-token grammar are also pinned.

The exact native evidence includes the 62-command base object transcript
[`native_cgate_show_objects.json`](rust/testdata/fixtures/native_cgate_show_objects.json),
the 69-row casing/error audit
[`native_cgate_show_audit.json`](rust/testdata/fixtures/native_cgate_show_audit.json),
the 78-row application matrix
[`native_cgate_show_appclasses.json`](rust/testdata/fixtures/native_cgate_show_appclasses.json),
and the 18-row parser matrix
[`native_cgate_show_parser.json`](rust/testdata/fixtures/native_cgate_show_parser.json).
Tagged response order, status, fields, and framing are compared exactly.
Runtime host/IP/JVM metrics and scheduled timestamps vary by process, so the
replay validates their native shape and normalizes only values explicitly
declared volatile by a fixture before comparison.

`NEW UNIT/GROUP/PHANTOM` creates durable, idempotent database objects without
pretending that a unit exists on the bus. Its address, application-child, and
known/unknown firmware-token boundaries are pinned by the 25-row
[`native_cgate_new_bounds.json`](rust/testdata/fixtures/native_cgate_new_bounds.json)
transcript. Tree output combines those records with physical units already
observed by an explicit sync; TREE flags do not trigger a hidden physical scan.
The multi-application hierarchy, application labels, `Groups` versus `Net
Vars`, object states, and XML detail framing are pinned by
[`native_cgate_tree_appclasses.json`](rust/testdata/fixtures/native_cgate_tree_appclasses.json).
`CMQTT CAPABILITIES` reports these inventory and object-creation boundaries
for clients that need to distinguish database state from live C-Bus evidence.
When the optional C-Gate authentication gate is enabled, NEW and
BROADCAST_EVENT require an authenticated session.

**All maintained non-obsolete C-Gate command paths now have a primary route.**
The executable inventory contains 431 paths: 230 physical, 199 local/session,
zero blanket `FailClosed502` paths, and the two native-obsolete `NET
CHECK_UNRAVEL` and `NET STATE_INTERVAL` paths. This closes command-path routing;
it does not make `full_cgate_compatibility` true. Individual handlers still
reject unsupported selectors before I/O, and confirmed delivery is not proof of
a downstream device's state, timing, persistence, or behavior on every firmware
and topology.

The embedded endpoint includes the full maintained CONFIG, FILE, ACCESS, PORT,
and DEPLOY_QUEUE families; local repository selection and repair; all five
portable TRANSFORM leaves; legacy local and physical database lifecycle; native
parent help; the physical application, DALI, network, label, scene, and PP
routes described below; and a verified `PP WRITE_PATCH` path for the explicit
`cmqttd.pp-patch/v1` manifest. DEPLOY_QUEUE ADD and RETRY run admitted
PROGRAMMER PP/DALI work asynchronously, stop at the first fault, and never
replay an uncertain command automatically. Direct and topology-resolved
one-to-six-bridge UNRAVEL handle the whole safe inventory plan, including
address 255 and larger duplicate sets, with exact-once moves, exact Reply
Network correlation, and a generation-bound target-network final proof.

Compatibility boundaries remain explicit. `NET SET_PROJECT_IDENTIFY` supports
direct and one-to-six-bridge targets with strict Reply Network correlation, one
fixed-tag STORE, routed readback, generation-bound target-cache updates, and no
automatic replay after uncertainty. Physical PP LOAD and
PP SAVE/SAVE_TO_SOURCE support topology-resolved targets for `direct`,
`paged`, `ncc`, `edlt`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and `goc2`
schema methods. Selector acknowledgements, recalls, tagged writes, and verified
readback are bound to the exact Reply Network, unit, parameter, tag, and count.
Routed `direct`, `paged`, and `ncc` lock challenges are also bound to the route
and allocated PCI confirmation and are never replayed. A changed C-Bus 3
specification follows verified routed STOREs with the native Save-to-NVM
EXECUTE/POLL sequence; its statuses are bound to the exact Reply Network, unit,
group, and operation.

Lighting ON/OFF/RAMP/STOP, their bare and `DO` aliases, Trigger EVENT/
INDICATORKILL, and Enable SET use topology-resolved one-to-six-bridge standard
SAL frames. Routed dynamic labels, Clock DATE/TIME/REQUEST_REFRESH, Temperature
Broadcast, and stored cross-network scene actions use the same contract. Scene
playback resolves every target route before the first write and requests status
only for direct-network actions. Each routed application command is sent once and waits only for
its exact PCI confirmation; it is never replayed, does not invent remote
status readback, and changes or invalidates only the target network's live
cache on the captured PCI generation. Routed label and clock/temperature sends
do not enter the configured-network observation/application cache. Standard
label cache clear, KFIGET/KFISET, KEYGL5 CLEAREDLT, and KEYGL5 FactoryDefault
also resolve one-to-six-bridge targets and reject direct or neighbouring-route
receipts. Unsupported selector forms inside otherwise-routed handlers and some
selector-specific DALI session plans refuse before I/O; the private Schneider
`patchset.zip`, repository/archive formats, and SQLite/XML schemas are not
reconstructed; cmqttd transforms only its versioned portable SQLite container
inside the controlled FILE namespace. Its ACCESS policy is a safer digest-only
local model, TLS can require a private-CA client certificate but does not map
its identity into ACCESS rows, and the exact
native per-handler access-level matrix is unfinished. Device-family coverage,
unusual bridges and adapters, electrical/timing behavior, power-loss recovery,
and hardware acceptance beyond the evidenced profiles still require validation.
The Toolkit CLI's separate 18/22/2 workflow ledger remains incomplete.
See the [supported operations and remaining work](docs/cmqttd-cgate.md).

The NET runtime catalogue is separate from the imported tag database, matching
C-Gate's lifecycle boundary. Its active definitions and `DB`/`FILE` snapshots
are atomic `cmqttd-json` state; `FILE` is an internal snapshot and never opens a
caller-selected host path. `NET LEARN` and all four `NETWORK LOCATE` selectors
use the configured direct shared PCI or a topology-resolved one-to-six-bridge
PPM route, send one exact SAL frame, wait only for its correlated confirmation,
and never replay an uncertain write or invent remote readback. `NET OPEN`/`NET CLOSE` and
`PROJECT START`/`PROJECT STOP` change runtime state and clear volatile caches
without disconnecting cmqttd's shared PCI or MQTT. Direct and topology-resolved
one-to-six-bridge `NET UNRAVEL`, `NET UNRAVELUNIT`, and `DO ... UNRAVEL` use a
complete route-correlated known-serial inventory, preflight every unique empty
destination, send selected-serial writes once, require exact direct or Reply
Network receipts, and verify the final target inventory before committing only
that network's cache. Unroutable or uncertain plans fail before mutation, and
uncertain writes are never replayed. This is scripted protocol acceptance, not
live bridge delivery or power-cycle persistence acceptance.
Routed `NET SET_PROJECT_IDENTIFY` is the bounded exception: selection, STORE,
and RECALL remain on the resolved one-to-six-bridge path, and only the target
network's volatile `ProjectName` can commit on the captured PCI generation.
`TOPOLOGY EXPLORE` reuses the active endpoint (including socket/CNI aliases) or
opens each other supported descriptor transiently, reports physical MMI/project
identity results, and closes temporary transports before returning.

## Development tools and simulation

`cbus-tools` provides small inspection commands:

```sh
rust/target/release/cbus-tools decode 05013800790148
rust/target/release/cbus-tools dump-labels --pretty 2 rust/testdata/fixtures/project.xml
rust/target/release/cbus-tools serial-verify \
  --pci 192.0.2.10:10001 --plan selected-plan.json
rust/target/release/cbus-tools serial-apply \
  --pci 192.0.2.10:10001 --plan selected-plan.json \
  --journal /operator/recovery/selected-plan-attempt.json
```

The selected-serial commands consume a strict plan produced by the Toolkit workflow. Each `--pci` invocation opens a direct TCP socket and requires exclusive ownership of the CNI; stop `cmqttd` or any other current owner before running it. Verify performs bounded read-only classification. Apply completes the exact bookended fresh-before inventory, immediately rechecks local option 66=`05`, durably records send intent in a new journal, sends once on that same PCI connection, and independently verifies afterward. Preserve one stable journal path and use `serial-verify --journal` after any interruption or uncertain result; recovery never authorizes replay. These guarantees are covered with scripted loopback peers and do not claim physical-unit compatibility or persistence.

For a routed plan, both commands also require `--project FILE`,
`--source-network N` and `--target-network N`. They re-derive its one-to-six-bridge
route from the exact pinned XML/CBZ snapshot before I/O. A completed routed
Rust apply-v2 journal can then be independently validated and reconciled into
that offline project with `cbus-toolkit serial-address reconcile`; preserve its
original path and attempt marker. See [routed execution](docs/rust-selected-serial-routed.md)
and [project reconciliation](toolkit-cli/docs/physical-addressing.md).

To exercise the Toolkit CLI against the Rust C-Gate model, start the server in one terminal:

```sh
rust/target/release/cgate-mock --bind 127.0.0.1:20033
```

Then, with the Python environment activated, use another terminal:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20033 project new DEMO
cbus-toolkit cgate --host 127.0.0.1 --port 20033 project list
```

`cgate-mock` implements all **431 unique command paths** in the maintained C-Gate inventory. It supports shared project state, per-client project selection, tagged replies, events, and programming sessions. This is complete command coverage in an in-memory test server; it does not establish full Toolkit workflow parity or physical-device behavior. State is lost when the server stops. See [C-Gate compatibility](docs/cgate.md).

For a PCI/CNI test endpoint, run `rust/target/release/cbus-simulator 127.0.0.1 10001`. This is a separate protocol from C-Gate: point PCI clients at the simulator and C-Gate clients at `cgate-mock`.

## Documentation and AI agents

- [Implementation review and path to 100%](docs/parity-review-and-roadmap.md)
- [Toolkit CLI guide](toolkit-cli/README.md) and [feature status](toolkit-cli/docs/implementation-status.md)
- [Architecture](docs/architecture.md), [command reference](docs/commands.md), and [protocols](docs/protocol.md)
- [MQTT bridge configuration](docs/configuration.md), [C-Gate compatibility](docs/cgate.md), and [physical DALI commands](docs/cgate-dali.md)
- [Testing and development](docs/testing.md)
- [Original Toolkit/C-Gate artifact provenance](toolkit-cli/docs/original-artifact-provenance.md) and [functional parity register](toolkit-cli/docs/parity-register.md)
- [AI skill](.agents/skills/cbus-cli/SKILL.md) with command, system, and workflow references; [repository agent guidance](AGENTS.md)

## Repository layout

```text
toolkit-cli/             Python cbus-toolkit application, tests, and feature docs
rust/                    Rust MQTT bridge, protocol libraries, and supporting tools
rust/testdata/           committed protocol vectors and system-test fixtures
docs/                    shared architecture, configuration, and development docs
.agents/skills/cbus-cli/ AI skill and operational references
cmqttd_config/           optional local Docker configuration
```

## License

GNU Lesser General Public License v3.0 or later. See [COPYING](COPYING) and [COPYING.LESSER](COPYING.LESSER).
