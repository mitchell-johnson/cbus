# Rust routed selected-serial execution

`cbus-tools serial-apply` and `serial-verify` execute saved
`cbus-selected-serial-plan-v1` plans through one to six bridges. Plan creation
remains in the Python coordinator. This implements the Rust software execution
gap in issue #28; it does not close native routed commissioning or physical
bridge acceptance.

```sh
cbus-tools serial-apply --pci 192.0.2.10:10001 --plan routed-plan.json \
  --project project.xml --source-network 254 --target-network 252 \
  --journal recovery.json --attempt-store /operator/commissioning-attempts
cbus-tools serial-verify --pci 192.0.2.10:10001 --journal recovery.json \
  --project project.xml --source-network 254 --target-network 252
```

The numeric endpoint must equal the plan. The source network must be a CNI or
Serial root. Each conventional Bridge transition must agree with its parent
and `BRIDGE2N` address. The full path and SHA-256 must equal the plan before
the endpoint lease, connection, attempt marker or journal. Direct plans refuse
project/network binding arguments. Library callers use `validate_route_binding`
and the explicit `apply_plan_bound`/`verify_plan_bound` APIs; their unbound
predecessors retain the direct-only refusal.

The project reader bounds files and expanded XML to 128 MiB, refuses nonregular
inputs, DTDs, duplicate or ambiguous structural fields, and caps XML node count.
It admits UTF-8 XML and ordinary stored/deflated CBZ files. ZIP64 directories, multidisk,
encrypted or ambiguous archives are outside this reader's admission scope.
The bound project is re-read before observation, after observation, before
durable intent and immediately before sending. These digest checks are not a
filesystem lock or a live topology discovery.

Routed verification first independently identifies the attached PCI, then
collects exact-route MMI / IDENTIFY4 / MMI bookends from the far network. The
far network need not contain the local PCI address. A remote unit may reuse
that number without becoming the local interface. The raw reply envelope
preserves the nearest bridge, local destination, route count, remaining path,
remote unit, CAL and serial. Wrong-route or contradictory observation frames
cannot establish an inventory. Unrelated application traffic cannot supply
commissioning evidence. The local identity is refreshed again just before the
option-66 check and send intent.

Apply retains exclusive journal creation, durable canonical-plan attempt
markers and the shared endpoint lease. It sends the re-encoded address request
exactly once. A matching receipt requires one positive literal confirmation
followed by one exact-route, exact-destination, exact-serial receipt. Missing,
duplicate, reordered or foreign receipts do not become matching receipts.
Only an independent post-send inventory equal to `expected_after` establishes
`observed_expected_change`; this classification does not prove causation or
persistence. Incomplete input, stream loss or interrupted transactions remain
uncertain and cannot authorize replay.

`--timeout` is a per-observation budget, covering lane acquisition and all
bookends. Routed connection/init and the final local identity/options check each
have a separate budget of the same size. Routed MMI and IDENTIFY each have a ten-second internal deadline;
IDENTIFY additionally requires a two-second quiet window. The routed one-shot
send has a thirty-second absolute bound including lane/init acquisition,
bounded write completion and its full two-second capture. These are phase
budgets, not one whole-apply deadline. Failed or cancelled strict observations
retire the PCI client. Recovery uses a new connection and the same project
binding, reads the embedded plan from the journal or marker, and sends only
read requests. A marker alone permits read-only recovery, never database
reconciliation.

## Routed apply-v2 and offline reconciliation

Routed apply journals use `cbus-selected-serial-apply-v2`; direct Rust apply
retains `cbus-selected-serial-apply-v1`. The plan remains version one, and
`serial-verify` remains a read-only classification command. Its output is not
a completed apply journal. Legacy Rust v1 journals are not accepted for offline
reconciliation.

The routed journal retains `reconciliation_evidence` with format
`cbus-rust-selected-serial-reconciliation-v1` and source
`cbus-transport-routed-selected-serial`. It covers the fresh before inventory,
the final direct local PCI IDENTIFY4 and option-66 checks, the one-shot exchange
and the fresh after inventory. Inventories use
`cbus-selected-serial-inventory-frames-v1`; each request capture uses
`cbus-selected-serial-frame-capture-v1` with source
`cbus-transport-strict-selected-serial`, the actual allocated confirmation,
request bytes, ordered `raw_frames_hex` and `parser_frames_hex`, ignored frames,
completion and termination fields.

Reader-original frames are retained. Parser copies may normalize only trailing
CR/LF to CRLF and add an outer checksum to a frame already validated in the
checksum-off session. They preserve the original payload, Reply Network,
destination, CAL and serial bytes; confirmations are unchanged. A valid
checksummed frame keeps its checksum. This is commissioning-frame evidence:
`frame_capture_scope: commissioning_frames`, `raw_connection_capture: false`.
It does not record every byte on the connection or authenticate the producer.
Original frames must contain uppercase wire hex and one CR, LF or CRLF
terminator, matching the Rust reader rather than a looser hex decoder.

