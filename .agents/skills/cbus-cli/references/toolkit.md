# Python Toolkit CLI

## Identity and installation

`cbus-toolkit` is the Python application under `toolkit-cli/`. It is independent of the Rust MQTT bridge and supports Toolkit-style project editing, commissioning, unit configuration, scenes, and diagnostics.

From the repository root:

```sh
python3.13 -m venv toolkit-cli/.venv
toolkit-cli/.venv/bin/python -m pip install -e ./toolkit-cli
toolkit-cli/.venv/bin/cbus-toolkit --help
```

Python 3.13 or newer is required. The base package has no external dependencies. Optional extras are `serial`, `usb`, `research`, and `test`. On Windows, the virtual environment executables are under `Scripts` instead of `bin`.

## Choose the command family

| Task | Command family | Backend |
| --- | --- | --- |
| Create, inspect, validate, edit, export XML/CBZ | `project` | Local files |
| Manage native projects, networks, databases, units | `cgate project`, `network`, `database`, `unit` | C-Gate server |
| Inspect or edit a physical unit through cmqttd PP | `cgate physical-pp` | Shared C-Gate/PCI service; physical reads and optional writes |
| Control groups, scenes, labels, triggers, Enable | `cgate on`, `off`, `ramp`, `scene`, `label`, `trigger`, `enable` | C-Gate server; may reach hardware |
| Invoke a stored KEYGL5 scene Trigger binding | `cgate edlt-scene-trigger` | One Trigger event through C-Gate; may reach every listener for the pair |
| Inspect or change addressing and serials | `cgate address`, `serials` | C-Gate; profile and identity guards apply |
| Direct CNI queries and commissioning | `pci`, `serial-address` | Explicit PCI/CNI endpoint |
| Discover CNI2/Wiser endpoints | `interface discover-cni` | One bounded IPv4 UDP query; no TCP or C-Bus connection |
| Inspect route bytes | `pci-route` | Offline |
| Plan supported device settings | `keys`, `sensors`, `edlt`, `unit-conversion`, `unit-scenes` | Offline, with explicit inputs/specifications |
| Edit scenes/templates or match serial inventories | `scene`, `unit-templates`, `unit-addressing` | Local files |
| Preferences, CSV, About and update diagnostics | `preferences`, `toolkit-database-csv`, `toolkit-about`, `update-*` | Varies; some require Windows/vendor files |
| Diagnose firmware or explicitly perform USB DFU | `firmware` | Offline or explicit device, depending on subcommand |
| Inspect current completeness | `coverage --require-complete` | Packaged feature ledger |

Inspect each subcommand's `--help` and the matching feature document before constructing parameters. There is no universal `--dry-run`; use it only where the chosen workflow exposes it.

## Offline project example

```sh
cbus-toolkit project new demo.cbz --name DEMO
cbus-toolkit project add demo.cbz --kind network --address 254 --name Local
cbus-toolkit project inspect demo.cbz
cbus-toolkit project export demo.cbz demo.xml --format xml
```

Use a scratch directory for examples. Edits preserve unknown XML and programming fields; `--output` directs an edit to a separate copy. Native C-Gate 3 SQLite projects use C-Gate operations instead of this legacy-file editor.

## C-Gate client

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20033 project list
cbus-toolkit cgate --host 127.0.0.1 --port 20033 exec 'PROJECT LIST'
cbus-toolkit cgate --host 127.0.0.1 --port 20033 run commands.txt
```

These examples target the Rust mock after it is started on port 20033. The native plain TCP default is 20023. Each CLI invocation creates a new connection; `run` keeps all commands in one session and stops at the first error. Project selection is session-local, so use explicit addresses/project arguments or one batch when later commands depend on a selection.

Native connections support TLS and client certificates. A live address such as `//PROJECT/254/p/20` can reach a physical unit; `/db//PROJECT/254/p/20` explicitly selects the database for programming workflows. Confirm which source the task requires and use the documented identity, backup, and verification behavior for writes.

For physical PP work through cmqttd, prefer the typed command:

```sh
cbus-toolkit cgate physical-pp inspect //PROJECT/NETWORK/p/UNIT --method direct
cbus-toolkit cgate physical-pp apply //PROJECT/NETWORK/p/UNIT \
  --method direct --set UnitName GARAGE
```

It preflights `CMQTT CAPABILITIES`, validates every selected parameter against
`PP INFO *`, issues one SAVE or SAVE_TO_SOURCE, and uses a distinct physical PP
LOAD for readback. Current methods are `direct`, `paged`, `ncc`, `edlt`, `giu`,
`sgiu`, `dali`, `goc`, `gocbyt`, and `goc2`. Never replay an uncertain save.
Treat fresh readback as in-run device verification, not power-cycle persistence
or broad hardware acceptance. Routed NCC apply requires the separate NVM
capability. See `toolkit-cli/docs/physical-programming.md`.

