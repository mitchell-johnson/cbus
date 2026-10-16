# Durable CGL Application order — 4–5 October 2026

Issue [123](https://github.com/mitchell-johnson/cbus/issues/123) addresses the
captured Application export order hidden by address-sorting comparators.
The C-Gate fixture and historical capture script remain unchanged. The current
projection changes exactly `cgl-validation-23`: 0,66,71,72 becomes 72,0,71,66.
Application 255 remains filtered from export while its retained prefix is tested
inside the owned model. Group/Level order and native identity/readback gaps stay
under [25](https://github.com/mitchell-johnson/cbus/issues/25).

## Implementation

A Network-owned serde field keeps tracked creation order, with a default unknown
history marker for older repositories. Shared insertion, pending completion,
readdress, delete, complete replacement and Network-copy paths keep it current.
Project/database snapshots, copies, daemon restart and internal archives retain
it. Foreign XML/admitted SQLite restore has unknown chronology. This is
independent of the existing XML/OID selection index and runtime physical state.

The public CLI retains returned arrays and exercises both owned Rust services.
The captured raw address/null refusal cases can retain a successful prefix;
typed Python imports validate their entire document before transmission. Broader
nameless-object refusal behavior remains under issue 25. Uncertain imports are never
automatically replayed or undone. Read [the operator guide](cgl-application-order.md)
for commands and exact capability markers.

Two adjacent unsupported workflows found during review remain explicit:
numeric whole-Application DBCOPYSAFE ([124](https://github.com/mitchell-johnson/cbus/issues/124))
and Application DBSETSAFE Address setters ([125](https://github.com/mitchell-johnson/cbus/issues/125)).
The accepted copy/readdress coverage uses existing admitted commands; it does not
establish those typed SAFE workflows.

## Execution epochs

| Epoch | Actual outcome | Scope |
| --- | --- | --- |
| Static1 | 7 parent passes, no failure/skip/subtests|Earlier capture-only projection checks; superseded by Static2|
| Static2 | 20 parent passes, 2 original-server skips, 13 separate passing subtest events|Focused CGL/offline differential modules, 402 inputs quiet|
| Static3 | 120 parent passes, 14 separate passing subtest events, no failure/skip|CI declaration/import-runner guards, 408 inputs quiet|
| Rust1 |Formatting/Clippy pass; workspace test stops at 598 passes, 2 failed new regressions, 1 ignored|Failed epoch retained; no release/debug build ran|
| Rust narrow1 |19 parent passes across 10 owner, 4 private, 4 blackbox, 1 vector tests; no failures/ignores|Corrected test assumptions; strict 158-vector replay; 475 Rust inputs quiet|
| Static4 |120 parent passes plus 14 separate passing subtests, no failure/skip|Current CI/helper guards after issue 126 fixture correction; 408 inputs quiet|
| Rust2 |Formatting/Clippy pass; workspace stops at native trust-store I/O failure|Failed external-runtime epoch retained; no release/debug build|
| Trust probes |One exact workspace executable test and one narrower Cargo-selected test pass separately|Documented internal byte copy, original native trust configuration; not added to workspace totals|
| Rust3 |Formatting/Clippy pass; routed liveness module has 17 passes and one exact-receipt failure|Actual active response-stream loss differs from between-poll disconnect; later safety assertions were not reached|
| Routed liveness successor |18 passes, no failures/ignores|Issue 127 test-only exact-receipt correction; actual observed receipt was PCI disconnected; 475 inputs quiet|
| Rust4 mandatory gates |Formatting, Clippy, workspace tests and release workspace build all exit 0|103 logged test summaries total 8,748 passed, zero failed, one ignored; all 475 Rust inputs quiet|
| Rust4 supplementary command |Exit 101 before compilation: binary name used as package ID|Raw producer summary remains failed; required four-gate success is reported separately|
| Debug1 |Two correct package/bin builds exit 0|Fresh mock and daemon binaries; 475 Rust inputs quiet|
| Source1 |One parent pass, 16 failed new parents, 158 separate passing subtests|All new cases stop at seed DBCREATENET status mismatch; 4,173 inputs and both binaries quiet|
| Source2 |14 parent passes, three failures, 158 separate passing subtests|Copy needs active-project context; XML archive adds one DBVersion envelope leaf; 4,173 inputs and binaries quiet|
| Source3 |17 parent passes plus 158 separate passing subtests, no failure/skip|16 IDs: seven mock and nine daemon, plus one existing strict native-capture vector parent; 4,173 inputs and binaries quiet|
| Metadata1 |25 parent passes plus five separate passing subtests, no failure/skip|Fresh differential integrity, census and packaged parity metadata; 4,173 inputs quiet|

Rust1 failed because the new tests assumed a 342 scalar receipt for plain CGL
labels and canonical movement from an opaque SAFE Address setter. Test
successors use the actual modeled envelope/internal label store and admitted
same-session raw OID readdress. Production hooks were unchanged. A private test
also checks all retained labels including 255; this is not native scalar/XML
getter acceptance. Static collection alone of the 16 new backend IDs is preparation,
not body execution. Its first missing-test-path collection failure is retained.

Required Rust gates were run because this change crosses shared mutation and
persistence code. The single ignored case is
`service::tests::private_existing_database_project_dlt_upgrade`, requiring
`CBUS_PRIVATE_PROJECT_XML` and `CBUS_PRIVATE_CGATE_STATE`. Static2's two skipped
`NativeCGLTests` require an explicitly configured owned native C-Gate; they are
not native acceptance. The documented internal test runner preserved executable
bytes and arguments, performed no CA override, and cleaned its temporary copies.
All 96 recorded Rust4 runner invocations were independently checked.

Source3 uses the exact same-session public `cgate run` project-selection and copy
commands. Its archive assertion accepts only the independently observed single
plain `DBVersion=2.3` envelope leaf, then checks every remaining node and all eight
issued OIDs. No global XML normalization hides graph loss. The two failed source
epochs remain retained; their fixture corrections do not change production Rust.

Six current owned-service differential receipts were recaptured and sanitized
through the maintained coordinate-only producer: nine session, eleven tagged
session, and twelve direct plus two combined Unit cases per backend. Exactly six
derivatives and five generated contract/applicability/parity/census outputs
changed. Original fixtures, native acceptance manifests and pre-fix evidence
remain exact. All producer/check commands passed; these are owned model/service
receipts, not a new native or physical run.

Fresh Wheel1 completed in 185.668 seconds: seven mock and nine daemon IDs passed,
with zero failures, skips or subtests. All 395 source/build/wheel/installed package
files and 406 RECORD rows matched; all 4,173 declared inputs, copied test references
and both binaries stayed exact. Its strict origin audit verified 151 Python
processes and 18 owned Rust children, all reaped, with zero violations. Collection
and installed console smoke were checked separately. The source3 and wheel1 maps
differ only at the eleven deliberately refreshed metadata outputs; they are not
claimed to be the same whole input epoch.

Combined raw readback of Wheel1’s two backend phases recorded 149 CLI calls,
205 CLI commands plus 228 direct raw commands, 167 connections and 38 document
transfers (30 CLI plus eight raw) across the sixteen cases. Four expected CLI failures are two whole-document preflight refusals with
no commands and two actual upstream `200` replies dropped before the client,
with uncertainty reported and no replay. All eighteen server PIDs were cleaned;
the eleven daemon processes emitted only their 88 exact initialization frames,
with no later PCI traffic or closed-network trap contact. Source3's new sixteen
journals independently have the same descriptive totals; no JUnit/trace files
were merged to manufacture execution.

Only this final report and the new sanitized release receipt are postterminal
annotations. Production, tests, CI, capabilities and generated metadata remain
the exact wheel-tested bytes. The receipt records the complete baseline overlay
and hashes of the actual epoch/reader evidence. Python remains focused; no full
Python suite is run locally for this batch.

## Declaration and acceptance limits

The maintained default installed-Rust declaration now contains 1,007 explicit
selectors: 498 mock and 509 daemon, including the exact inherited 991 plus 16 new IDs.
Seven whole-module declarations remain. The full hosted declaration is separate
from a focused 16-ID local run; registration is not a full hosted pass.

Native capture scopes remain 13 scenarios / 163 structured rows, 161 source replay
rows with explicit equality exclusions, and 158 derived vectors. These counts
must not be presented as interchangeable original acceptance. No original
Toolkit/C-Gate, VM, house light, hardware provisioning or controller programming
is performed in this batch. No compatibility gate is promoted by these model
and owned-service checks. `coverage --require-complete` remains enforcing and
full Toolkit/C-Gate parity remains unfinished.

## Adjacent CI corrections and remaining work

Issue [127](https://github.com/mitchell-johnson/cbus/issues/127) corrects only the
routed NVM-loss test/vector: exactly one complete terminal must equal the source's
between-poll `PCI disconnected` or active `PCI response stream lost` receipt.
Every later execute-once, reconnect, staged readback, stale-completion, MQTT and
no-replay assertion remains byte-identical. The focused successor observed the
first receipt; the second is source-proven and was observed in the retained
failed predecessor, not claimed as a newly accepted hardware outcome.

Issue [126](https://github.com/mitchell-johnson/cbus/issues/126) corrects the
installed-runner helper's synthetic argv0 fixture to a real alias in the selected
venv. The positional executable and empty environment assertions stay strict;
local Mac/Linux fixture checks and Static4 pass. New hosted Linux acceptance
remains pending.

The first full hosted lane from PR 122 remains failed under
[128](https://github.com/mitchell-johnson/cbus/issues/128): mock execution passed
510 parents with one admitted optional skip and 158 separate subtests, then the
origin guard rejected 312 test-generated Python-to-Rust exec wrappers. All 312
are independently bound to the selected binary and reaped journals, but their
process-image handoff lacks guard receipts. Daemon and console phases were not
reached. The strict guard is unchanged. A direct-launch implementation plan is
published on that issue; no full hosted pass is inferred from the local subset.

`coverage --require-complete` exits 1 with `complete=false`: 487 provisional
obligations, 22,103 unresolved scope items and zero accepted obligations. The
census is unfinished, so no functional percentage is available. Parent 25,
numeric Application DBCOPYSAFE 124, Application DBSETSAFE Address 125 and release/native/hardware issue 22 remain open.

Final sanitized evidence will be retained in
[the release receipt](../research/fixtures/cgl-application-order-release-20261004.json).
