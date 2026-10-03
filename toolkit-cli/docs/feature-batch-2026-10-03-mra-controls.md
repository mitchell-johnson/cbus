# MRA control integration — 3 October 2026

The Python Toolkit CLI now supports explicit retained control histories for
KEYGL5 / 5055EDL firmware 5.5.00 MRA Zone Control, Source Select and Source
Control panels. The histories compose with ordinary eDLT operations through
one owning parent transaction and the existing cmqttd C-Gate service. This is
a source-backed database editing profile; complete original Toolkit and
physical audio/display acceptance remain unfinished.

## Completed behavior

Use `mra_controls` inside a `zone-control`, `source-select` or `source-control`
operation. The [command guide](edlt-mra-controls.md) gives the event schema,
exact offered identities and preview commands.

- Explicit panel bindings cover the actual variant, status, macro, ramp and
  source choices. Icon Index writes preserve each family's recovered coupled
  assignment order and require the causal `UseBigIcon` setting. A raw property
  setter and a finite UI choice remain separate contracts.
- Label and eligible status controls retain all 64 full static Names across
  earlier dialogs and later MRA panels. Input, Enter-key, Leave, preview,
  selection, refresh and close events are explicit. Pending text blocks save;
  close does not implicitly commit. Copied bindings and detached JSON receipts
  cannot resume an owning control.
- Callback-only edits preserve complete 32-byte records, RestoreLevel, hidden
  status references, raw variants/sources/ramp values and opaque fields.
  Read-only views leave invalid macro pairs unchanged. Only the explicit Zone
  macro getter invokes its recovered repair. Type conversion executes ordered
  defaults; explicit ordinary scalar configuration retains its normalizer.
- Shared multiplexer and zone values are initialized from the first surviving
  loaded MRA model before conversion. Removing that model does not erase the
  initialized values; discarded terminator-tail records do not supply them.
  Explicit globals remain independent owner constraints and distribute during
  terminal BeforeSave, after the control histories. Stored raw multiplexer 3
  survives when no public choice overrides it.
- Native automatic metadata issues the exact binding at each causal operation
  position. The identity covers owner, family, widget, whole PP snapshot,
  operation, full Names, external references and project/provider digests.
  Canonical apply reuses that exact issued instance.
- Existing closed-project, exact-network lock, backup, stale-source and graph
  preservation guards remain active. PP save and project save are separate
  boundaries. A possibly successful save with a missing reply is uncertain;
  no automatic replay or rollback follows it.

Operation-1 Reset keeps its earlier admission bounds. Initial Source Control
(type 9) is outside that profile. The new callbacks do not establish arbitrary
initial MRA form-history acceptance. See [Reset](edlt-reset.md).

## Current validation

The focused source run and a newly built, isolated installed wheel each ran
**18 selected modules: 668 parent tests passed, five skipped, and 1,066 separate
subcases passed**. Pytest and the maintained JUnit/trace auditor both exited 0.
Their actual parent IDs and outcomes match. The subcases are not added to the
parent count, and the two environments are not added together.

Both runs executed all **22 public MRA cases**: eight positive profiles, two
refusals and one lost-save case per backend. They made 40 actual CLI calls over
38 connections per environment. Positive cases checked complete selected
records, RestoreLevel, all 64 static rows, all 844 PP parameters and the
remaining complete project graph. Sixteen cases also verified a fresh project
CLOSE/LOAD. Two tests dropped an actual upstream successful PP-save reply and
verified uncertainty, zero retries, no rollback and no later mutation.
Refusals checked pending text and invalid identity, including rejection before
connection. The daemon used only its exact eight startup PCI frames per
fixture; no house network or physical device was contacted.

The fresh wheel's **373 Python/JSON package files** matched source and ZIP bytes
before and after the run. Runtime guards recorded 140 observations across 81
processes with zero import violations, including startup and terminal checks
for the actual pytest process. All 3,958 phase inputs and both pinned Rust
binaries remained unchanged during each frozen execution.

The five explicit skips were:

- pinned static-source regeneration without its private source fixture;
- original model/UI vectors without the Toolkit DLL fixture;
- original full PP/CRC/save-reload acceptance without native C-Gate, specs and DLL;
- original MRA save normalization without the Toolkit DLL;
- the native database parent save/reload gate without C-Gate and specs.

CI and Make now register all 11 public cases per backend and require successful
bodies from the new component, static and parent modules. GitHub CI status is
separate from the locally completed selection; this report does not assert a
new green GitHub run.

## Evidence and preserved history

The [release receipt](../research/fixtures/mra-controls-owned-release-20261003.json)
binds the frozen source/wheel execution, package/import proofs, exact selection,
review artifacts, fresh modeled protocol captures and retained failures.
The [literal vectors](../research/fixtures/edlt-mra-control-literal-vectors.json)
contain 325 complete-record histories and 595 steps, with separate refusals and
lifecycle facts. Their [provenance](../research/fixtures/edlt-mra-control-provenance.json)
qualifies form activation versus binding declaration and Enter-key semantics.
The source annex publishes hashes, ranges and decoded facts, not vendor source,
IL bytes, unit specifications or site projects.

Earlier component/static 380-parent/447-subcase, ad-hoc parent 17-test and public
22-case author runs remain separate predecessor scopes. Their setup, fixture
and expectation failures are retained. Fresh six modeled C-Gate comparisons
passed 64 primary and four combined cases after Make/CI registration; seven
capture/check commands and the separate register/census phase exited 0.
Those protocol captures do not establish MRA frontend or original execution.

Rust code did not change. The retained four Cargo gates and 8,711 passed tests
with one private ignore were independently bound to all 464 unchanged Rust
inputs and both current binary hashes. Cargo was not rerun for this Python
change. The full Python suite was not run. This report and status annotations
were written after the frozen executions; they do not change tested runtime,
CI, test, fixture or package bytes.

## Outstanding acceptance

[Issue45](https://github.com/mitchell-johnson/cbus/issues/45) remains open for
complete original parent lifecycle and bindings. Implicit framework reads,
notifications and currency/modal scheduling, culture-specific suggestions,
modal image chooser outcomes, rendering, other models/firmware and physical
or power-cycle behavior remain unverified. Software database preservation is
not a successful physical audio command.

The installed `coverage --require-complete` still exits 1 with `complete=false`
and an incomplete functional census. The ledger remains **18/42 categories**;
42.9% is a category ratio, not a percentage of all Toolkit functions. No global
completion state, denominator, original acceptance or physical gate is promoted.