Checksum addition requires the plan's checksum-off mode. A checksum-on journal
cannot omit an original checksum and keep a valid parser copy. Each direct
local IDENTIFY4 capture must contain exactly one reply, while remote captures
retain duplicates and allow at most seven replies. These bounds match the Rust
producer's admission rules before serial deduplication.
The source/schema strings establish a checked internal contract, not a signature.
Rust retains `raw_transport_evidence_verified: false` and the library's
`endpoint_binding_verified: false`; the CLI independently checks the plan
endpoint. Operator-controlled offline files are not trusted attestations.

Python `serial-address reconcile --journal recovery.json --project project.xml`
independently validates this format in `cbus_toolkit.rust_serial_reconcile`;
add `--apply` for the offline database move. XML and CBZ are supported. The
validator re-encodes each request with its recorded confirmation, verifies the
permitted original/parser relationship, and uses Python protocol parsers to
reconstruct complete exact-route MMI bookends and IDENTIFY4 identities. It
requires the before inventory to equal the plan, the direct local PCI identity
to match, option 66 to be exactly `05`, and the after inventory to equal
`expected_after`. It reparses the exchange and checks `receipt_matched`; a clean
completed exchange with a missing or mismatched receipt may still qualify when
the independent after inventory proves the exact expected map.

Admission requires `state: after_observed`, `outcome: observed_expected_change`,
one completed send, durable attempt intent and complete, consistent evidence.
Ignored traffic, missing or partial captures, wrong routes, gaps or reordered
MMI blocks, unknown fields or versions, inconsistent summaries and uncertain
attempts refuse before a database write. The canonical-plan attempt marker must
still exist, with the same plan, fingerprint, journal path and scope. The
journal's absolute recorded path must match its current caller path; moving a
journal alone invalidates this provenance check. Marker binding canonicalizes
only the journal parent and preserves its filename, matching the Rust producer.
Existing parent aliases are admitted; a rebound parent, unrelated marker
journal or scope, and journal/marker filename symlinks refuse. These checks
provide no filesystem lock or atomic protection against concurrent path changes.
They establish internal
consistency, not authenticated history.

Reconciliation uses the caller-supplied offline project and recorded target
network, rechecks the original project hash and route, and shares the existing
backup, candidate verification and restart contract. Keep the marker, original
backup and exclusive project ownership. Routed C-Gate reconciliation remains
refused before connection. See the [database reconciliation contract](../toolkit-cli/docs/physical-addressing.md#reconciling-a-selected-serial-move-with-the-database).

## Evidence and limits

The implementation reuses the committed shared routed serial/MMI/IDENTIFY
encoders and plan vectors. `native_cgate_routed_unravel.json` explicitly pins a
composition of the native direct selected-serial payload and routed PPM/Reply
Network rules. It contains no native routed selected-serial mutation capture.
`NativeRoutedWriteProbe.java` executes original C-Gate WRITE construction and
ACK matching against constructed cache responses; it does not run a sender,
bridge or device. Neither receipt is a new native end-to-end acceptance run.

The focused Rust tests execute strict raw-frame collectors, one-shot capture,
deadline/cancellation handling and the actual CLI against deterministic duplex
or loopback PCI peers. These peers provide scripted before/after inventories;
they establish software control flow and correlation, not independent device
movement. No real CNI, broker, bridge, unit or physical bus is contacted. Native
routed commissioning, live bridge delivery, device compatibility and NVM
persistence remain unverified. The current
[combined Rust receipt](../toolkit-cli/docs/acceptance/2026-10-01-routed-commissioning/rust-focused-acceptance.json)
records formatting, workspace/all-target Clippy, the release workspace build
and 151 distinct focused tests, including MQTT preservation. Full workspace
tests were not run. The separate
[alias regression](../toolkit-cli/docs/acceptance/2026-10-01-routed-commissioning/alias-fix-acceptance.json)
uses the actual current Rust CLI; its counts overlap combined Python acceptance.

`toolkit-cli/tests/test_rust_serial_reconcile.py` optionally runs the actual Rust
CLI against an independent literal fake PCI, once for one-bridge XML with every
routed response checksum-off and once for six-bridge CBZ with checksums on.
It validates the original CLI journal and genuine marker before relocating
fixture paths for isolated tests. The tests cover dry-run/apply, preservation,
restart without another project write, and strict evidence/marker refusals.
These fixtures do not establish movement on a physical network.
The [Rust/Python offline reconciliation receipt](../toolkit-cli/docs/rust-selected-serial-reconcile-evidence.json)
records this slice's focused validation. No native C-Gate or hardware was
launched for this slice.

The [historical source-bound execution receipt](rust-selected-serial-routed-evidence.json)
records hashes and validation for its earlier source revision. It has not been
regenerated for apply-v2 and does not verify current-source hashes or this new
offline validator. It remains a software acceptance receipt, not issue closure.
