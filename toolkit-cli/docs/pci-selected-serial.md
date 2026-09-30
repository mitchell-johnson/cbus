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
activity for the entire sequence. Apply takes a nonblocking host-local advisory
lease keyed by the canonical numeric IP and port before its fresh inventory,
journal or address request. A second cooperating Toolkit process on the same
host and endpoint fails before PCI I/O and can try again after the first exits.
The OS releases the lease even after a process crash; the durable journal still
requires read-only recovery and never authorizes replay. Plan stays read-only
and takes no lease. Verify observes through the same commissioning lanes an
apply would move, so it holds the same lease: a contended observation refuses
before PCI I/O (outcome uncertain) instead of classifying a bus another process
may be moving.

The lease is a lock file in a private user directory under `/tmp` on POSIX
systems, independent of `TMPDIR`; Windows uses the user's configured temporary
directory. It cannot exclude a separate user, another computer, cmqttd, C-Gate
or any controller that does not acquire the same lease. Neither a TCP connection
nor this process lock establishes exclusive bus ownership. The caller must still
control all commissioning activity outside cooperating Toolkit processes.

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
unchanged. Apply also accepts `--attempt-store DIR` to share its attempt marker
across journal directories (see below), and `verify --recovery` accepts an
attempt marker in place of a journal. Corrupt/ambiguous recovery JSON is rejected before connecting.

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
validation and process-lock and endpoint-lease acquisition. It includes inventory, fresh local
checks, journal operations, send and verification. Every child is given that
same absolute deadline; late child results retain evidence and prevent another
request. File-system calls cannot be interrupted by a socket timeout, so a late
file operation is detected before subsequent network admission. Lock admission and
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

## Routed plans through one to six bridges

A `cbus-selected-serial-plan-v1` document may carry two optional fields. Both
are absent from a direct plan, so direct canonical bytes, attempt IDs and marker
file names are unchanged. Python `SelectedSerialPlan.from_dict` and Rust
`cbus_transport::plan` apply the same rules and reason codes:

| Rule | Reason |
| --- | --- |
| `route` is a JSON array of 1 to 6 distinct integers in 1..254: the bridge addresses in outgoing order. An empty array, a seventh bridge, a repeated bridge (a cycle), 0 (the direct/programming route marker), 255 (broadcast), a Boolean, float, string or `null` are rejected. | `invalid_route` |
| A route requires `project_sha256`: the 64-character lowercase SHA-256 of the saved XML/CBZ project whose topology produced it, as in [`commissioning_route`](../src/cbus_toolkit/commissioning_route.py). `project_sha256` without a route is rejected, so each direct intent has only one fingerprint. | `route_binding` |
| The first bridge is on the local network, where the local PCI already owns `local_unit`, so `route[0] == local_unit` is contradictory. Later hops are on other networks and may reuse that number. | `route_proof` |
| Any other field is still rejected. | `plan_fields` |

When a route is present, the canonical fingerprint and attempt marker cover
both fields.

**Evidence.** A routed plan's `before` inventory is a capture of the *far*
network, and every capture in it is bound to the route:

| Exchange | Routed wire (bridges `FD`, `FC`; PCI `10`) |
| --- | --- |
| Installation MMI | `\\03FD12FCFFFAFF00g\r` (point-to-point-to-multipoint, native `NET PINGU` form) |
| MMI block | `86 FD 10 02 FC <unit> E0+len 00 FF <start> <states>` + checksum |
| IDENTIFY4 at unit `FF` | `\\46FD12FCFF2104g\r` |
| Serial reply | `86 FD 10 02 FC FF 8D 04 <12 bytes>` + checksum |
| Selected-serial `co` for `101136.1558` to `06` | `\\03FD12FCFF0F0018B106160615g\r`: `03`, nearest bridge, 9 x count, later bridges, `FF 0F`, then the direct CAL body |
| Receipt from new address `06` | `86 FD 10 02 FC 06 87 00 <serial> <tail>` + checksum |

A reply counts only on the exact Reply Network: outer source the nearest
bridge, destination the local PCI, count equal to the bridge count, and entries
repeating the later bridges then the queried (or new) unit. MMI blocks record
their replying unit but do not require one. Direct blocks, other routes, bare
replies and other destinations are unrelated traffic, so an observation that
contains them cannot be plan or classification evidence. Each routed inventory,
MMI and serial observation records `route`; a direct capture under a routed
plan, or a routed capture under a direct plan, is rejected. The local PCI is
not on the far network, so routed MMI has no local-presence anchor, the far
network may reuse the local unit number, and the destination may equal it.
`local_identity` and `local_options` remain direct captures of the attached PCI.

