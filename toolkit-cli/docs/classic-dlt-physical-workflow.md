# Saved classic DLT Indicators to guarded physical PP

The new `cgate physical-pp dlt-indicators` command delivers an existing typed
Indicators plan for exactly KEYML5 firmware `2.1.00`, catalogue `5055DL`. It
uses the existing direct PP backend, one durable attempt journal and one native
`PP SAVE_TO_SOURCE`. It introduces no unit family or firmware admission.

The saved project must contain the plan's **edited result**, while a fresh
physical LOAD must contain the plan's **original baseline**. Both checks bind
all ten named indicator fields and both complete bytes at `0x33`/`0x34`.
Editing the database cannot bypass the physical stale-baseline check. The
ordered controls and changed values are re-derived from the immutable plan.

## Server identity dependency: design confirmed, implementation pending

The Python command is implemented, but its integrated acceptance remains
blocked on implementation of the centrally confirmed cmqttd loaded-session
identity contract and a rebuilt binary. The pre-existing server does not expose
its freshly identified
physical type/firmware in PP INFO. A retained negative test demonstrated an
incorrect successful delivery when physical firmware was `2.1.01` and the
plan required `2.1.00`. That failing evidence remains open.

The confirmed `pp-info-loaded-identity-v1` design puts exactly three
case-sensitive attributes on the physical session's PP INFO root:

```xml
<Parameters UnitType="KEYML5" FirmwareVersion="2.1.00" Source="//TEST/254/p/5">
  <!-- Existing Param elements retain their schema. -->
</Parameters>
```

These must be the immutable IDENTIFY results and canonical Source of that
successful physical LOAD. Python refuses missing, duplicate, malformed,
namespaced, additional or mismatched attributes before the first PP SET.
There is no database or inventory fallback. Older servers fail closed. The
parser matches the confirmed attribute names; implementation compatibility is
not yet verified against a rebuilt binary.

The server design captures canonical Source, observed type/firmware and PCI
generation in an immutable physical LOAD stamp. The stamp commits with PP/raw
memory under the existing PCI commit guard. INFO checks session ownership and
the connected/current generation through response construction. A failed or
replacement LOAD, NEW, DB/FILE LOAD, uncertain SAVE, Source change, reconnect
or session cleanup clears the stamp. No `PciGeneration` XML attribute is added.
These are confirmed design requirements awaiting central implementation and
its conflicting-DB, inventory-change, failed-reload, reconnect, session-name
reuse, unchanged DB INFO and alternate SAVE destination tests.

Identity is checked again after staging, before the journal or SAVE, and after
a distinct fresh physical LOAD before completion. Each check also requires a
connected PCI with the same `pci_generation` as the initial preflight. A
disconnect or generation change stops the workflow. These observed generation
checks do not establish that Rust bound the session itself to a captured
generation; `loaded_pci_generation_binding_verified=false` records that limit.
The server's reconnect/invalidation design is confirmed above; its runtime
evidence remains pending. The generation-binding flag stays false until
separate verified evidence supports that claim.

Catalogue is verified only against the saved project database. The command
does not establish a physical serial identity, display effects or power-cycle
persistence. It does not itself save or reopen the project file;
`project_disk_persistence_verified=false` requires independent project checks.

## Public command sequence for an owned synthetic project

`PORT` below is the ephemeral loopback C-Gate listener of an owned scripted-PCI
cmqttd. `SPECS` contains the test's synthetic specifications. `TEST`, network
254 and unit 5 belong to that closed synthetic project. These commands have
not been authorized against a real unit.

```sh
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  unit --lock-address //TEST/254 --source /db//TEST/254/p/5 export before.json

cbus-toolkit dlt --spec-dir "$SPECS" indicators plan --file before.json \
  --indicator-control page_fallback=yes \
  --indicator-control duration_seconds=5 \
  --indicator-control pressed_level=12 \
  --indicator-control nightlight_keys=yes \
  --indicator-control first_key_throwaway=yes > plan.json

cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  unit --lock-address //TEST/254 --source /db//TEST/254/p/5 \
  dlt-labels --spec-dir "$SPECS" --plan plan.json

cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" project save TEST
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" project close TEST
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" project load TEST
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  unit --lock-address //TEST/254 --source /db//TEST/254/p/5 show

cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  physical-pp dlt-indicators //TEST/254/p/5 --plan plan.json --dry-run
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  physical-pp dlt-indicators //TEST/254/p/5 --plan plan.json \
  --journal journals/attempt.json

cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  physical-pp inspect //TEST/254/p/5 --method direct \
  --parameter TimerDuration --parameter IndicatorPressedLevel \
  --parameter EnableNightlight --parameter DisableTimerFlash \
  --parameter EnablePageFallback --parameter EnableIndicatorPressedLevel \
  --parameter FirstKeyThrowAway --parameter EnableNightlightOnUserKeys \
  --parameter EnableNightlightOnToggleKey --parameter EnableNightlightControl
```

The preview performs reads and temporary session SETs, with no SAVE. Delivery
stages all ten fields, retaining unchanged values, so the journal covers both
complete bytes even if only one byte changes. Native SAVE may STORE the same
shared byte for several schema fields; those are planned ranges within one
SAVE, not retries.

The retained pre-identity demo saved/reopened every database PP, delivered
literal physical bytes `af8e` to `c5be`, preserved all other bytes of the
independent peer's 128-byte memory, and read all ten fields in a separate CLI
process. It is useful journey evidence, but it does not close the outstanding
exact physical firmware admission failure.

## Interruption and read-only recovery

A failure before durable journal creation or before the `save-sent` phase
sends no SAVE. After an uncertain SAVE, keep the journal and failure output.
Do not repeat delivery. If the owned daemon lost its PCI connection, restart
that test daemon before observing the attempt:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  physical-pp recover --journal journals/attempt.json
```

Existing generic recovery reloads and classifies the journaled complete byte
ranges. It sends no SET, SAVE, parameter unlock or NVM operation. A new daemon
may have a different generation counter. Recovery can resolve an observed
partial write; resolution does not mean the typed workflow completed. Recovery
does not prove the typed physical identity, catalogue, serial or power-cycle
persistence. A later typed attempt still must satisfy the original baseline
and exact loaded identity; partial recovery never bypasses those gates.

## Bounded validation and remaining acceptance

[`classic-dlt-physical-workflow-python.json`](../research/fixtures/classic-dlt-physical-workflow-python.json)
records the independent Python checks and the remaining server dependency.
Run the modest owned admission checks with the existing Python environment:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m pytest \
  tests/test_dlt_physical_programming.py tests/test_physical_programming.py \
  tests/test_cli_physical_programming.py tests/test_dlt_indicators.py \
  tests/test_cli_dlt_indicators.py -q -p no:cacheprovider -k 'not native'
```

After the reviewed identity seam is built, the bounded
`test_dlt_physical_programming_interop.py` journey must pass against that real
binary and independent scripted PCI, including the still-open exact type and
firmware refusals. It must again prove save/close/load preservation, unchanged
bits and fields, full physical readback, pre-save interruption, and lost-ACK
restart/read-only recovery. No live hardware or full-suite acceptance is
claimed.
