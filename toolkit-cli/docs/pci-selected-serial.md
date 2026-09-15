# Selected-serial commissioning with independent observations

`SelectedSerialCoordinator` implements the first bounded direct selected-serial
workflow. It sends at most one explicit serial/destination `co` broadcast. It
does not use native MATCHDB, protected address STORE, fallback destinations,
option changes, retries or automatic rollback.

The acceptance profile is the [serial-keyed synthetic fixture](serial-address-fixture.md):
two distinct KEYE1 2.5.00 identities at address 255 and a PC_CNIED 5.5.00 local
PCI. The collector observes serials, not each duplicate node's firmware/type.
**Physical device-family compatibility and firmware power-cycle persistence are
not verified.** A matching receipt is never used as proof of movement.

The caller must exclusively own the numeric-IP PCI endpoint and all commissioning
activity for the entire sequence. Neither a TCP connection nor a process lock
can establish that another PCI, C-Gate instance or commissioning process is
inactive. This operational prerequisite is explicit; the API cannot detect it.

## CLI

For an independently owned fixture endpoint with the documented profile:

```sh
cbus-toolkit serial-address plan 101136.1558 6 \
  --host 127.0.0.1 --port 10001 --local-unit 16 \
  --expected-local-serial 100966.1187 --output new-plan.json

cbus-toolkit serial-address apply new-plan.json --recovery new-recovery.json
cbus-toolkit serial-address verify --recovery new-recovery.json
```

`plan` is read-only and requires a new output file. Its stdout is a
`cbus-selected-serial-plan-export-v1` wrapper with `plan_file`, the validated
`plan`, `address_command_sent: false` and `database_updated: false`. The file
contains the validated plan itself, without that wrapper. Existing output files
and missing parent directories are rejected before network observation.

Planning accepts `--source 255`, all constructor timing/limit options below
using hyphens, and `--checksum`. The overall option is named `--timeout`, and
`--checksum` must match the already configured SRCHK mode. Defaults retain the
native two-second quiet/address windows. The CLI does not configure the PCI.

`apply PLAN --recovery NEW_JOURNAL` and `verify --plan PLAN` or
`verify --recovery JOURNAL` obtain endpoint, local identity and timing settings
from the strictly validated plan. They accept no endpoint/settings overrides.
The two verify inputs are mutually exclusive. Apply repeats the live guards and
requires a new journal; verify performs inventory only and leaves both files
unchanged. Corrupt/ambiguous recovery JSON is rejected before connecting.

Apply and verify print the full result and exit0 only for
`observed_expected_change`; unchanged, unexpected and uncertain outcomes exit1.
Thus verifying an unexecuted plan normally reports `observed_unchanged` with
exit1. A forged matching receipt can still exit1, while a real independently
observed move with no receipt can exit0. Interruptions exit130, retaining
`selected_serial_evidence` and the journal path. If that evidence cannot be
exported as finite JSON within16MiB, the CLI preserves the original error and
emits an explicit `evidence_export_complete: false` summary; it does not replay
the request or silently discard the export failure.

The existing `serial-address encode` and `serial-address receipt` commands
remain offline byte operations and never connect to an endpoint.

## Python API

```python
from cbus_toolkit.pci_selected_serial import (
    SelectedSerialCoordinator, SelectedSerialPlan,
)

coordinator = SelectedSerialCoordinator(
    "127.0.0.1", 10001, local_unit=16,
    expected_local_serial="100966.1187",
)
plan = coordinator.plan("101136.1558", 6, source=255)  # read-only
reviewable = plan.as_dict()

# After review, while retaining exclusive commissioning ownership:
result = coordinator.apply(plan, recovery_path="new-recovery.json")
print(result.outcome, result.as_dict())

# Explicit recovery is read-only, including after an interruption or failure:
recovered = SelectedSerialCoordinator.load_recovery("new-recovery.json")
observation = coordinator.verify(recovered)
```

