# Classic DLT edit, physical save, reload and recovery

The public Python CLI now connects a saved KEYML5 `2.1.00` / `5055DL`
Indicators edit to guarded physical delivery through cmqttd. The first issue-36
fixture enables page fallback, then sets a five-second duration, on synthetic
`WFDLT/254/p/4`. It saves and reopens the database project, programs once,
verifies a separate physical LOAD and supports read-only recovery.

This delivers a major bounded software workflow in
[issue 36](https://github.com/mitchell-johnson/cbus/issues/36). The broader issue
remains open for original Toolkit comparison, other profiles/workflows and
physical acceptance. No home network, Windows VM or real device was used.

## Operator behavior

Use the existing `dlt indicators plan` and database `unit dlt-labels --plan`
commands to review and save the edit. After project save/close/load, deliver it
with `cgate physical-pp dlt-indicators TARGET --plan FILE --journal FILE`.
The [operator sequence](classic-dlt-physical-workflow.md) contains the complete
commands and recovery instructions.

Admission requires the exact saved database identity and edited result, while
a fresh physical LOAD must match the plan's original baseline. It binds all ten
indicator fields and both complete bytes at `0x33`/`0x34`, including unchanged
shared bits. The ordered controls are rederived from the reviewed plan; forged
changes, database drift, physical drift and wrong type/firmware fail before SAVE.
Older servers lacking the physical identity contract fail closed.

The new cmqttd physical PP INFO contract exposes exactly `UnitType`,
`FirmwareVersion` and canonical `Source` root attributes from the successful
LOAD. Database and inventory changes cannot relabel them. Connected-generation
and ownership guards protect response construction; replacement attempts,
reconnects and uncertain saves invalidate provenance. Attempt IDs prevent an
old completion from replacing a new/recreated session. Confirmed same-source
SAVE may retain the original LOAD stamp; another destination cannot acquire it.

The CLI checks identity and generation before staging, before the durable SAVE
attempt and on a distinct fresh LOAD. It sends one `PP SAVE_TO_SOURCE` and never
replays an uncertain mutation. Journal phases distinguish planned, possible-send,
confirmed, readback-verified and complete states. Existing `physical-pp recover`
performs fresh reads and reports observed/partial states without SET, STORE,
unlock or NVM operations. Resolution alone does not declare delivery complete.

## Acceptance

The [acceptance receipt](acceptance/2026-10-01-dlt-physical-workflow/acceptance.json)
binds current source/test bytes, binary and fresh wheel hashes, actual import
origins, unique test rosters and retained raw artifacts. Published artifact
derivatives replace only declared local path coordinates. Exact private raw
bytes remain hash-linked; the substitutions are not new execution evidence.

Source and a fresh isolated installed wheel each passed **102 distinct normal
cases**: 88 focused tests, 11 typed DLT interop cases and three generic physical
programming regressions. Each reported 64 passing subtests separately. Exactly
one configured original-C-Gate opt-in test was excluded before collection;
there were zero selected failures, errors or skips. Both environments matched
all **324 package Python/JSON files** and stayed unchanged through the runs.
The wheel's README metadata and licenses matched the frozen source inputs.

The unit-4 journey executed **20 public CLI commands per environment**. Literal
indicator bytes changed from `af8a` to `a58e`; all 128 peer memory bytes were
compared, and only addresses 51/52 changed. Full project XML, unit metadata,
nonindicator PP and save/reopen equality were checked independently. The peer
validated 58 direct unit-4 requests and injected 174 wrong-route, wrong-unit or
stale-parameter frames. Ten schema STORE ranges occur within one SAVE attempt;
shared-byte stores are planned native work, not retries. A separate multi-control
unit-5 case verifies `af8e` to `c5be`.

Interop also covers exact wrong type and `2.1.01` firmware refusal, edited and
unchanged physical-bit drift, forged-plan/database drift, missing identity,
journal failure/interruption before SAVE, lost STORE acknowledgement, daemon
restart and read-only recovery. The earlier actual wrong-firmware success and
the earlier overbroad name-based exclusion remain historical evidence; the
final selector excludes only the genuine native opt-in node.

The generic regressions retain all ten physical programming methods, complete
journal phases and refusal of a repeated incomplete attempt. Separate focused
publication/differential/parity checks each passed **126 distinct tests and 545
subtests** in source and installed-wheel environments. These are disjoint from
the 102-case selection; repeated recorded interop runs do not increase unique
case counts.

A private external recorder repeated only the 14 interop cases in each
environment, forwarding results and in-process streams unchanged. Each repeat
retains 141 actual CLI subprocess results and three in-process results with
argv, exit, stdout and stderr, including 19 material negative/recovery outputs.
Expected exits are 128 successes, 15 refusals/failures and one interruption
(`130`). The public derivatives retain all recorded outputs. Independent
inspection verified the actual wrong-firmware error, both pre-save failures
with zero SAVE attempts, and read-only recovery. These observations add evidence
to existing cases rather than increasing the distinct test count.

Seven new Rust loaded-identity tests, eight existing physical-save regressions
and the routed LOAD/SAVE/session checks passed. Formatting, workspace Clippy
with warnings denied and the release workspace build passed. Six genuine
current-binary replays passed 40 retained SESSION exchanges and 28 direct or
combined Unit XML comparisons. The contract inventory, physical applicability
receipt and packaged parity register were generated from those current inputs;
their checks are current. No full local suite ran. Published-revision CI is a
separate check.

## Remaining gates

The result retains `loaded_pci_generation_binding_verified=false`: the client
wire document does not independently expose the captured server epoch.
Internal Rust generation guards are separately tested. Catalogue is checked
against the saved database; physical serial, display/button behavior and
power-cycle persistence remain unverified. Project disk persistence is checked
by the complete acceptance journey, not by the physical-delivery command alone.

This does not establish complete original Toolkit GUI lifecycle, every unit
profile or programming method combination, live bridges, broad device coverage,
vendor repository/archive interoperability or real-device persistence/recovery.
The broad ledger remains **18/42 (42.86%)**, the functional denominator remains
incomplete and zero obligations are fully accepted. Full Toolkit and full
C-Gate behavioral parity remain unfinished.
