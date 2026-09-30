# Known-serial commissioning into a loaded project

The Python Toolkit CLI now reconciles a verified direct or routed serial move
into an exclusively owned, closed cmqttd C-Gate project and proves the saved
result through actual SAVE/CLOSE/LOAD. Only the matching Unit Address and its
stored PP `UnitAddress` change. OIDs, other programming, metadata, topology and
references from other units remain bound to the original whole project.

This delivers the loaded-project software milestone in issue #32. The supported
physical move selects one known serial at duplicate address 255 and an empty
nonlocal destination. Displacement cycles, unknown-serial fallback, wider device
profiles and native/hardware commissioning acceptance remain outstanding.

## Completed behavior

- Direct and one-to-six-bridge routed journals can plan and apply a loaded
  database move. Routed C-Gate operations require the same original raw export
  as the physical plan, supplied explicitly through `--route-project`.
- Native DBGETXML exports work unchanged in Python and Rust: `Project.Address`
  supplies identity when legacy `TagName` is absent. Missing, duplicate or
  explicitly blank identity is refused.
- An uncertain Python apply can be followed by a fresh direct/routed read-only
  verification handoff. The original journal and canonical marker remain
  unchanged. A completed Rust apply-v2 journal is independently reparsed by
  Python before loaded-project reconciliation.
- C-Gate records bind complete original/candidate content, native Unit digests,
  the physical proof, backup identity and saved readback. Backup contents are
  checked, with only the copied repository project name normalized.
- Fresh whole-project, topology, immutable-route-file and closed/idle checks
  run after durable intent and immediately before database mutation, baseline
  SAVE, backup COPY, target SAVE and CLOSE.
- Pending recovery classifies the saved original or exact candidate. A saved
  candidate completes through readback. A saved original requires explicit
  `--retry-database --apply`; recovery never repeats the physical address
  command or automatically rolls back and saves an uncertain operation.
- Completed records validate current whole-project content before reporting a
  no-op. Foreign loaded edits, stale routes, poisoned records and contradictory
  marker operation/flags/scope refuse without authorizing a write.

[The operator guide](known-serial-commissioning-journey.md) contains direct and
routed commands, ownership requirements and recovery instructions. The updated
repository AI skill documents the same public API.

## Acceptance

The [current acceptance receipt](acceptance/2026-10-01-loaded-project-commissioning/acceptance.json)
links the source and isolated installed-wheel executions, current source/test/
Rust fingerprints, actual binary and wheel hashes, command artifacts and
declared privacy transformations. Unique parent tests and subtests are recorded
separately. The selected native vendor test is explicitly excluded; no native
or hardware gate is credited as passing.

The final source and installed-wheel selections each passed **229 unique parent
tests and 822 subtests**, with zero failures, errors or runtime skips. The fresh
wheel's SHA-256 is
`24b82dad0caeb7ab35e277693e9ee46e913bf8059918ae132b1a73495611f6fc`;
all 324 packaged Python/JSON files match the executed source exactly. The public
receipt retains 52 declared evidence derivatives.

Each environment executes 247 actual public CLI subprocesses: 112 in the direct
profile and 135 in the routed profile. Each profile makes exactly one literal
address request to its independently defined PCI fixture. A deliberately corrupt
reply leaves apply uncertain; a new process verifies the exact expected inventory
and exports the handoff. Reconcile then verifies backup, saved persistence,
whole-project preservation and a fresh-process no-op.

Ten interruptions per profile cover database write/verification, target SAVE,
CLOSE, LOAD and saved-readback completion. Those faults are injected into the
library in the producer process; recovery uses fresh public CLI subprocesses.
They are distinct execution boundaries. Eight record and three direct/four
routed handoff tamper cases refuse without project changes. Routed acceptance
also checks stale snapshot bytes and an actual conflicting loaded topology.
Focused tests cover uncertain baseline SAVE/COPY, foreign edits, all closed/idle
runtime guards and edits made after durable intent. Six-bridge and actual Rust
apply-v2 integration use the rebuilt public Rust CLI.

Rust validation includes 13 focused route tests, formatting, workspace Clippy
with warnings denied and a release workspace build. The two servers remained
byte-identical after optimization, while the Rust CLI changed to accept native
route snapshots. All six existing compatibility comparisons were genuinely
rerun and revalidated against the current source closure: each backend matches
9 SESSION_ID cases, 11 tagged cases, 12 exact Unit wire cases and two combined
Network checks. The receipts contain 1,045 verified source bindings. These are
comparisons against retained original captures, not fresh original execution.

The static census covers 611 test modules. Its native selection remains
byte-identical. Full local suites were not run, following the requested focused
testing policy. Full CI is monitored separately and is not inferred from these
local results.

## Evidence qualifications and remaining work

Raw argv, exits, stdout/stderr, literal PCI frames, project exports, backups,
journals, markers, records and durable daemon state are retained privately.
The public derivatives replace declared local coordinates with roles and retain
their original SHA-256 and transformation lineage. Coordinate-bearing CLI JSON
is transformed in both text and its corresponding UTF-8 hex representation;
protocol frame bytes remain unchanged. Owned processes and listeners are checked
after cleanup. The six-comparison cleanup manifest distinguishes sampled children
from fast mock children terminated/waited by their maintained producers.

Initial combined source/wheel runs exposed a test setup defect: new guards
borrowed a cached journal directory that an earlier test module had deleted.
Each guard now owns its evidence through a real fixture move. The failed runs
and exact ordering reproduction remain available; assertions were preserved and
final acceptance was repeated with a fresh wheel. Earlier native-export refusal
and exploratory producer failures remain historical, uncredited evidence.
The two previous direct-journey fixtures are preserved byte-for-byte.

Native Installation/Project/Network child ordering is treated as immaterial by
the project digest. Arbitrary ordered extension siblings at those levels are
outside this batch's accepted preservation scope; the receipt covers the exported
native fixture model and keeps ordered data inside opaque nested nodes in scope.

The broader compatibility ledger remains **18/42 (42.86%)**. That historical
category count is not a functionality estimate: the functional denominator is
incomplete and no obligation is fully accepted across its required software,
native and hardware dimensions. This batch does not close all of issue #32 or
claim full Toolkit/C-Gate parity.

Remaining commissioning work includes occupied-address displacement,
unknown-serial fallback, broader unit/firmware cases, typed new-network setup,
original Toolkit/native C-Gate workflow comparison, live bridge acceptance and
power-cycle persistence. No house address was changed. Existing lighting-test
authorization was not used to commission house units.
