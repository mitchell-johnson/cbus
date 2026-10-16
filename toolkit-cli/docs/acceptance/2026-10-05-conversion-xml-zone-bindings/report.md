# Conversion XML preservation and prepared thermostat zones

The CLI now protects significant XML throughout supported conversion creation, replacement, backup, save/reopen and read-only recovery. Thermostat settings now expose all 34 retained prepared Boolean bindings in the same synchronous owner and ordered history.

Code commit: `58f32198dfde789d8a4f975c9f189c8929a892b5`. The tested parent was `7088af27b3161b8a68642883684b6db0648e7e53` with a frozen 4,215-file overlay; the exact tested files were then committed. This report, receipt and final status annotation were added after testing.

## User behavior

- [Conversion XML preservation](../../conversion-xml-preservation.md) retains inherited `xml:space`, mixed separators, CDATA and whitespace-only leaves. Default element-container indentation may vary. Detached Units use actual ancestor namespace/scope; legacy journals stay read-only and cannot gain new persistence credit.
- [Prepared thermostat zones](../../thermostat-zone-controls.md) accepts `zone-checkbox-binding` with one exact binding and JSON Boolean. Source callbacks, equality guards, shared references, Basic/Programmable save tails and the issued owner seal remain active. This is explicit property selection; native GUI Click admission is unverified.

## Focused verification

| Scope | Passing parents | Passing subtest events | Qualification |
| --- | ---: | ---: | --- |
| New XML/zone pure tests plus affected model regressions | 228 | 0 | No failures/errors/skips |
| Registration and installed-package guard tests | 175 | 14 | Missing/skipped bodies still reject |
| New XML public CLI, both Rust services | 18 | 0 | Complete trees, PP, backups and uncertainty |
| Existing conversion public CLI regressions | 56 | 0 | Both Rust services |
| Initial zone public CLI | 32 | 0 | Four Basic preview expectations failed |
| Corrected Basic zone cases | 4 | 0 | Separate successor epoch, both aliases/services |
| Metadata integrity tests | 157 | 550 | No failures/errors/skips |
| Fresh installed-wheel new CLI cases | 54 | 0 | 25 mock, 29 daemon; no failures/errors/skips |

The fresh wheel SHA-256 is `03e99b63bfa97b7bcc5f1c86068232aec0f44bce55b0906256a5575f7e7321bd` (3,020,205 bytes). All 397 product files and 408 RECORD entries matched; source, copied reference and both binaries stayed quiet. During the two pytest body phases, the import guard recorded 106 Python processes, 18,532 origin rows and 18,320 product import events with zero violations. All 50 owned Rust children were reaped. Collection, body traces and JUnit identities agree on the exact 54 selected cases.

The XML profile checks literal opaque data and exact PP/identity, complete source/unrelated/backup trees, significant-loss refusals, lost successful save replies and read-only recovery. Returned-XML faults retain upstream/client bytes separately. Thermostat cases cover every offered binding, synchronous consequences, all final PP fields, complete graph/OIDs, fresh reopen, pre-mutation refusals and actual lost PP/project-save 200 replies without replay. Basic damper refs allocate 0–3 according to the retained load/callback rules while preserving old groups 40–43.

Historical failures are retained: XML fixture18 failed before workflow calls because a raw Level could not be re-admitted as whole XML; the successor restores XML before its sole raw setter. A wrong root environment skipped32 zone bodies. Four Basic expectations omitted damper creation; source-backed literals corrected them, then a test-wrapper collection error was fixed. Product code was unchanged by those fixture corrections. The source32-pass and corrected4-pass results are separate; the fresh installed wheel supplies one complete current36-zone epoch.

All 18 maintained metadata refresh commands exited0. Six current owned-service captures were regenerated from actual producers; ten files changed within the eleven-file allowlist. The 484 Rust inputs, exact accepted debug pair, six closure maps and eight original/pre-fix captures stayed unchanged. Independent artifact readbacks inspect PP, graphs, wires, real dropped200 replies, process cleanup and sanitizer payload preservation.

## Publication and remaining scope

The maintained declaration is now 1,121 explicit IDs (552 mock, 569 daemon) plus seven whole-module selections. All 1,067 inherited IDs remain ordered and unchanged. These are declaration counts, not a full executed selection. Required hosted CI and merge remain separate under [issue128](https://github.com/mitchell-johnson/cbus/issues/128).

This implements the XML guard in [issue135](https://github.com/mitchell-johnson/cbus/issues/135) and completes the bounded software work of [issue136](https://github.com/mitchell-johnson/cbus/issues/136). Issue135 still needs supplemental fresh-process restart persistence/recovery evidence; the current checks verify save/close/load and recovery in the same owned process. Wider original GUI/native importer, Windows scheduling and physical obligations remain in issues42/43; deferred VM/oracle work remains in72/74. No house deployment or light programming occurred. `coverage --require-complete` still exits1; the provisional census does not support an overall completion percentage.

Artifact hashes, selected identities and separate execution epochs are recorded in [receipt.json](receipt.json). Private raw data stays outside the published repository.
