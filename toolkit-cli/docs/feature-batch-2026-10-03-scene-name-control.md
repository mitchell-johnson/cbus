# Retained eDLT SceneName property and control histories

This batch completes a major bounded portion of issue #45: SceneName property
allocation, complete retained name/getter views and explicit name-control
callbacks in the Toolkit CLI, including ordered parent save/reload through
cmqttd and cgate-mock. Complete Toolkit parity remains unfinished. The 42-area
ledger remains 18 implemented, 22 in progress and 2 pending; 18/42 = 42.86% is only
category arithmetic. The functional denominator is incomplete and zero
obligations are fully accepted.

## Implemented behavior

For KEYGL5 /5055EDL firmware 5.5.00, the sealed SceneManager holds all 64 names,
eight scene getter/value rows and private per-scene control states. Explicit
`get-name` reads the current name without allocation. Source-faithful property
writes retain the old scene index during allocation, check ordinal cached reuse
before capacity and allocate the highest available index. An old row remains
stored when the scene reference moves or clears. The historical additive
`set-name-text` operation retains its existing release-before-allocation and
strict new-text policy.

`scene-name-control` admits explicit input, Enter/Leave, arrow-preview,
selected-name, qualifying list-refresh and close events. Enter/Leave writes
then reads; an arrow suppresses one selection write; list refresh only reads.
Input-only state is reviewable and can continue through issued internal state,
but composition/save refuses unresolved text. Caller JSON cannot inject cache
or control state. Malformed operation schemas refuse before opening C-Gate.

Input allows 64 UTF-16 units, including 32 supplementary characters. Saved PP
keeps the first 63 UTF-8 bytes plus its terminator; retained getters preserve
full cached names until a fresh load. The initial source-established Framework
replacement decoder preserves unchanged malformed rows. Stable Framework
whitespace clears the reference to 255; U+001C and U+FEFF do not. Only-whitespace
U+180E refuses because its classification depends on the original host Unicode
tables. Embedded NUL input and unpaired surrogates remain refused.

Ordered parent operations adopt names only after checked scene composition.
Earlier widget reservations affect allocation; later widgets can reuse the full
cached name. A later indexed grid edit updates every scene getter referencing
that slot without reallocating it. New parent loads and Reset rebuild names;
nested and failed calls preserve enclosing cache isolation. This models explicit
callbacks, not automatic host notification or scene-switch rebinding.

Read [SceneName callbacks](edlt-scene-name-control.md),
[the retained model](edlt-scene-manager.md) and
[ordered parent operations](edlt-parent-transaction.md) for operation schemas.

## Evidence and validation

All four execution slots contributed: independent source/evidence extraction,
retained-model implementation, pure control engine, and owning integration.
After implementation, agents independently reviewed other authors' files.
The source annex pins 32 managed method spans, 26 source symbols, seven Framework
declarations and 23 ordered-call/constants checks. A separate direct metadata
read verifies all 64 FixedStrings literals; initializer order is not culture
suggestion order. No original or Framework instructions were executed.

Ten independent literal profiles provide complete 64 static rows, the 232-byte
SceneBucket, eight pointers and scene count. Public owned-service journeys add
an ordered grid/control/widget/shared-edit case. Each preview/apply case checks
all 844 synthetic PP fields, the full substantive project graph and identities,
one owning PP save, separate project save, backup and close/load. A fresh
Python process reads stored names through the public offline CLI. Refusal cases
cover pending text and attempted private state injection. Lost-successful-save
cases retain the actual lost tagged 200 receipt and do not replay after either
PP or target-project save uncertainty. Invented fixtures contain no house data.

The initial public author runs remain failed records rather than acceptance:
attempt 1 passed 4 and failed 26 parents, attempt 2 passed 8 and failed 22, and
attempt 3 passed 8 and failed 22. These exposed incorrect test-result shape,
Lighting mode, fault-selector matching and offline specification-option placement,
and a real early-validation gap. Corrected expectations follow independent
source/literal facts. Attempt 4 passed all 30 parents before independent review
tightened the companion end-marker, raw readback and exact uncertainty checks.
Those historical runs are not frozen release acceptance. Malformed parent
schemas now refuse before TCP; the existing language regression explicitly
expects zero connections for four schema errors and one for the cache-dependent
English-lock refusal. Final results, separate subtest counts, skips and actual
source/wheel bindings are in the
[publication receipt](../research/fixtures/scene-name-control-owned-release-20261003.json).

## Remaining boundaries

Complete automatic WinForms notification/scene-switch rebinding, culture-sensitive
suggestion sorting/equal-name survivors, autocomplete, pending modal-close
ordering, asynchronous dispatch, source index 64 behavior, wider Unicode-host
classification and original/full combined form acceptance remain open. The
control does not infer a read callback after a direct model edit; a later Enter
writes its retained display unless an explicit read refreshed it first.
Physical rendering, device effects and power-cycle persistence are unassessed.
Database save/reload is not physical programming or cross-command atomicity.

Issue [#45](https://github.com/mitchell-johnson/cbus/issues/45) retains those
broader lifecycle gates; [#69](https://github.com/mitchell-johnson/cbus/issues/69)
retains final acceptance. Deferred manual/protected work in #72–75 is unchanged.
No full local suite is required for this Python-only chunk; owning features,
CLI integrations, current evidence guards and installed-wheel provenance are
validated with focused selections. Rust production and binaries are retained
only when their exact unchanged bindings are verified.
