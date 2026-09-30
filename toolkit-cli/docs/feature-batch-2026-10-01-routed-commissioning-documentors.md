# Routed commissioning, reconciliation and documentors

This batch follows `3c25ea86` and integrates six audited source revisions,
plus a reviewed Rust/Python journal-path correction found during acceptance.
It implements missing routed Rust execution and independent offline project
reconciliation, together with bounded Bytecraft and SceneModify report bodies
and dependencies. The broad ledger remains 18/42 (42.86%); the functional
denominator is incomplete, so a functionality percentage is unavailable.

| Source chain | Implemented behavior | Remaining acceptance |
| --- | --- | --- |
| Rust/Python `b7c8aa9b` → `2abc4ab3` → `756a1eb1` | Project-bound one-to-six-bridge Rust apply/verify; complete routed inventories; durable intent/marker/endpoint lease; one-shot send and read-only recovery; versioned original/parser frame evidence independently validated by Python before XML/CBZ reconciliation; backup/freshness/fsync/restart guards. | Original routed selected-serial mutation, live bridge delivery, physical firmware/persistence, broader duplicate/occupied-address workflows and routed C-Gate reconciliation. |
| Documentors `5fdf0b4f` → `28201602` | Old DIMPR12 twelve-channel/DMX/restore/curve/fade/scene body, packed 33-record scene decoder and independent usage; canonical NeoClassic SceneModify consumers with bounded dependencies. | DIMPR12A/L1, later firmware, initialized GUI history, original complete loaders, full-page byte/visual comparison, printing/cancel, broader bodies and physical acceptance. |
| IOPE `cd33ff7b` | Regular-file admission, nonblocking descriptor open/fstat, bounded actual bytes and closure for snapshot/edit/plan JSON; tiny FIFO and substitution regressions refuse before client construction. Four affected native matrices were genuinely reaccepted, followed by combined source/wheel acceptance. | Regular-file substitutions remain admitted; no immutable snapshot claim. Complete original forms and physical acceptance remain open. |

Rust apply-v2 evidence is an operator-controlled commissioning-frame proof,
not authenticated connection history. The independent Python validator
reparses original and parser copies, constrains checksum/terminator
normalization, reconstructs exact inventories and request/receipt relationships,
and requires matching route, project digest, local identity/options and
surviving canonical attempt marker. Uncertain, partial or contradictory proof
refuses before database writes. Direct v1 behavior and existing MQTT/C-Gate
operation remain separate. See [routed Rust contract](../../docs/rust-selected-serial-routed.md)
and [reconciliation](physical-addressing.md).

Documentors require complete explicit consumed data and exact class/firmware
admission. Unknown dependencies retain unresolved markers. All 19 supporting
module hashes in the retained static receipt agree with the integrated source;
no nonexistent DALI/SENLL documentor entries were added. See
[Bytecraft body](project-documentation-bytecraft.md),
[packed scenes](project-documentation-bytecraft-loader.md),
[usage](project-documentation-bytecraft-usage.md) and
[NeoClassic usage](project-documentation-neoclassic-usage.md).

The [IOPE input contract](iope-json-inputs.md) adds the ready four-file
reader correction. Historical native fixtures are preserved by fingerprint;
four owned current-source matrix proofs were rerun before combined acceptance
to establish fresh bindings without weakening retained-receipt guards.

The combined run exposed a real operator-path interoperability defect. Rust
records the supplied absolute journal path in its evidence but canonicalizes
the parent for its durable attempt marker. Python now checks that same parent
contract while preserving the exact caller-bound journal name. A genuine Rust
CLI regression admits a symlinked parent and refuses an unrelated marker
journal, wrong scope, rebound alias and journal filename symlink. Marker file
symlinks also refuse. These checks do not establish a filesystem lock or atomic
protection against a concurrent path change.

## Accepted validation

