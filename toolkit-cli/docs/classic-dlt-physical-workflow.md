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

## Identity and generation admission

cmqttd implements `pp-info-loaded-identity-v1`. A successful physical LOAD
commits its observed type, firmware, canonical source and PCI generation with
PP/raw memory under the PCI commit guard. Physical PP INFO exposes exactly
three case-sensitive root attributes:

```xml
<Parameters UnitType="KEYML5" FirmwareVersion="2.1.00" Source="//WFDLT/254/p/4">
  <!-- Existing Param elements retain their schema. -->
</Parameters>
```

Python refuses missing, duplicate, malformed, namespaced, additional or
mismatched attributes before PP SET. There is no database or inventory fallback;
older servers fail closed. The rebuilt server and public CLI have passed the
actual wrong-type and `2.1.01` firmware refusal cases against an independent PCI
peer. The earlier wrong-firmware success remains retained as a historical
failure; it is superseded by the new execution rather than erased.

INFO checks session ownership and the connected captured PCI generation through
response construction. Replacement LOAD, NEW or file LOAD invalidates the old
stamp before validation. A failed replacement preserves staged values but cannot
expose their old identity. Successful database/NEW/file transitions retain their
plain INFO behavior. Reconnect and cleanup invalidate physical provenance;
service-issued attempt IDs prevent an old completion from replacing a newer or
recreated session. Physical SAVE invalidates before I/O. Confirmed same-source
SAVE can retain the original LOAD stamp under the same generation guard;
uncertain SAVE cannot. SAVE to another unit never relabels the source's stamp.
Seven focused Rust tests exercise these transitions, including a real two-unit
LOAD A / SAVE B exchange and unchanged fresh A readback.

The CLI checks identity after initial LOAD, after staging before journal/SAVE,
and on a distinct fresh physical LOAD. Each check also requires a connected PCI
with the initial preflight's `pci_generation`. The client result deliberately
keeps `loaded_pci_generation_binding_verified=false`: the INFO wire document
has no `PciGeneration` attribute and does not independently expose the server's
captured epoch. Internal Rust guard tests and the client's generation
observations are separate evidence.

Catalogue is verified only against the saved project database. The command
does not establish a physical serial identity, display effects or power-cycle
persistence. It does not itself save or reopen the project file;
`project_disk_persistence_verified=false` requires independent project checks.

## Public command sequence for an owned synthetic project

`PORT` below is the ephemeral loopback C-Gate listener of an owned scripted-PCI
cmqttd. `SPECS` contains the test's synthetic specifications. `WFDLT`, network
254 and unit 4 belong to that closed synthetic project. These commands have
not been authorized against a real unit.

```sh
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  unit --lock-address //WFDLT/254 --source /db//WFDLT/254/p/4 export before.json

cbus-toolkit dlt --spec-dir "$SPECS" indicators plan --file before.json \
  --indicator-control page_fallback=yes \
  --indicator-control duration_seconds=5 > plan.json

cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  unit --lock-address //WFDLT/254 --source /db//WFDLT/254/p/4 \
  dlt-labels --spec-dir "$SPECS" --plan plan.json

cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" project save WFDLT
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" project close WFDLT
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" project load WFDLT
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  unit --lock-address //WFDLT/254 --source /db//WFDLT/254/p/4 show

cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  physical-pp dlt-indicators //WFDLT/254/p/4 --plan plan.json --dry-run
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  physical-pp dlt-indicators //WFDLT/254/p/4 --plan plan.json \
  --journal journals/attempt.json

cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" \
  physical-pp inspect //WFDLT/254/p/4 --method direct \
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

The issue-36 first-edit journey runs the exact ordered controls above through
20 public CLI commands. It verifies literal `af8a` to `a58e`, every one of the
independent peer's 128 memory bytes, all nonindicator PP fields and complete
project XML before edit, after edit, after reopen and after physical delivery.
Only the two indicator bytes change. An additional unit-5 multi-control journey
retains literal `af8e` to `c5be` as a separate acceptance case.

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

The [Python receipt](../research/fixtures/classic-dlt-physical-workflow-python.json)
retains admission checks and historical failures. The
[delivery report](feature-batch-2026-10-01-dlt-physical-workflow.md) records final
source and isolated-wheel bindings and the exact command, XML, memory, wire,
journal and recovery artifact hashes. The bounded integration selection contains
11 typed DLT cases and three existing generic programming regressions, including
all ten programming methods. No full suite or native/hardware execution is
claimed by this checkpoint.

Run the focused Python selection from `toolkit-cli/`; only the explicitly
configured original C-Gate test is excluded before collection:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m pytest \
  tests/test_dlt_physical_programming.py tests/test_physical_programming.py \
  tests/test_cli_physical_programming.py tests/test_dlt_indicators.py \
  tests/test_cli_dlt_indicators.py -q -p no:cacheprovider \
  --deselect tests/test_cli_dlt_indicators.py::IndicatorCliTests::test_native_owned_database_dryrun_apply_and_save_reload
```

Set `CBUS_CMQTTD_BIN` to the built cmqttd to run
`tests/test_dlt_physical_programming_interop.py` against owned loopback peers.
The scripted PCI checks direct wire correlation while injecting wrong-unit,
wrong-route and stale-parameter replies. Complete original Toolkit workflow
comparison, other profiles/method combinations, real display/button behavior,
live bridge and device coverage, and power-cycle persistence remain open under
their separate acceptance gates. This first fixture does not close the full
issue-36 umbrella or establish 100% Toolkit parity.
