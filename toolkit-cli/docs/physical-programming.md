# Guarded physical PP programming through cmqttd

`cbus-toolkit cgate physical-pp` is the typed physical counterpart to the
generic `cgate unit` programming API. It uses the production `CGateClient` and
the native `PROJECT USE`, `PP LOCK`, `PP START`, `PP LOAD`, `PP INFO`, `PP GET`,
`PP SET`, `PP SAVE`/`PP SAVE_TO_SOURCE`, `PP END`, and `PP UNLOCK` commands. The
selected cmqttd service owns the CNI connection and resolves a database bridge
route; the Python process does not open a second PCI connection.

The workflow admits the ten methods currently declared by cmqttd:
`direct`, `paged`, `ncc`, `edlt`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and
`goc2`. A missing `ProgramMethod` in the native schema means `direct`, matching
the C-Gate specification behavior.

## Inspect one method

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 \
  physical-pp inspect //PROJECT/NETWORK/p/UNIT --method edlt

cbus-toolkit cgate --host 127.0.0.1 --port 20023 \
  physical-pp inspect //PROJECT/NETWORK/p/UNIT --method direct \
  --parameter UnitName --parameter Project
```

The command first reads `CMQTT CAPABILITIES`. It requires the cmqttd service,
physical and routed PP LOAD support, the requested method, a connected PCI, and
a `ready` programming lane. It then derives the exact `//PROJECT/NETWORK` lock,
loads the physical source, parses `PP INFO *`, and reads either every parameter
using the requested method or the explicitly selected parameters. It rejects a
method mismatch before any edit or save.

Inspection performs physical reads. It returns no persistence claim and sends
no PP save.

## Edit and verify

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 \
  physical-pp apply //PROJECT/NETWORK/p/UNIT --method direct \
  --set UnitName GARAGE --set Project GRENACHE
```

Omitting `--destination` selects native `PP SAVE_TO_SOURCE`. An explicit
physical destination on the same project and network lock selects `PP SAVE`:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 \
  physical-pp apply //PROJECT/NETWORK/p/4 --method goc2 \
  --set ParameterName '0x12 0x34' --destination //PROJECT/NETWORK/p/5
```

All `--set` rows are validated for unique names and native quoting before the
capability command. After physical LOAD, every parameter must exist and use the
one selected method before the first `PP SET`. The command captures the values
before editing, stages each edit, and reads every edited parameter back from the
same PP session. It then issues exactly one save command.

After a confirmed save, the first session is ended and unlocked. A distinct
session performs another physical `PP LOAD` from the saved destination, repeats
the schema checks, and compares every edited value. Numeric comparison follows
the declared native type and array length, so spelling-only differences such as
`0x00` versus `0x0` do not cause a false failure. The schema itself must remain
identical. The successful JSON reports `saved=true`,
`staged_readback_verified=true`, and
`fresh_physical_readback_verified=true`.

`--dry-run` performs the physical load, schema checks, edits, and same-session
readback, then releases the PP session without a save or second load. It is a
hardware-reading and temporary server-session operation, not an offline plan.

## Failure and persistence boundary

The client never retries a `PP SET`, `PP SAVE`, or `PP SAVE_TO_SOURCE`. If a
save reply is rejected, lost, times out, or is interrupted, the emitted
`physical_programming_evidence` keeps `save_attempts=1`, `saved=false`, and
`save_outcome_uncertain=true`. Do not repeat that operation until the device and
server state have been independently inspected. A confirmed save followed by a
fresh-read mismatch reports `saved=true` and
`fresh_physical_readback_verified=false`; it also is not replayed.

An apply against a decoded unit specification containing any NCC parameter
additionally requires `physical_pp_routed_nvm_commit=true`, even when the
selected edit uses another method. cmqttd's native boundary is unit-wide: after
any confirmed change in that C-Bus 3 specification it performs the separate
Save-to-NVM sequence. The client checks the complete schema after physical LOAD
and refuses before the first `PP SET` when that capability is absent. Inspection
and dry-run remain available without it. The output always keeps
`power_cycle_persistence_verified=false`,
`original_toolkit_workflow_executed=false`, and
`hardware_method_matrix_accepted=false`. A fresh PP reload proves the selected
service read back the encoded value during that run. It does not prove behavior
after power loss, every device/firmware combination, a live bridge route, or
execution of the original Toolkit UI.

## Native method and protection contract

cmqttd follows the per-method limits of C-Gate 3.4's `lP` PP codec. Every
STORE group holds at most twelve bytes (`direct`, `paged`, `ncc`, `edlt`,
`giu`, `sgiu`, `dali`), ten bytes (`goc`, `gocbyt`) or eleven bytes (`goc2`),
and `paged`/`ncc` groups also end at a 256-byte page. Page-aware methods
select the page (`39`) before the first group on each page. OEM methods
reselect the `41` pointer before each `42` data group. GIU writes its run
flag halt (`FC 03 00`) before its STOREs and resume (`FC 03 01`) after them.
DALI waits one second before its first STORE. Reads use the native single
request limits: twelve bytes for `direct`, `paged`, `giu`, `sgiu` and `dali`,
six for `goc`/`gocbyt`, and up to 255 for `goc2` and `ncc`; `edlt` keeps the
captured 128-byte block. A paged or NCC reply fragment must name the
parameter of its own first byte (`start + bytes received`), as native `L`
requires.

