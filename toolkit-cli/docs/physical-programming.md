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

## Evidence

`tests/test_physical_programming.py` exercises all ten methods, both save forms,
dry-run, capability and schema refusal (including the mixed-method unit-wide NCC
preflight), uncertain save handling, fresh-read mismatch, and zero replay.
`tests/test_cli_physical_programming.py` pins the exact tagged C-Gate command
order through the production socket client.
`tests/test_cmqtt_interop.py` drives a direct-method physical write and fresh
reload through the production Python CLI, real cmqttd, and an independent
synthetic PCI. `tests/test_cmqtt_programming_methods_interop.py` extends that
real product boundary through a one-bridge route for all ten methods. Its
independent Python peer checks the literal route, unit, parameter, tag and
count, injects valid wrong-route, wrong-unit and stale parameter/tag frames
before each matching response, and verifies the final memory bytes after the
CLI's fresh reload. Separate cases reject an over-count correlated read before
any save and drop the PCI connection after one STORE to prove the mutation is
reported uncertain and never replayed.

Five focused one-bridge cases pin the complete outgoing checksummed PCI
transcript, including physical LOAD, one save, verified STORE readback and a
distinct fresh LOAD. They cover standard `direct` with `checksum` protection,
`paged` with `lock` across the page-one/page-two boundary and both unlock
challenges, OEM `edlt` memory, `goc2` memory, and `ncc` with the routed
Save-to-NVM EXECUTE. The existing direct-network CLI/daemon test supplies the
other route class. These cases establish only their synthetic schema and
scripted response combinations; other method/protection combinations and
hardware behavior still need acceptance.

The machine-readable method roster and lower Rust scripted boundary are in
`rust/testdata/fixtures/native_cgate_routed_pp_methods.json`; protection is in
`native_cgate_routed_pp_protection.json`, and the exact C-Bus 3 nonvolatile
sequence is retained in the [routed NVM commit fixture](../../rust/testdata/fixtures/native_cgate_routed_nvm_commit.json).
The Python and Rust peers are scripted transports. They explicitly do not
claim a live bridge, power-cycle persistence, original Toolkit execution, or
broad device and firmware acceptance.