| Check | Actual result |
| --- | --- |
| Frozen Python source | 1,159 normal test nodes and 1,304 subtests passed; zero failures/skips; nine exact nodes excluded before execution. |
| Isolated installed wheel | The same 1,159 nodes and 1,304 subtests passed with the same exclusions; all 192 product module imports and 180 completed product-process audit records bind installed files. |
| Rust | Formatting, workspace/all-target Clippy with warnings denied, and the release workspace build passed. 151 distinct focused tests passed with no failures/ignored tests, including seven MQTT preservation tests. No full workspace test suite ran. |
| Current `SESSION_ID` comparisons | 40 cases passed: nine plain and eleven tagged cases against each of `cgate-mock` and cmqttd, with four strict current-receipt validators. These compare retained original captures, not a fresh original-runtime execution. |
| IOPE reader native prephase | Four affected producer methods and 27 subtests passed before registration/final acceptance. Their original imported component bytes remain current. |
| Journal alias regression | Eight tests and 48 subtests passed against the actual current Rust release binary before the combined run. |

These counts overlap and must not be added. The combined selection contains
52 modules: six serial, 28 documentor, 15 IOPE, one alias module and two session
comparison modules, plus three exact coverage/register guards. The earlier
49-module estimate missed three existing IOPE modules; the original glob scope
was retained. Nine original instruction/runtime or optional native
reconciliation producers were excluded before any test executed. Static
EXE/MAP/specification inspection is separately admitted. No real network,
broker, USB or physical device was contacted.

The [combined receipt](acceptance/2026-10-01-routed-commissioning/acceptance.json)
binds all 321 source, wheel and installed product files and 2,753 reference
inputs. References stayed in place and were hashed before/after execution;
they were not copied into an isolated reference snapshot. Research helpers can
insert the source directory, so the wheel runner explicitly restricts product
resolution to installed files and audits product-importing subprocesses.
Each context recorded 3,477 disk-resource samples; minimum free space exceeded
4 GB. See the [Rust receipt](acceptance/2026-10-01-routed-commissioning/rust-focused-acceptance.json),
[alias receipt](acceptance/2026-10-01-routed-commissioning/alias-fix-acceptance.json)
and [independent root audit](acceptance/2026-10-01-routed-commissioning/root-validation.json).

The imported IOPE workflow matrix method executes under two collected node
IDs. Four matrix definitions therefore produce five matrix call nodes in each
context; the shared workflow report retains the last successful write, while
both passing call outcomes are preserved. The separately retained settings
report lacks service lifecycle fields; its owned session teardown passed.
Four matrix services have explicit cleanup evidence in each context. CNI
connection counts were not independently measured. These are closed synthetic
database persistence checks, not full Toolkit forms or hardware acceptance.
Three registration JSON files and the alias validator differ from the native
prephase package map; the final acceptance separately binds the current package.

## Preserved failures and evidence limits

Acceptance was not an uninterrupted green run. An initial sandbox attempt
stopped in collection with 52 loopback-admission errors and zero executed
tests, followed by an old-runner missing-gate error. The first admitted source
run exposed seven interoperability setup errors from the journal-path bug.
It also encountered ENOSPC during a selected-serial case and pytest capture,
causing later setup/teardown errors. Its 1,307 JUnit error elements are phase
events, not 1,307 distinct failing tests. All logs, receipts, JUnit hashes and
the unexecuted superseded wheel remain preserved in the combined receipt.
The reviewed two-file product fix and ordered, sampled resource guards preceded
the fresh source/wheel runs; no observation timeout caused a repeat.

Automatic approval review rejected both a broad external reference export and
a narrower external product export. The accepted alternative built and ran
entirely in an owned internal temporary directory. External vendor/runtime,
public dependencies and the exact Rust binary were read only; no external
export was retried. Raw artifacts remain private, with their exact hashes and
declared public derivatives preserved. Historical receipts are not relabeled
as fresh acceptance.

The historical routed receipt is a declared sanitized derivative: only the
private host-name role is normalized, with the raw original fingerprint and
all source/native hashes, commands, results and remaining gates preserved. Raw
original evidence remains private. Rust build artifacts used an owned local
external directory; Python acceptance used the permitted internal alternative.
No prior private environment files, credentials or vendor binaries were exported.
