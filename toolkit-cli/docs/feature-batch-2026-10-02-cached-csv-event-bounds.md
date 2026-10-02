# Replacement lifecycle, cached NeoPro CSV and bounded mock delivery

This batch advances [#43](https://github.com/mitchell-johnson/cbus/issues/43),
[#56](https://github.com/mitchell-johnson/cbus/issues/56) and
[#37](https://github.com/mitchell-johnson/cbus/issues/37), with the mock fanout
slice also relevant to [#54](https://github.com/mitchell-johnson/cbus/issues/54).
Three implementation lanes ran concurrently with root integration; finished
authors review another lane. Category counts and fully accepted obligation
counts do not change. Full functionality percentage remains unavailable while
the authoritative denominator is incomplete.

## Delivered functions

The separate `cgate conversion tweak-replace` command reuses all 123 admitted
tweaker pairs. It derives the first available staging address in 1..255 from
a fresh closed/idle project, retains admitted source metadata and database
serial, creates/verifies one backup, and initializes a fresh target. After one
PP save it freshly verifies the source and unrelated project, deletes the
source, readdresses the target to that address, and verifies project/PP before
and after save/close/load. Every persistent send has a preceding durable journal
checkpoint. Temporary PP planning occurs before journal creation. The
`tweak-recover` command validates a retained journal locally and performs
read-only project/backup/PP classification on its bound endpoint. It never
replays, restores or automatically deletes an uncertain scaffold. See
[the complete lifecycle contract](toolkit-tweaker-lifecycle.md).

This source-established database lifecycle is distinct from the original GUI's
catalogue selection, editor state and exception cleanup. Static inspection of
pinned original EXE/MAP bytes recovers the metadata, staging, deletion and
readdress order; it executes no original instructions. Non-ASCII fallback
names, unrepresentable scalar metadata, arbitrary opaque whitespace, full
Toolkit workflow and physical replacement remain open. The shared XML
comparator ignores all whitespace-only text, including `xml:space="preserve"`.

Public cached CSV v2 admits KEYB2/KEYB4/KEYB6 at exactly 2.5.00, with explicit
primary/secondary Application identity, complete Group membership and byte
mask. It validates all eight block routes before modeled provider events or
output creation and resolves Area through primary independently of traversal
order or an all-secondary mask. The finite retained provider contract covers
two Area observations, reference transitions and missing-255 create/save
outcomes. This caller-provided cache performs no database reads or writes;
native XML supplies its authoritative context through the same projector.
Existing families retain v1 behavior; NeoPro v1 remains refused. See
[the exact schema, provider outcomes and limits](toolkit-database-csv-neopro-cached.md).
The 35-type admission registry is unchanged.

Each mock TCP peer admits at most 512 whole event/reply batches and 32 MiB of
active/queued wire payload. Origin-filtered events and complete responses are
atomic, preserving continuation/document framing; a response with more than
512 rows remains one batch. Admission never waits under the shared model lock.
Budget exhaustion, oversized output or a ten-second batch write timeout
retires that peer while other clients continue. A command may already have
executed before its receipt is lost; neither rollback nor replay is inferred.
The reader retains at most 1 MiB plus one line byte and drains oversized rows
to the delimiter within the existing 16 MiB document policy. The normal
one-second final-reply teardown drain remains. See
[mock resource bounds](../../docs/cgate.md) and
[the interaction vector](../../rust/testdata/vectors/cgate_mock_delivery_bounds.json).
These are per-peer wire bounds, excluding allocator metadata, socket buffers,
shared model, transient formatting and aggregate clients. cmqttd's separate
broadcast receiver and the library event queue retain their own policies.

## Verification

Final integrated release results are recorded in the
[bounded receipt](../research/fixtures/cached-csv-event-bounds-owned-release-20261002.json).
The gates use owned synthetic projects/specifications, ephemeral loopback
servers and failure relays; source and fresh installed-wheel subprocesses
exercise the same public cases. Counts distinguish parents, subtests,
provisioning skips and historical attempts. No private input or vendor binary
is published.

Independent reviews identified and corrected a cached generated-OID collision,
recovery endpoint test drift and test coverage gaps; their final pinned reports
are separate from execution evidence. Failed author/preparation attempts and
the initial root Clippy test-lint failure remain retained. Corrected source is
never rebound to a prior failed execution. The required Rust gates passed with 8,690 tests and one ignored private-project
DLT upgrade case. Focused source and installed wheel each passed 650 parents
and 2,512 separate subtests; 13 original/native provisions were skipped.
These include three earlier original-input gates and ten adjacent classic
replacement gates (one original-source and nine native-server/spec gates).
Maintained interop passed 254 parents/framing checks and 227 separate subtests,
with two decoded-vendor-specification skips. The full Python suite was not
repeated.

| Gate | Executed result |
| --- | --- |
| Required Rust format, Clippy, workspace tests, release build | Pass; 8,690 tests, one private-input ignored case |
| 28-module source and initial fresh installed wheel | Each 650 parents and 2,512 subtests pass; 13 provisions skipped |
| Maintained mock/daemon interop, including all 34 lifecycle cases | 254 passes (252 JUnit parents plus two framing checks) and 227 subtests; two decoded-spec skips |
| Final seven-module resource consumers, source and fresh final wheel | Each 167 parents and 552 subtests pass; no skips |
| Final package byte proof | All 329 Python/JSON files equal current source, wheel and installed bytes |
| Installed completion declaration gate | Exit 1; census incomplete and no trusted evidence root supplied |

The original source/wheel and interop gates kept all 3,669 input pins and both
release binaries unchanged. The first wheel records 470 import snapshots from
262 Python processes, with zero violations and both snapshots for the actual
pytest PID. Fifty-four processes have startup-only snapshots; this is not an
all-process terminal-cleanup guarantee. The final wheel's narrower resource
selection records four snapshots from two processes, including both actual
pytest snapshots. Per-case owned-server cleanup is separate evidence.

Late publication review found 12 local-coordinate fields across six generated
comparison records. The maintained sanitizer retained exact raw captures and
published declared derivatives without changing observed results or 1,141
source bindings. Two packaged parity JSON files were regenerated. The later
source/resource gates and a second fresh wheel prove those current bytes;
the earlier 650-test executions remain tied to their earlier package. All
Python files and the 329-file package roster are unchanged between wheels.
One lifecycle vector wording change after the Rust gates is separately pinned
and consumed by the final Python tests; no Rust source change is hidden.
Final batch/status prose and the sanitized release receipt follow validation
as explicit publication deltas.

The interop launcher's requested private pytest parent was filtered from its
environment; its actual default pytest artifacts are retained. The earlier
preparation assertion is corrected without a retroactive isolation claim.
An extra copied older context has no framing-test credit; framing success is
bound to the actual command/result log. Product results and owned process
cleanup remain verified. Read-only recount preparation errors are retained
separately and caused no product rerun.

The previous published `7d57f358` commit has green
[CI run 36955852990](https://github.com/mitchell-johnson/cbus/actions/runs/36955852990).
Its native/hardware jobs were skipped. This precommit report makes no current
publication CI-success claim.

## Outstanding work

#43 retains 169 unadmitted tweaker registrations, original catalogue lookup and
exception cleanup, retained agent/editor history, complete GUI/template/reset
behavior, broader metadata/whitespace fidelity and physical programming.
#56 retains fresh original provider/manager/GUI/locale evidence, cold native
report acceptance, remaining device/firmware profiles and associations.
#37/#54 retain original/native overflow and timing semantics, long-save and
physical/MQTT coexistence acceptance, and aggregate model/client resource
guarantees. This batch closes these named software pieces, not those umbrellas.

Manual cyber-deferred [#73](https://github.com/mitchell-johnson/cbus/issues/73)
and [#74](https://github.com/mitchell-johnson/cbus/issues/74) are untouched.
Current original instruction execution, VM, real broker/CNI and hardware
operation are zero; static original-byte inspection is recorded separately.
`coverage --require-complete` must continue to refuse full parity.