**Binding.** `route_from_project(project, source_network=, target_network=)`
derives the route and hash with the same bounded snapshot read and topology
planner as typed routed WRITE/RECALL/IDENTIFY. `apply` and `verify` of a
routed plan require `project`, `source_network` and `target_network`; before
any lease, attempt marker, journal, connection or PCI byte they re-read the
project, require its SHA-256 to equal `project_sha256` and require the
re-derived route to equal `route`. A missing binding, changed or unparsable
project, or a network absent from the topology refuses with `route_binding`;
a different derived route refuses with `wrong_route`. A direct plan refuses
any binding. Apply rechecks the project hash immediately before reserving the
attempt marker; a replaced project stops with `preconditions_failed` before
any marker or send. Evidence records `route_binding` (path, hash, networks,
route, `topology_fresh_at_handoff`, `physical_bridge_acceptance_verified:
false`).

**Execution.** Apply keeps every direct guard: the lease, a fresh routed
inventory equal to the plan's, fresh direct local identity/options, the
shared attempt marker, the durable journal before the one routed `co`, and a
fresh routed after-inventory that alone decides the outcome. A lost,
duplicate, reordered or wrong-route receipt leaves `receipt_matches_request:
false` and cannot set the outcome. A disconnect or incomplete capture during
the exchange is `uncertain`, stops network I/O and is recovered only by
read-only `verify`; the marker refuses a repeat. Lost, duplicate or
reordered MMI blocks, missing serial replies and foreign Reply Network
traffic in the after-inventory also leave the outcome `uncertain`.

```sh
cbus-toolkit serial-address plan 101136.1558 6 --host 127.0.0.1 --port 10001 \
  --local-unit 16 --expected-local-serial 100966.1187 --output routed-plan.json \
  --project house.xml --source-network 254 --target-network 252
cbus-toolkit serial-address apply routed-plan.json --recovery routed-recovery.json \
  --project house.xml --source-network 254 --target-network 252
cbus-toolkit serial-address verify --recovery routed-recovery.json \
  --project house.xml --source-network 254 --target-network 252
```

