# NET SAVE DB integration corrections

The runtime-network materialization workflow now preserves the existing physical
and database ownership rules in the paths identified during integration review.
These changes complete the bounded software corrections to
[the first candidate](feature-batch-2026-10-01-net-save-db-materialization.md).
They do not establish full Toolkit or C-Gate semantic parity.

## Corrected behavior

An independently saved tag Network such as exact `0254` cannot address the
configured physical network `254`. The shared DALI gateway resolver now rejects
that independent target before numeric parsing, covering core, emergency,
specialized gateway and commissioning-session operations. `PP WRITE_PATCH`
checks the same ownership before resolving a patch manifest or sending PCI
traffic. Both return 404. Programming authorization still runs first, and
legacy numeric spellings without an independently owned exact row retain their
existing behavior.

Materialized tag trees defer modeled descendant OIDs to the established database
owner. A duplicate OID continues to select the existing winning object rather
than the first XML descendant; deleting it through `DBDELETE !OID` keeps its
lookup invalidated under the existing rules. Other surviving objects remain
accessible by their numeric paths. This preserves the implemented model's
lookup contract, rather than claiming acceptance of every original duplicate
OID shape.

Typed Application and Group `TagName` edits use their existing database owner.
They no longer revalidate untouched legacy Unit programming fields as a new
complete `DBSETXML` document. Already admitted PP attributes, nested additions
and Unit extensions survive an unrelated scalar edit. Complete replacement
documents still pass the existing strict admission rules.

Interface options retain the captured sequential name/value pairing behavior,
including duplicate names and an ignored final unmatched token. The iterator
implementation passes Rust 1.98.1's Clippy checks without suppressing the lint
or introducing a new Rust version requirement.

The [operator guide](network-definitions.md) also clarifies the offline address
profile. Explicit older DBVersion projects retain numeric aliases. An
unversioned Network with NetworkNumber `255`, including one added to the
unversioned Installation produced by `project new`, selects exact lexical
addressing: Address `254` resolves as `254`, while `0xfe` does not resolve.

## Controlled regression evidence

The physical-alias tests used only an owned in-memory PCI peer. Before the
guards, five of six cases failed. The observed DALI KNOWN and ADDRESS_UNKNOWN
frames were `\061400E381DA87` and `\061400E381DA82`, followed by CR. A manifest-
admitted PP patch target sent `\460500210193h`, followed by CR. After the guards,
all six unchanged regression cases passed, including legacy alias/OID controls,
authorization ordering and manifest admission. No real adapter was contacted.

Separate controlled regressions observed the duplicate OID selecting an
Application instead of the previously winning Unit, and the unrelated
Application tag edit returning 408 because the retained PP had extra attributes.
The first post-fix combined run passed 18 of 20 cases. Two test assumptions
were then corrected: OID deletion, rather than numeric-path deletion, invokes
the established invalidation rule; existing materialization normalizes raw Unit
serialization. Final checks assert semantic decoration preservation after
materialization and exact Unit XML preservation across the subsequent scalar
edit. No further product edit was needed. The initial OID/PP test-source hash
was not captured, so those failure logs are observations rather than a claim of
byte-identical tests across the initial and final runs.

## Acceptance and remaining work

The [supplemental acceptance receipt](acceptance/2026-10-01-net-save-db-integration/acceptance.json)
is separate from the immutable first-candidate receipt. Its SHA-256 is
`6fb35550d9db3f3fe28af51af5ee64d0a6378b3223a446567852e9fafa5f7207`,
with 104 sanitized supporting derivatives.

| Validation | Result |
| --- | --- |
| Rust 1.98.1 formatting, workspace/all-targets Clippy and release workspace build | Passed; 208 source/Cargo hashes unchanged |
| Targeted Rust regressions, including shared DALI/MQTT | 93 executions, 92 distinct tests, zero failures or ignored cases |
| Python source and fresh installed wheel | Each passed 218 parent tests and 742 subtests, zero runtime skips |
| Public CLI against owned cmqttd | Each environment completed 114 calls |
| Public CLI against fresh original C-Gate | Each environment completed 89 calls: 73 with exact online wire checks, 16 offline/preflight |
| Six protocol differential replays | Passed with 1,093 current source bindings |

The fresh wheel matches all 326 source package files. Its SHA-256 is
`eec0a78757ddacc8ac6a07cca1be7d1de503d22f6a9f52ef1f9667c2daca8947`.
Source, installed package, binaries and input/output artifacts were checked
unchanged across execution. Owned process/listener, proxy and trap cleanup
completed. CNI traps saw zero connections; serial-path absence was checked,
without a serial-open syscall-tracing claim.

Parent tests and subtests are separate measures. Standalone CLI journeys overlap
the selected tests and are not added to the unique test count. The fresh
original C-Gate journeys re-execute the bounded materialization contract; they
do not establish original acceptance of every new Rust correction branch.
The 126-command native boundary capture, 15/19-command supplemental captures
and separate legacy-transform native results remain qualified historical
evidence and receive no new execution credit here. Provisioning-only native
classes were not selected; this was not a full native release-gate run.

The first candidate's offline CI run
[36813895477](https://github.com/mitchell-johnson/cbus/actions/runs/36813895477)
failed the Rust Clippy job on the earlier option-pair implementation. Its Rust
tests and release build were consequently skipped. Local corrected checks do
not turn that historical run into a pass; the corrected candidate requires its
own CI result.

Issues 27, 29 and 32 retain their broader original Toolkit, native-format and
hardware obligations. The broad ledger remains 18 of 42 implemented rows
(42.86% of those rows), with zero fully accepted obligations and an incomplete
functional denominator. No functionality percentage, full-suite pass, Windows
execution, deployment, real-device effect or full native release-gate acceptance
is claimed by this batch.
