# Original C-Gate large and cross-Network shared-OID mutations

The [owned 1,551-request capture](../../rust/testdata/fixtures/native_cgate_large_cross_network_oid.json)
has SHA-256 `b60edf7be4fc127f9461a0a12e3f3c9eabe24a7f1d0845adc313c7f45a2e2914`.
Its [reproducer](../research/cgate_large_cross_network_oid.py) has SHA-256
`ac6117104ced6651ecafea595c742d9882b9568784c3f86c190df3fdc8bde5ad`.
The [seven/eight-Unit vectors](../../rust/testdata/vectors/cgate_large_unit_oid.jsonl)
and [cross-Network vectors](../../rust/testdata/vectors/cgate_cross_network_oid.jsonl)
pin the selected object, wire receipt and save/reload fallback. The source-bound
Python test verifies the sequence and provenance; the Rust replay executes all
50 captured mutation cases against `cbus-cgate`.

The capture used the original C-Gate 3.4.0 build 2001 JAR SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`
and explicit Java 11 SHA-256
`94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4`.
The harness verified six child-owned listeners on `127.0.0.1`, process exit
and removal of its disposable working directory. It created only synthetic
closed Networks 253 and 254 with CNI address `127.0.0.1:1`; that endpoint was
never opened. No site project or physical C-Bus endpoint was used.

Seven Units were submitted in order `26, 24, 21, 20, 25, 23, 22`; eight in
order `27, 25, 20, 24, 21, 26, 23, 22`. All shared one OID. In each of five
reset-and-mutate cases per cardinality, `DBGETXML !oid` selected the final
submitted Unit 22, independent of numeric address. `DBSETSAFE` and `DBSET`
changed only its `UnitName`; complete `DBSETXML !oid` replaced only that Unit;
`DBCOPYSAFE !oid` minted a new OID and copied Unit 22's `UnitName` and PP
`UnitAddress=22`; `DBDELETE !oid` removed only Unit 22. Direct-path siblings
remained readable. After delete, OID lookup returned 401 until `PROJECT SAVE`,
`CLOSE`, `LOAD`, `USE`; it then selected Unit 23. The other four verbs retained
Unit 22 as OID winner after reload.

The cross-Network cases each placed one shared-OID object in each Network,
then repeated all five verbs in both Network insertion orders. The four
shapes were Unit 20 on 254 / Unit 21 on 253; the same two addresses reversed;
Application 56 on 254 / Unit 21 on 253; and Unit 20 on 254 / Application 56
on 253. In every case the object on lower-numbered Network 253 won OID
resolution, regardless of insertion order, Unit address or kind. Both direct
paths stayed independently readable. `DBSETSAFE`, `DBSET`, and complete
`DBSETXML` mutated only the selected object; `DBCOPYSAFE` created a new Unit
or leaf Application at address 30 in Network 253; `DBDELETE` removed only the
selected object. Deletion made OID lookup 401 immediately; save/close/load
selected the survivor on Network 254. Every project lifecycle command returned
200. The copied Unit retained its source PP `UnitAddress` with a new OID.

The Rust model admits the two-through-ten-Unit same-Network cases, including
the [later nine-/ten-Unit capture](native-cgate-nine-ten-unit-oid-mutations.md), and the
captured two-Network Unit/Unit and leaf-Application/Unit shapes. Its
cross-Network selector is limited to Networks 253 and 254 with one object of
the shared OID in each; duplicate Unit addresses across Networks remain
guarded because the addressed Unit metadata key would collide. More than
ten same-Network Units, more than two Networks, repeated Applications in
one cross-Network collision, descendants, and other topology or vendor XML
shapes still need separate native and representation evidence. These are
database-only observations and establish no physical C-Bus side effects.
