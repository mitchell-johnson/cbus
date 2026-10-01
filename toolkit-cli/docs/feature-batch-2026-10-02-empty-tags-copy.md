# Copying associated Levels with an empty label collection

The Rust C-Gate service and Python Toolkit CLI support copying an admitted Level
after save/reload has materialized its empty `TagsDLT` collection. This extends
the [associated owner repair](feature-batch-2026-10-02-associated-levels.md): the
renamed secondary Network still resolves to its original numeric database
owner, and the destination remains a child of its actual Group or NetVar.

The admitted payload is absent or exactly one unnamespaced, attribute-free
`TagsDLT` element with no children except whitespace. A deferred LOAD marker is
also preserved. Nonempty labels, attributes, namespace declarations including
`xmlns:xml`, comments, processing instructions, declarations, BOM and arbitrary
retained data return controlled refusal before mutation. These are modeled
preservation boundaries, not original error-code acceptance.

## Operator workflow

Start with an existing loaded secondary project `LAB`, numeric Network `11`
whose associated tag Address is `Renamed`, Application `56`, source Group `1`,
destination Group `2` and source Level `7`. These names are fixture examples;
use your actual database objects and service endpoint. The configured hardware
project's existing rename restriction remains.

```sh
cbus-toolkit cgate project save LAB
cbus-toolkit cgate project close LAB
cbus-toolkit cgate project load LAB
cbus-toolkit cgate database copy //LAB/Renamed/56/1/7 \
  //LAB/Renamed/56/2 10 Reading --project LAB
cbus-toolkit cgate database get //LAB/Renamed/56/2/10/Value --project LAB
cbus-toolkit cgate project save LAB
cbus-toolkit cgate project close LAB
cbus-toolkit cgate project load LAB
```

Typed copy requires a fresh `301 OID`, verifies that identity and initializes
Value=10 on the same selected connection. Raw SAFE and unsafe COPY retain source
Value; unsafe copy remains incomplete until its required identity fields are
supplied. Neither form implicitly saves. Collision and LOGIN refusals stop
before initialization or replay.

COPY stages the whole operation, leaves source XML bytes unchanged and uses
canonical `<TagsDLT/>` on the destination. A deferred marker keeps its existing
LOAD timing. Scoped semantic recognition prevents a second empty collection
when retained source whitespace accompanies that marker. It creates no
synthetic pending mirror and does not change typed NULL getters. Independent,
foreign, unassociated numeric and unrecognized payload policies remain scoped
to their previous owners.

## Validation

Fresh integrated validation passed against the frozen Rust 1.99 release
binaries. The [bounded release receipt](../research/fixtures/empty-tags-owned-release-20261002.json)
records the actual source and artifact hashes, commands, results and remaining
acceptance limits:

- All four required Rust checks passed: formatting, workspace/all-target Clippy
  with warnings denied, workspace tests and release workspace build. Tests
  passed 8,641 with zero failures and one ignored private-project case. The 41
  named-database module tests are included in that total.
- Source and an isolated installed Python 3.13 wheel each passed eight public
  CLI journeys without failures or skips. All 326 package files matched between
  source, wheel and installation. Each environment recorded 150 CLI calls,
  including 74 wire-captured connections with 200 tagged commands. Eleven owned
  processes closed; fake PCI peers saw 64 initialization frames and no later
  frames or closed-graph trap contacts. The existing 76 calls retain argv, exit
  and JSON evidence; they have no new wire-capture credit.
- Maintained interop passed 22 mock, 156 daemon and two framing parent tests.
  The mock and daemon runs also reported 158 and 69 passing subtests. Two
  vendor-specification-dependent parents were skipped.
- Six modeled comparisons were refreshed against retained original captures.
  Their maintained publication markers bind literal execution inputs directly;
  all 1,111 source bindings were current. Evidence generation/checks and all
  261 affected consumer parent tests passed, with 934 separately reported
  passing subtests and one original-input regeneration skip.

Independent static reviews closed three XML classifier/LOAD findings and two
CLI oracle gaps before integration. The evidence authors then cross-reviewed
components they did not author; the root independently recounted logs, raw
commands, terminal replies, process cleanup, package bytes and JUnit parents.
These reviews add no execution credit. Publication prose was completed after
the tests; the receipt records that documentation-only delta separately from
the unchanged 19 source/test/vector/guide/generated-resource pins.

The full Python suite was not repeated for this extension. The preceding
checkpoint's 14 publication-format failures and selected correction remain
historical evidence; the current selected passes do not establish a final
full-suite pass.

The same batch removes two redundant `&remap` closure borrows flagged by Rust
1.99 Clippy in [the preceding main-push CI](https://github.com/mitchell-johnson/cbus/actions/runs/36907124421).
The immutable closure is copied by value; network path remapping behavior is
unchanged. Validation uses the same Rust 1.99 compiler as that CI.

Public tests cover raw source Value, explicit typed initialization, fresh OIDs,
exact destination path, source and unrelated whole-graph preservation, repeated
LOAD, fresh daemon JSON restart, collision and LOGIN refusal without an
initializer or replay. Their local wire expectations are in
`rust/testdata/vectors/cgate_associated_empty_tags_cli_wire.json`.

Controlled retained-snapshot library tests separately cover namespaces,
attributes, comments/PI/text, declaration/BOM and leading whitespace plus a
saved marker. Fresh strict DBSETXML canonicalizes supported empty collections;
these retained-snapshot edges have no public CLI or original-execution credit.

Nonempty label copy and label OID allocation, general/Unit/cross-owner copying,
raw/NULL/NetVar schema semantics, Project-OID XML hierarchy, full original GUI,
hardware and power-cycle acceptance remain open. Original renamed-associated
comparison is deferred under [issue #72](https://github.com/mitchell-johnson/cbus/issues/72).
No original, vendor, VM or hardware execution is credited by this batch.
The broad ledger remains 18/42 categories (42.86%), not a verified functionality
percentage; the functional denominator is incomplete and zero obligations are
fully accepted.

## Later review: deferred corrections

Known associated-owner bugs are deferred in [issue #74](https://github.com/mitchell-johnson/cbus/issues/74):
canonical numeric Group COPY destinations return `401`, while renamed lexical
paths and Group OIDs succeed for admitted byte copies. The newer LOAD sweep
can also alter unsupported retained XML on a plain Level with a deferred empty
label marker. Those payloads are outside the accepted LOAD profile. A separate
missing-descendant Value-getter fallback is an unverified source-review
hypothesis. The attempted fixture failed before that edge executed. These
corrections were stopped by cyber protection; no private untested edits are
integrated or credited.
