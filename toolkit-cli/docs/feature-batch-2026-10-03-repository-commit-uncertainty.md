# Repository commit uncertainty

This continuation addresses the post-rename consistency gap in
[issue77](https://github.com/mitchell-johnson/cbus/issues/77). The existing
256 MiB capacity profile and sixteen-backup workload remain unchanged.

Previously, a successful repository rename followed by a failed directory sync
returned the same error as a failed write before rename. Command callers then
restored their old live model and reported that the change was rolled back,
although the replacement repository file was already visible.

The storage layer now marks only the post-rename directory-sync error as
uncertain durability. Every live persistence caller retains the corresponding
model and returns an explicit 500 asking the operator to inspect state and
avoid replay. The staged Project Repair path installs its replacement model;
project selection, startup tracking and event bookkeeping finish for the visible
change. Startup still propagates an error rather than silently treating the
repository as durably committed. Pre-rename failures keep existing rollback.

Fault validation also exposed a repair-staging defect: serialization omits live
network state, retry settings, observed levels and physical inventory. Repair
must preserve those observations rather than reset them through its database
round trip. The configured empty-OID runtime shell retained after DBNEW needs
the same preservation, while remaining excluded from the serialized database.
The repair-only correction and its normal/pre-rename/post-rename cases remain
part of this batch; ordinary startup still begins without physical observations.

The deterministic fault injector is test-only, one-shot and scoped to an exact
repository path. It adds no production command, environment toggle or physical
endpoint. Exact response vectors and interaction tests use invented projects,
temporary repositories and scripted PCI connections.

The Python command client recognizes only this exact terminal reply, preserves
the complete response in `CGateRepositoryUncertainError`, and closes its command
connection. It does not reconnect or send cleanup commands automatically. Parent
metadata transactions explicitly record repository/database uncertainty and
suppress their ordinary pre-save rollback. Other complete error replies retain
their existing synchronized-connection behavior.

## Validation

Five owning Rust tests pass all 29 fault/repair histories without skips. The
focused Python source selection passes 54 tests and 73 subtests, with three
explicit native-provisioning skips. Real socket tests cover ordinary/document
commands, exact versus near-match replies, cleanup errors, and a metadata Add
that becomes visible before the uncertain reply. Independent review found no
remaining blockers. Formatting, strict workspace Clippy, release workspace
build and freshly regenerated parity receipts pass.

The final Rust workspace suite passes 8,724 tests with no failures and one
ignored test. The final-source evidence selection passes 188 tests and 545
subtests in a temporary directory outside synthetic Git ancestors. An isolated
installed-wheel selection passes 176 tests and 650 subtests with three native
provisioning skips. After evidence sanitization, a rebuilt wheel passes its
110 packaged-evidence tests and 545 subtests. Sanitization preserves technical
payloads and source fingerprints; it does not claim another execution.

The broad Python baseline finished with 9,728 passing tests, 21 failures,
1,211 skips and 42,965 passing subtests. It began before these changes and is
not an acceptance receipt for this batch. Seventeen failures are the temporary
archive guard described below; the remaining four are a transient source-bound
coverage receipt mismatch, stale test census, stale Neo report expectation and
stale Neo/NeoUsage hashes in the historical static report receipt. The coverage
check passes against the final regenerated receipts. Census/expectation
maintenance is recorded separately; the historical receipt remains blocked
because regeneration requires its pinned original executable and map. Its
hashes have not been manually rewritten.

The refreshed census and final coverage checks pass seven tests and 42 subtests.
The source-grounded Neo expectation correction and admitted-profile selection
pass 215 tests with one native skip. They preserve explicit missing-field
refusals and do not introduce a new device mapping. The baseline report receipt
mismatch originates in the base commit's Neo/NeoUsage source changes.
The final combined report/coverage/census selection records 52 passing tests,
one native skip, 42 passing subtests and that single retained static-receipt
failure. The complete broad Python suite has not been rerun after maintenance.

The broader interoperability run used predecessor binaries containing the commit
uncertainty change but preceding the repair-only runtime preservation fix.
Its log stopped during the mock selection, and its processes are no longer
running. It has no final result and receives no completed-suite credit.
Its completed substeps passed nine SESSION_ID cases per backend, eleven tagged
cases per backend, twelve DBSETXML cases plus two combined-Network cases per
backend, and two command/XML-framing tests. The later mock suite stopped
mid-selection; the daemon suite was not reached.
Exact final-source/installed-wheel checks above cover the changed workflows;
the predecessor interoperability run is not exact final-binary acceptance.
An additional maintained command/XML-framing selection against the final Rust
binaries passes 21 tests and 158 subtests, with one native-specification skip.
The source/artifact binding manifest is retained locally outside the checkout.

The first sandboxed interoperability selection failed its strict listener
verification because `lsof` could not inspect `/dev/mqueue`. Granting that path
inside the sandbox did not resolve its mount warning. An approved one-case run
outside the sandbox passed with listener checks intact. The interrupted broader
selection used that same context. These setup failures are retained separately.

The evidence sanitizer tests also refuse temporary archives under `/tmp`:
synthetic `.git` mount points make their ancestors appear to be Git checkouts.
The guard remains intact; an isolated `/var/tmp` local rerun passes. Both failed
selections retain their 17 archive-guard failures in local logs.

## Remaining acceptance

An injected directory-sync failure establishes software handling of that
boundary. It does not establish filesystem crash behavior, survival through
power failure, original C-Gate compatibility or physical hardware acceptance.
Issue77 remains open for broader capacity and scaling work; original acceptance
remains in the manual handoff under issue72. Full Toolkit parity is unfinished.

Automatic approval review initially rejected the GitHub progress comment. After
the user explicitly approved its payload and recipient, the reviewed draft was
[posted to issue77](https://github.com/mitchell-johnson/cbus/issues/77#issuecomment-5969703463).
Its statement that broader runs were still being recorded reflects the draft
approved before their final/interrupted outcomes were inspected.
