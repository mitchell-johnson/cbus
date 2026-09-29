# Project-resolved and explicit routed WRITE

`RoutedWriteClient` sends one direct `WriteCAL` and never retries it. The CLI
offers two admission modes. Typed mode resolves the bridge route and the
independent return path from one exact legacy XML/CBZ project snapshot. Raw
mode retains caller-supplied bridge and reply bytes. Both modes require a
caller-supplied ACK tag, one positive PCI confirmation, and one addressed
`AcknowledgeCAL` whose complete return path, parameter and tag match.

The same saved-project route planner serves typed
[RECALL](pci-routed-recall.md) and [IDENTIFY](pci-routed-identify.md). Those
read commands derive a Reply Network path without inventing an ACK tag.

Use typed mode when project data is authoritative:

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 --local-unit 16 routed-write \
  4 7 AABB --expected-ack-tag 0x55 \
  --project-file house.cbz --project-name GRENACHE \
  --source-network 254 --target-network 252
```

The project must contain the selected target unit and an unambiguous connected
route. A Bridge network declares its parent as
`PARENT/p/INTERFACE_UNIT`. In the retained C-Gate convention the emitted route
byte is the far-side network address, and the source side must contain a
`BRIDGE2N` unit at that conventional address. The child `INTERFACE_UNIT` must
name that same far-side network address; a contradictory saved link is refused.
CNI and Serial are the admitted
root interfaces. Cycles, disconnected roots, malformed parent references,
duplicate addresses, absent or non-`BRIDGE2N` transitions, unsupported roots,
and routes deeper than six bridges fail before socket I/O.

The selected source itself must be CNI or Serial. A Bridge source is refused,
so the direct PCI workflow never invents a child-to-parent or sibling starting
attachment from saved topology.

The result includes `route_plan`, with the source and target networks, target
unit and type, outbound bridge bytes, independent ACK path, and SHA-256 of the
complete project file. `--project-sha256` can pin that digest. The CLI hashes
one regular file of at most 128 MiB before parsing, detects a replacement during planning, and rechecks
the exact bytes immediately before the one-shot transport handoff. A mismatch
is a stale-topology refusal and sends nothing. The hash binds the file; it does
not prove that the saved topology matches currently connected hardware.

Raw mode remains available for evidence and endpoints whose route is already
known:

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 --timeout 5 routed-write \
  4 7 AABB --bridge 20 --bridge 21 \
  --expected-source 20 --expected-destination 16 \
  --expected-route 21 --expected-route 4 --expected-ack-tag 0x55
```

In raw mode the unit, parameter, data, bridge values, expected path and
expected ACK tag are literal bytes. Data is zero through 30 bytes. At most six
outgoing and six incoming route entries are accepted. Neither mode infers a
programming method or reads a unit specification.

Only numeric IPv4 or IPv6 endpoints are accepted, so the transaction performs
no DNS lookup. The client revalidates mutable settings before opening the
socket, sends one command, and never reconnects or retries. One monotonic
deadline covers connect, send and receive. A timeout, disconnect, rejection,
malformed response, interrupt or cleanup failure after send is retained as an
uncertain write outcome. Recovery is read-only and belongs to the calling
workflow.

The stream accepts explicit two-byte confirmations, CR-terminated ASCII hex
frames and idle CR/LF. Incoming frames use the strict addressed-route decoder:
headers `06` or `86`, an exact route count from zero through six, one supported
CAL and a mandatory checksum. Unmatched valid frames and confirmations remain
ordered evidence. Duplicate matching confirmations or ACKs, rejected
confirmations, malformed input and incomplete trailing data fail the operation.

A successful receipt proves the resolved or declared wire match. It sets
`physical_delivery_verified`, `parameter_commit_verified` and
`nonvolatile_persistence_verified` to false. A device-specific programming
workflow must add its own schema, protection, readback and persistence rules.

## Evidence

The existing frozen original route matrix includes direct and programming
`WriteCAL` forms at zero, small and 30-byte payload sizes, route depths zero,
one and six, checksum calculation and route overflow. The independent incoming
matrix includes exact ACK decoding across 1,142 constructor/checksum cases.
Those fixtures establish the byte transforms, not a live mutation.

