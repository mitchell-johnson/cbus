# CI integration corrections after the DLT physical workflow

This corrective batch follows `1f5788dadf09ec460560768dc08f8da7503c9ced`.
It addresses the independent UnitName namespaces, the generated native-gate
census, and the conflict between explicit deployment retry and physical PP
session invalidation. It does not add a new Toolkit parity claim.

## Retained failures

The spec-free Rust interoperability tests previously treated scalar UnitName
as a PP reset default. The two affected tests are
`RustInteropTests::test_create_unit_parameter_round_trip` and
`RustInteropTests::test_parameter_replies_terminate_with_native_315` in
`tests/test_rust_cgate_interop.py`. A local run against the published release
mock reproduced both failures. The same original tests passed with a private
synthetic specification, which explains why a catalogue-backed check could
miss this configuration difference. These are separate observations from the
earlier CI failures reported for `8402`.

The native-gate census also remained at 602 modules after the tracked test
tree grew. The maintained generator's `--check` rejected that census; its
fresh output counts 607 modules, including 288 with skip sites and 319
without. The native profile still requires and selects 258 gated tests.
`research/release-gates/native.json` is unchanged; its SHA-256 is
`f720bc657a2613a5cbcf361173cbc936f0971ac056757b85cbac6537b60b756c`.

