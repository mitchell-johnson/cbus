# Original C-Gate five- and six-Unit shared-OID mutations

The [owned 289-request capture](../../rust/testdata/fixtures/native_cgate_duplicate_unit_oid_five_plus.json)
has SHA-256 `79d333ba33b0f83242ddfbb5df68c34384df6f14dc4a834e6c6f25980ba4613d`.
Its [reproducer](../research/cgate_duplicate_unit_oid_five_plus.py) has SHA-256
`78f99adf54793d5d22086cc61a03d57a7ffe516392086930a1ded06ff4f408a0`.
The source-bound [vectors](../../rust/testdata/vectors/cgate_duplicate_unit_oid_five_plus.jsonl)
and Python and Rust tests pin the wire receipts and resulting Unit fields.

The capture used original C-Gate 3.4.0 build 2001 JAR SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`
and Java 11 SHA-256
`94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4`.
The harness verified all six listeners belonged to its child process and were
bound to `127.0.0.1`. It created only disposable projects and closed Networks;
the synthetic CNI `127.0.0.1:1` was never opened. Process exit and removal of
the owned working directory were confirmed. No site project, broker, or
physical C-Bus endpoint was involved.

Each case replaces one Network with Units sharing one OID, directly reads every
Unit and the OID, runs one OID-targeted mutation, directly reads every Unit and
the OID again, then saves, closes, loads, reselects, and reads them again. The
five-Unit submission order is `24, 21, 20, 23, 22`; the six-Unit order is
`25, 20, 24, 21, 23, 22`. Address 22 is the final submitted Unit and is not
the highest address.

| OID-targeted command | Native result for both cardinalities |
| --- | --- |
| `DBSETSAFE !oid/UnitName ByOID` | `200 OK.`; only Unit 22's name changes. |
| `DBSET !oid/UnitName ByOID` | `200 OK.`; only Unit 22's name changes. |
| `DBSETXML !oid` with a complete Unit | `301 OID=<shared OID>`; only Unit 22 is replaced. |
| `DBCOPYSAFE !oid //XUFIVE/254 30 Copied` | `301 OID=<new OID>`; Unit 30 inherits Unit 22's name and `PP UnitAddress=22`, with new address, tag, and OID. |
| `DBDELETE !oid` | `200 OK.`; only Unit 22 is removed. The OID returns 401 immediately, then selects Unit 23 after save/close/load. |

All four project lifecycle commands returned 200 in every case. Direct reads
of the other four or five Units remained available and their names were
unchanged. The Rust mock extends its final-submission OID selector through the
[later owned seven-/eight-Unit capture](native-cgate-large-cross-network-oid.md).
That capture also covers bounded cross-Network Unit/Unit and
leaf-Application/Unit collisions. A
[later nine-/ten-Unit capture](native-cgate-nine-ten-unit-oid-mutations.md)
extends the same selected-Unit behavior through ten. Eleven or more Units and wider cross-Network
shapes remain guarded.
