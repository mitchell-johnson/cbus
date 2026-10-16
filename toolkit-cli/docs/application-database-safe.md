# Application database copy and identity edits

This guide describes the bounded phase2 Application routes in the owned Rust
C-Gate servers. All four mandatory Rust gates passed, together with 59 focused
source CLI cases and separate fresh installed-wheel phases of 28 mock and 31
daemon cases. Exact native acceptance remains open under issues 124 and 125.
The examples use
the existing Python CLI and explicit project selection; they are not new native
C-Gate acceptance evidence.

`database copy` copies one complete admitted Application subtree into an existing
Network. The copied Application and every admitted OID-bearing descendant receive
fresh OIDs. `database set PATH/Address` moves an admitted Application within its
existing Network while retaining its OID, descendant OIDs and recorded Application
creation-order position. `database set PATH/TagName` changes the Application name
after checking sibling uniqueness.

These operations edit the database model. They do not program devices, rewrite
Unit PP, open a C-Bus Network or prove a physical effect. General C-Gate and
Toolkit workflow parity remain incomplete.

## Select the project on the operation's connection

Use an endpoint that you have selected and an already loaded project. `--project`
issues `PROJECT USE` on the same connection as the database operation. A separate
invocation of `cgate project use` does not establish a later command's session.
Relative selectors and issued `!OID` selectors depend on this selected project.
Prefer exact numeric `//PROJECT/NETWORK/APPLICATION` paths when reviewing an edit.

The names `SOURCE`, `DEST` and `SAFEAPP` below are synthetic placeholders. Replace
`HOST`, `PORT`, names and addresses with the reviewed endpoint and loaded database
objects. The examples are mutations and do not provide a dry-run option.

## Copy an Application

Inspect the source and destination before choosing a free destination address
and name:

```sh
cbus-toolkit cgate --host HOST --port PORT database get-xml //SOURCE/254/71 --project SOURCE
cbus-toolkit cgate --host HOST --port PORT database get-xml //DEST/253 --project SOURCE
cbus-toolkit cgate --host HOST --port PORT database copy //SOURCE/254/71 //DEST/253 80 "Copied application" --project SOURCE
cbus-toolkit cgate --host HOST --port PORT database get-xml //DEST/253/80 --project DEST
```

The CLI reads the source with `DBGETXML`, then sends one `DBCOPYSAFE` with the
source, destination parent, destination address and name. It always supplies the
address and name, including for a same-parent copy. For example, copying beneath
`//SOURCE/254` instead of `//DEST/253` requires a different free Application
address and a unique sibling name. Cross-project copies require both loaded
projects and a destination Network; an Application cannot be copied beneath a
Group or another Application. The admitted `!OID` source must resolve to one
typed Application, and a destination `!OID` must uniquely identify a Network in
the selected project.

The server validates the whole source and destination before allocating or
committing. It preserves admitted scalar fields and the Group, NetVar and Level
hierarchy, changes only the copied root's Address and TagName, rebuilds copied
parent paths and assigns fresh identities. Admitted `TagsDLT` metadata retains
its content with fresh label identities. The source remains unchanged. The new
Application is appended once to the destination Network's recorded creation
history; existing entries are not reordered.

Occupied addresses, duplicate sibling names and retained destination state
refuse the copy. A sibling raw Application can reserve a name before it has an
Address or exported path; that name is also unavailable for a SAFE copy. The
reservation must belong to the destination project and its exact numeric Network
parent or actual live Network-OID parent. An unrelated Network or project's name
does not reserve this destination. Retained state includes orphan scalar fields, marker objects,
pending descendants and Level records even when no normal Application is
exported at that address. Copy also refuses incomplete or ambiguous identities,
conflicting scalar aliases, unowned source fields, associated raw Level values
and unclassified XML metadata. It does not silently omit unsupported children.
This is a complete copy of the admitted profile, not an arbitrary XML copier.
Scalar references outside the copied subtree retain their literal values; broad
native reference-retargeting behavior has not been established.

