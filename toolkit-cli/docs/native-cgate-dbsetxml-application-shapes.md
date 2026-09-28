# Original C-Gate repeated-OID Application order and replacement

The [114-request capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_application_shapes.json)
has SHA-256 `3712ae2e4e355f011cc5c6f2478bc3d08fed507bd38811a5ecc9448f87014b3d`.
It was produced by the [capture script](../research/cgate_dbsetxml_application_shapes.py)
(`009c5faf6ea63ac747e1cc212203e418b3c114f1782215f5c86825f1d2995001`),
its [tagged exchange helper](../research/cgate_dbsetxml_duplicate_applications.py)
(`22580ef1eb861b029df4154efa267872ea4864115ee0949ac40f25403f24e2a4`),
and the [owned-service harness](../research/local_cgate.py)
(`3df3f50db74bc1321b7d8b173927d88f50082df4bc67042b0bb2446e5f99e111`).
The original C-Gate 3.4.0 build 2001 JAR and Java 11 executable have SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`
and `94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4`.
Three synthetic projects ran under one temporary, child-owned service with six
`127.0.0.1` listeners. Their `127.0.0.1:1` CNI was never opened. The harness
confirmed process exit and directory removal. No broker, site project or
physical C-Bus network was involved.

Each project submitted a complete Network containing leaf Applications with
one shared OID and distinct addresses:

| Project | Submitted Application order | `!OID` selection |
| --- | --- | --- |
| `XREVA` | 57, 56 | 56 |
| `XTRIA` | 56, 57, 58 | 58 |
| `XQUAD` | 59, 57, 56, 58 | 58 |

Original C-Gate returned `301 OID=<Network OID>` for each Network replacement.
Network `DBGETXML` kept **submission order**, not numeric Address order, before
and after `PROJECT SAVE`, `CLOSE`, `LOAD` and `USE`. Every direct Application
path was present. `DBGETXML !<shared OID>` and `DBGET !<shared OID>/Address`
selected the **last submitted Application** in all three shapes. The reversed
pair proves this is not a highest-Address rule.

For every shape, direct-path `DBSETXML` replaced the first submitted
Application while retaining the other paths, their order and the original OID
selection. `DBSET !<shared OID>/TagName` then changed only the final submitted
Application. `DBSETXML !<shared OID>` replaced that same Application. A second
save/close/load cycle retained the resulting order and values. The [exact Rust
vector](../../rust/testdata/vectors/cgate_dbsetxml_application_shapes.jsonl)
enumerates all 12 set/write tags and 69 read tags; the Rust server test checks
each native post-setup response after substituting generated Network and
Interface OIDs. The service test checks order and OID selection through JSON
repository restart and direct replacement without PCI traffic. The [Python
evidence test](../tests/test_native_cgate_dbsetxml_application_shapes.py)
binds the fixture to its source script and asserts the native outcomes.

Rust stores submission positions with repeated-OID Application records, so
save/reload, repository restart, project copy/rename and direct replacement do
not turn OID selection into highest-Address selection. Older JSON repositories
without this field keep their prior address-based ordering. The accepted
complete-Network shape remains leaf Applications with distinct addressed
paths; nested same-OID descendants, cross-network identity collisions and
unprobed duplicate-Application Address/deletion operations remain guarded.
The native capture proves two, three and four records; larger lists use the
same bounded model but have not been separately accepted against the original.
Native project file serialization and physical effects are outside this
capture.