`SelectedSerialPlan.from_dict(document)` and `.load(path)` validate a saved plan.
The coordinator must use the plan's exact endpoint, local identity and settings.
It can apply once; `verify` never constructs the address transport and can be
called independently on a fresh coordinator. A plan file does not authorize
replaying an uncertain operation.

Constructor options are `overall_timeout=600`, `observation_timeout=10`,
`confirmation_timeout=2`, `mmi_response_timeout=5.5`, `quiet_period=2`,
`options_response_timeout=2`, `address_response_timeout=2`, `max_mmi_frames=7`,
`max_serial_frames=7`, `max_unrelated=64`, `max_bytes=65536` and
`command_checksum=False`. Pure constructors validate them before any I/O.
Shorter explicit windows in synthetic tests are recorded as such; they do not
replace the original wired two-second address response default.

The overall deadline bounds the admitted transaction **after** pure input/plan
validation and process-lock acquisition. It includes inventory, fresh local
checks, journal operations, send and verification. Every child is given that
same absolute deadline; late child results retain evidence and prevent another
request. File-system calls cannot be interrupted by a socket timeout, so a late
file operation is detected before subsequent network admission. Lock wait and
plan-file parsing are outside the network transaction budget.

## Guards and protocol evidence

Both planning and apply obtain a fresh full direct inventory with independently
covered addresses 0..255 in each MMI bookend. Raw confirmations, block offsets,
checksums, complete coverage, full state-vector equality and local presence are
reparsed. Every present address needs known serial replies. Source 255 must
contain exactly two distinct serials and state 2, including the selected serial.
Other duplicates, a serial appearing at multiple addresses, state 3, partial
coverage, unrelated traffic and missing identities are rejected. Destination
must be empty in the complete MMI/identity map, nonlocal, and in 2..254.

Apply requires the fresh full identity/state map to equal the plan's map. It then
requires a **fresh local IDENTIFY4** with the pinned serial and a **fresh local
RECALL66** exactly equal to byte `05`, close to the address request. The latter
has one successful `g` confirmation followed by exactly one complete bare local
CAL82/parameter66/one-byte reply; wrong count, parameter, checksum, framing,
extra frames and trailing partial input fail. Attribution of this bare reply
depends on the explicitly owned local endpoint, not on an invented wire source.

Independent local literals are:

| Exchange | Ordinary wire |
| --- | --- |
| Read local byte 66 at PCI16 | `\\4610001A4201g\r` |
| Explicit SRCHK read | `\\4610001A42014Dg\r` |
| Byte05 response | `g.82420537\r\n` |
| Byte07 response (unsupported precondition) | `g.82420735\r\n` |

The exact original `CBusBaseUnit.c`/`cg` path reads before a native Local SAL
05/07 write; `CBus2PCILocalable` uses a cached Boolean and ignores disable/restore
results in Unraveller. That does not prove a hardware necessity or restoration
of arbitrary original bytes. The coordinator's fresh05 requirement is a
conservative scope restriction. It never changes options. Exact source/javap
notes are in ignored `research/runtime/local-sal-audit/`; original `co` request
and weak native receipt semantics are pinned in
[codec evidence](serial-address-codec-evidence.json) and
[selected-serial research](selected-serial-addressing-research.md).

For serial `101136.1558`, target6, the one mutation request is the independently
verified literal `\\05FF000F0018B106160615g\r` (SRCHK adds `ED` before `g`). It
contains no source address: the serial selects a recipient across the network.
The [single-request transport](pci-serial-address-transport.md) captures a whole
bounded window before the receipt is classified. A valid full capture with a
missing, wrong or forged receipt can still be followed by independent inventory.
Transport/close errors, malformed frames, trailing partial input, byte saturation,
deadline failure or interruption stop further network I/O in that call.

## Recovery journal and outcomes

`apply` requires a **new** recovery path. It creates a mode0600 file exclusively,
flushes/fsyncs it and its directory, then records `write_attempted` through a
checked same-directory atomic replacement and another directory fsync **before**
invoking the transport. Failure to durably record the attempt prevents the co.
Existing files are never silently overwritten. Later writes check the previous
content; external growth, symlinks and nonregular files fail. The journal assumes
one exclusive writer; the content comparison is not a cross-process transaction.