## Move an Application or change its name

Use the selected project that owns the Application. An explicit foreign-project
selector does not bypass the setter's project ownership check.

```sh
cbus-toolkit cgate --host HOST --port PORT database get-xml //SAFEAPP/254/71 --project SAFEAPP
cbus-toolkit cgate --host HOST --port PORT database set //SAFEAPP/254/71/Address 70 --project SAFEAPP
cbus-toolkit cgate --host HOST --port PORT database set //SAFEAPP/254/70/TagName "Renamed application" --project SAFEAPP
cbus-toolkit cgate --host HOST --port PORT database get-xml //SAFEAPP/254/70 --project SAFEAPP
```

The CLI sends `DBSETSAFE`. Application Address values must contain only ASCII
decimal digits and have a value from 0 through 255; hexadecimal, signs, fractions
and embedded spaces refuse. The destination must be free, including its retained
descendant state. A sibling incomplete Application also reserves its assigned
Address before it has a TagName or numeric path. SAFE moving into that reservation
refuses before changing either identity. This check recognizes the selected
Network's numeric parent and its exact retained Network-OID parent; it does not
make every raw Network-OID creation form a supported public operation.

The current owned implementation treats a same-address edit as
an unchanged move and keeps the input scalar lexeme for a changed address while
using a canonical decimal path. These are owned policies whose exact native
no-op and lexical replies remain unverified.

Address validation checks the complete modeled Application owner before one
staged commit. The move updates its database paths and descendant parent links,
retains all OIDs and the recorded creation-order slot, and preserves unrelated
Applications, Unit PP and physical observation state. It can preserve existing
opaque or missing Level Value fields without reinterpreting them as bytes. This
does not make those raw-value subtrees admissible for copying or strict typed XML
replacement.

An admitted leading-zero value such as `070` remains `070` in the Application's
stored Address/XML, while its typed database path is `//SAFEAPP/254/70`. SAFE
scalar delegation uses that canonical Application coordinate. Later Application
TagName edits can use its actual 1-based `Application[N]` position, literal `070`,
canonical `70`, or unique issued OID. The existing Group TagName route also uses
the canonical Application ancestor, so an indexed Group or literal child address
beneath `070` still selects the same Group. Derive list positions from a fresh
read; do not guess an ordinal or substitute a TagName as a path alias. These
aliases preserve the Application's stored `070`, Group and descendant identities,
Level data and recorded creation-order slot. Raw `DBSET`/`DBDELETE` and other
object coordinate policies retain their existing behavior.

An issued unique Application OID can address either scalar field. Ambiguous
Application Address ownership refuses. Existing captured shared-OID routes keep
their established resolver: a winning Unit is not reselected as an Application,
and the retained duplicate-Application TagName route remains under its existing
owner. A successful OID read alone is not proof that every possible mutation of
that repeated-OID shape is admitted.

TagName must be nonblank and must not equal a sibling Application's name under
the current owned comparison. This includes a sibling raw Application whose
TagName is assigned before its Address/path exists, under the same numeric
Network parent or actual live Network-OID parent. The current target is excluded
by its exact path, so reassigning its same name remains admitted; another
identity is not ignored merely because it shares an OID. The refusal happens
before staging a rename or allocating a copy. Network-OID parent tests use an
explicit retained-state fixture and do not establish every public raw creation
form. The existing SAFE setter tokenization joins words
with one space; do not rely on it to preserve repeated spaces. Native case,
whitespace and same-value policy, and exact mutation/error envelopes, still need
target execution evidence. Raw `DBSET`, old Unit/Level routes and their existing
reply conventions are preserved; this change does not broaden them.

## Level Value writes are a separate boundary

