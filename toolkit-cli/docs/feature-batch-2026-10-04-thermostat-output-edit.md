# Typed thermostat output Edit — 4 October 2026

The [settings owner](thermostat-output-edit.md) now accepts ordered output Edit
outcomes on the same 23 plant, damper and relay selectors as Select and Add.
Edit renames the group selected at that point in the history, preserving its
identity and address. Cancellation keeps the object without running the
dialog's OK validation. Earlier accepted renames and creations remain in the
shared graph even when a later selection changes the control's reference.

The source rules use an evolving duplicate-name inventory that excludes only
the edited identity, ASCII-only uppercase comparison, exact Project.TagName
comparison and trimming of edge code points at or below U+0020. Explicitly
entered names have a 32 UTF-16-unit limit before trimming. Omitted names retain
the full programmatically loaded text, including longer existing names:
WM_SETTEXT is independent of the edit control's EM_LIMITTEXT entry limit.
Edit requires an eligible selected non-unused group but no free address.

The native owner verifies the fresh OID and preceding name, then sends the
source-encoded quoted TagName through DBSET. Repeated spaces, NBSP, quotes,
backslashes and Unicode remain exact within the admitted command/XML domain.
The ordered ledger retains intermediate renames even when a later edit returns
to the original name. Shared output and remote role views use the final names.
Edit itself assigns no PP reference: a graph-only change uses zero PP saves
and one final target project save, with the backup source save separate.
Uncertain writes stop without replay, deletion or subsequent owner writes.

## Frozen validation

The [release receipt](../research/fixtures/thermostat-output-edit-owned-release-20261004.json)
binds the uncommitted execution tree by exact hashes on base
66773292fe2aa9fd940f6c30f8879e9a6b69eb96. Private logs and traces are identified
by digest without publishing private input locations.

| Check | Result |
| --- | --- |
| Focused source, 21 selected modules | 259 parent passes, 1,510 separate subtests, 12 skips |
| Fresh noneditable installed wheel, same selection | 259 parent passes, 1,510 separate subtests, 12 skips |
| Owned backend cases, in each run | 12 Edit + 16 Add + 16 ordinary outputs + 16 optional levels + 24 remote references, all passed |
| Package inventory and bytes | All 380 source, wheel and installed files equal |
| Execution inputs | All 4,036 tracked/unignored repository files and both debug binaries unchanged |
| Static Add/Edit source reproduction | 337 checks, 138 method spans, five DFM resources, 70-method Edit hook scan |
| Rust binary reuse | All 470 Rust inputs match PR #97; no Rust changes or repeated Rust build/test claim |
| Complete feature coverage | Exit 1; full parity remains unfinished |

Counts overlap and must not be added. The 12 skips comprise five optional
original-file static checks and seven vendor-native integration cases. The new
Edit static receipt was independently reproduced outside the selected pytest
run and exactly matched its committed fixture. Its 337 checks include the 211
shared Add checks. Static inspection executes no original instructions.

The actual installed console ran with child PYTHONPATH removed. It added a
group, renamed that issued identity with repeated spaces, selected the original
group again, and retained the new renamed group after independent reopen.
PP values stayed unchanged: zero PP saves and one final target save, with the
backup source save separate. The command-wire assertions use literal names.

Six modeled C-Gate differential receipts, the contract inventory, parity
register and skip census were refreshed before the final freeze. Independent
source/core and native-adapter reviews found no blocker. The final outcome
audit checks both JUnit/trace pairs, the exact 84-case backend roster, raw
journey receipts, package imports, source/binary hashes and installed-console
evidence. The status and release documents are annotations after execution;
runtime, tests, CI selection and packaged metadata remain frozen.

## Development evidence

Two backend development runs stopped during fixture provisioning before any
public Edit command: the immutable backends reject custom Group/TagName
attributes and omit the synthetic Project custom node from their emitted
profile. The corrected fixtures retain the supported Network metadata,
Level 7/Value 207, Level 200/Value 1 and nonempty DLT data. All 12 corrected
cases pass in development and again in both final runs. Full emitted graph
preservation is checked; pure tests separately verify arbitrary source-snapshot
metadata, including opaque Group/TagName attributes. These evidence layers
are not interchangeable.

Pure development collection/setup and new-test assertion errors are retained
separately from final acceptance. They corrected the test harness and fixture
expectations, including the existing Level 7, without changing the source
rules. No failed attempt is relabeled as a pass.

## Boundaries

This is a typed outcome projected into the existing owning transaction.
Original Edit immediately invokes storage and project-save callbacks, even
for an unchanged accepted name; the owned no-op transaction deliberately
omits redundant saves. Manager label changes can schedule sorting timers.
Numeric Select, first-free Add and duplicate existence checks do not consume
that order, and the native timer/message lifecycle is not reproduced.

The source controls expose Add and Edit by default. Generic Delete/Clear
methods do not prove that those actions are visible thermostat controls.
Application migration, zone histories, complete initialized form behavior,
native-server acceptance and physical thermostats remain open under issues
42 and 72. No full Python/Rust test suite, fresh original instruction execution,
vendor service or physical endpoint is part of this increment. The thermostat
feature category remains in progress.
