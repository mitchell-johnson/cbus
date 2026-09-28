# Original C-Gate Levels under same-OID Applications

The [62-request capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_nested_levels.json)
comes from the [reproducible script](../research/cgate_dbsetxml_nested_levels.py),
the [tagged exchange helper](../research/cgate_dbsetxml_duplicate_applications.py),
and the [owned-service harness](../research/local_cgate.py). The fixture SHA-256
is `b5259cc61051182ca8275c961db4238f6e552aee59b4e16bc77e715462516fbe`;
the script SHA-256 is
`6125cd7d1ea80a82f4d58b3717f7d7e2cee27457db99a7936f34a5d07d78b6a1`.
The [source-bound evidence test](../tests/test_native_cgate_dbsetxml_nested_levels.py)
pins these inputs, the C-Gate 3.4.0 build-2001 JAR, Java 11, request framing,
and every tagged response. The temporary service owned six loopback listeners,
confirmed child exit, and removed its own working directory. Its synthetic CNI
at `127.0.0.1:1` was never opened. No broker, site project, or physical bus was
involved.

`XLGR` and `XLNV` each submitted a complete Network with two Applications at
addresses 56 and 57 sharing one OID. Each Application had a distinct child OID
and a distinct Level OID under a Group or NetVar, respectively. The Level had a
byte `Value` attribute, `TagName`, and address 2. Original C-Gate accepted both
trees with `301 OID=<Network OID>` and retained the two applications and their
own Levels in Network, direct Application, child, and OID readbacks. Shared
Application-OID lookup selected the final submitted Application at address 57.

Before save, Level readbacks had no `TagsDLT`. A `PROJECT SAVE` followed by an
immediate Network read still had none. After `PROJECT CLOSE` and `PROJECT LOAD`,
the Network read already included `<TagsDLT/>` under both Levels; a subsequent
`PROJECT USE` changed nothing. Group/Level direct-path `DBGETXML` succeeded both
before and after load. NetVar/Level direct-path `DBGETXML` returned exactly
`500 Internal error.` in both phases, while the same Level read by `!OID`
succeeded. The [Rust vector](../../rust/testdata/vectors/cgate_dbsetxml_nested_levels.jsonl)
records the two replacements, all XML reads, and the four native 500 responses.
The Rust replay compares every scoped replacement receipt, XML snippet, and
500 response after substituting only generated Network and Interface OIDs;
the service test checks durability across its JSON repository restart and no
PCI traffic.

This is a bounded Level-grandchild extension to the earlier
[nested-Application capture](native-cgate-dbsetxml-nested-applications.md).
It does not establish colliding descendant OIDs, mixed or other duplicate
container shapes, unsaved close/load semantics, general Level materialization,
private vendor file interchange, or physical behavior. Those remain outside
the admitted parity claim for [P2.02](https://github.com/mitchell-johnson/cbus/issues/24).