Protection follows the same save loop. `none` and `checksum` use the
identical tagged STORE; the tag is a transaction index and no checksum field
is rewritten. `lock` sends one `11` UNLOCK for each group's first parameter,
then that group's STORE. `special` fields and non-bit `factory` fields are
skipped. A `factory` field of Type `bit` is native class 14 and uses the
ordinary STORE. When `physical-pp apply` edits a skipped field, the save is
confirmed but the unit is unchanged. The fresh reload then reports
`fresh_physical_readback_verified=false` and exits with status 1.

[`pp-protection-matrix.json`](pp-protection-matrix.json) lists the
method/protection pairs that the decoded Toolkit 1.18 specifications declare.
It contains only names, declaration counts, per-type counts, source file
names, and SHA-256 digests. It never retains specification text. The 280
inputs admit 19 pairs:

- `direct` with `none`, `checksum`, `lock`, `factory` and `special`
- `paged` with `none`, `checksum`, `lock` and `factory`
- `ncc` with `checksum` and `factory`
- `sgiu` and `goc2` with `none` and `factory`
- `edlt`, `giu`, `dali` and `gocbyt` with `none` only

No specification uses `goc`. Only `direct` and `paged` declare factory bits.
To regenerate the table, or to check it with `--check`, run
`research/derive_pp_protection_matrix.py` with `CBUS_UNITSPEC_DIR`.

cmqttd keeps several documented differences from the native codec:

- It reads exact parameter extents. Native LOAD instead reads a whole
  N-byte block from each parameter start.
- It never halts a GIU during LOAD, so reads remain write-free.
- It selects the page again at the start of each paged STORE range.
- After every STORE range, it reads the complete range back.
- It writes a whole parameter when any byte changed. Native C-Gate writes
  only changed bytes, except for `gocbyt`/`goc2`.
- It stores each changed parameter separately, numbering STORE tags from
  zero. Native C-Gate merges adjacent fields with the same method and
  protection, and numbers groups across the whole save.

When one parameter changes in every byte, its STORE groups, tags and UNLOCK
order match the native group plan. The extra writes and readbacks repeat
values that are already on the unit.

## Evidence

`tests/test_physical_programming.py` exercises all ten methods, both save forms,
dry-run, capability and schema refusal (including the mixed-method unit-wide NCC
preflight), uncertain save handling, fresh-read mismatch, and zero replay.
`tests/test_cli_physical_programming.py` pins the exact tagged C-Gate command
order through the production socket client.
`tests/test_cmqtt_interop.py` drives a direct-method physical write and fresh
reload through the production Python CLI, real cmqttd, and an independent
synthetic PCI. `tests/test_cmqtt_programming_methods_interop.py` extends that
real product boundary with an independent Python peer and a separately
derived expected transcript. Its module docstring cites the source of each
expectation. The peer checks the literal route, unit, checksum, parameter, tag
and count. Before every matching response, it injects valid wrong-route,
wrong-unit and stale parameter/tag frames. The tests pin the complete request
transcript of LOAD, one SAVE_TO_SOURCE and the fresh LOAD:

- All ten methods on the local network and through one bridge, with two-byte
  fields.
- All ten methods through one bridge with 23- or 25-byte fields. These cover
  three STORE groups with their offsets and tags, twelve-byte recall blocks,
  page-crossing `paged`/`ncc` ranges, fragmented NCC and eDLT replies, and
  the GIU halt/resume bracket. They also check that the DALI settle is at
  least one second.
- `direct`, `ncc`, `giu` and `gocbyt` through six bridges.
- Every admitted method/protection pair from the matrix, on the local
  network and through one bridge. These include lock UNLOCK counts, factory
  and special skips, and factory-bit writes.
- Unchanged fields that are pre-read but never stored or committed.
- The unit-wide NCC rule: a `direct` edit in a specification that declares
  NCC fields is followed by Save-to-NVM EXECUTE and POLL.

Separate cases reject an over-count correlated read before any save. Others
drop the PCI after the first STORE of `direct`, `paged`, `ncc`, `giu`,
`edlt`, `gocbyt` and `goc2`. Each drop must be reported as uncertain, with
no later chunk, repeated STORE, GIU resume or NVM commit.

`research/verify_network.py --fixture key4 --backend local` runs the owned
C-Gate 3.4 service at the Clipsal access level. A 2026-09-29 run completed
native UnitName LOAD, SAVE_TO_SOURCE, restore and disk reload. Native LOAD
recalled twelve bytes (`1A2A0C`) for the six-byte field. SAVE sent one
six-byte tagged STORE (`A82A00...`). The run still reports `incomplete`
because it does not establish device checksum behavior.

The machine-readable method roster and lower Rust scripted boundary are in
`rust/testdata/fixtures/native_cgate_routed_pp_methods.json`; protection is in
`native_cgate_routed_pp_protection.json`, and the exact C-Bus 3 nonvolatile
sequence is retained in the [routed NVM commit fixture](../../rust/testdata/fixtures/native_cgate_routed_nvm_commit.json).
The Python and Rust peers are scripted transports. They explicitly do not
claim a live bridge, power-cycle persistence, original Toolkit execution, or
broad device and firmware acceptance.
