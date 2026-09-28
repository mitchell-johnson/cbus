# Original C-Gate Application/Unit shared-OID mutations

The [184-request owned capture](../../rust/testdata/fixtures/native_cgate_cross_kind_oid_mutations.json)
has SHA-256 `395311a39661f374b9d36cc9d71e5bd14ea6e49c76178cbd2ded56e759cb6657`.
Its [reproducer](../research/cgate_cross_kind_oid_mutations.py) has SHA-256
`b0dbc770e478215d430a6a3f4f3fa34419950f430aa898ec5a84b337ae4806db`.
The fixture pins original C-Gate 3.4.0 build 2001 JAR SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`
and Java 11 SHA-256
`94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4`.
All six listeners were child-owned on `127.0.0.1`. The synthetic CNI
`127.0.0.1:1` was never opened. The harness confirmed process exit and removal
of the disposable project directory. No broker, physical bus or site project
was used.

Each of ten cases resets a complete synthetic Network whose Application 56 and
Unit 20 share one OID. Five mutations run once with Application then Unit in
the submitted XML and once with Unit then Application. Both submission orders
select Unit 20 for `DBGETXML !oid` and for all five mutations:

| Command | Native receipt | Result |
| --- | --- | --- |
| `DBSETSAFE !oid/UnitName ByOID` | `200 OK.` | Unit 20 name changes; Application 56 stays intact. |
| `DBSET !oid/UnitName ByOID` | `200 OK.` | Same selected Unit and preservation. |
| `DBSETXML !oid` with a complete Unit | `301 OID=<shared OID>` | Unit 20 is replaced; Application 56 stays intact. |
| `DBCOPYSAFE !oid //XCROSS/254 21 Copied` | `301 OID=<new OID>` | Unit 21 inherits Unit 20's name and `PP UnitAddress=20`; its address, tag and OID are new. |
| `DBDELETE !oid` | `200 OK.` | Only Unit 20 is removed. OID lookup returns 401 until reload, then resolves to the surviving Application. |

Every case records direct Application and Unit XML before and after mutation,
the OID read before and after, four project lifecycle commands, and direct/OID
reads after save, close, load and use. The
[wire vectors](../../rust/testdata/vectors/cgate_cross_kind_oid_mutations.jsonl)
pin both orders, selected object types and receipts. Source-bound Python tests
check the capture's sequential wire and provenance. A Rust integration test
replays all ten transactions and compares the native semantic readbacks. A
focused running-`cmqttd` TCP test covers all five verbs and the reload
fallback through its durable service.

Rust now admits this one-Application, one-Unit, one-Network shape for those
five OID mutations. Repeated Applications with a Unit and Unit collisions
across Networks remain guarded. A [separate owned capture](native-cgate-five-plus-unit-oid-mutations.md)
covers five and six Units with one OID in a single Network; seven or more remain
guarded. These database-only observations do not
establish any physical C-Bus side effect or broader vendor XML compatibility.
