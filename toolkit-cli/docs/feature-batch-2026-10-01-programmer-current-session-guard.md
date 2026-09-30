# Preserve edits made during physical PP reload

This batch fixes a reproduced data-loss race in cmqttd's physical PP LOAD and
explicit deployment retry. A session owner could change typed parameters or
raw bytes while a retry reload waited for PCI. The published implementation
could replace those newer edits with the fresh read, or restore an older
snapshot after a failed or identity-mismatched read.

The correction refuses that raced reload, preserves the newer staged evidence,
and prevents retry replay or STORE. It also protects edits made while LOAD
waits for command admission and while its successful result is handed back.
This is a bounded programming/recovery correction; full Toolkit and C-Gate
parity remains unfinished.

## Reproduction and behavior

On production source from `6d6e25490f1fa577a0c0c071a841c807e102060b`, all six
new held-PCI cases failed: typed PP_SET and SET_RAW_DATA edits during each of
successful, failed and firmware-mismatched reloads. The exact commands, source
hashes and failure logs are retained in the
[acceptance artifacts](acceptance/2026-10-01-programmer-current-session-guard/acceptance.json).
An earlier two-case red run is retained separately and is not counted again.
The red runs used added tests in a working tree; their captured test-source
hashes differ from both the published baseline and final formatted tests.

Both public LOAD and retry reserve their complete expected session before
waiting for the command lock. The loader compares that exact snapshot before
physical I/O and again at commit under the current PCI generation guard.
Typed values, dirty parameters, raw bytes, changed-byte positions, source,
identity, lock and attempt identity participate in the comparison.

The loader captures its successful committed snapshot in the same model
critical section as the commit. Retry uses that returned witness, rather than
cloning potentially newer state after the await. It continues only when the
current session still exactly matches the committed witness and retained
physical identity. Restoration requires an exact pending or committed witness.
Newer edits survive; raced retry provenance remains invalidated. Replacements
and newer LOAD attempts retain their own state.

The SAVE implementation and native lifecycle test are unchanged. START and
ordinary SAVE do not automatically recover or replay an uncertain operation.
Explicit RETRY retains its original-owner, initial-restaging, exact typed/raw
reconstruction and all-session admission requirements.

## Executed validation

An independent read-only review verified the frozen source fingerprints and
all three admission/read/handoff boundaries. Final targeted Rust validation
passed **34 unique tests**, without failure, ignored tests or skips:

| Selection | Passed |
| --- | ---: |
| Retry controls, including ten new test parents | 16 |
| Loaded physical identity safeguards | 7 |
| Physical SAVE safeguards | 8 |
| Routed LOAD/SAVE, PP lifecycle, unchanged native lifecycle replay | 3 |

The new controls cover six held-PCI outcomes, four public/retry admission
combinations and four exact-witness handoff combinations. Loop scenarios are
not additional test parents. The handoff controls perform actual scripted
physical reads, then exercise the completion boundary directly. Admission and
handoff controls were added after the held-PCI red matrix and have no separate
red execution.

From `rust/`, formatting, workspace/all-target Clippy with warnings denied and
the release workspace build passed:

```sh
cargo +1.92.0 fmt --all --check
cargo +1.98.1 clippy --workspace --all-targets -- -D warnings
cargo +1.92.0 build --release --workspace
```

All six genuine fresh compatibility replays passed against those rebuilt
binaries. Each backend matched nine SESSION_ID cases, eleven numeric-tagged
SESSION_ID cases, twelve exact Unit XML wire cases and two combined Network
readbacks. The root independently reproduced each maintained sanitizer
derivative byte-for-byte and checked all **1,045 source bindings**. Exact raw
producer commands, results, binary/source fingerprints and cleanup are retained.
Four server PIDs were sampled; the two fast mock children were not. Maintained
producers terminated their children, observed endpoints were closed, and owned
scratch directories were removed.

The contract inventory, physical applicability and packaged parity data were
genuinely regenerated. A fresh wheel was built afterward and installed with
offline `uv pip install --no-deps --reinstall` into a new Python 3.13
environment. All **324** packaged Python/JSON files match source; actual import
origins and the installed console entry point were verified.

| Final focused Python selection | Source | Installed wheel |
| --- | ---: | ---: |
| Namespace, census, release-gate and Unit XML receipts | 16 | 16 |
| Current contract/parity/session evidence and physical workflows | 39 | 39 |
| Unique parents, with no failures/errors/skips | **55** | **55** |

Each environment also passed 54 subtests, reported separately from parent
counts, and recorded 144 public CLI calls: 128 successful exits, fifteen expected
exit-one refusals/recovery outcomes and one intended exit-130 interruption.
Input bindings remained stable and owned test daemons were terminal or absent.

## Evidence and remaining scope

The receipt links **71** declared evidence derivatives to immutable private raw
archives by SHA-256. Runtime coordinates are role templates; each transformed
string or object key has a normalized public pointer and original-string digest.
Exit results, protocol payloads and source digests are retained. Staged-byte
verification binds all current replay source closures, packaged files, tracked
Toolkit test modules and changed files to the actual index and working tree.

Preparation history is retained outside Git. A preliminary wheel built before
the final receipt/parity refresh was superseded and never used for acceptance.
Publication preparation refused undeclared owned scratch paths, and a repeat
refused existing aggregate paths; final publication declares only captured
scratch roles and reuses aggregate logs only after exact byte comparison.
Transformation pointers identify normalized fields, including normalized keys.
Earlier published reports and receipts remain historical; their claims did not
cover this newly reproduced race.

No full test suite, provisioned native release gate or live hardware acceptance
was run. Scripted peers do not establish original Toolkit concurrency behavior,
live device effects or power-cycle persistence. CI is a separate checkpoint.
The enforcing `coverage --require-complete` command still exits one. The broad
feature ledger remains **18/42 (42.86%)**, with 487 provisional obligations and
22,103 source-scope items; the functional denominator is incomplete. This fix
does not inflate those counts or establish full feature parity.
