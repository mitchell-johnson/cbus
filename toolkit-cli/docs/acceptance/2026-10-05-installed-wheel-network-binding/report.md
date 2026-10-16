# Installed-wheel network acceptance binding — 5 October 2026

The installed-wheel runner now passes its own freshly built and validated wheel to the maintained network acceptance helpers. Its cleaned environment continues to discard caller C-Bus provisioning values; the runner supplies the exact wheel alongside its selected owned binaries. Package, RECORD and process-origin checks remain enforced.

The preceding PR 130 full daemon epoch failed two network acceptance parents because this wheel argument was absent. Both refused before executing their workflow. The retained artifact digest and actual failure identities are recorded privately and in [issue 128](https://github.com/mitchell-johnson/cbus/issues/128); that red run is preserved.

Focused validation of both complete network modules passed from a fresh noneditable wheel: **10 parents and 49 subtest events**, with no failures, errors or skips, in 345.02 seconds of pytest. Both formerly failing public workflows ran: network creation/definition lifecycle and Network materialization with save/reopen/restart. Their passing assertions check complete graphs/OIDs, persistence boundaries, closed owned peers and unchanged PCI captures. Temporary inner helper records are cleaned after assertion; the outer trace, JUnit, package and process evidence remain retained.

The runner observed 309 Python processes and three reaped Rust children, with zero origin violations. All 395 product files and 406 RECORD entries validate. Source/reference and both binary pins stayed unchanged through this epoch. Separate focused runner/matrix regressions passed 138 tests; an earlier collection error caused by a missing tests import path is retained, not counted as acceptance.

The [receipt](receipt.json) records exact selection identities, artifact hashes, the fae29 checkout plus tested one-line overlay and these limits. Later documentation updates are separate from that tested source snapshot. No local full-suite or Cargo run, original/native execution, physical activity, complete installed matrix acceptance or merge is claimed. Issue 128 remains open for full required CI and merge.
