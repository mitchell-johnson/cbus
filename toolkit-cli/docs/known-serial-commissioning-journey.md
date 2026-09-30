# Known-serial commissioning through a saved, reopened project

Issue #32 now has direct and routed software journeys into
an exclusively owned closed C-Gate database project: plan, one address attempt,
fresh independent verification, database reconciliation, SAVE/CLOSE/LOAD,
whole-project readback and a new-process no-op. The receipt uses actual public
Python CLI processes, the built `cmqttd` product and independently modeled
synthetic PCI peers. The routed journey uses bridge 252 from network 254 to
network 252. This is software acceptance, with no hardware or original C-Gate
acceptance. Offline XML/CBZ reconciliation remains supported.

## Public workflow

Use the selected endpoint and known identities, an already loaded project with
all networks closed/idle, a new journal and an existing shared attempt directory.
The destination must be empty, nonlocal and in 2..254. Only duplicate source
address 255 is supported. These examples use the owned synthetic `SYNTH/254`
project; they do not authorize site commissioning.

```sh
cbus-toolkit serial-address plan "$SERIAL" "$DESTINATION" \
  --host "$PCI_HOST" --port "$PCI_PORT" --local-unit "$LOCAL_UNIT" \
  --expected-local-serial "$LOCAL_SERIAL" --output plan.json
cbus-toolkit serial-address apply plan.json \
  --recovery move.json --attempt-store attempts
cbus-toolkit serial-address verify --recovery move.json --output verified.json
cbus-toolkit serial-address reconcile --journal verified.json \
  --cgate "$GATE_HOST:$GATE_PORT" --project-name SYNTH --network 254 \
  --unit-type KEYE1 --firmware 2.5.00
cbus-toolkit serial-address reconcile --journal verified.json \
  --cgate "$GATE_HOST:$GATE_PORT" --project-name SYNTH --network 254 \
  --unit-type KEYE1 --firmware 2.5.00 --apply --exclusive-project
```

For a routed move, first export the complete original loaded project through
`cgate database get-xml //SYNTH --project SYNTH --output original.xml`. Preserve
its exact bytes. Supply `--project original.xml --source-network 254
--target-network 252` to plan, apply and verify. The reconcile command takes
that same immutable snapshot through a separate flag:

```sh
cbus-toolkit serial-address reconcile --journal verified.json \
  --cgate "$GATE_HOST:$GATE_PORT" --project-name SYNTH --network 252 \
  --route-project original.xml --unit-type KEYE1 --firmware 2.5.00 \
  --exclusive-project --apply
```

Routed C-Gate planning also requires `--exclusive-project`: it stages database
PP values and selects projects while checking their topology. It never follows
the private project path recorded in a journal. The caller supplies the original
file explicitly; its raw SHA-256 must match the physical plan throughout
planning, backup, write, saved readback and completed-record validation. Every
loaded project must equal the complete original or the record's exact two-field
candidate. A project with unrelated changes is refused. One to six bridge
routes are admitted; the public end-to-end receipt exercises one bridge and
focused integration tests also exercise six. Native `Project.Address` identity
is accepted when an exported project has no legacy `TagName`; an explicitly
blank identity remains invalid.

If apply is interrupted or uncertain, preserve `move.json` and its marker and
continue with read-only verification. Never repeat the address apply. Verification
with `--output` requires the original apply journal, succeeds only for the exact
expected inventory and exclusively creates a separate artifact. A plan-only
verification or marker-only observation cannot produce reconciliation authority.
The original journal and marker remain byte-for-byte unchanged. Completed apply
journals remain admitted through the existing path.

Successful C-Gate reconciliation itself saves, closes, loads and selects the
project, then compares its complete reopened content before recording `db_done`.
Only database Unit Address and PP `UnitAddress` may change. Unit OIDs, references,
metadata and other PP values remain bound to the original. It stages native `/db`
PP values to obtain the encoding; it performs no physical PP SAVE/STORE.
An additional SAVE is unnecessary. A new process running the same reconcile
command returns `already_reconciled` after checking the whole project.
For an independent operator readback, the typed command is:

```sh
cbus-toolkit cgate --host "$GATE_HOST" --port "$GATE_PORT" \
  database get-xml //SYNTH/254/p/6 --project SYNTH --output reopened-unit.xml
```

There is no public `PROJECT OPEN` leaf. `PROJECT LOAD` alone while already
loaded does not prove persistence; the transaction uses actual CLOSE followed
by LOAD. No NET OPEN is part of this workflow.

## Durable recovery

C-Gate reconciliation uses `cbus-serial-reconcile-record-v2`; offline records
retain v1. The v2 record binds the original project XML, whole-original/candidate
and Unit digests, physical evidence, serial, source/destination paths, OID,
backup identity and backup readback. The candidate is rederived from the original
with exactly two edits on every recovery. Backup comparison normalizes only
its repository Project Address; its contents must otherwise match the original.

The journal records intent and completion separately for baseline save, backup,
database mutation, target save, close, load and saved readback. The transaction
never automatically restores, repeats an uncertain SAVE or resends an address
request. Every network must remain closed with synchronization idle, and the
caller must explicitly own all project editing/reloading with
`--exclusive-project`.

