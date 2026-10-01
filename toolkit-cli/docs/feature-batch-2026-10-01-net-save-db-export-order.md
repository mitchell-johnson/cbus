# Project export order matched to original C-Gate

Whole-project XML export preserves Network creation order. Original C-Gate
3.4.0.2001 exports Network `254/Later` before `1/First` when they are created in
that order, including before runtime-to-tag materialization. The existing Rust
export implementation already follows that rule. This checkpoint corrects an
older test's numeric-order expectation and binds it to fresh original evidence.

## Original ordering contract

An owned original C-Gate process executed 27 commands in a disposable project.
The ordered Address/TagName/NetworkNumber projection was consistently
`254/Later/254`, then `1/First/1`:

- Before `NET LOAD DB` or `NET SAVE DB`.
- After `NET LOAD DB` and after `NET SAVE DB`.
- After explicit `PROJECT SAVE`, `CLOSE`, `LOAD` and `USE`.
- After selecting `OTHER` before exporting `SNAP`.

Ten exact comparisons also confirmed that each whole-project Network subtree
equaled its direct Network XML fragment, excluding the XML declaration.
All XML operations ended with native 344.
The probe confirmed owned process/listener/proxy/trap cleanup, unchanged inputs
and zero trap connections. It did not open an interface or contact a real device.
Optional Unit/Application children were not probed, and original internal
selection or model immutability was not inspected.

The [order vector](../../rust/testdata/vectors/cgate_project_export_order.json)
pins that exact JSON projection and its original software/capture provenance.
Raw capture SHA-256:
`42f025fb9f32e62e59ebbcaa4e7a02239a44bee55145bf7e9633062c029560ee`.
Private order-proof SHA-256:
`5f41f8862e5a1345e114c37f3392eeed95522a8d5bed0399d9bcd5fc80be2351`.
These are ordering and subtree observations; cmqttd's minimal Installation
wrapper is still not an exact original whole-project document.

## Corrected regression

The offline CI run for
[`6b208d08`](https://github.com/mitchell-johnson/cbus/commit/6b208d087fd7433c605cc44b97c4c09896ffa0eb)
failed `project_xml_composes_networks_without_selection_or_mutation` because its
two created Networks were compared in numeric order `[1, 254]`. The crate had
498 passing tests, one failure and one ignored case. Formatting and Clippy
passed; release building was skipped. That failed run remains historical:
[36817825556](https://github.com/mitchell-johnson/cbus/actions/runs/36817825556).

The exact failure was reproduced locally before editing. The test now compares
Address, TagName and NetworkNumber against the captured ordered vector and
checks each complete subtree against its direct export. Its existing checks
for unchanged project selection, unchanged model state, unselected export,
XML escaping and missing-project behavior remain intact. The empty-project
vector also clarifies that its wrapper is modeled and its ordering evidence
comes from the separate original capture.

The code diff is confined to this one test body. All production bytes and the
remaining test-module bytes are unchanged. Afterward, 29 distinct focused Rust
tests passed with zero failures or ignored cases. Rust 1.98.1 formatting,
workspace/all-targets Clippy and release workspace building passed. All 208
Rust source/Cargo hashes stayed unchanged across those checks. Rebuilt release
binaries exactly match the preceding candidate's binaries.

## Acceptance and remaining work

The [export-order acceptance receipt](acceptance/2026-10-01-net-save-db-export-order/acceptance.json)
records fresh source-bound differential and source/installed CLI execution in
a separate checkpoint, with 114 sanitized supporting derivatives. Its SHA-256 is
`572004ed257ca8dbeb101489fbf15d9b8fc60e4a68d5234dd305f6eb1cc7e02c`.

| Validation | Result |
| --- | --- |
| Targeted Rust regressions | 29 distinct tests and executions; zero failures or ignored cases |
| Rust 1.98.1 formatting, workspace/all-targets Clippy and release workspace build | Passed; 208 source/Cargo hashes unchanged |
| Python checkout and fresh installed wheel | Each passed 218 parent tests and 742 subtests; zero runtime skips |
| Public CLI against owned cmqttd | Each environment completed 114 calls |
| Public CLI against fresh original C-Gate | Each environment completed 89 calls: 73 exact online wire checks, 16 offline/preflight |
| Six protocol differential replays | Passed with 1,099 current source bindings |

The fresh wheel matches all 326 source package files. Its SHA-256 is
`1b7d63f8ac29598160592c5966c9e8ba72aaf9ee7bb360ebfe1e47b94cae1fc6`.
Inputs, source, installed package and binaries stayed unchanged across
execution. Owned process/listener, proxy and trap cleanup completed with zero
trap connections. The public derivatives retain private capture hashes and
declare coordinate and XML Hostname role substitutions, including decoded
wire payloads. Parent tests, subtests and standalone CLI calls are separate
measures and are not combined into a unique-test total.

The 27-command original ordering probe is fresh. Earlier 126/15/19-command
native captures and the integration correction's before/after observations
remain qualified historical evidence without new execution credit. The fresh
89-call original journeys re-execute the bounded materialization contract;
they do not accept every Rust correction branch. Provisioning-only native
classes were not selected; no full native release gate was run.

The
[preceding integration receipt](acceptance/2026-10-01-net-save-db-integration/acceptance.json)
and [first materialization receipt](acceptance/2026-10-01-net-save-db-materialization/acceptance.json)
remain immutable historical evidence. Passing local checks do not convert an
earlier failed CI run into a success; the corrected candidate needs its own
CI classification before main publication.

The [network operator guide](network-definitions.md) and preceding
[integration report](feature-batch-2026-10-01-net-save-db-integration.md)
describe the delivered workflow and its broader limits. Named child
`DBADD`/`DBADDSAFE` and same-project unsafe copy remain refused; standalone
typed database edit commands still lack explicit project selection on their
own connection. Native private formats, complete Toolkit workflows and
physical acceptance remain separate work. These gaps do not undermine the
captured export-order contract and are not presented as completed features.

The broad ledger remains 18 of 42 implemented rows, zero fully accepted
obligations and an incomplete functional denominator. This checkpoint makes
no full-functionality percentage, full local suite, full native release-gate,
Windows, deployment or hardware-acceptance claim.
