# Thermostat remote references — 3 October 2026

The existing `thermostat settings preview|apply` command now resolves enabled
setback and schedule references for PC_TSA, PC_TSA5, PC_TSB and PC_TSB5. It
composes their ordered application/group creation and form validation with the
existing scalar, fan and optional temperature projection in one transaction.
See the [operator workflow](thermostat-settings.md) and
[static source review](thermostat-remote-references-source.md).

Source 1 uses the existing scalar ApplicationNumber application; source 2 uses
Enable Control 203. Schedule enable comes from normalized program flags.
Validation uses object identity: one unused setback role is allowed, every
enabled schedule role must be non-unused, and selected non-unused objects must
be distinct across the two features. Optional level additions are declined.
Missing native group 255 is a real object named `<Unused>` when an enabled
getter creates it. The source-backed creation command is `Group`, including
under 203; the maintained backends also export those new objects as `Group`.

The command validates a complete project snapshot, makes a backup, creates
references in order, and saves changed PP values once. A graph-only change
uses zero PP saves. Both mutating paths use one final project save and explicit
reload verification. No-op requires both deltas to be empty. Full PP and graph
freshness, unrelated metadata and returned object identities are checked.
Selected-unit PP ordering, Config OID regeneration and absent/empty Level
TagsDLT are documented representation exceptions. Plans are single-use and
uncertain operations are never retried or rolled back automatically.

## Focused validation

The [release receipt](../research/fixtures/thermostat-remote-references-owned-release-20261003.json)
binds the final execution bytes and private raw evidence. Source and a fresh
noneditable installed wheel each passed **137 parent tests and 1,207 separate
subtests**, with **eight skips** and zero test failures. Each executed all
24 owned public backend cases. These overlapping scopes are not additive.

- Seven scenarios run on each backend: joined PP/graph save, alias with equal
  numeric addresses across applications, basic Lighting references, basic
  alias with one unused role, graph-only creation, complete no-op, and disabled
  references that still create application 203.
- Each backend also exercises a selected-object collision, stale unrelated
  graph, stale PP, a lost successful PP save reply and a lost successful final
  project-save reply. Literal independent oracles check commands, full values,
  object reuse, ordered creation, opaque metadata and no replay.
- Across both executions, 24 mutating normal journeys include a second explicit
  save/close/load. Four no-op journeys read fresh PP/XML without another save.
  Eight lost-reply journeys retain fresh PP/XML; they do not claim reopen or
  confirmed target persistence.
- All 378 source/wheel/installed package files match. Actual pytest imports
  came from the installed package, and its console entry point passed an
  additional owned PC_TSB preview/apply with PYTHONPATH removed.
- All 2,727 scoped inputs and both shared backend binaries remained unchanged
  through execution. The 468 Rust source files and binary hashes match the
  retained DIN-controls validation manifests; no Rust rebuild was needed.
- The static reproducer passed 166 checks over 33 method spans and verified
  the two decoded base specifications plus their common include. The optional
  static pytest node also passed separately. No original code was executed.

The eight skips comprise that optional static-input node in the clean source
and wheel environments and seven native-server settings tests. The audit
runner initially required the entirely unprovisioned native module to pass;
both initial audit failures are retained. The corrected audits require passing
cases from all ten provisioned modules, using the unchanged eleven-module
JUnit reports and execution traces. No test failure was reclassified and no
tests were rerun for that configuration correction.

Preliminary backend attempts exposed selected-unit PP sorting on save and the
backends' omitted Project OID. Their failed receipts remain separate from the
final frozen execution. The resulting guards preserve complete named PP
records and require all consumed graph identities while allowing an omitted
Project OID. Independent source/native and final outcome reviews are retained
by hash in the release receipt.

## Remaining scope

This is raw-edit-before-load projection, not the event history of an open GUI.
Implicit source-change callbacks, optional Add dialogs, complete parent
validation, inherited loaders/service factories, other thermostat tabs,
original native acceptance and physical thermostat timing remain open under
issues 42 and 72. The thermostat category remains `in_progress`, and
`coverage --require-complete` still exits 1. No full-suite or publication-head
CI pass is claimed. Release/status annotations follow frozen execution without
changing runtime, tests or packaged metadata.
