# Ordinary Level Value resilience — 5 October 2026

Five public cases now verify the remaining owned interactions for [issue 131](https://github.com/mitchell-johnson/cbus/issues/131): nested NetVar and Group Level edits, lost successful Value and project-save receipts, and disk-backed daemon restart. They passed from source and from a fresh installed wheel. The accepted byte/raw/NULL policy is grounded in the maintained source; new native execution is not a precondition for this owned issue. Exact native equivalence remains a separate scope.

Use the [operator guide](../../ordinary-level-value.md). The [earlier twelve-case acceptance](../2026-10-05-ordinary-level-value/report.md) remains unchanged and records the original consistency fix. This checkpoint adds five cases; it does not repeat those earlier proofs.

| Actual epoch | Passing parents | Failures, errors, skips or subevents |
| --- | ---: | ---: |
| Source | 5 | 0 |
| Installed wheel, cgate-mock | 2 | 0 |
| Installed wheel, cmqttd | 3 | 0 |

These are the same five selected cases, not ten unique cases. Source collection and pytest were two successful commands in a 45.1227-second driver. The wheel ran nine successful maintained commands plus one successful outer wrapper in 241.1707 seconds. Collection and console observations are separate from the pytest body counts. The exact [selected identities](selected-nodeids.json) and [hash-bound receipt](receipt.json) accompany this report.

## Effects and preservation

Each case changes only the nested NetVar child Level from 66 to 42 and the Group child Level from 77 to 99. Complete ordered XML and issued OIDs preserve the NetVar root, sibling byte 88, labels, opaque metadata and unrelated Unit 20 with its three PP values. Numeric, relative and issued-OID reads agree. The NetVar root itself is not a Level byte owner.

Four cases each forward one target request and drop its real upstream tagged `200 OK` terminal: two Value edits and two project saves. The CLI reports an uncertain result; fresh graph/readbacks show the accepted effect. No automatic retry, inverse cleanup, or subsequent database write/save occurs. Explicit CLOSE/LOAD after a lost save verifies the saved image separately.

The restart case saves both edits, reaps the first daemon, then opens a distinct daemon context using the same explicit state file. It does not reseed, rewrite or save again. Full graph and PP readbacks survive restart and explicit CLOSE/LOAD. The final state file is pinned. An earlier state hash was recorded, but its earlier file image was not separately retained.

The source packet recorded 199 CLI calls (195 exit zero, four expected uncertain exits), 205 connections and 519 tagged requests: 389 CLI and 130 direct. It retained 10 documents, 22 whole-graph/Unit checkpoints and 66 PP responses. The separate wheel phases recorded 73 mock calls/191 requests and 126 daemon calls/328 requests. Both the source packet and wheel union used six reaped Rust processes, 32 startup PCI frames, no later PCI traffic and five closed zero-contact traps. Cleanup is supported by retained process/listener records and passing ordered assertions, rather than a new historical OS probe.

## Package and provenance

All 395 product files agree across source, reference, build, wheel ZIP and installation; all 406 RECORD entries validate. The mock pytest guard observed 74 Python processes and 13,308 origin rows; the daemon guard observed 127 processes and 22,954 rows. Both report zero violations. Auxiliary collection and console observations have their own counts; this is not universal executed-code attestation.

Execution used checkout `c02c4f8c7f34f93cfe773ca0765ea2cae9c005cf` with six test/registration changes and ten refreshed output changes. The 4,201-input map, 484 Rust inputs, 395 product files, Git index/HEAD and both recorded binary pairs stayed unchanged through the proof/readback epochs. That physical code overlay was later committed as `b487b4f1f05f6f38f80b68f86b6fddffef9fa7c9`; it is not a new tested checkout. These later documentation annotations are outside the six capture source maps and product package.

The separate maintained refresh completed 18 commands, changed ten outputs within its eleven-path allowlist, reproduced the inventory unchanged and preserved eight original/pre-fix inputs. It does not constitute five-case acceptance. Separate metadata/registration validation passed 197 parents plus 550 unitemized passing subevents (747 aggregate), with no failures, errors or skips, in two commands.

B authored the public expected graphs and supplied raw readbacks. C supplied qualified physical/origin and cross-terminal checks; C also authored the underlying implementation/library tests. A independently reconstructed the literal before graph and inspected the five semantic outcomes. Their individual descriptors and limits remain separate in the receipt.

At this acceptance checkpoint, issue 131 remains open pending merge and required CI. Its remaining local owned interactions are supported by this proof. The configured 1,067 explicit identities plus seven whole modules were not fully executed here. There is no new Cargo/full-Make run, native or physical acceptance, complete Toolkit parity, or functional percentage claim. Historical Application and ordinary Level reports/receipts remain byte-exact.
