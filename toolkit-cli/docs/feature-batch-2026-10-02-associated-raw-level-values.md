# Literal Values on associated Levels

The Rust C-Gate service retains nonempty scalar Value strings on existing
numeric-associated Levels, including after a secondary Network is renamed.
The Python Toolkit CLI exposes this through its existing selected-project
`database set` workflow. Levels under a Group and under a NetVar share the same
authoritative owner; this does not add a Value field to the NetVar parent.

## Operator workflow

For an existing fixture project `LAB`, associated Network `11` renamed to
`Renamed`, Application `56`, Group `1` and Level `7`:

```sh
cbus-toolkit cgate database set //LAB/Renamed/56/1/7/Value oops --project LAB
cbus-toolkit cgate database get //LAB/Renamed/56/1/7/Value --project LAB
cbus-toolkit cgate project save LAB
cbus-toolkit cgate project close LAB
cbus-toolkit cgate project load LAB
cbus-toolkit cgate database get //LAB/11/56/1/7/Value --project LAB
```

Use your actual objects and service endpoint. Each database command with
`--project` selects it on its own connection; lifecycle commands name their
project directly. There is no implicit save or hardware I/O. For scalar Value
reads/writes, qualified/bare exact canonical numeric paths, renamed lexical
paths and an issued Level OID
resolve one owner; an existing independent numeric-looking Network keeps its
lexical precedence on successfully resolved objects. Scalar and whole XML reads retain the raw string, with XML
escaping applied only to its representation. Writes update exact completed
pending mirrors, preserve OIDs and unrelated graphs, and refuse stale competing
mirrors before mutation. Internal JSON snapshots retain the value across a
fresh daemon process; old snapshots without the optional raw field keep their
byte/absent interpretation. Uniform object Level XML reads use an OID or renamed
qualified/bare path. Bare numeric object DBGETXML remains unsupported with local
`404`; qualified numeric object XML uses legacy owner-dependent projection and
its raw/renamed profiles are outside this acceptance. [Issue #73](https://github.com/mitchell-johnson/cbus/issues/73)
tracks the original numeric selector contract and any needed implementation.

SAFE and unsafe setters retain their established byte grammar: SAFE recognizes
an i64 in byte range and unsafe recognizes a u8. Accepted bytes are canonical
decimal, including `077` and `+77` becoming `77`; SAFE `-0` becomes `0`, while
unsafe `-0` stays text. Existing C-Gate tokenization folds tail whitespace to
single spaces, so retention does not preserve verbatim whitespace or quoting.
Other supported nonempty tails remain text; hexadecimal-looking strings are
not inferred as control levels. Literal `null` remains text, distinct from
absence in XML. SAFE blank/`#` validation stays in force, and characters that
cannot be represented in XML 1.0 refuse atomically before acknowledgement.

## Preservation boundaries

DBCOPY/DBCOPYSAFE of a raw Level or a containing subtree return local `408`
before a byte-only copy projector can lose the value. The guard covers numeric
aliases, multiple leading slashes and legacy OID-suffix projection. Tag-tree
resynchronization also refuses before replacing acknowledged raw data.
Complete external DBSETXML remains strict: exporting this internal graph does
not establish that its raw Value can be reimported. These modeled refusals are
explicit outstanding functionality, not native error-code acceptance.

## Deferred corrections

Known associated-owner bugs are deferred in [issue #74](https://github.com/mitchell-johnson/cbus/issues/74):
canonical numeric Group COPY destinations return `401`, while renamed lexical
paths and Group OIDs succeed for admitted byte copies. The newer LOAD sweep
can also alter unsupported retained XML on a plain Level with a deferred empty
label marker. Those payloads are outside the accepted LOAD profile. A separate
missing-descendant Value-getter fallback is an unverified source-review
hypothesis. The attempted fixture failed before that edge executed. These
corrections were stopped by cyber protection; no private untested edits are
integrated or credited.

## Validation

All four required Rust 1.99 checks passed: formatting, workspace all-target
Clippy with warnings denied, workspace tests and release workspace build. The
literal workspace result is **8,649 passed, zero failed, one ignored** across
97 summaries. The ignored private-project upgrade needs
`CBUS_PRIVATE_PROJECT_XML` and `CBUS_PRIVATE_CGATE_STATE`. The eight new library
parents overlap the 49 owning-module parents and the workspace run; they are
not added to it. Rust product, tests and library vector stayed unchanged after
these checks. Later Python test-oracle, CLI-only vector and known-limit guide
corrections are bound separately in the release receipt.

Fresh source and isolated installed Python 3.13 wheel each passed **11 public
CLI parents with zero failures/errors/skips**, including all four plain/completed
Group/NetVar owners, both servers, LOGIN refusals and fresh daemon JSON restart.
Each environment recorded **1,754 CLI calls**: 76 existing argv/exit/JSON calls
and 1,678 proxy-captured connections (49 associated-Level, 25 empty-TagsDLT and
1,604 raw-Level calls), containing 3,628 tagged commands. Every captured call
has definite terminal replies. All 16 owned backend processes and listeners
closed. Fake PCI peers received 96 startup-only frames, zero later frames and
zero closed-network CNI trap contacts. The 266 expected denied calls are
preservation/authentication checks, not failed tests.

All **326 source/wheel/installed package files** matched byte for byte. The
three final phases shared the same 3,622-file input roster and **24 frozen
source/resource pins**. Maintained `make check-interop` passed 23 mock, 158
daemon and two framing parents, with one vendor-specification skip on each
server selection. Its 158 mock and 69 daemon passing subtests are reported
separately. Aggregate JUnit/trace counters include those unitemized subtests;
410 aggregate passes are not 410 parent tests.

Six fresh modeled comparisons against retained captures and six direct-literal
canonical publications passed. All 1,117 source bindings remained current,
with no decoded privacy findings. Evidence generation/checks and 12 consumer
modules passed: 261 parent passes, one original-input environment skip and 934
separate passing subtests. The earlier V6 metadata execution is preserved as a
superseded attempt; prepared V7 configuration has no execution credit. Five
private CLI failures remain retained: API/terminal expectations, the genuine
bare numeric XML404 limit, invalid CLI argv and expected error handling were
corrected or explicitly scoped before the final run. Private debug results
are not added to the current release counts.

Independent reviewers checked Rust source/phase logs, CLI source/API/wires,
metadata publication payloads, package bytes and the terminal root receipt.
Reviews add zero execution credit. The full Python suite was not repeated;
original/vendor/VM/hardware execution remains zero. The
[bounded release receipt](../research/fixtures/associated-raw-level-owned-release-20261002.json)
binds actual artifacts and the later report/status prose delta.

Before raw writes, each final environment also retained eight controlled
qualified numeric object-XML observations at byte77: all end with `344`, but
only the completed Group returns a `Level`; the other three owner shapes return
`Object`. These direct-owner observations are outside the public CLI wire
census and do not establish raw qualified numeric XML acceptance. The bare
numeric object form is explicitly tested as local404. Imported-byte original
captures separately retain ten Group344 and four NetVar500 responses, with
eight successful OID counterparts; those shapes do not accept this renamed/raw
workflow. Preserve both distinctions in [issue #73](https://github.com/mitchell-johnson/cbus/issues/73).

## Original evidence and remaining work

Retained original C-Gate captures establish ten SAFE/unsafe scalar/XML cases
for `255`, `0xff`, `999`, `oops` and `-1` on an independent named owner. A
separate SAFE case with Value `oops` establishes explicit save/close/reload and
materialized empty TagsDLT. Those captures contain no raw COPY case and do not
accept the current associated-owner implementation. Broader tails, numeric
aliases, raw preservation refusals and internal restart are modeled tests.
No current original Toolkit/C-Gate, vendor, VM or hardware execution is claimed.
The manual original comparison remains in
[issue #72](https://github.com/mitchell-johnson/cbus/issues/72).

Raw-value copying/resynchronization, complete external raw XML interchange,
NULL and NetVar-parent semantics, mixed/decorated copies, Project-OID hierarchy,
full original GUI, hardware and power-cycle acceptance remain open. The ledger
remains 18/42 categories (42.86%); that category ratio is not a verified
functionality percentage. The functional denominator is incomplete and zero
obligations are fully accepted.
