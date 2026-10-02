# Retained eDLT grid and saved report corrections

This batch improves three active Toolkit CLI workflows against the owned
cmqttd and cgate-mock backends. Full Toolkit/C-Gate compatibility remains
unfinished: the category ledger is 18/42 (42.86%), the functional denominator
is incomplete and zero obligations are fully accepted. None of these counts
is a measured percentage of complete functionality.

## Completed behavior

Ordered eDLT parent histories retain one private StaticLabels name table
across static-text dialog opens, widget edits and SceneManager allocations.
The original names can remain longer than their truncated 63-byte PP image.
Later exact-name lookup reuses the cached row instead of decoding it again or
allocating another slot. Initial load uses the source-established .NET
Framework replacement decoder; malformed rows retain their bytes when their
decoded name is unchanged. A new parent load or Reset rebuilds the cache.
Nested and failed invocations restore their enclosing context.

Explicit grid histories admit begin, input, commit, cancel and focus events.
Cancellation discards the current pending cell and preserves earlier commits.
The value column remains read-only. Pending modal close is explicitly refused:
the exact host WinForms automatic-close sequence remains unproved. The private
cache cannot be injected in operations JSON. Standalone text allocation keeps
its existing strict admission policy. See
[static text and languages](edlt-static-language-add.md).

ST7 SENLL firmware 2.0.01 through the selected factory upper bound 9 has zero
fresh physical and virtual InputKeys. Stored active key commands, occupancy
masks and scenes do not create inherited five-minute template defaults or
report dependencies. Block 4's TimerMin clamps stored zero through nine to ten
seconds; other selected blocks retain zero. The selected derived consumers
report Level Group then On/Off Group, and Light Level Broadcast Group then
Enable Group, preserving repeated role matches. Output/action use is empty.
See [the ST7 source and literal annex](project-documentation-st7-light-level.md).

Native reports now separate exact database Address identity, the original
signed-integer Address projection for headings/anchors, and physical
NetworkNumber. Exact named and noncanonical numeric database selectors are
preserved, without case folding or byte aliases. Source report formatting
canonicalizes 0254 to 254, maps NA to 0 and invalid names to 255; distinct database
identities can therefore share HTML anchors. JSON metadata preserves their
exact ownership. Thermostat, wireless and bridge consumers resolve consumed
physical Numbers independently. Ambiguous consumed Numbers and unresolved
unknowns remain explicit refusals; unrelated duplicate or missing Numbers do
not prevent a proven reference. The Bridge loader initializes its destination
Number to 255 before consuming the last valid forwarding prefix. See
[native report identities](native-project-documentation.md).

DIMPR12A already selects the DIN ErrorReportOutput implementation. It is not
an outstanding Bytecraft body. The separate old and L1 Bytecraft profiles
retain their own device/class limits.

## Validation and evidence

Three implementation lanes ran in parallel with integration, then independent
agents reviewed other lanes. Validation uses invented complete projects,
retained source hashes, literal expectations, ephemeral loopback Rust servers
and closed CNI traps. Public journeys verify PP/database save uncertainty,
snapshot/output digests and complete substantive project preservation. This
does not operate original Toolkit instructions, the VM or a physical network.

Current ST7 expectations explicitly supersede two historical expectations.
The historical remaining-family vector and static receipt retain their exact
bytes. Native public fixtures separately declare the owned archive admission
profile: decimal 42 replaces 0x2A and explicit 255 replaces an absent Number.
General hexadecimal/missing-Number live archive interoperability is unaccepted;
raw saved native XML remains a separately tested input profile.

The initial 76-module source and fresh-wheel selections each ended with
**1,882 passing parents, three bridge failures, 43 provisioning skips and
903 separate passing subtests**. The bridge regression incorrectly marked a
proven absent destination as unresolved. The original nil branch instead writes
`Send Messages to Remote Network: Unknown Network<br/>`; the corrected renderer
retains ambiguity/unknown refusals and restores that exact proven-absence line.

Independent review also found a SceneManager length check before cached-name
lookup. Public validation then exposed its separate no-Add metadata path, which
projected SceneManager before earlier static edits. The correction uses ordered
replay, including prior widget reservations and Blank, without bypassing the
actual cached-name equality or unmatched 63-byte limit. Earlier author failures
remain retained: incorrect Lighting-field offsets, pre-write cached-name
refusals, case-insensitive output-name collisions and provisioning/setup errors.

The final 39-module correction selections each pass **850 parents and 864
separate subtests, with 13 explicit provisioning skips and no failures**. All
16 new public journeys execute without skips against both owned Rust backends.
These include ten eDLT grid journeys, four exact-native-address report journeys
and two ST7 report journeys. Preview/apply results preserve the full cached name,
exact reused index, complete record bytes and substantive project graph. Lost
successful-save receipts retain uncertainty without replay. All 3,818 inputs
and both binaries remain fixed during each final selection.

All **351** final source, wheel and installed runtime files match. Five Python
files differ from the first failed wheel; the other 346 files are unchanged.
Actual import guards cover 140 wheel processes with zero provenance violations.
This is a successful correction selection with an unchanged-package proof;
the original 76-module runs remain red and are not relabeled as a new green gate.
Overlapping counts are not added. The final skips comprise nine explicitly
unconfigured original/native/vendor-schema acceptances and four optional
pinned-source regeneration checks. Separate source recovery reproduces those
available pinned static facts; it does not replace original/native acceptance.

Three independent agents passed the ST7, grid and native/integration reviews.
Six freshly replayed modeled comparisons retain 64 primary cases and four
combined checks, with 1,141 declared bindings across 213 source paths. Their
frontend exclusion is explicit. A current resource/census successor leaves
those maps and outputs unchanged. Rust production and published baseline files
are unchanged; the two new JSON vectors are consumed by Python and are not
inputs to the Rust JSONL loader. The previous Rust gates are retained rather
than repeated. `coverage --require-complete` still exits 1: full parity is open.

The [publication receipt](../research/fixtures/grid-native-report-corrections-owned-release-20261003.json)
binds the failed and final executions, source/wheel overlays, actual import
provenance, reviews, source facts and maintained modeled comparisons. Raw logs
and source coordinates remain private; published artifacts expose logical roles
and hashes. Subsequent prose edits add these results without changing runtime
or tested inputs.

## Outstanding work

Original full-page/generated HTML comparison, native manager and locale
ordering, duplicate-number first-match behavior, complete GUI/form histories,
host-framework modal close and original/hardware acceptance remain open.
Exact database identity support does not establish unique native HTML anchors.
Standalone strict allocators are separate from the retained-parent consumer.
Broad report/device profiles still require their documented consumed fields.
The existing additive SceneManager `set-name-text` operation detaches its old
name reference before a new allocation. The original property setter retains
that reference while allocating. Exact cached-name reuse is covered here;
complete SceneName control callbacks, getter views and replacement-allocation
ordering remain a separate extension under issue #45.

Issues [#45](https://github.com/mitchell-johnson/cbus/issues/45) and
[#57](https://github.com/mitchell-johnson/cbus/issues/57) continue to track these
broader eDLT and documentation gates; protected/manual work in
[#72](https://github.com/mitchell-johnson/cbus/issues/72) through
[#75](https://github.com/mitchell-johnson/cbus/issues/75) is not advanced by this
software-only batch. The full test suites are not repeated for these Python
changes; final validation targets the affected features and evidence guards.