The raw transport tests use independent IPv4/IPv6 loopback peers,
both confirmation/ACK orders, every split point, every parameter and ACK tag
byte, zero and 30-byte payloads, route depths zero through six, exact path and
tag rejection, resource bounds, interruption evidence, CLI JSON and the
one-send/no-retry rule. The typed planner adds direct, two-hop and six-hop
routes plus ambiguous, cyclic, disconnected, over-depth, malformed,
unsupported, missing-target and stale-snapshot refusals. CLI peers pin literal
typed outbound and return bytes and preserve the route plan on an uncertain
post-send result. The expected multi-hop Reply Network layout is also retained
by the one- and six-bridge vectors in
[`native_cgate_routed_pp_methods.json`](../../rust/testdata/fixtures/native_cgate_routed_pp_methods.json).
See
[`pci-routed-write-acceptance.json`](../research/fixtures/pci-routed-write-acceptance.json).
The retained acceptance fixture covers the earlier raw checkpoint. No physical
bridge or device acceptance, physical readback, commit, reboot or power-cycle
persistence is claimed by the typed addition.

## Original ACK correlation matrix

[`NativeRoutedWriteProbe.java`](../research/NativeRoutedWriteProbe.java) drives
the unchanged C-Gate 3.4.0 build 2001 WRITE command class `ct` (the class
`CBusUnit` uses for parameter STOREs), its `aW.k(int)` route prepend, the `cj`
received-message constructor and the `cr` counter over constructed
network/unit bridge caches. Sender, receiver and network dispatch are never
invoked, and the process runs under a deny-all-network sandbox and Java
security manager. [The sanitized vectors](../research/fixtures/pci-routed-write-original-vectors.json)
retain 150 generated cases (`research/pci_routed_write_original.py`), each with
the observed decision summary and a semantic hash of every original field.
Route depths zero through six each cover nominal, wrong parameter, wrong tag
and wrong unit; depths one through six add wrong first/middle bridge, short
route and a cached-network-identity mismatch.

The original matcher accepts an ACK only when its tag equals the first WRITE
byte after the parameter; `3B` with the same parameter and tag is a negative
acknowledgement. Received routes are resolved through cached bridge objects to
a logical network, which must be the command's network. It does not compare
the destination or validate the checksum, ignores a trailing CAL, admits any
header whose low three bits are `110` and a bare ACK when no route is
involved, tolerates duplicate ACKs/confirmations and, with `n=true`, drops an
ACK that precedes the PCI confirmation.

`tests/test_pci_routed_write_original.py` replays every case through the real
`RoutedWriteClient` with a scripted one-chunk peer and pins the relation per
family. Python agrees on nominal and wrong route/unit/parameter/tag/count,
negative ACK and negative confirmation cases. It is stricter on destination,
checksum, trailing CAL, header, bare ACK, duplicates, unconfirmed and `#`
confirmations. It is deliberately wider in three declared places: it accepts
an ACK before the confirmation, decodes lowercase hex, and correlates the
declared byte path rather than cached network objects (`original_cached_object_correlation_verified`
stays false; the saved-topology planner supplies that path). The native outbound
command string equals the Python wire for every case, and every refusal after
send is an uncertain, unreplayed outcome. The seven nominal ACK frames are
also Rust decode vectors (`fp-native-routed-write-ack-d0..d6` in
`rust/testdata/vectors/decode_from_pci.jsonl`).

The fresh original test uses `CBUS_CGATE_JAVA`, `CBUS_CGATE_JAVAC` and
`CBUS_LOCAL_CGATE_VENDOR` on macOS; `CBUS_PCI_ROUTED_WRITE_REPORT_DIR` may
select an owned report root. This is original matcher evidence, not bridge,
device, commit or persistence evidence.

## Rust simulator composition gate

The Rust protocol decoder now retains all outbound Network-PCI bridge bytes,
including the first bridge, when it receives a client-to-PCI routed CAL frame.
Six exact decode/re-encode vectors cover one through six bridges. The
`cbus-simulator` binary has an opt-in tagged CAL fixture: `--cal-unit 4
--cal-local-unit 16` selects one simulated unit and each repeated
`--cal-bridge ADDRESS` selects the exact source route. `--cal-srchk` enables
checksummed incoming commands. In this fixture mode the
simulator starts each TCP session in smart mode without a power-on greeting or
local echo, accepts a tagged standard WRITE, sends a checksummed Reply Network
ACK and PCI confirmation, and retains the parameter bytes for a later RECALL
on a new connection. Wrong routes receive neither an ACK nor a write side
effect. The normal simulator mode is unchanged.

Run the focused Python-to-Rust gate after building the simulator:

```sh
cd rust && cargo build -p cbus-simulator
cd ../toolkit-cli
CBUS_SIMULATOR_BIN=../rust/target/debug/cbus-simulator \
  PYTHONPATH=src:tests:. .venv/bin/python -m pytest -q \
  tests/test_rust_simulator_routed_cal.py
```

That gate exercises project-bound WRITE and independent RECALL for direct
through six-bridge routes, SRCHK at representative depths, and wrong-route
preservation. Its parameter memory
is process-scoped and synthetic. It does not establish real bridge delivery,
hardware readback, NVM persistence, or the original C-Gate's routing state.
