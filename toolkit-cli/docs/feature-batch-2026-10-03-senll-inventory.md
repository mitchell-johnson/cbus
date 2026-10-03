# Complete SENLL getter inventory and inherited scene saves

SENLL ST7 2.0.01..2.4.99 now automatically consumes the four retained
Area/Scene fields alongside the previous 43 workflow fields. Area objects
become available before raw-block refresh; Scene objects become available
afterward. These objects can satisfy later control selections without adding
collision reservations. Missing creation decisions still refuse.

Complete snapshots also perform the native enabled-scene save on explicit
histories and flat saves. The implementation preserves the first level for
each group within a scene, pointer-boundary order, empty scene holes and the
fixed-versus-compact packing rule. Exact disabled Patch bytes preserve raw
table/pointers. Area and Patch always remain unchanged. Native numeric PP
semantics are established; literal hexadecimal text formatting is outside
this comparison. Read [sensor controls](senll-application-controls.md) and
the [static annex](senll-inventory-source-review.json), which contains 38
independently reviewed method pins and 47 independently verified layouts.

The frozen tree `2ba1bacd8b5ecc8e518151a6764a2ffe40ee9279` and a fresh
installed wheel each passed **202 parent tests and 507 separate subtests**,
with **four provisioning skips** and zero failures/errors. The twelve-module
selection includes all **32 new public cases**: 26 positive cases, four
read-only refusals and two lost successful PP-save replies without retry,
split equally between owned `cgate-mock` and `cmqttd`. Positive cases also
invoke the offline CLI and compare with native preview, then save/reopen the
whole synthetic project. Both scopes also pass the 22 earlier sensor cases.
All **379 package files** match source/ZIP/installed bytes, and all **4,008
tracked repository files plus both binaries** remain unchanged across the
frozen executions. Full suites were deferred per the user's speed instruction.

The [release receipt](../research/fixtures/senll-inventory-owned-release-20261003.json)
records exact selections, skip IDs, artifact hashes and package proof.
The skips require private original Toolkit receipt inputs, native SENLL
acceptance and two native sensor CLI workflows. Independent review also
probed every one of the 91 inventory bytes for stale refusal and checked
forged/omitted scene normalization and application-profile escapes before
staging. Those review probes are separate from the reported test counts.

Adding the Makefile selectors refreshed only four affected compatibility
receipts through maintained drivers: 46 primary comparisons and four combined
checks. Both unchanged SESSION receipts retain valid source bindings. Raw and
sanitized receipts, generated inventory/register and skip census pass. The
native selection remains 259 required/selected tests across 731 test modules.

This slice is based on PR82. It preserves the earlier absent-inventory profile
and all final forced-save rules. Partial inventory refuses; complete snapshots
require the proven Lighting application profile on both flat and explicit
paths. Broader sensor families, nonzero-key models, complete network catalogue
and creation decisions, initialized original GUI history, native vendor service
and physical acceptance remain open in issue41. `coverage --require-complete`
remains nonzero; this batch does not complete Windows Toolkit parity. Outcome
annotations follow frozen executions; publication-head CI is separate.
