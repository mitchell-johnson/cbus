# Deterministic mock delivery bounds after Linux CI

This follow-up to the [three-feature batch](feature-batch-2026-10-02-cached-csv-event-bounds.md)
corrects a test timing assumption exposed by
[run 36963616488](https://github.com/mitchell-johnson/cbus/actions/runs/36963616488)
on published `09b1be1e`. Its Rust job failed one slow-subscriber TCP test;
six sibling TCP tests passed. The original local gates remain historical
executions and are not rebound to this correction.

## Failure and change

The old test sent up to 1,600 events through serial producer round trips and
required count overflow to retire a nonreading subscriber. On Linux the
independent ten-second active-batch write deadline won first. The recorded
diagnostic was `outbound socket write timed out; pending receipts are unconfirmed`.
That is a supported bounded retirement path. Serial producer pacing did not
establish that 512 pending batches must accumulate before the writer deadline.

The TCP journeys now require either their applicable capacity diagnostic or
the writer deadline. They retain unrelated-client latency and filtering,
session removal, buffered-prefix EOF/reset, incomplete-upload cancellation and
no replay after reconnect. They stop generating events after observed removal.
Their names describe bounded retirement rather than an OS-dependent cap winner.

Two additional controlled-writer tests use the production `channel()` and its
actual limits. A handshake proves the writer owns one pending active batch.
With paused time, one active plus 511 queued batches fills the 512 count budget
while more than half the byte budget remains free. Separately, an active 16 MiB
payload plus one queued 16 MiB payload fills the 32 MiB byte budget while 510
count permits remain. Each next admission fails with the exact applicable
diagnostic, cancellation drops the writer and releases every permit, and no
socket timeout or kernel-buffer assumption supplies the result.

All helper changes are inside `#[cfg(test)]`. The 6,433-byte production prefix
is identical to `09b1be1e` (SHA-256
`8ddd018e5ee0ec0b64f52fa8771d34c0b790616cf2f4c5295e07cc4ca426872a`).
No runtime limit, admission, writer, cancellation or reader behavior changes.

## Verification and provenance

The [bounded follow-up receipt](../research/fixtures/mock-delivery-ci-fix-owned-release-20261002.json)
records a separate execution context:

- 17 focused parents pass: nine delivery helpers, seven TCP interactions and
  the existing overflow-after-execution uncertainty case. These are included
  in the workspace total below.
- Required format, Clippy, workspace tests and release build all pass. The
  workspace has 8,692 passes, zero failures and one ignored private-project
  input case; all 440 Rust input files remain quiet during the gates.
- Newly built, separately frozen release binaries are byte-identical to the
  preceding batch. Four maintained comparison drivers produce six fresh
  backend results: 64 primary cases and four combined checks pass. The fresh
  receipts carry 1,141 current bindings over 213 distinct source paths.
- Each final source and fresh noneditable wheel selection passes 167 parents
  and 552 separate subtests with no skips or failures. The JUnit aggregate is
  719, rather than 719 parent tests. All 3,671 input files and frozen binaries
  remain quiet; all 329 source/ZIP/installed Python and JSON files match. The
  actual wheel pytest process has verified startup and terminal import guards,
  with zero violations.

Metadata refresh explicitly omits `build-interop` because the completed release
gate supplies the verified binaries. All generators and comparison commands
execute; raw observations are archived before maintained coordinate sanitation.
Nine resource files change, including two packaged parity JSON files; no
Python implementation file changes. Earlier 650-parent and 167-parent contexts
remain historical. The full Python and broad maintained interop suites are not
repeated for this test-only correction.

Corrected Linux execution and publication CI success remain unclaimed until
the corrected revision runs in GitHub Actions. The final follow-up prose, the
earlier note's distinction between #73 and #74, and the sanitized receipt are
explicit post-consumer publication deltas.
The original failure log is retained with SHA-256
`8c0ad85b346ef1e6e059b0c5d2e37812e9f64fa1888eed461d6158300239b0de`.
An empty earlier `gh` log is a failed preparation attempt, not test evidence.

Transient disk exhaustion prevented the first focused launch; it receives no
test-execution credit. Disposable compiler object files were removed after an
inactive-compiler check. A completed wheel staging directory was archived,
reopened and verified file by file before removal. Original logs, receipts,
wheels, installations and test artifacts remain preserved; the archive is
restorable. Failed archive preparation is retained separately.

## Acceptance boundary

These are owned mock bounds and TCP interaction tests. They establish no
original C-Gate overflow/timing contract, physical programming behavior or
full Toolkit parity. The broader work in #37/#54 and other parity issues stays
open. The open #73 selector work and cyber-deferred #74 work remain untouched.