The Application copy/Address/TagName evidence above remains its own checkpoint.
The [ordinary numeric Level Value guide](ordinary-level-value.md) describes a
separate issue 131 consistency fix: its isolated candidate binds one complete
selected-project typed owner, applies the existing issued-OID byte initializer
and keeps numeric/OID/XML readbacks coherent. It passed 13 library cases,
12 source CLI cases, separate installed mock 6/daemon 6 phases and four required
Rust gates. The adopted branch passed its own exact source 12 and fresh installed
mock 6/daemon 6 cases with the current runner; issue 131 remains open pending
merge. Full 1,062-ID and native acceptance remain separate. The earlier
Application acceptance report remains unchanged.

Use a build containing that fix before relying on an ordinary numeric SAFE
Value route. Earlier builds can acknowledge a numeric scalar alias while
authoritative Level XML retains the old byte. Select the project on the edit's
connection and compare complete XML with fresh numeric and actual issued-OID
readbacks. The ordinary add response exposes `lines`, `final` and `status`, not
an invented JSON `oid` property. Raw `DBSET`, existing shared Unit/OID routes and
the associated tag-Network's opaque Value owner retain their previous dispatch;
neither this fix nor a status-only readback establishes arbitrary raw, NULL,
lexical/error or native mutation parity. SAVE is an explicit separate operation.

## NULL Levels and copied LOAD metadata

A Level created through the ordinary `DBADDSAFE` constructor can have no Value.
Complete typed `DBSETXML` still requires a numeric Level Value; the copy fixture
constructs a real NULL Level separately rather than weakening that import rule.
An admitted Application copy preserves that absent Value, gives the Level a fresh
OID and retains the complete hierarchy. Its issued `!OID/Value` getter reports
`342 ...=null`, while the exported Level still omits the Value attribute. The
copied Level has both a typed record and a pending XML mirror. The NULL getter
uses the matching typed owner only when that pending mirror lacks Value and the
typed record has neither numeric nor opaque Value. An explicitly empty pending
Value, an opaque Value, a mismatched owner or another object kind is not silently
reinterpreted as this NULL profile.

The copy also retains existing SAVE/LOAD metadata timing. For a copied pending
Level that lacks a label collection, `PROJECT SAVE` records the deferred marker;
the empty `<TagsDLT/>` appears on the following `PROJECT LOAD`, not immediately
on SAVE. This one empty child leaves the NULL Value and all OIDs unchanged, and
already populated label collections remain intact. The ordinary source NULL
constructor has no pending XML mirror, so it does not acquire this child through
the same nested-Level marker. Compare the complete pre-save, saved and loaded
graphs against their explicit phases rather than ignoring empty collections.
This describes the current owned lifecycle; it is not a new native NULL
Application-copy transcript.

## Read back, then save explicitly

Neither `database copy` nor `database set` requests `PROJECT SAVE`. Review the
returned response and a fresh database readback. When a saved-project baseline is
intended, save the project that changed:

```sh
cbus-toolkit cgate --host HOST --port PORT project save DEST
cbus-toolkit cgate --host HOST --port PORT project save SAFEAPP
```

For a cross-project copy, save the destination rather than the unchanged source.
cmqttd's durable JSON state and its saved-project baseline are separate concepts;
neither is a Schneider backup-format guarantee. Later reload and restart checks
must use the server's declared persistence profile. Imported or old snapshots
that lack Application creation metadata retain an explicitly unknown historical
prefix and deterministic fallback; numeric or XML order is not relabeled as
proven native creation chronology.

Each requested write is sent once. If a reply is lost, do not automatically
repeat the copy, move, rename or save. Inspect the retained command evidence and
read the state independently before deciding on recovery. A lost success reply
can leave the server mutated even though the caller reports failure. The CLI
does not create a backup or roll back these scalar/copy operations automatically.

## Evidence boundary

The retained target C-Gate **3.4.0 build 2001** `HELP *` capture documents
`DBCOPYSAFE` at response index **58** and `DBSETSAFE` at index **70** in
[`native-cgate-help-differential-acceptance.json`](../research/fixtures/native-cgate-help-differential-acceptance.json).
These are zero-based indices in
`profiles.target_cgate_3_4.help_star.response`. They establish documented
decimal-byte, parent-type, sibling uniqueness and fresh-OID/field-retention
rules. Target-specific `HELP DBCOPYSAFE` and `HELP DBSETSAFE` requests return
`101 Help: No help is available for this command.` The separate detailed exact
HELP profile for 2.11.10 build 3342 must not be described as a target 3.4 mutation
capture.

