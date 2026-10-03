# Thermostat remote Levels and output Add integration — 4 October 2026

The Toolkit CLI now combines optional remote-Level creation, all 23 ordinary
output load/selection roles and typed output Add/cancel histories for PC_TSA,
PC_TSA5, PC_TSB and PC_TSB5. These workflows share one current graph and one
terminal thermostat owner save. The detailed input contracts remain in
[remote Levels](thermostat-remote-levels-source.md),
[output groups](thermostat-output-groups-source.md) and
[output Add](thermostat-output-add.md).

An integration correction preserves the exact optional XML `Value` of existing
Levels. Reuse depends on Level Address, so missing, opaque, noncanonical and
out-of-byte Value metadata can remain on unrelated or reused existing records.
Declined and omitted prompts preserve that metadata. Whole-graph freshness,
unique Address/OID, correct parent and ownership checks still apply, and newly
created Levels still require the exact planned canonical byte Value.

Two shared Rust database fixes support the workflows. OID-addressed Level
TagName updates persist in pending and existing Group/NetVar state. Quoted
`DBSET` raw tails are decoded once before database routing, preserving doubled
ASCII spaces, NBSP, quotes, backslashes and `#`. Unquoted `DBSET`, `DBSETSAFE`
and `DBADDSAFE` retain their existing contracts. Exact wire vectors and
database interaction regressions accompany both changes.

The Add adapter follows the recovered Group save sequence: `DBADD` under the
fresh application OID, fresh object/OID verification, then separate Address
and source-encoded TagName setters. Accepted/cancelled dialogs and selections
retain causal order. Uncertain replies stop without retry or inverse mutation;
no later PP/project save is sent. A changed completed workflow issues at most
one PP save and one final target-project save, with its source backup save
reported separately.

## Integrated acceptance

The [release receipt](../research/fixtures/thermostat-integration-owned-release-20261004.json)
binds the exact uncommitted source and fresh binaries tested on main base
`1cc79977ddcc7b4912e9329706d9cd94e8f99b5f`, incorporating PRs 92, 94 and 97
through `66773292fe2aa9fd940f6c30f8879e9a6b69eb96` plus the issue 96
admission correction. The earlier three feature-head receipts remain
historical evidence; their counts are not added to current integration counts.

| Check | Integrated result |
| --- | --- |
| Focused source, 72 selected modules | 1,101 parent passes, 3,519 separate subtests, 40 disclosed skips |
| Fresh noneditable installed wheel | 1,101 parent passes, 3,519 separate subtests, 40 disclosed skips across the same 72 modules |
| Thermostat backend identities, within each accepted run | 78: 24 preserved remote references, 20 optional-Level cases, 16 output cases and 18 Add cases |
| Rust required gates | Formatting, all-target workspace Clippy with warnings denied, workspace tests and release workspace build passed |
| Rust test results | 8,730 passes, no failures, one ignored test, across 102 terminal summaries |
| Frozen inputs | All 4,104 tracked/nonignored repository inputs and 473 Rust inputs stayed unchanged during their applicable gates |
| Package source/wheel/installed bytes | All 389 files equal before and after execution |
| Copied reference closure and actual pytest imports | All 4,104 reference files plus exactly two synthetic extras remained equal; actual pytest startup/terminal origins were installed-only |
| Complete feature gate | Both installed checks exited 1 with complete=false; the functional denominator remains incomplete |

The 78 thermostat cases include six integration regressions, three on each
owned backend. They exercise accepted prompt reuse, actual omitted/default
decline, and ordered Add/cancel histories with preserved opaque existing
Value. This total contains the 24 earlier remote-reference cases. Counts of
parents, subtests, backend cases, wire records and Rust summaries describe
different scopes and must not be added together.

The source raw-record review examined 130 CLI calls, 11,726 tagged commands and
78 terminated backend PIDs. It checked full PP/graph preservation, fresh
readback/reopen, four controlled stale changes and lost successful replies.
Two dropped 301 and ten dropped 200 replies produced no replay or later owner
mutation. The 312 daemon PCI rows were startup-only; no later physical/trap
requests occurred. The independent installed-wheel raw review confirmed the same 78 case signatures and these same counts and preservation/failure outcomes.

The 40 skips comprise 27 native/environment gates, nine private static-input
checks, three original instruction/assembly cases and one vendor-schema
case. The receipt publishes canonical test identities without raw private
locations. Skips do not earn passing-body credit. All 72 selected modules were
collected and all 71 body-required modules passed; the provision-only thermostat
native module is the sole body exemption.

Six current owned C-Gate captures and downstream contract/parity/census
metadata were refreshed before validation. Their exact source maps contain
1,183 path occurrences across 220 distinct inputs. The source-independent
review checked 64 primary and four combined cases, 150 response lines and
eight peer roles. Saved native comparisons were read, with no new original
or physical execution and all 50 protected predecessor artifacts unchanged.
The contract inventory, parity register and skip census passed their builders
and freshness check. The historical category ledger remains 18 complete,
22 in progress and two pending.

## Retained failures and remaining work

The first integration wheel build failed with `ENOSPC` before tests. Moving
regenerable build output allowed the second wheel to build/install and run
console help, but internal reference staging still failed with `ENOSPC`.
Neither attempt has pytest, terminal package or closure acceptance. A later
external-output attempt was rejected before execution by automatic approval
review. A fully internal build attempt also stopped before pytest when the sandbox denied an ignored egg-info timestamp update. Its approved successor `wheel-final5` keeps all new runtime artifacts,
the venv and copied reference closure on the internal filesystem, uses APFS
clones with distinct inodes and permits no external/hardlink fallback.

Independent artifact reviews re-parsed both JUnit/trace pairs, checked exact registration and actual passing bodies, inspected raw thermostat graph/wire/lifecycle records and verified package, clone, binary and metadata preservation. The published receipt contains only selected counts, canonical/normalized skip identities and artifact hashes; private raw XML, locations and skip tracebacks remain private. Both installed coverage checks remained incomplete: the default call grants no trusted-root acceptance, and the explicit copied-root diagnostic verifies artifacts but refuses current fingerprints because the installed running package is not the checkout package. The 487 obligations remain provisional and no functional completion percentage is available.

No full Python suite, fresh original instructions, Schneider native server,
Windows GUI or real C-Bus network ran. The complete Rust suite ran because
repository instructions require it before a Rust code commit. Output Edit,
application migration, complete initialized form/control/message behavior
and broader thermostat/native/hardware parity remain open under issue 42
and the original-acceptance issues. Full Toolkit or C-Gate replacement parity
is not established by these owned database tests.

Runtime, tests, CI selection and packaged metadata stayed frozen during
acceptance. Only the declared report/status/receipt annotations were written
afterward and checked against the frozen-input exception rule. Staged and
committed readback is recorded separately when complete.
