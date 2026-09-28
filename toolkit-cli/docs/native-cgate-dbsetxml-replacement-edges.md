# Original C-Gate DBSETXML replacement edges

The [37-request original-service capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_replacement_edges.json)
has SHA-256 `c99483fe80bc4be0e2105b943fd7325a5150067ca130eed2fbf9f7394a55dd82`.
It records every tagged request and response from Schneider C-Gate 3.4.0
build 2001 (`cgate.jar` SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`).
The [capture script](../research/cgate_dbsetxml_replacement_edges.py) and
[owned-service harness](../research/local_cgate.py) are identified by their
SHA-256 values in the fixture and checked by
[`test_native_cgate_dbsetxml_replacement_edges.py`](../tests/test_native_cgate_dbsetxml_replacement_edges.py).

The original JAR ran under a pinned Java 11 binary in a new, disposable
`LocalCGate` work directory. The harness verified six listeners owned by its
direct child, all bound to `127.0.0.1`; it confirmed process exit and work
directory removal. The synthetic `XEDGE` project's Network 254 used the
unresponsive CNI address `127.0.0.1:1`. No `NET OPEN`, PCI, CNI, broker,
physical C-Bus network, or site project was used. The capture tests confirm
the greeting, framing, source hashes and cleanup receipt. This host-local
oracle is distinct from the earlier disposable Windows VM captures.

Tags 104–119 pin the implemented mapper slice. A complete Network with an
Application and Unit returned `301 OID=<network OID>` and schema-ordered XML.
Adding comments and processing instructions to its Network, Interface,
Application and Unit nodes returned `301`; the subsequent Network,
Application and Unit XML was byte-identical to the plain baseline. Unknown
namespaced Network attributes, Interface children, Application attributes and
children, and Network children were also accepted and absent on readback.
Direct Unit replacements with comments/processing instructions behaved the
same way. A namespaced child inside `Description` was discarded while the
present scalar read back empty. A later complete replacement that omitted
`CatalogNumber`, `SerialNumber` and a `UnitAddress` PP removed all three; the
first two fields then returned `401 Object is null` via `DBGET`.

Tags 122–126 show `PROJECT SAVE`, `PROJECT CLOSE` and `PROJECT LOAD` all
returned `200`. The reloaded Network still contained the same Application and
Unit identity, and the omitted optional Unit fields remained absent. Native
project reload also added default `DeviceName` and `GroupNumber` Unit fields;
the Rust regression checks stable identity and omission across this boundary,
not an identical post-load XML string. Tags 127–130 add two direct Unit mapper
observations: an unknown plain `<Foo>` child disappeared, direct text on both
sides of a namespaced `Description` child became `AB`, and a nested-only
`CatalogNumber` became an empty scalar.

The [seven exact-readback vectors](../../rust/testdata/vectors/cgate_dbsetxml_replacement_edges.jsonl)
are replayed by `dbsetxml_replacement_mapper_matches_owned_native_edge_vectors`
against the Rust server with only generated Network and Interface OIDs
substituted. They cover the plain combined graph, comments, processing
instructions, namespaces, direct Unit decoration, omitted optional fields,
and empty nested `CatalogNumber`. The unknown plain `<Foo>` observation is
retained as evidence but remains outside that exact Rust differential.

Tags 131–136 first established a duplicate-OID conflict boundary. The original
accepted an Application and Unit sharing an OID, then accepted two Units at
addresses 20 and 21 sharing an OID; both requests returned `301`, and XML
readback showed both records. The [follow-up owned capture](native-cgate-dbsetxml-duplicate-oids.md)
pins distinct Unit scalar/PP readback, save/reload and path-targeted mutation.
Rust now retains these two shapes with address-keyed Unit metadata; other
duplicate shapes remain closed until their lossless representation and native
semantics are established. A following
replacement missing `UnitName` returned native `446` and left the duplicate
graph unchanged. Other conflicts, all optional Unit fields, comments or
namespaces in every typed family, private Schneider formats and physical
network effects remain outside this capture.