Documentation is distinct from executed replies and effects. Existing original
captures cover selected Unit/shared-OID, Application TagName and XML lifecycle
behavior; they do not establish this complete new numeric Application Address
or subtree-copy matrix. Unknown XML shapes, broader duplicate-identity graphs,
native Address/no-op/case/whitespace/error behavior, vendor archive interoperability
and physical acceptance remain open. Issues 124 and 125 retain those unmet
native requirements; local owned tests must not be presented as their completion.

The four mandatory Rust commands for the tested feature overlay passed: formatting, Clippy, workspace
tests and release build. The workspace log contains 104 result blocks reporting
8,789 passed and one ignored private-project test; these are logged aggregate
counts, not vector rows or an independently enumerated case roster. A separate
fresh debug-server build also passed. The name reservation tests first produced
four real refusal failures and two passing controls, then the same six tests
passed after only the two preflight guards changed.

Public source and fresh installed-wheel validation are separate actual epochs.
The original source selection passed all 59 parents. The installed mock phase
passed 28 and the installed daemon phase passed 31, each without failures, errors,
skips or subtests. They check complete Application graphs, OID retention or fresh
copy identities, genuine unrelated Unit PP preservation, save/load/restart and
no replay after uncertain successes. The earlier source1/source2 and wheel1/wheel2
failures remain retained; issue 131 is an open product gap rather than a fixture
error. Read the [acceptance report](acceptance/2026-10-05-application-database-safe/report.md)
and [receipt](acceptance/2026-10-05-application-database-safe/receipt.json) for exact
scopes, hashes and historical failures. The separate required offline Make repeat
passed 10,541 parent cases and skipped 1,714 provisioning cases, with 44,906
unitemized subtests passing. Its first failed run and private executor-prefix
probes remain separate. The separate complete source interop target passed all 1,050 required IDs
(519 mock, 531 daemon) and seven whole core modules, with exactly two optional
UnitSpec skips. Mock passed 538 parents plus 158 unitemized subevents; daemon
passed 682 parents plus 69 subevents; framing passed two parents. These source
commands are distinct from the focused installed phases. Owned acceptance does
not imply native or hardware parity.

The separate complete source `make check-interop` passed all seven actual
commands. Its 1,050 explicit required IDs all reached passing call bodies and
JUnit cases: 519 mock and 531 daemon. The seven whole core modules expanded the
mock command to 539 parents (538 passed, one optional UnitSpec skip, plus 158
unitemized passing subevents) and the daemon command to 683 parents (682 passed,
one optional UnitSpec skip, plus 69 unitemized passing subevents). The separate
framing command passed two parents. Make took 6,105.293 seconds. The optional
skips are the retained UnitSpec derivations, never substitutes for required IDs.
These are complete source Make results, separate from the installed 28/31 phases
and from the offline repeat; they do not prove a full installed matrix.

The tested checkout recorded HEAD `6807786f` with an uncommitted Application
feature overlay. Root verified its original 4,185-file map before committing that
byte-exact overlay as `79a4c2e6b35efebd9c8014b851dde8de25f34947`.
The original phase maps and binary pins remained exact within their own epochs.
The later `e1e7073` matrix, serial fixture and generated-metadata composition is
a separate integration checkpoint. Its Make/CI/runner/test/document changes are
outside these original full-Make results; no current post-composition 4,185-file
equality or repeated full-matrix execution is claimed. The 481 Rust inputs are
unchanged by that composition, but Toolkit checks and capture freshness remain
separate follow-up work.

At that original Application checkpoint, issue 131 had a separate unadopted
13-case library proof and no public or installed acceptance in that feature
epoch. The later adopted consistency fix and its focused proofs are described
above; they do not rewrite this historical Application acceptance.