The coordinator reported a genuine new failure in
[CI run 36773002191, Rust job 110083845449](https://github.com/mitchell-johnson/cbus/actions/runs/36773002191/job/110083845449).
The unchanged `native_programmer_lifecycle_replays_against_cmqttd` case
`deploy_fault_partial_and_retry` expected `P2 STOPPED` with
`remainingSeconds: 0`, but received `ERROR` with `remainingSeconds: 3`.
A local replay reproduced that failure. A lost acknowledgment invalidated
the physical PP session; explicit `DEPLOY_QUEUE RETRY P2` then tried to
reuse that session without another physical LOAD. Original red and
intermediate failed outputs remain in private evidence outside Git.

The sole CI reviewer subsequently reported that this published run finished
with FAILURE. Both offline source and installed-wheel selections failed the
same stale census check, the mock selection failed the two UnitName tests,
and Rust failed the explicit-retry lifecycle case. The cmqttd Python selection
passed 137 tests with one skip; native/physical jobs were skipped. These are
results for the previous published commit, not for this correction. CI for
the eventual corrective commit requires its own exact-SHA result.

## Independent scalar and PP unit names

The tests now assert the actual namespaces independently. Creating a
spec-free unit retains scalar `UnitName=KEY1`, while the loaded PP session
has no `UnitName` entry and PP GET returns 460. QUICKGET retains its existing
scalar fallback without inventing a PP field. A framing fixture explicitly
stages and saves `PP UnitName=PPNAME`, requires the exact
`315 UnitName=PPNAME` response, and verifies complete XML still contains
scalar `UnitName=KEY1` alongside the distinct PP value. The explicit
UnitAddress SAVE/LOAD round trip cannot alter either namespace.

The catalogue-backed branch retains its existing NEWUNIT reset-default and
UnitAddress assertions. No product default or response code was changed to
make these tests pass.

## Explicit deployment retry

Only an accepted explicit DEPLOY_QUEUE RETRY enables recovery. Before replay,
the worker admits every invalidated physical session and verifies the original
owner of every PP_SET/PP_SAVE that refers to it. Each dirty parameter must have
an initial PP_SET before that session's first PP_SAVE. Encoding the staged
typed values against the retained physical image must reproduce every changed
raw byte, including shared bits. Unknown schema parameters or unrelated edits
are refused before any recovery read or physical write.

The worker then performs fresh physical LOADs under the original instruction
connection, requiring the same canonical source, unit type, firmware and lock.
Each LOAD has a dedicated service attempt and commits only on its captured
current PCI generation. A failed or mismatched read restores the staged
evidence and leaves physical identity invalidated. If a later session fails,
earlier prepared sessions are also restored when they still equal their
recorded prepared snapshots. Concurrent edits or recreated sessions are never
overwritten by that restoration.

The RETRY marker is installed atomically with requeueing. The connection that
issues RETRY does not acquire the original PP session. START and ordinary SAVE
retain their existing refusals and never perform this recovery automatically.
A deliberate manual fresh LOAD continues to use the ordinary loaded-session
contract. The native lifecycle test and its STOPPED/zero-time expectations
remain unchanged.

Six added controls cover unrestaged dirty values and raw/shared bits, failed
reads and identity conflict, session recreation and PCI replacement, missing
owner/source/lock, mixed instruction origins, and a later session failure with
both unchanged and concurrently edited earlier sessions. They assert retained
evidence and the relevant absence of physical writes.

## Validation and publication boundary

Before the additional Rust correction, both UnitName tests passed from source
and the previously verified installed wheel, with and without a synthetic
specification: two parents per run, no failures, errors, or skips. All 324
installed package Python/JSON files matched source. Source and installed
census/release-gate checks each passed 11 parents without skips. Two genuine
Unit XML replays each matched 12 exact-wire cases and two combined Network
cases. Those binary/source-bound results are retained as pre-Rust-correction
evidence, not final acceptance of a changed Rust service.

Final frozen Rust validation passed 24 tests without failures or skips: six
retry controls, seven loaded-identity safeguards, eight physical SAVE
regressions, routed LOAD/SAVE, PP session lifecycle, and the unchanged native
lifecycle replay. Before/after source hashes bind those results. The initial
red run did not sample source or binary hashes at execution; one intermediate
compiler log was overwritten by the first passing lifecycle log, while its
diagnostics remain in the tool transcript. These limitations are retained
explicitly rather than reconstructed as observed evidence.

The final release workspace build, formatting check and workspace/all-target
Clippy check with warnings denied passed. The recorded commands are
`cargo +1.92.0 fmt --all --check`,
`cargo +1.98.1 clippy --workspace --all-targets -- -D warnings`, and
`cargo +1.92.0 build --release --workspace`, run from `rust/`.

Six genuine fresh replays against those rebuilt binaries passed. Each backend
matched nine SESSION_ID cases, eleven numeric-tagged SESSION_ID cases, twelve
exact Unit XML wire cases and two combined Network cases. The root independently
regenerated each declared privacy derivative with the maintained helper,
required byte equality, checked all 1,045 source bindings, and copied the
validated canonical receipts. Original commands, raw outputs and bytes are
archived outside Git. Four of six server PIDs were sampled; the two fast mock
children were not. All four producers exited after their maintained cleanup,
observed endpoints were closed, and no release server processes remained.

The contract inventory, SESSION_ID physical applicability and packaged parity
files were genuinely regenerated and checked. The inventory still has 431
primary and 11 supplement paths; the register has 487 provisional obligations
and 22,103 source-scope items with `census_complete=false`. Their regeneration
does not resolve any additional acceptance axis or complete the denominator.

A fresh wheel was built from the final package and installed with offline
`uv pip install --no-deps --reinstall` into a new Python 3.13 environment.
All 324 package Python/JSON files match source, actual import origins were
checked, and the installed `cbus-toolkit --help` entry point exited zero.

| Final focused selection | Source parents | Installed-wheel parents |
| --- | ---: | ---: |
| UnitName, census, release-gate and Unit XML receipt checks | 16 | 16 |
| Current contract/parity/session evidence and DLT/generic physical workflows | 39 | 39 |
| Unique total, with no failures/errors/skips | **55** | **55** |
| Two UnitName nodes repeated with synthetic catalogue | 2 repeats | 2 repeats |

Each unique selection also passed 54 subtests, which are not added to parent
counts. Each environment recorded 144 public CLI calls with their outputs:
128 exited zero, 15 exited one for expected refusals/recovery cases, and one
exited 130 for the intended interruption. Source, tests, artifacts and import
bindings remained stable. Owned mock processes were terminal and no owned
cmqttd processes remained.

Early harness failures are retained separately: loopback listeners were
sandbox-blocked, and one preliminary selection omitted the unittest class in
six node IDs. The corrected final selections ran with owned loopback access.
These attempts are not credited as passing acceptance or new unique tests.

The [acceptance receipt](acceptance/2026-10-01-ci-integration-corrections/acceptance.json)
links 59 coordinate-sanitized evidence derivatives to their exact private raw
SHA-256 values, including JUnit, command traces, retained red output, build and
validation records. Acceptance executed with HEAD at the preceding commit
and the corrective working-tree files present; fingerprints and staged-byte
checks bind the actual executed sources. The preceding commit alone is not
claimed to contain this correction. Historical DLT acceptance receipts remain
unchanged checkpoints.

Final release hashes:

- `cmqttd`: `f8e9ec1ed5473b991d9477c4f73ce6be3fbf68e1833ab72b73f715b65219615a`
- `cgate-mock`: `6ad6647caf24ace9498b51fdc40b069ebbe26bbc4cc35be7ed5d8e8569d52090`
- fresh wheel: `d9bb137485176c4a592e5d56c86f923a5b79fa92b4561b7fc715975a295bb586`

No full test suite, native release gate, Windows Toolkit session, real CNI,
broker, hardware programming, or power-cycle acceptance is claimed by this
correction. Full Toolkit and C-Gate behavioral parity remains unfinished;
the broad ledger remains 18/42 (42.86%).
