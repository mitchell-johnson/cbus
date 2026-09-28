# Original C-Gate nine- and ten-Unit shared-OID mutations

The [owned 409-request capture](../../rust/testdata/fixtures/native_cgate_duplicate_unit_oid_nine_ten.json)
has SHA-256 `a53ec6f01a87fd548a244ebcc3b36e89f007d984678ff68d35472ff44dfc6cd1`.
Its [reproducer](../research/cgate_duplicate_unit_oid_nine_ten.py) has SHA-256
`5b1a7fd579ab24b9a7c2962dec4e8c2d4a61ed74812765f8cc1d73866af24fcd`.
The [exact vectors](../../rust/testdata/vectors/cgate_duplicate_unit_oid_nine_ten.jsonl)
and source-bound Python and Rust tests pin the wire receipts and resulting
Unit fields for all ten cases.

The oracle is original C-Gate 3.4.0 build 2001 JAR SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`
on explicit Java 11 SHA-256
`94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4`.
The harness verified all six child-owned listeners were on `127.0.0.1`, then
confirmed process exit and removal of its disposable working directory. It
used only synthetic project `XUNINE` and a closed Network with CNI address
`127.0.0.1:1`; that CNI was never opened. No site project or physical C-Bus
endpoint was used.

Nine same-OID Units were submitted in order `26, 24, 21, 20, 25, 23, 27,
28, 22`; ten in order `29, 27, 25, 20, 24, 21, 26, 23, 28, 22`. Each case
replaced the Network, read every Unit by address and the shared OID, applied
one OID-targeted mutation, read all addresses and the OID again, then ran
`PROJECT SAVE`, `CLOSE`, `LOAD`, `USE` and repeated the reads. Every Network
replacement returned 301, every lifecycle command returned 200, and all
surviving Units remained independently readable after load.

| OID-targeted command | Native result at both cardinalities |
| --- | --- |
| `DBSETSAFE !oid/UnitName ByOID` | `200 OK.`; only final submitted Unit 22's name becomes `ByOID`. |
| `DBSET !oid/UnitName ByOID` | `200 OK.`; only Unit 22's name becomes `ByOID`. |
| `DBSETXML !oid` with a complete Unit | `301 OID=<shared OID>`; only Unit 22 is replaced and its name becomes `Changed room`. |
| `DBCOPYSAFE !oid //XUNINE/254 30 Copied` | `301 OID=<new OID>`; Unit 30 retains source Unit 22's name and `PP UnitAddress=22`, with new address and tag. |
| `DBDELETE !oid` | `200 OK.`; only Unit 22 is removed. Shared-OID lookup returns 401 immediately and selects preceding submitted Unit 28 after load. |

Rust now admits the observed two-through-ten-Unit same-Network shapes. Eleven
or more same-OID Units remain guarded. This capture does not establish wider
cross-Network collisions, descendant collisions, physical behavior, or
additional XML shapes.

The production `cmqttd --cgate-bind` test
`ten_shared_unit_oids_select_last_submission_and_reload_prior_unit` also
exercises a ten-Unit replacement over TCP, OID-targeted mutation and deletion,
the `401` gap before reload, Unit 28 selection after project reload, and that
selection after a daemon restart using its durable JSON repository. This is a
synthetic local service test, not independent native or hardware acceptance.
