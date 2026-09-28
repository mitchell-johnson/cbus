# Original C-Gate duplicate-OID DBSETXML behavior

The [39-request capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_duplicate_oids.json)
has SHA-256 `9cddffd48c597fa0eb9752411b67d415942cd005275707e9fa7bf9cf381d2e9c`.
It was produced by the [capture script](../research/cgate_dbsetxml_duplicate_oids.py)
(`5eab7b8f4fd70d90d61fe2356dc239415c4a1501bce285e6a0f11c6598ec466a`)
and the [owned-service harness](../research/local_cgate.py)
(`3df3f50db74bc1321b7d8b173927d88f50082df4bc67042b0bb2446e5f99e111`).
The original C-Gate 3.4.0 build 2001 JAR was pinned by SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`
and Java 11 by `94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4`.
The synthetic `XDUP` project ran in a disposable work directory with six
child-owned `127.0.0.1` listeners. Its CNI address was the unresponsive
`127.0.0.1:1`; the Network was never opened. The harness confirmed process
exit and directory removal. No broker, physical C-Bus network or site project
was used.

Tags 204–216 show a complete Network whose Application and Unit share one OID.
`DBSETXML` returned `301 OID=<Network OID>`. Both objects had separate,
schema-ordered path readbacks before and after `PROJECT SAVE`, `CLOSE` and
`LOAD`. `DBGETXML !<shared OID>` and `DBGET !<shared OID>/Address` selected
the Unit at address 20. Reload added the native `DeviceName` and `GroupNumber`
default Unit fields; it did not change either identity or the `UnitAddress` PP.

Tags 217–229 show two Units at addresses 20 and 21 sharing one OID. Their
different `TagName`, `UnitName`, firmware and `UnitAddress` PP values all read
back independently and survived save/reload. The ambiguous OID read selected
the last Unit, address 21. Tags 230–238 replaced only the Unit at path
`//XDUP/254/p/21`, changing its name and firmware; the address-20 Unit was
unchanged and both remained distinct after another save/reload.

The [Rust vectors](../../rust/testdata/vectors/cgate_dbsetxml_duplicate_oids.jsonl)
compare the two submitted Network documents, their `301` receipts, ten exact
native readbacks and the ambiguous OID selection. A service test also checks
that both Unit templates and PP values survive JSON repository restart and
one direct path replacement without PCI traffic. Rust admits these captured
duplicate shapes through address-keyed Unit metadata. A [later owned
capture](native-cgate-dbsetxml-duplicate-applications.md) adds two leaf
Applications sharing one OID. Typed descendant, Interface and Network OID
collisions remain closed with `409`; those shapes have no native evidence or
lossless Rust representation yet.
Project-wide collision checks also prevent two Networks from importing the
same Unit OID and address into one project. Path-based Unit replacement and
deletion retain the other Unit and any same-OID Application. A project copy
retains both identities independently of later source-project deletion.

## OID-targeted mutations of two Units

The [89-request owned capture](../../rust/testdata/fixtures/native_cgate_duplicate_unit_oid_mutations.json)
has SHA-256 `79010f478e9a12cb91762f2385d2c59e219033f923aad125bf52a1a161656686`.
Its [reproducer](../research/cgate_duplicate_unit_oid_mutations.py) is pinned
by `95d71bd2e8b3f0a1da47d7bfd5941f2ef82b81829c61713242fe39bb029e054f`
and uses the same original JAR, Java 11 and owned loopback service harness.
Every case resets a synthetic Network with Units 20 and 21 sharing one OID,
captures direct and OID readback, performs one mutation, then saves, closes,
loads and reselects the project. The CNI address `127.0.0.1:1` is never opened.

Original C-Gate selected the final submitted Unit, address 21, for all five
bare shared-OID targets:
`DBSETSAFE !oid/UnitName`, `DBSET !oid/UnitName`, `DBSETXML !oid`,
`DBCOPYSAFE !oid //XOIDM/254 22 Copied`, and `DBDELETE !oid`.
The two scalar writes returned `200 OK.` and changed only Unit 21. XML
replacement returned `301 OID=<shared OID>` and changed only Unit 21.
Copy returned `301 OID=<new OID>`; Unit 22 inherited Unit 21's `UnitName`
and `PP UnitAddress=21`, while gaining address 22 and `TagName=Copied`.
Delete returned `200 OK.` and removed only Unit 21. Its OID lookup returned
401 despite Unit 20 surviving at its direct path; after `PROJECT LOAD`, the
OID lookup selected Unit 20. The [Rust vectors](../../rust/testdata/vectors/cgate_duplicate_unit_oid_mutations.jsonl)
and source-bound Python test cover all five cases and reload behavior.

The [21-request reversed-order capture](../../rust/testdata/fixtures/native_cgate_duplicate_unit_oid_reverse_order.json)
has SHA-256 `6f8907860cda4c7cda51bbd2707b336741e8792e568f3a3557efd0fef13c68cc`;
its [reproducer](../research/cgate_duplicate_unit_oid_reverse_order.py) is
pinned by `e55d35049a3e5d8913359ecb040afae467085d925da544fe87075409e2723d7d`.
It submits Unit 21 before Unit 20. `DBGETXML !oid` selects Unit 20,
`DBSETSAFE !oid/UnitName Selected` changes only Unit 20, and save/load keeps
that selection. The [reverse-order vector](../../rust/testdata/vectors/cgate_duplicate_unit_oid_reverse_order.jsonl)
prevents accidentally treating this as highest-address selection.

## Three- and four-Unit OID-targeted mutations

The [229-request owned capture](../../rust/testdata/fixtures/native_cgate_duplicate_unit_oid_cardinality.json)
and its [reproducer](../research/cgate_duplicate_unit_oid_cardinality.py)
extend the same five commands to three Units submitted as `20, 21, 22` and
four Units submitted as `23, 21, 20, 22`, all sharing one OID in one Network.
The capture is pinned to C-Gate 3.4.0 build 2001 and Java 11 by the hashes in
the fixture. It used six owned loopback listeners, an unopened synthetic CNI
address and a disposable project; process exit and work-directory removal were
confirmed. No real C-Bus network or broker was involved.

In all ten cases the OID selects Unit 22, the **final submitted** Unit. In the
four-Unit case address 23 is the highest, so address sorting would be wrong.
`DBSETSAFE`, `DBSET`, and `DBSETXML` change only Unit 22; `DBCOPYSAFE` creates
Unit 30 with Unit 22's name and `PP UnitAddress=22`; `DBDELETE` removes only
Unit 22. Immediately after deletion the shared-OID lookup returns 401 even
though the other Units remain accessible by path. After save, close, load and
use, OID lookup selects Unit 21 in the three-Unit case and Unit 20 in the
four-Unit case. The [vectors](../../rust/testdata/vectors/cgate_duplicate_unit_oid_cardinality.jsonl)
and source-bound Python and Rust tests pin the exact command receipts, direct
readbacks and selection lifecycle.

Rust applies final-submission selection to the captured two-, three- and
four-Unit shapes with the same OID in one Network and no same-OID pending
object. Cross-kind, cross-network and five-or-more Unit collision mutations
remain guarded pending separate native evidence.
Native file format and physical effects remain outside these captures.
