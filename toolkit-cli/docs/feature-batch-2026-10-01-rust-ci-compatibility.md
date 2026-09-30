# Rust CI compatibility follow-up

The routed commissioning batch was published as
`4f1b604b81a4e63af343c39e583d13399aa6f2e3`. Its local Rust acceptance used
Rust 1.92.0. GitHub's Rust workspace job used Rust 1.98.1 and failed during
Clippy, before the workspace tests or release build ran:
[`clippy::chunks_exact_to_as_chunks`](https://github.com/mitchell-johnson/cbus/actions/runs/36728608029/job/109931899331)
rejected a four-byte chunk iterator in the commissioning test helper under
`-D warnings`.

This follow-up replaces `chunks_exact(4)` with `as_chunks::<4>().0` in
`rust/cbus-tools/tests/serial_commissioning.rs`. Both process complete groups
of four bytes and discard a partial tail. The change adds no lint suppression
and fits the documented current-stable Rust requirement. Production Rust,
Python, native fixtures and the earlier acceptance receipts are unchanged.

## Validation

The [follow-up receipt](acceptance/2026-10-01-routed-commissioning/clippy-fixture-followup.json)
records exact commands, tool versions, source fingerprints and raw-log hashes.
Independent review verified all 410 Rust source bindings and the four logs.

| Check | Result |
| --- | --- |
| Rust 1.92.0 formatting check | Passed. |
| Rust 1.98.1 workspace/all-target Clippy, warnings denied | Passed, offline and locked. This matches the failed CI job's installed toolchain. |
| Rust 1.92.0 commissioning integration tests | 32 distinct tests passed; zero failures or ignored tests. |
| Rust 1.92.0 release workspace build | Passed; all five release binary hashes match the earlier accepted binaries. |

These 32 tests repeat the earlier commissioning selection; they must not be
added to its 151 distinct focused Rust tests. No full local workspace or Python
suite ran for this test-only correction. The follow-up claims no new native,
original-runtime, physical or `SESSION_ID` acceptance. Owned loopback peers
were used for the affected integration tests.

The failed GitHub run remains a failed run. A passing local reproduction does
not establish that a subsequent GitHub run passed; verify the workflow for the
published follow-up revision separately. Historical receipts retain their
original bindings and limitations. See the
[feature batch report](feature-batch-2026-10-01-routed-commissioning-documentors.md)
for implemented behavior and outstanding acceptance. The broad ledger remains
18/42 (42.86%); the functional denominator is incomplete.
