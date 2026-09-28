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
same Unit OID and address into one project. For the Unit-containing shapes,
ambiguous OID-based mutations
(`DBSET`, `DBSETSAFE`, `DBSETXML`, `DBDELETE`, `DBCOPYSAFE`) return `409` and
leave both objects unchanged; the owned capture establishes OID read
selection, not those mutation semantics. Path-based Unit replacement and
deletion retain the other Unit and any same-OID Application. A project copy
retains both identities independently of later source-project deletion.
Native file format and physical effects remain outside this capture.