Evidence distinguishes `attempt_recorded` (attempt marker prepared),
`attempt_durability_verified` (the writer completed file/directory synchronization)
and `send_attempted` (the transport actually called sendall). A failure after atomic
replacement can leave the new record visible without proven crash durability.
`journal.last_update` records replacement progress, disk comparison and cleanup
errors. A disk record may conservatively retain an earlier knowledge state; for
example, the write-attempt marker is serialized before its own fsync completes.
None of these flags proves bus delivery or movement.
If a child interruption also prevents its evidence serialization,
`transport_invoked: true` and `send_attempted: null` preserve that uncertainty;
the coordinator does not invent a negative send result or a byte count.

After a clean complete capture, the journal is updated before a fresh full
inventory. Verification compares the **entire** independently observed identity
map and MMI state vector with the exact expected map: only the selected serial
moves to the target, and the other serial remains at255. The old address must
remain present in this duplicate case. Unrelated identity/state changes remain
visible in `unexpected_changes`.

`SelectedSerialResult.as_dict()` retains the full plan, fresh before inventory,
local checks, exchange and after inventory, plus separate fields:

* `outcome`: `observed_expected_change`, `observed_unchanged`,
  `observed_unexpected_change` or `uncertain`.
* `receipt_matches_request`, `after_collection_complete` and
  `expected_identity_change` describe different evidence; a receipt cannot set
  the latter flag.
* `atomic_observation: false`, `firmware_persistence_verified: false`,
  `physical_compatibility_verified: false`, `database_updated: false`,
  `automatic_retries: 0` and `automatic_rollback: false` remain explicit.

Exceptions retain `selected_serial_evidence`; the same best evidence is available
as `coordinator.last_evidence`. Original interruption objects survive later
serialization, close, disk-probe or recovery-update failures. Ordinary failures
after a write likewise stop network I/O and keep evidence. An error during
read-only recovery remains uncertain, rather than implying failed preconditions
or a write. Explicit `verify` obtains a new inventory only; it never resends co,
reuses the write transport or changes the journal.

Plan JSON is bounded to4MiB; journal JSON is bounded to16MiB. Imports reject
duplicate keys, nonfinite values, unsupported top-level fields and inconsistent
derived expectations, then reparse complete MMI/serial/options raw evidence.
Files are not authenticated history. Apply always repeats live observations;
recovery only compares a newly observed map with the supplied validated plan.

Matching bookends are non-atomic: a concurrent identity swap, identical physical
serials, delayed traffic and analogue bus collisions cannot be excluded. An
unchanged observation does not guarantee against delayed movement. Fixture
restart persistence is an explicit simulator storage policy, not device EEPROM
or power-cycle evidence. Broader compatibility, occupied displacement, cycles,
wireless, bridge/local relocation and native fallback remain unsupported.

## Acceptance

`tests/test_pci_selected_serial.py` uses an independent literal multi-connection
peer and the serial-keyed fixture. It checks actual topology and separately
reloads persisted fixture nodes for move/reply, move/no-reply, fake success/no-move
and wrong-source receipt cases. Additional tests cover changed late local identity,
occupied targets, state3/cross-address ambiguity, missing MMI ranges, unexpected
extra moves, no replay, durable-marker failures on both sides of replacement,
post-send journal failure, deadlines and interruption preservation. Reader tests
cover fixed windows, exact local literals and framing/count/checksum rejection.

The generated focused report is
[selected-serial-coordinator-acceptance.json](selected-serial-coordinator-acceptance.json).
`tests/test_cli_selected_serial.py` also exercises actual subprocess parsing,
the exact request sequence, SRCHK fixture restart recovery, independent missing
and forged receipt outcomes, file/identity/settings preflight, read-only saved
plan/journal verification, interrupted send evidence and bounded error export.
Underlying original native request/literal acceptance is recorded separately in
the codec, transport and fixture evidence documents. No real network or hardware
is opened by this acceptance suite.