A pending record reopens and classifies the saved image. The loaded image must
already equal the bound original or candidate before it may be closed; unrelated
loaded edits cause refusal. An exact saved candidate completes through readback
without mutation or SAVE. An exact saved original remains pending and returns
an error rather than falsely certifying unsaved memory. After that proof, the
operator may explicitly authorize **one database-only retry**:

```sh
cbus-toolkit serial-address reconcile --journal verified.json \
  --cgate "$GATE_HOST:$GATE_PORT" --project-name SYNTH --network 254 \
  --unit-type KEYE1 --firmware 2.5.00 \
  --apply --exclusive-project --retry-database
```

That flag requires an existing pending C-Gate record and fresh saved-original
readback. It never authorizes a physical address retry. Conflict, changed source,
OID, evidence, candidate, backup or saved project leaves the record unresolved.
A completed C-Gate record whose current whole project differs is also refused.
Legacy C-Gate records without saved-state evidence are refused; they cannot be
upgraded by trusting their current in-memory Unit. Existing offline v1 and Rust
apply-v2 journal admission remain supported. Python routed verification handoff
export also rederives the route from the unchanged snapshot after its fresh
inventory. A completed Rust routed apply-v2 journal is independently admitted;
an uncertain Rust attempt has no exported Python verification handoff.

The separate `cbus-selected-serial-verification-handoff-v1` wraps the existing
read-only result, binding the immutable original journal SHA-256, canonical plan,
attempt ID, marker path and marker SHA-256. Reconciliation reparses the fresh
raw inventory and requires exact expected identities, route/endpoint fields and
all read-only flags. It does not invent a successful apply receipt or assert
firmware persistence from an inventory observation.

## Executed acceptance and limits

The current [loaded-project batch](feature-batch-2026-10-01-loaded-project-commissioning.md)
records fresh source and installed-wheel execution, complete command artifacts
and literal PCI transcripts. Each direct/routed profile sends exactly one
fixture address request. Its intentionally corrupt receipt leaves apply
uncertain; a fresh CLI verification produces a separate handoff while preserving
the original journal and marker. Undoing only Address and PP `UnitAddress`
restores the whole original project, including OID references and other PP.

Ten interruption cases per profile cover database mutation, verification,
target SAVE, CLOSE, LOAD and final record completion. Faults are injected into
the library in the producer process; recovery and no-op checks use fresh public
CLI processes. They are not original firmware or public subprocess fault
injection. Eight record and three direct/four routed handoff tamper cases refuse
without changing the project. Routed acceptance additionally retains stale
snapshot and actual loaded-topology conflict refusals. Focused tests cover
uncertain baseline SAVE/COPY, foreign loaded edits, closed/idle guards and
durable-intent freshness. Owned processes and listeners are checked after cleanup.

[The earlier direct receipt](../research/fixtures/known-serial-journey.json)
is a historical checkpoint. Its source/binary hashes and original evidence
remain unchanged; it does not certify the current routed implementation.

The [published-main baseline](../research/fixtures/known-serial-journey-baseline.json)
pins `7cea3280456ab9512ce4609a73662ca5e9e83eaf` and retains the previously
reproduced false unsaved completion and fresh-process `404 Project not selected`.
Those software seams are closed by this change. Typed creation of a new cmqttd
network still fails at NET LOAD DB with `408 Network definitions file not found`;
the demo seeds its existing closed project through public raw DBCREATENET and
DBSETXML. It does not claim that new-network setup is finished.

Sources and retained originals:
[addressing.md](addressing.md) identifies `TCBusUnitCGateAgent.DoReAddress`,
`TfrmUnitsNode.ReaddressDBUnit`, native Address/PP encoding and OID preservation.
[Native lifecycle evidence](native-cgate-dbsetxml-lifecycle.md) distinguishes
unsaved DBSETXML readback from SAVE/CLOSE/LOAD. The retained
`rust/testdata/fixtures/native_cgate_project_copy_delete.json` pins original
COPY completion, required LOAD, preserved identities and restart behavior.
Existing `NetworkAddressing` supplies the closed/idle runtime guard.
The legacy `DatabaseAddressing.apply` automatic rollback path is not reused for
this transaction because an uncertain save must not trigger a restore/save.

Original C-Gate execution requires explicitly selected Java 11/keytool, lsof,
matching unit specifications and the pinned C-Gate 3.4 build 2001 JAR SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`.
Those vendor/runtime selections are unconfigured here. Native normalization,
backend durability and hardware behavior remain unverified. No home address
change, physical PP programming, power-cycle acceptance, native process, full
suite or broad build was performed. No personal endpoints or serials are in the
receipt; existing synthetic serials and owned loopback endpoints are used.

Reproduce from `toolkit-cli` with Python 3.13+ and an explicitly built product:

```sh
PYTHONPATH=src:tests:. PYTHONDONTWRITEBYTECODE=1 \
python -m research.known_serial_commissioning_journey \
  --python /explicit/python3.13 \
  --cmqttd-bin /explicit/built/cmqttd \
  --profile both --output-dir /new/owned/evidence-directory
```

Run the producer with the same interpreter/package environment as `--python`.
For installed-wheel acceptance, remove `src` from `PYTHONPATH`, retain the
`toolkit-cli` research/test path and add `--wheel /actual/installed.whl`.
The producer checks all executed package bytes against current source and
the wheel, then checks source/tests/Rust/binary hashes again after execution.

The runner requires a new report path and exits nonzero on a failed journey.
A passing diagnostic is not substituted for a finished save/reopen workflow.
