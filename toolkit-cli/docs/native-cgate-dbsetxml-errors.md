# Original C-Gate DBSETXML error and conflict classes

The [owned error capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_errors.json)
has SHA-256 `bfb8989058c09da65651372f0682486cf3df4bd36683e85d9589a3e29b7d38af`.
It records 46 DBSETXML probes against Schneider C-Gate 3.4.0 build 2001
(`cgate.jar` SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`) under the
pinned Java 11 runtime. The [capture script](../research/cgate_dbsetxml_errors.py)
and [owned-service harness](../research/local_cgate.py) are bound by SHA-256
and checked by
[`test_native_cgate_dbsetxml_errors.py`](../tests/test_native_cgate_dbsetxml_errors.py).
The owned process had six verified loopback listeners, confirmed exit and a
removed work directory. The synthetic `XERR` Network 254 used the unopened CNI
address `127.0.0.1:1`; no PCI, CNI, broker, physical network or site project
was used.

The baseline is a saved and reloaded Network with Application 56 and Unit 20.
Each probe is followed by a complete Network readback. When a probe changed
the Network, the capture read its target, then used `PROJECT CLOSE`/`LOAD` to
restore the saved baseline (see the [lifecycle capture](native-cgate-dbsetxml-lifecycle.md)).

## Native classes

- **446, SAX:** an unclosed root, non-XML text, a mismatched end tag, two
  roots and an empty body return `446 Unable to set XML:
  org.xml.sax.SAXParseException; ...`. Direct text inside `Unit` returns
  `446 ... SAXException: Illegal Text data found as child of: Unit ...`.
- **446, Castor validation:** a repeated `TagName` or `Address`, a missing
  `TagName` or `UnitType`, and a `TagName` longer than 32 characters. A body
  is bound to the target's class whatever its root element is called: a
  Network or Application body at a Unit path fails as a Unit without
  `UnitType`, and an unknown root without `TagName` fails on `TagName`.
- **401 and 440:** a missing Unit or Network target returns
  `401 Bad object or device ID: Element N not found.`. A path naming a
  project that is not loaded returns
  `440 There is no tag database to perform this operation on`.
- **301, accepted:** native accepts many shapes without checking them against
  the path. A Unit or Project body at a Network path replaces the Network,
  which then fails lookup at 254. A Unit body at an Application path turns
  the Application into a copy of the Unit's scalars. Body addresses that
  differ from the path, are non-numeric, out of range or missing are stored
  as submitted. Interface address, type, OID or presence, and the Network
  OID, all change on this closed Network. A Unit nested in an Application is
  dropped. An undeclared namespace prefix, unknown PP names and a PP without
  `Value` are kept or ignored. A malformed or missing Unit OID is replaced by
  a fresh OID.
- **Size:** a 64 KiB body in 1 KiB lines returned `301`. A 1 MiB body sent the
  same way had no reply within 120 seconds on a fresh connection.

The capture did not open the CNI, so it does not show whether native refuses
an Interface change on a live network.

## Rust disposition

The [44 vectors](../../rust/testdata/vectors/cgate_dbsetxml_errors.jsonl)
cover every probe except the two size probes. Each has one disposition:

| Disposition | Count | Rust behaviour |
|---|---:|---|
| `native-exact` | 11 | Same status and reply text: Castor 446s and the 440. |
| `native-status` | 7 | Same status; SAX detail and 401 text are Rust's own. |
| `accepted-both` | 12 | Both return `301`, including address moves, interface changes on a secondary project, unknown PP names, a 32-character TagName and a direct `!OID` Unit target. |
| `rust-refuses-native-accepts` | 14 | Rust refuses with 400 (446 for an undeclared prefix) instead of storing a destructive or unrepresentable shape. |

`dbsetxml_errors.rs` replays every vector against the in-memory server, and
`dbsetxml_error_matrix_refuses_without_mutation_or_pci_io` replays them against
the cmqttd service. Each refused request must leave the Network and Unit
readbacks unchanged, and in cmqttd the persisted repository too. The test then
uses CLOSE/LOAD to restore the baseline, as native did, and sends no PCI
traffic.

The deliberate differences are:

- Rust's 400 refusals keep the database in a state it can represent and
  read back. Native corrupts or replaces the object in those cases.
- On the configured hardware project, cmqttd still returns 408 for a Network
  move or interface rebinding.
- Rust bounds a here-document at 16 MiB and returns a tagged 400 beyond it.
  Native was unresponsive long before that size.
- DTD and entity declarations remain refused with 400.
