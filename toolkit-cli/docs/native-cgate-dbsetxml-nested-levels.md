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

## Post-load XML roundtrip

The [108-request follow-up capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_nested_levels_roundtrip.json)
reused the same owned C-Gate JAR, Java 11 runtime, synthetic CNI, and Level
shape. Its [script](../research/cgate_dbsetxml_nested_levels_roundtrip.py)
SHA-256 is `09950fbe23c361fd00f434891ad1f831e9b3bafae63be9a535d1f4787508728d`;
the fixture SHA-256 is
`33f7ac5fb6dd6937138382de8b7bec0ca56598a18c0c05a9a48f348dcce48c52`.
The [source-bound test](../tests/test_native_cgate_dbsetxml_nested_levels_roundtrip.py)
pins the script, source shape, tagged exchange helper, owned-service harness,
all requests and replies, listener ownership, and cleanup.

Six fresh projects submitted the exact XML returned by post-load `DBGETXML`
back to `DBSETXML`: complete Group and NetVar Networks, one Group, one direct
Group/Level, one NetVar, and one NetVar/Level by OID. All six replacements
returned `301 OID=<submitted root OID>`. Immediate target readback equaled the
submitted XML, including each empty Level `<TagsDLT/>`. Whole-Network readback
kept both Level tags and remained byte-identical after another
`PROJECT SAVE`, `CLOSE`, `LOAD`, and `USE`. The
[Rust vector](../../rust/testdata/vectors/cgate_dbsetxml_nested_levels_roundtrip.jsonl)
and exact replay cover all 108 requests. A service test also roundtrips the
post-load Network on both child kinds, verifies the second lifecycle and JSON
repository restart, and observes no PCI traffic.

## Nonempty Level labels

The [24-request owned C-Gate capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_level_dlt.json)
extends the same synthetic Group/Level shape to one nonempty `TagsDLT`. Its
[reproducible script](../research/cgate_dbsetxml_level_dlt.py) submits a
`TagDLT` with language 1, flavour 1, type `TEXT` and a text value but no OID.
Native C-Gate returns `301`, issues a TagDLT OID, and shows the label in direct
Level and whole-Network XML. A later direct Level replacement with that explicit
OID changes the text while retaining the identity. The label and identity
survive `PROJECT SAVE`, `CLOSE`, `LOAD`, `USE`, and a complete Network XML
roundtrip. The [source-bound test](../tests/test_native_cgate_dbsetxml_level_dlt.py)
pins the exact requests, replies, input hashes, owned loopback listeners and
cleanup. The Rust replay substitutes only the generated Network, Interface and
TagDLT OIDs. The Rust parser accepts bounded unnamespaced Level label rows,
normalizes the native child order, and retains them in its durable database;
malformed rows fail before tree mutation. The capture also shows that a single
Application Level gains an empty `TagsDLT` on load, expanding the prior
repeated-Application-only materialization rule.

## Nonempty Group labels

The [34-request owned C-Gate capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_group_dlt.json)
extends the same Group/Level tree to its parent Group's `TagsDLT`. Its
[reproducible script](../research/cgate_dbsetxml_group_dlt.py) is pinned by
the fixture SHA-256
`d078ce2d67b0819abb4a3f86c1e6492bd96fed56e3472b2e44848475effcb357`;
the script SHA-256 is
`1f0a398e274b47e4a9b2548f5f5d0ee35d89991b684f9d811760becb16686992`.
It creates a Group text label without a TagDLT OID; native C-Gate issues one and returns it in
direct Group and whole-Network XML. Direct Group replacement with that OID
changes the text without changing the identity. A complete Network replacement
retains it. Adding a second flavour without an OID generates a distinct OID;
both variants survive save/close/load/use. A final direct Group replacement
with an empty `TagsDLT` removes both variants and preserves the empty
collection in direct and Network readback. The temporary service owned six
loopback listeners, confirmed process exit and cleanup, and never opened its
synthetic CNI at `127.0.0.1:1`.

The [source-bound test](../tests/test_native_cgate_dbsetxml_group_dlt.py)
pins the fixture SHA-256, all input scripts, Java 11 and C-Gate JAR hashes,
exact tagged framing and label lifecycle. The
[vector](../../rust/testdata/vectors/cgate_dbsetxml_group_dlt.jsonl) and Rust
replay compare every request and scoped XML response after substituting only
the four generated Network, Interface and label OIDs. A service test keeps the
label and nested Level through durable JSON restart without PCI traffic.
Duplicate Group collections fail before tree mutation.

### Group label field and collection boundary

The [30-case owned build-2001 capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_group_dlt_boundaries.json)
extends the same disposable Group/Level project through immediate direct-Group
`DBSETXML` and `DBGETXML` pairs. The
[reproducible script](../research/cgate_dbsetxml_group_dlt_boundaries.py),
[source-bound assertions](../tests/test_native_cgate_dbsetxml_group_dlt_boundaries.py),
and [Rust replay vector](../../rust/testdata/vectors/cgate_dbsetxml_group_dlt_boundaries.jsonl)
pin the original JAR, Java 11 executable, all six owned loopback listeners,
tagged wire replies and cleanup. No C-Bus endpoint was opened.

Native Group `TagDLT` fields behave as ordered XML records in this capture.
`LanguageID` and `FlavourID` retain zero, values above 255 and nonnumeric text;
`TagType` retains `IMAGE`, lowercase, unknown and empty strings. Two, four,
five and 65 rows return `301` in submission order. Two rows with the same
language/flavour or explicit OID both survive immediate Group readback; an
explicit TagDLT OID equal to its parent Group or nested Level OID also survives.
Those readbacks establish only XML replacement, not safe resolution of a
colliding OID by later OID-targeted commands.

The probed default namespace on an empty `TagsDLT` and an unknown collection
attribute materialize as a plain empty collection. An unknown `TagDLT`
attribute is dropped; a namespaced `TagDLT` with no recognized fields receives
only a generated OID; a namespaced `TagType` field is omitted. Two Group
`TagsDLT` containers produce native `446` with the prior Group XML unchanged.
The Rust Group parser reproduces these captured forms, with an explicit
65-row and 1,024-byte-per-field safety bound. Level labels retain their
earlier, narrower parser. Larger collections, other malformed or namespaced
shapes, save/load of these unusual field values, and OID-targeted effects are
unprobed.

This is a bounded Level-grandchild extension to the earlier
[nested-Application capture](native-cgate-dbsetxml-nested-applications.md).
It does not establish colliding descendant OIDs, mixed or other duplicate
container shapes, unsaved close/load semantics, general Level materialization,
private vendor file interchange, or physical behavior. Those remain outside
the admitted parity claim for [P2.02](https://github.com/mitchell-johnson/cbus/issues/24).
