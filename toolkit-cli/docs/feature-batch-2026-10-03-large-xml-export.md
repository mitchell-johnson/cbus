# Explicit large XML exports — 3 October 2026

The public `cgate database get-xml --output` command now accepts an explicit
`--max-xml-bytes` budget in 1..134217728 (128 MiB). Existing commands retain
their current bounds. The option is limited to a read-only export connection;
it does not widen XML imports, automatic metadata reads or historical
native-bound document profiles. The [operator guide](native-database-xml-files.md)
documents the command and its independent server limits.

The exported UTF-8 XML snippet must fit the declared budget. Transport allows
that budget plus 64 KiB for framing, retains the existing 100,000-line ceiling,
and limits this connection to one unsolicited event. A second event, an
oversized document or wire response, a failed reply or an interrupted read
publishes no export and is never retried. Existing destinations are refused
before connection; publication still protects against a competing writer.

The owned Rust frontends have a separate 32 MiB output budget. Neither the
client's 128 MiB ceiling nor cmqttd's 256 MiB serialized repository profile
proves equally large TCP exports. The new acceptance uses an explicitly owned
Python loopback wire peer with a compact XML snippet exceeding 17 MiB. It
establishes bounded client behavior, not original C-Gate capacity, Rust daemon
delivery at the client ceiling, or physical hardware acceptance.

## Completed source and fresh-wheel scopes

Five new public loopback cases cover widened success with exact bytes/hash,
unchanged default refusal, document/wire overflow, failed replies,
no-overwrite publication, event overflow, preconnection option validation and
exact-once command histories. They ran with the existing database-project CLI
and native XML-file CLI modules. Both source and fresh isolated-wheel scopes
passed **71 parent cases and six separate subtests**, with **one original
C-Gate provisioning skip**, and exited 0. The wheel imports from its isolated
Python 3.13 site-packages and includes the `test,research,serial,usb` extras.
All 388 wheel package files match both source and the isolated installed
package byte-for-byte; the wheel identity is retained in the receipt.
These overlapping scopes are not added to broad source totals.

The completed original source epoch ran `TMPDIR=/var/tmp make check` and exited
0 with **10,027 passing parent cases, 1,410 provisioning skips and 44,477
separate passing subtests** in 4,778.08 seconds. Its 14 scoped inputs stayed
unchanged through completion. This source epoch supplied no Rust backend
environment overrides; absent worktree binaries account for backend skips.
The skips do not establish original software or hardware acceptance.

## Separate relay successor and complete backend scopes

**The complete owned mock and daemon scopes pass in separately retained epochs.**

Its complete mock selection has passed 390 cases and 158 separate subtests,
with one absent-vendor-spec skip, in 4,255.00 seconds. The daemon selection
then failed the owned Network SAVE DB journey's public call 108,
`portable-XML_TO_SQL`, with a complete 408 transform error reporting a read-only
filesystem. The invocation supplied `TMPDIR=/var/tmp`; Rust's transform staging
uses that directory directly, outside this execution session's writable roots.
Root requested interruption of only the verified large-read daemon pytest.
The actual Make exit was 2; the partial daemon scope retained one failure,
226 passes, one specification skip and 69 separate subtests in 1,199.98 seconds.
The test's temporary-directory cleanup removed raw relay artifacts, so this
log does not supply a complete wire census. No wire totals are fabricated.
This failed/interrupted successor does not establish complete interop acceptance.

After workspace-only provision of the official Debian SQLite 3.46.1 CLI and
correction to `TMPDIR=/tmp`, the separately owned root recheck of that exact
failed node passed (one case, 59.51 seconds). The large-read complete daemon
successor then ran `make check-cmqtt-interop` with the same frozen daemon binary
and explicit Make override. It exited 0 with **531 passing cases, one absent
vendor-specification skip and 69 separate passing subtests** in 5,817.23 seconds.
All 16 scoped runtime inputs and both binary hashes remained unchanged. The
SQLite package/CLI hashes, version and corrected environment are recorded
separately in the receipt. No runtime source or census change was used to
repair this environment failure.

The failed monolithic `make check-interop` retains its actual exit 2. Its clean
mock scope and the later complete daemon scope establish the backend selections
in separate epochs; they must not be described as a monolithic Make exit 0.

The earlier stable interop epoch failed the Global images
`lost_first_target_save[mock]` history: its fault saw zero matches before the
first `PP SAVE_TO_SOURCE`, and cleanup recorded `BrokenPipeError`. Root then
interrupted the remaining selection. Its actual exit was 2, with one failure,
339 passes, one absent-vendor-spec skip and 158 separate subtests in 3,847.35
seconds. These partial outcomes are retained, not promoted to a complete pass.

A later test-only relay successor batches bounded bulk replies and uses
TCP_NODELAY while preserving the exact fault boundary. It also finalizes the
Global evidence on failed histories and adds six focused relay cases. The
large-read helper/regression selection passed ten cases (nine deselected) with
exit 0; the separately owned root recheck of the formerly failing Global node
passed against both mock and daemon (two cases, 53.03 seconds). The regenerated
skip census check exits 0 with 752 modules and 259 required native selections.
The complete interop successor uses explicit Make binary overrides into the
separate `/workspace/cbus-large-read-target` build directory.

These later harness files and census belong to a separate 16-input epoch. The
earlier complete source pass must not be described as a final full-source run
over those revisions. Production export code and the isolated wheel remain
unchanged; the focused source/wheel export proof is still bound to those files.

Three earlier source epochs and one incomplete-harness interop epoch were
interrupted while shared test harness integration was incomplete. Their logs,
partial summaries and artifact hashes remain in the
[owned checks receipt](../research/fixtures/large-xml-export-owned-checks-20261003.json).
The receipt also distinguishes original source inputs, successor inputs,
binary identities, wheel identity and the retained failed interop epoch.
No parent or subtest totals from overlapping/interrupted epochs are summed.

This batch does not close the broader repository capacity issue #77 or claim
full Toolkit parity. Original workload comparison, server delivery beyond
owned transport limits, mutation-memory scaling and broader durability remain
separate work.
