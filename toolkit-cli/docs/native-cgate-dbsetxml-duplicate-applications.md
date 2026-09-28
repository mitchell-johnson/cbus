# Original C-Gate same-OID Application behavior

The [39-request capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_duplicate_applications.json)
has SHA-256 `310ce265b6545029769456ebeb552beaf4cf35b793779908a341f648664520fc`.
It was produced by the [capture script](../research/cgate_dbsetxml_duplicate_applications.py)
(`22580ef1eb861b029df4154efa267872ea4864115ee0949ac40f25403f24e2a4`)
and the [owned-service harness](../research/local_cgate.py)
(`3df3f50db74bc1321b7d8b173927d88f50082df4bc67042b0bb2446e5f99e111`).
The original C-Gate 3.4.0 build 2001 JAR was pinned by SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`
and Java 11 by `94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4`.
The synthetic `XAPP` project ran in a disposable work directory with six
child-owned `127.0.0.1` listeners. Its CNI address was the unresponsive
`127.0.0.1:1`; the Network was never opened. The harness confirmed process
exit and directory removal. No broker, physical C-Bus network or site project
was used.

Tag 304 submitted a complete Network with two leaf Applications at addresses
56 and 57 carrying the same OID. Original C-Gate returned `301` with the
Network OID. Tags 305–309 show both Applications in the Network and at their
separate paths. `DBGETXML !<shared OID>` and `DBGET !<shared OID>/Address`
selected address 57. Tags 310–317 show that both path identities and this OID
selection survived `PROJECT SAVE`, `CLOSE` and `LOAD` byte-for-byte.

Tags 318–327 replaced only address 57 through its direct path, then saved and
reloaded again. Address 56 stayed `First`; address 57 became `Changed`.
Tags 328–333 changed `TagName` through the shared OID: the selected address
57 became `ByOID` while address 56 stayed `First`. Tags 334–338 repeated an
OID-targeted `DBSETXML` replacement: address 57 became `ViaXML` and address
56 again remained unchanged.

The [Rust vector](../../rust/testdata/vectors/cgate_dbsetxml_duplicate_applications.jsonl)
and focused server test replay all post-setup native transactions and compare
every direct and OID XML/field readback. A service test also checks both
records through JSON repository restart and later direct replacement without
PCI traffic. Rust keeps the captured pair under separate project/OID/path
keys, selects the higher-address Application for OID reads and the captured
TagName writes, and preserves both on copy, rename and archive restoration.
Its support is intentionally limited to two leaf Applications in ascending
address order in one complete Network. Other repeated Application counts,
reversed submission order, nested same-OID Application descendants, mixed
Application/Unit/typed-container collisions beyond the [earlier captured
shapes](native-cgate-dbsetxml-duplicate-oids.md), and cross-network identity
collisions still need native evidence and/or a broader identity model.
Uncaptured duplicate-Application Address and other field writes, and
`DBDELETE` of a duplicated Application, its descendants or its containing
Network return `409` rather than risking sibling loss. The offline safety
regression checks OID field suffixes, both Application paths, numeric Network
aliases, project selection and Network rename; these deletion and rename
results are mock safeguards, not native observations. Native file format and
physical effects remain outside this capture.
