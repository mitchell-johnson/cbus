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

Successful operations emit JSON on stdout, operation errors emit JSON on stderr, and failures return nonzero. Argument usage errors can be plain argparse text. `--compact` is a global option before the command; event monitoring emits JSON lines. Preserve partial-operation evidence and do not replay uncertain writes automatically.

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

For two or more distinct Measurement, Lighting or proximity activation edits,
use `edlt parent-transaction-plan` offline or database-unit
`edlt-parent-transaction`. Supply `--operations` as a strict ordered JSON
array and the same explicit lifecycle cache. The transaction reconciles one
page mode, rejects duplicate/conflicting byte ownership, composes shared text
allocation in order and enters every validated control before one terminal
lifecycle/CRC projection. Review `operation_results`, `ownership`,
`preservation` and `execution_counts`. The original component evidence does
not establish an executed original multi-selection form; see
`toolkit-cli/docs/edlt-parent-transaction.md`.

When a current native project snapshot is the source of truth, replace the
manual cache with the bounded automatic resolver. Offline, pass
`--project-xml` and the selected `--unit`; for the database command pass
`--auto-metadata --exclusive-project`. It derives required applications,
groups, complete consumed scene-level addresses and all 64 static-label slots,
then deterministically plans missing application/group records. Review the
plan before applying and use the selected source network as the exact PP lock
address. The apply creates a project backup but DBADDSAFE, PP SAVE
and PROJECT SAVE are separate C-Gate operations. Automatic rollback stops once
PP SAVE is attempted, and an uncertain reply must not be retried. Project/DLTP
image-dependent dynamic facts fail closed. See
`toolkit-cli/docs/edlt-parent-metadata.md`.

Retained SceneManager edits have a separate automatic resolver with the same
offline/native option shapes. It derives complete existing application/group
lists, consumed trigger level sets and safe default-language action text. An
exact missing action reached by the retained getter/setter is planned under
the existing Trigger Control group as `Action Selector N`, Address=Value=N,
with four blank variants. Review every creation. Native apply requires the
exact source-network lock, closed/idle project networks and exclusive caller
ownership. Use `--backup-project` when applying: it saves/copies the source,
rechecks it, creates and reads back levels, then crosses separate PP SAVE and
PROJECT SAVE boundaries. Rollback stops once either applicable save is
attempted; treat a lost save reply as uncertain and never retry it. Missing applications/groups
and image-dependent label facts remain unsupported; use manual `--metadata`
for independently established DYNAMIC/FONT/ICON labels. See
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