Successful operations emit JSON on stdout, operation errors emit JSON on stderr, and failures return nonzero. Argument usage errors can be plain argparse text. `--compact` is a global option before the command; event monitoring emits JSON lines. Preserve partial-operation evidence and do not replay uncertain writes automatically.

The typed network learn/locate forms cover the six retained learn grades and
all four retained locate selectors. They require fully qualified direct paths
and return an interface-delivery receipt without claiming device action,
readback or persistence. Use the exact range and no-replay boundary in
[`network-learning-locate.md`](../../../../toolkit-cli/docs/network-learning-locate.md).
Run them only against a C-Gate service with the intended direct physical
network bound:

```sh
cbus-toolkit cgate network learn //PROJECT/254 56 init-relay 1
cbus-toolkit cgate network locate //PROJECT/254/208 unit 1 ON
```

For supported classic UnitTemplate work, use `template-export` and
`template-import` for XML files. Use database-unit `template-copy` to transfer
the original 26-field template set directly between distinct matching
KEY1/KEY2/KEY4 1.2.67 units under one exact network lock. Use
`template-reset-defaults` to restore only that field set from the selected
decoded specification. Preview either transaction with unit-level `--dry-run`.
An apply sends one PP SAVE and opens a fresh destination session; inspect
`staged_verified`, `save_confirmed`, `reload_verified` and
`preserved_parameters`. `project_file_saved=false` means a separate project
save is still required for file durability. Never retry when
`save_outcome_uncertain=true`. These commands require `/db` units, reject
cross-profile conversion and do not perform a physical or factory reset. See
`toolkit-cli/docs/unit-templates.md`.

## eDLT Measurement decimal values

For a KEYGL5 / 5055EDL 5.5.00 database unit, configure exact scaling with
`--gain-mantissa/--gain-exponent` and
`--offset-mantissa/--offset-exponent`. To reproduce the Toolkit Measurement
text editor, use `--gain-value` or `--offset-value` plus an explicit
`--measurement-culture`:

```sh
cbus-toolkit edlt measurement-plan snapshot.json \
  --page 1 --position 1 --device-id 42 --channel 3 \
  --gain-value '1,5' --measurement-culture de-DE
```

The default culture is `canonical`: dot decimal, no grouping, blank rejected,
and stored exponent limited to -128..127. Source-pinned Toolkit profiles are
`invariant`, `en-NZ`, `de-DE`, and `fr-FR`. They reproduce each observed
decimal/group separator, final blank→1 and Gain zero→1 behavior, invariant
fixed-50-place formatting, and signed-byte exponent wrapping. Read
`composite_conversions`: `editor_exponent` is the pre-write value, `exponent`
is the stored signed byte, and `display_value` is the original getter's
post-storage rendering. Never substitute the process locale or normalize
commas on your own. The CLI rejects non-finite text because Toolkit accepts
`NaN` and then hangs in its number-break loop. See
`toolkit-cli/docs/edlt-measurement.md` for exact grouping and preservation
rules.

To combine one Measurement edit with the parent proximity percentage control,
use `edlt parent-form-plan` offline or database-unit `edlt-parent-form`. Both
require `--metadata` with a complete lifecycle cache. Use `--level-percent`
only when the resulting `--wake-mode` is `primary-event`; mode changes can
reinterpret the shared byte as a Trigger action. Inspect `phases`,
`cross_control`, `preservation`, `initialization_concurrency` and
`original_save_order` before applying. This bounded composition validates all
supplied controls before mutation and preserves the retained scene/MRA models.
Its original order is source-pinned and its individual controls have retained
native probes, but `native_parent_form_executed=false`: do not describe it as
an end-to-end execution of the original WinForms dialog. See
`toolkit-cli/docs/edlt-parent-form.md`.

