# SENLLA surface component view — 3 October 2026

`sensors surface-light-level-view` now inspects identified
SENLLA / 5754PE / 2.4.00..2.4.99 exports through the separate surface model.
Thirteen source-proven fields expose target/margin, power-up and bank usage
state and their detached component overlay. Inputs stay unchanged; unsupported
identities, unsigned-width/count violations and out-of-byte projections refuse.
There are no edit flags or native save action. Read
[the guide](senlla-surface.md) and [static audit](senlla-surface-source-review.json).

Authored commit `2fe7d4c4` and native census commit
`043e19244f5e0d6ef5cd4dd3eb01287be3eebc49` were frozen before final acceptance.
Source and a fresh installed wheel each passed **105 parent tests and 239
separate subtests**, with **two native-service provisioning skips** and zero
failures/errors in the seven-module selection. This includes all 24 new model
and CLI parent tests. The public offline CLI checks exact firmware endpoints,
literal component projections, specification/snapshot byte preservation,
identity refusal before schema load, absence of edit flags and the retained
SENLL-to-SENLLA refusal. No new native backend SENLLA cases are claimed.

All **380** package files match source, wheel ZIP and installed bytes under
Python 3.13.14 with the required extras. All **4,021 tracked repository files**
plus both backend binaries stay unchanged across frozen execution. All six
existing compatibility receipts retain valid exact source bindings and are
reused without rewriting: 64 primary comparisons and four combined checks.
Inventory, register and census checks pass. All 259 required native cases stay
selected across 735 test modules. The 487-obligation functional census remains
incomplete and `coverage --require-complete` exits 1.

Independent review verified all 120 method pins against original EXE/MAP
identities and checked the fixed raw unsigned guards. Its separate 24-parent /
213-subtest run and 615 boundary probes are overlapping review evidence, not
additional release counts. The [path-free receipt](../research/fixtures/senlla-surface-owned-release-20261003.json)
records exact selections, skips, hashes and boundaries.

This slice is stacked on PR88. Full suites remain deferred for speed. Original
instructions/GUI, vendor/native service and hardware acceptance are unrun.
The inherited eight-key normal-save, nonzero-key Scene, Global/control and raw
bank loader pipelines remain outside this read-only view. Their source recovery
continues separately; issue41 and complete Windows Toolkit parity remain open.
This report, status and release receipt annotate frozen execution only;
publication-head CI is separate.