Python `serial-address reconcile --journal routed-recovery.json --project house.xml`
now plans the target-network database move; add `--apply` to back up, move,
save and verify the offline XML/CBZ file. No new flags are required.
`--network` is optional and must match the recorded target when supplied.
It admits only a completed Python apply journal with the shared attempt marker,
reparsed routed before/after/raw receipt evidence, direct local PCI checks and
an exact fresh route binding. Explicit database type/firmware pins do not prove
physical compatibility. It binds the first run to the original raw project
SHA-256 and restart to the retained original backup and recomputed candidate;
keep the backup and exclusively own the file. Routed C-Gate reconciliation is
refused before connection. Completed Rust routed `cbus-selected-serial-apply-v2`
journals also qualify through an independent Python frame validator, as described
below. Legacy Rust v1 journals remain unsupported offline. Direct journals still
refuse bridge projects. See [the reconciliation contract](physical-addressing.md#reconciling-a-selected-serial-move-with-the-database).

Rust `cbus-tools serial-verify`/`serial-apply`
now execute routed plans with the same explicit `--project`, `--source-network`
and `--target-network` binding. They recompute the route from the exact saved
project digest before acquiring the endpoint lease, and recheck freshness
before durable intent and send. The library's `apply_plan_bound` and
`verify_plan_bound` require an independently validated `RouteBinding`; legacy
unbound `apply_plan`/`verify_plan` remain direct-only and refuse a routed plan
before I/O. See [the Rust routed execution contract](../../docs/rust-selected-serial-routed.md)
for its admission limits, deadlines and evidence boundary.

Rust routed apply-v2 retains `cbus-rust-selected-serial-reconciliation-v1`
evidence: complete before/after inventories, fresh direct PCI identity/options,
and the one-shot exchange. Each `cbus-selected-serial-frame-capture-v1` retains
the actual request/confirmation, ordered reader-original `raw_frames_hex` and
separate `parser_frames_hex`, ignored traffic, completion and termination.
Parser copies only normalize trailing CR/LF to CRLF or add an outer checksum
to a validated checksum-off frame; they preserve payload and route bytes.
`frame_capture_scope: commissioning_frames` and `raw_connection_capture: false`
explicitly exclude a full connection capture.

`cbus_toolkit.rust_serial_reconcile` independently reconstructs these observations
with Python protocol parsers and checks the raw/parser relationship, requests,
exact Reply Network, all 256 MMI states, every present-address serial probe,
direct PCI identity and option 66 byte `05`. It requires the before map to equal
the plan and the after map to equal `expected_after`, and reparses the exchange
to verify its receipt summary. Only a completed, durable, single-send
`after_observed` journal with `observed_expected_change` qualifies. Ignored
traffic, missing/partial proof, uncertain attempts, unknown versions/fields or
inconsistent summaries refuse. The existing canonical-plan marker must still
bind the same plan, journal path, fingerprint and scope; the journal's absolute
recorded location must match its current path. These are internal consistency
and provenance checks, not authentication or physical acceptance. Direct Rust
v1 behavior is unchanged, and `serial-verify` output or a marker alone cannot
authorize offline reconciliation.

**Evidence boundary.** `tests/test_pci_selected_serial_routed.py` drives the
coordinator and CLI against independent scripted peers that build every
Reply Network frame from literal bytes: one-, two- and six-bridge plan, apply,
journal recovery and verify; binding, wrong-route and stale-project refusals
with no I/O; lost, entirely lost, duplicate, reordered, wrong-route and direct
receipts; a reconnect mid-receipt followed by read-only verification and a
marker-refused repeat; and lost, duplicate and reordered MMI blocks, a missing
serial reply and a foreign-route serial reply in the after-inventory. The
shared vectors in `rust/testdata/vectors/selected_serial_plan.jsonl` pin
accepted one-bridge (bare and checksummed), six-bridge and reused-local-number
routed plans with attempt IDs, routed/direct evidence swaps and foreign MMI
and serial Reply Networks, and are checked by both implementations. The
routed wire forms mirror cmqttd's routed MMI/IDENTIFY/selected-serial
transport and the `sa-enc-routed-*` encoder vectors; they are not original
Toolkit/C-Gate routed-commissioning captures. The Rust simulator's routed
fixture serves only WRITE/RECALL, so it is not used here. No native C-Gate
routed selected-serial result, live bridge delivery, device persistence or
physical acceptance exists for this workflow.

**Native feasibility boundary.** The existing direct-only `UnravelBusFixture`
rejects routed commands. The retained [native one-bridge probe](../research/experiments/2026-09-26/cgate-bridged-topology-native-acceptance.json)
reached outbound MMI but did not establish initialization or readback. Further work needs a research-only
bridge identity/MMI initialization model and strict success assertions; a wrapper
alone cannot establish native routed UNRAVEL acceptance. A pinned standalone JAR does not satisfy `LocalCGate`: an accepted Java 11/keytool
pair and the original application support tree are also required. No LocalCGate
process was launched for this reconciliation slice. These findings do not
establish a successful native routed move or hardware effect.

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

A second durable guard is a canonical-plan attempt marker
(`.cbus-selected-serial-attempt-sha256-<hex>.json`, mode0600, fsynced) shared
by the Python coordinator and the Rust `serial-apply`. The filename carries
SHA-256 over the Rust fingerprint encoding of the validated plan (sorted keys,
integral floats as integers, numeric IP hosts normalized), which the Python
coordinator reproduces byte for byte; both suites pin the same encoder golden
vector and the same marker filename for the committed vector plan. The marker
lives in the resolved journal directory, or with `--attempt-store DIR` (Python
`serial-address apply` and Rust `serial-apply` alike; `attempt_store=` in the
Python API) in one existing shared directory, so repeats contend across journal
directories. The record names its scope, and a missing store refuses before
any I/O. An existing marker, from either
implementation, refuses apply before any PCI I/O or journal creation. Otherwise
the marker is reserved after the fresh preconditions and before the journal and
the one-shot request. Like the journal, its envelope conservatively records
`send_may_have_occurred: true`. It embeds the validated plan, so
`verify --recovery MARKER` (or Rust `serial-verify --journal`) resumes read-only
recovery from a marker alone. Recovery rejects an attempt ID that does not
match the embedded plan. Apply evidence names the marker in `attempt_identity`.
Deleting a stale marker (operator action, never automatic) is the only replay
path. The marker deduplicates one plan file, not a bus state: plans embed live
observations, so independently generated plans never share a fingerprint, and
the endpoint lease remains the plan-agnostic cross-implementation guard.

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

The Rust `cbus-transport` crate contains three interoperability primitives for
this workflow. `plan::validate_plan_document` validates the same version-one
plan envelope, raw captures, derived expectations, strict UTF-8/duplicate-key
rules and size/depth limits without performing I/O. `journal::RecoveryJournal`
provides exclusive creation, checked atomic replacement, bounded guarded reads
and durable-write evidence using the Python journal's canonical JSON form.
Atomic replacement and no-follow race protection are currently verified on
macOS and Linux; other hosts do not have the same `O_NOFOLLOW` guarantee.
`verify::verify_plan` adds the read-only classification phase over an already
reset, exclusively owned shared `PciClient`. It validates the original plan
bytes before I/O, collects a duplicate-preserving serial-only identity snapshot
between complete MMI bookends, rejects partial, drifting, state-3,
missing-local and cross-address-conflict observations, then reports expected,
unchanged, unexpected or uncertain state. It constructs no selected-serial
address request, writes no journal and never replays the whole observation. The
shared client may retry confirmed read packets while the observation is active;
caller bounds replace the plan timing and are reported explicitly. Both local
commissioning lanes remain held for the snapshot, while ordinary SAL, raw
sends and external bus traffic remain outside that guard. Cancelled writes that
have not started are discarded and release their confirmation allocations.
Started writes and retransmits cannot be retracted; their confirmation codes
remain reserved through the bounded late-ack window. After a deadline or
external cancellation, the caller must close the old transport and reconnect
before any further I/O. Focused integration tests cover the three classifications, strict
raw-plan admission, lane exclusion, deadline cleanup, and incomplete or
inconsistent observations; lower-level unit tests cover the flow-queue and
confirmation-allocation cancellation paths.

The Rust `cbus-tools serial-apply` and `serial-verify` commands now take the
same host-local advisory endpoint lease as the Python coordinator; both sides
hold it for verify as well as apply, since observation lanes contend the same
way. A competing
cooperating process on that host is refused before its PCI connection or
journal creation, and a crash releases the OS lock. The durable attempt marker
still controls no-replay recovery; the lease does not exclude `cmqttd`, remote
hosts, or controllers that do not cooperate.

Rust `serial-verify` and `serial-apply` run the whole session in the plan's
`command_checksum` mode, as the Python coordinator does: a checksum-off plan
sends bare install-MMI, IDENTIFY and local-options recall frames (and the
already plan-encoded one-shot request) instead of the checksummed frames a
checksum-off peer rejects. Peers still emit checksummed MMI blocks and CAL
replies into a checksum-off session, and those parse in either mode; a
checksummed session never reinterprets a frame failing its checksum as bare.
Both commands also bind the plan's local unit as the reply-correlation hint
before any I/O, so sourceless local IDENTIFY replies correlate. A plan file
written by either implementation therefore verifies and applies with the other.

The plan and journal components do not authorize a bus mutation. Direct Rust
library verification leaves endpoint/local-serial enforcement to the caller,
who supplies and exclusively owns the connected client; the CLI checks its
endpoint and enforces the plan's command-checksum mode. Bound routed
verification independently checks the local PCI identity and collects the
commissioning-frame inventory used by apply-v2. This proof does not authenticate
history or prove movement cause, firmware persistence, physical compatibility
or an atomic observation, and it does not replace apply/recovery.
The retained Rust flags `raw_transport_evidence_verified: false` and library
`endpoint_binding_verified: false` reflect these limits; the CLI's separate
endpoint check does not turn frame evidence into authenticated history.

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
`tests/test_commissioning_lease.py` verifies interprocess refusal, independent
endpoint admission, release after normal and abrupt process exit, reentry refusal
and POSIX symlink rejection. Coordinator and actual CLI subprocess tests verify
that lease contention opens no PCI socket, creates no journal and does not
consume the one-shot apply. Cross-implementation tests pin the shared attempt
marker (encoder golden vector and vector-plan filename on both sides), refuse
repeats across journals and shared stores before any request, recover from a
marker alone, and apply the committed Rust vector plan live under the Python
coordinator against the fixture (`observed_expected_change`). The Rust CLI suite
verifies and applies with bare and checksummed session frames; live against
the fixture, a Python-generated plan verifies and applies through the Rust CLI
in both checksum modes, and the Rust-reserved marker then refuses a Python
apply of the same plan while resuming Python read-only verification.

`tests/test_rust_serial_reconcile.py` uses actual Rust CLI journals from an
independent literal fake PCI: one-bridge XML with all routed responses
checksum-off and six-bridge CBZ with checksums on. It validates the original
producer journal and genuine marker before any fixture path relocation, then
tests offline preservation, dry-run/apply, restart without another save and
strict frame, summary and marker refusals. Set `CBUS_TOOLS_BIN` to the built
CLI to enable these tests. This is software interoperability evidence, not
native routed commissioning or hardware acceptance.

The generated focused report is
[selected-serial-coordinator-acceptance.json](selected-serial-coordinator-acceptance.json).
`tests/test_cli_selected_serial.py` also exercises actual subprocess parsing,
the exact request sequence, SRCHK fixture restart recovery, independent missing
and forged receipt outcomes, file/identity/settings preflight, read-only saved
plan/journal verification, interrupted send evidence and bounded error export.
Underlying original native request/literal acceptance is recorded separately in
the codec, transport and fixture evidence documents. No real network or hardware
is opened by this acceptance suite.