For two or more supported KEYGL5 5.5.00 panel edits, use `edlt
parent-transaction-plan` offline or database-unit `edlt-parent-transaction`.
The ordered operations cover Measurement, Lighting, Enable, Fan, HVAC, Multi
Level, Room Courtesy, Scene, Shutter, Time/Date, Timer, MRA Zone Control,
Source Select, Source Control, Blank, activation, General, Display, Standby, Colours,
Navigation, Quick Status, Page Control, MRA globals, Applications and
Corridor, one retained SceneManager sequence, plus an optional operation-1
Reset baseline. Applications, Corridor and Reset require the complete
application cache; SceneManager requires the complete SceneManager cache. The
automatic parent metadata resolver derives existing ordered DBGETXML lists and
exact Unit PP strings for operation-1 Reset without projecting missing list
objects. It can project the validated ordered-list/Reset/contiguous-Blank
state into the SceneManager branch, which creates only exact required Trigger
application/group/action objects. The
transaction reconciles one page mode, rejects overlapping complete records or
settings fields, reserves both Time/Date slices, validates application/group
and effective dynamic-variant dependencies, composes shared text allocation in
order and enters every validated control before one terminal lifecycle/CRC projection.
Place Display before a dependent HVAC/MRA icon edit, Standby before dependent
idle Colours controls and a retained/new MRA widget before `mra-globals`.
Shared multiplexer and zone components each have one explicit owner; omitted
values use the first existing pre-conversion MRA record. Review `operation_results`,
`operation_metadata_dependencies`, `ownership`, `preservation` and
`execution_counts`. Blank uses whole-slot ownership. Reset creates a fresh
widget/scene graph before later operations and reports layered baseline
overrides; Reset after operation 1 and duplicate Reset fail closed. Blank may
form only the contiguous prefix after Reset, where it binds an exact issued
fresh-graph receipt; a later Blank fails closed. Applications must precede
SceneManager, and SceneManager must precede
every Scene widget so final graph dependencies are validated. The original
component evidence does not establish an executed original multi-panel form; see
`toolkit-cli/docs/edlt-parent-transaction.md`.

When a current native project snapshot is the source of truth, replace the
manual cache with the bounded automatic resolver. Offline, pass
`--project-xml` and the selected `--unit`; for the database command pass
`--auto-metadata --exclusive-project`. It derives required applications and
groups for every admitted operation, complete consumed scene-level addresses,
safe dynamic-variant facts and all 64 static-label slots, then deterministically
plans missing application/group records. With `scene-manager`, it reuses the
exact retained resolver and adds missing Trigger application, group and action
levels after container creation and before the one parent PP save. Review the
`automatic_ordered_application_cache` database-view provenance for
Applications/Corridor/Reset: XML child order and TagName are exact, while
Toolkit registry display/sort preferences are unobserved. Review the
plan before applying and use the selected source network as the exact PP lock
address. The apply creates a project backup but DBADDSAFE, PP SAVE
and PROJECT SAVE are separate C-Gate operations. Automatic rollback stops once
PP SAVE is attempted, and an uncertain reply must not be retried. Project/DLTP
image-dependent dynamic facts fail closed. See
`toolkit-cli/docs/edlt-parent-metadata.md`.

Retained SceneManager edits have a separate automatic resolver with the same
offline/native option shapes. It derives complete existing application/group
lists, consumed trigger level sets and safe default-language action text. An
exact retained getter chain can plan missing application202 as `Trigger
Control`, exact non-255 groups as `Group N`, and exact actions as `Action
Selector N`, Address=Value=N, with four blank variants. Review every creation.
Native apply requires the
exact source-network lock, closed/idle project networks and exclusive caller
ownership. Use `--backup-project` when applying: it saves/copies the source,
rechecks it, creates and reads back the objects, then crosses separate PP SAVE and
PROJECT SAVE boundaries. Rollback stops once either applicable save is
attempted; treat a lost save reply as uncertain and never retry it. The
interactive blank Add dialogs are separate and unsupported; their action path
uses first-free 0..254 and editable `Level N`. Image-dependent label facts
remain unsupported; use manual `--metadata` for independently established
DYNAMIC/FONT/ICON labels. See
`toolkit-cli/docs/edlt-scene-metadata.md`.

The lifecycle receipt names all five calculated CRC fields. Do not infer a
missing calculation from `phases.crc`, because that changed-only view omits an
already-correct stored CRC.

The database save follows verified PP staging. If its reply fails or is
interrupted, do not replay the command: `saved=false` means unconfirmed, while
the transaction evidence marks both save outcome and current PP/database state
uncertain.

## Compatibility and tests

Target: Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001. Full Toolkit parity is unfinished. `coverage --require-complete` deliberately exits 1 until both implementation and acceptance requirements are complete. Command forwarding, the Rust mock's 431 paths, and simulator results do not establish physical-device or full Toolkit equivalence.

Read the repository's `toolkit-cli/docs/implementation-status.md` for supported functions/profiles and outstanding work, and `toolkit-cli/README.md` for detailed examples. Source is in `toolkit-cli/src/cbus_toolkit/`; tests and retained acceptance evidence are part of this application.

For development, install `./toolkit-cli[test,research,serial,usb]`, then run `make check` and `make check-interop` from `toolkit-cli/`. Native/vendor/hardware tests require explicit environment gates; report skips separately from passes.
