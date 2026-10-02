# Toolkit conversion CLI, NeoPro CSV and programming event delivery

This batch advances [#43](https://github.com/mitchell-johnson/cbus/issues/43),
[#56](https://github.com/mitchell-johnson/cbus/issues/56) and
[#37](https://github.com/mitchell-johnson/cbus/issues/37). Three implementation
lanes ran concurrently, with separate root integration and independent reviews.
It adds working software features without changing the 18/42 category count
or claiming complete Toolkit or physical parity.

## Operator changes

`cbus-toolkit cgate conversion tweak` exposes all 123 currently admitted
client-side tweaker pairs. Preview binds the exact closed/idle project,
immutable private specification include graphs, source PP and fresh target
defaults. Apply requires exclusive caller ownership and the reviewed plan
digest. It creates a fresh Unit at another unused address, initializes narrow
metadata, submits schema-staged ordered assignments and saves PP once.
Fresh PP and whole-project readbacks verify target identity and source/unrelated
structural preservation. The shared comparator ignores all whitespace-only
text, including `xml:space="preserve"`; attributes, comments, processing
instructions, namespaces and non-whitespace mixed text are checked. Full
opaque whitespace fidelity remains open. Declared parameter refusals retain separately verified defaults
and exit 1; uncertain replies retain scaffolds without replay or deletion.
See [the command and all profile boundaries](toolkit-conversion-tweakers.md).

Native-XML CSV export now admits KEYB2/KEYB4/KEYB6 at exactly 2.5.00. All eight
blocks retain their primary/secondary application selection, with Area 255 in
the primary application. Project and Network selection retain the existing
snapshot ordering; explicit selection retains caller order. Live export reads
one project snapshot and rejects an incomplete or unsupported selection before
creating any output. Public cached JSON refuses these three types because its
schema lacks primary application identity. See [NeoPro rules and evidence](toolkit-database-csv-neopro.md).

cmqttd now delivers subscribed events on a command connection while its
serial request is awaiting programming. Previously that connection awaited
the entire command before polling its event subscription; separate sockets
could receive events, but the command socket stalled. The new helper polls
one command future alongside the existing 512-entry broadcast receiver.
It adds no application command backlog or detached programming task. Ready
commands take priority over a continuous event stream; a finite queued prefix
is delivered before the terminal response. Owner-only programmer replies,
event modes, channels and OID formatting retain their filtering. Slow writes
time out after ten seconds and subscribed overflow fails explicitly. Dropping
the active programming future retires an incomplete PCI generation through
the existing transaction guard. The separate mock TCP fanout remains unbounded;
the library's default 4,096-entry event queue is a different component.

## Verification and evidence

The public interop modules execute the CLI in subprocesses against explicitly
owned `cgate-mock` and `cmqttd` processes on ephemeral loopback ports. Synthetic
projects, private generated specs, brokers, PCI peers and failure relays are
owned and cleaned by each case. Raw commands/replies, child process ownership,
binary hashes and no-contact traps distinguish software proof from live-site
operation. Both source and installed-wheel tests use these maintained cases.

Rust system tests cover direct, one- and six-bridge routes, paged reads,
NCC/NVM, eDLT/GIU/SGIU/DALI and GOC/GOCBYT/GOC2 programming. They exercise
same-socket events, separate socket/MQTT delivery, PCI loss, broker outage,
stalled subscriber cancellation, stale acknowledgements, event mode changes
and an ordinary physical command waiting behind programming. The exact
[interaction vector](../../rust/testdata/vectors/cgate_pp_programming_liveness.json)
states the modeled boundary.

NeoPro class/agent rules were checked by read-only static inspection of pinned
Toolkit EXE/MAP bytes and a fresh maintained registry extraction. The new
current receipt admits 35 types; the historical 32-type receipt is unchanged.
This executes no original instructions and grants no native or GUI acceptance.
Earlier exploratory failures and preparation faults are retained separately
from final release results.

The [bounded release receipt](../research/fixtures/conversion-csv-liveness-owned-release-20261002.json)
records the executed candidate source, binaries, immutable logs/JUnit/trace,
source/resource pins and independent reviews. Results:

| Gate | Executed result |
| --- | --- |
| Rust 1.99 required format, Clippy, workspace tests, release build | All pass; 8,675 tests, one ignored private-project DLT case |
| 22-module source selection | 469 parents and 1,713 subtests pass; three original-input skips |
| Fresh installed wheel, same 22 modules | Same results; all 328 Python/JSON package files equal source, wheel and installed bytes |
| Maintained `make check-interop` | 220 parents/framing checks and 227 subtests pass; two vendor-specification skips |
| Supplementary metadata consumers | 104 parents and 384 subtests pass; one original dialog-input skip |
| Fresh static EXE/MAP extraction | One test passes; reads original bytes without instruction execution |
| `coverage --require-complete` from installed wheel | Exit 1; functional denominator incomplete, zero fully accepted obligations |

Source and final wheel each kept all 3,655 repository input pins and both
release binary hashes unchanged during execution. The wheel additionally
records 173 import snapshots across 97 Python processes, with no violations;
the actual pytest process has both startup and terminal snapshots. Twenty-one
processes have startup-only snapshots, so this does not prove their terminal
cleanup. Per-case server ownership and cleanup are asserted separately.

The first wheel attempt remains failed: 83 failing parents and one failing
subtest arose from missing source-as-data and Git metadata in the private
staging harness. No product/test changes were needed. The corrected fresh
wheel stages the complete frozen source closure as reference data while
keeping `src` off runtime paths, binds the actual pytest PID, and requires
installed-package import records. Git metadata is used only for the selected
read commands; no filesystem read-only enforcement is claimed. Distinct
maintained audit outputs preserve per-node results after a private command-log
filename collision; audit postprocessing is not a new product execution.

Historical author failures, a stopped publication preflight for the explicitly
classified Project-OID prose correction, compiler cache/disk preparation and
private harness preparation faults remain retained. The completed native API
receipts are historical acceptance; the public frontend has current owned
software acceptance. Three final wording/report edits are recorded as
post-validation prose deltas without rebinding earlier executions. The full
Python suite was not repeated. Current original-instruction, VM, native service
and hardware execution is zero; read-only static extraction is separate.

## Outstanding work

#43 still needs the remaining 169 tweaker registrations, source metadata and
delete/readdress lifecycle, retained editor history, project save/reopen,
complete original Toolkit GUI and physical replacement acceptance.
#56 still needs cached primary-application identity, exact provider/Area
outcomes, original GUI/manager/locale and cold native report acceptance,
remaining device/firmware profiles and associations.
#37 still needs original/native and hardware timing/long-save acceptance and
broader load/fanout resource guarantees. Modeled command dispatch is not proof
of those domains.

The manual cyber-deferred [#73](https://github.com/mitchell-johnson/cbus/issues/73)
and [#74](https://github.com/mitchell-johnson/cbus/issues/74) are untouched.
No Windows VM, original instruction execution, real broker/CNI or physical
C-Bus operation is part of this batch. Full functional completion remains
unmeasurable while the authoritative denominator is incomplete;
`coverage --require-complete` continues to fail.
