# Conversion XML and recovery across daemon restart

The remaining software restart work in [issue #135](https://github.com/mitchell-johnson/cbus/issues/135) is implemented and verified by two public CLI cases. Tested code is `bf237341cd96662bf0f7e74cc1caa53280aa9503` on the PR138 parent; report/status annotations are added afterward. The tests and CI registration change; conversion product code and all 484 Rust proof inputs remain unchanged.

| Actual focused epoch | Passing parent cases | Separate passing subtest events | Failures/errors/skips |
| --- | ---: | ---: | --- |
| Source public restart CLI | 2 | 0 | 0/0/0 |
| Source CI/wheel-runner guards | 181 | 14 | 0/0/0 |
| Source metadata checks | 157 | 550 | 0/0/0 |
| Fresh installed-wheel restart CLI | 2 | 0 | 0/0/0 |

Each case starts a second, separately owned cmqttd process with the same explicit state file. The original client relay endpoint, journal and attempt-marker bytes stay unchanged. Fresh current XML and the separately CLOSE/LOAD-observed saved image preserve the complete remaining project tree, unrelated project, backup, OIDs and significant character nodes. Fresh target and backup PP sessions verify all eight values and identities both before and after the saved-image observation. Recovery itself remains read-only.

The completed journal retains confirmed persistence. In the fault case, the real upstream PROJECT SAVE succeeds with 200 and its response is deliberately lost after one forwarded request. The restarted current and saved images match, but the original journal still has an unconfirmed SAVE: `project_saved=null`, `outcome_uncertain=true`, `persistence_verified=false`. No SAVE is replayed, and no seed/import/save occurs after restart. Each epoch reaps all four daemon children with 32 startup PCI frames and zero later frames or closed-project trap contacts.

The freshly built noneditable wheel passes the exact two-ID daemon selection in 14.27s. All 397 product files and 408 RECORD entries match; source/reference/binary checks remain quiet across 4,218 inputs. All seven commands succeed. The body import guard observes seven Python processes, 1,142 origin records, 1,128 product import events and four reaped Rust children with zero violations. Source restart and registration epochs precede metadata refresh; installed-wheel and metadata epochs use the refreshed map. They remain separate scopes.

All 18 maintained capture/sanitizer/generator/check commands pass. Ten outputs change within the eleven-file allowlist, and eight original/pre-fix receipts stay byte-exact. The current declaration is 1,123 explicit IDs—552 mock and 571 daemon—plus seven whole modules, retaining all 1,121 previous IDs in order. This is declaration coverage, not a full 1,123-body local run. The [earlier 54-case report](../2026-10-05-conversion-xml-zone-bindings/report.md) remains historical and is not combined into a fresh 56-case claim. Detailed pins and raw-epoch identities are in [receipt.json](receipt.json). An independent artifact review confirms both epochs: six CLI calls, ten closed connections, 364 tagged requests and 69 full XML replies each, including the actual dropped successful SAVE and unchanged journals.

This proves graceful process restart of cmqttd's owned JSON repository. Mock storage is process-local; no restart durability is claimed for it. Power loss, physical power-cycle, Schneider repository/importer behavior and original Toolkit execution remain separate. No house endpoint, vendor provider, new Cargo run or full local test suite is used. Required hosted CI and main merge remain pending in [issue #128](https://github.com/mitchell-johnson/cbus/issues/128); wider GUI/native/hardware work remains in #42/#43 and the deferred handoff #72/#74. The global parity gate remains incomplete.

The pre-restart state-file image has a recorded hash/size checkpoint rather than a separately retained raw copy. Full current/saved XML observations, journal/marker bytes and final state are retained; no independent full-state byte identity across restart is claimed.
