# DALI commands in the embedded C-Gate service

cmqttd exposes all 128 maintained DALI command paths registered by C-Gate
3.4.0.2001. The inventory has 103 physical leaves and 25 local paths: six
group-help roots, 62 core/emergency physical leaves, 41 specialized physical
leaves, and 19 specialized catalogue/session/database leaves. No complete DALI
path falls through to the generic unimplemented-command response.

This is command-path coverage, not a claim that every commissioning selector
has full native parity. `DALI SESSION EXTRACT` and `DALI SESSION DEPLOY` have an
exact physical implementation for `EXT_ONLY`. The retained typed-device plans
listed under [Known boundary](#known-boundary) refuse before PCI I/O until their
complete C-Gate model codec is evidenced. `CMQTT CAPABILITIES` therefore keeps
`dali_full_compatibility` false.

## Core and emergency commands

The 48 core commands and 14 commands below `DALI EMERGENCY` use priority-zero
direct point-to-point extended CAL addressed to a configured `SYS_DAL2` unit.
EXECUTE is sent once. AUTO follows that one execution with no more than ten
polls, 1.5 seconds apart, while the gateway reports `IN_PROGRESS` or
`FAIL_BUSY`. Completion requires a source-correlated reply from the addressed
gateway on the same PCI generation. A missing reply or reconnect makes the
outcome uncertain; cmqttd never replays the execution.

Native help advertises STATUS, but retained C-Gate does not supply its
mandatory selector. cmqttd preserves the observed pre-I/O 400 result instead
of inventing a value.

## Specialized commands

The 60 specialized leaves divide into 41 physical operations and 19 local or
durable operations.

### Catalogue and local gateway views

`DALI CATALOG LIST`, `GET_SPEC`, and `RELOAD` read project-scoped JSON from the
durable virtual FILE repository:

```text
%PROJECT%/dali_catalogue/devices/*.json
```

These paths never open a caller-selected host file. The repository deliberately
does not ship vendor catalogue data. Upload the required specifications through
the C-Gate `FILE` family, then run `DALI CATALOG RELOAD`.

`DALI GATEWAY LIST`, `DEVICE_ID_LIST`, `NAC_SUMMARY_LIST`, and
`PROJECT_CUSTOM` read the selected project and saved DALI session state. They
perform no PCI I/O. `SET_EXTENDED_PARAMETERS` stages bytes in volatile gateway
state; `WRITE_EXTENDED_PARAMETERS` is the separate physical commit.

### Gateway programming

Gateway factory reset, restart, preset load, and NVM save use native DALI
gateway group-zero extended CAL operations 1 through 4. Factory reset and
restart reverse the packed native gateway serial in the execution payload.
They use the same source-correlation and reconnect generation rules as the
core family.

Paged memory operations share cmqttd's PCI programming lane. Recalls never
cross a 256-byte page in one request. Stores use at most 12 data bytes, require
the native page selection and tagged acknowledgement, and read the stored
range back before success. The retained layouts are:

| Data | Line A | Line B | Size/stride |
| --- | ---: | ---: | --- |
| Primary address | 768 | 3872 | 1 byte, 32 bytes per object |
| Short-address map | 7040 | 7104 | 16 bytes |
| Virtual group | 7168 | 7296 | 8 bytes, 8 bytes per group |
| Extended parameters | 256 | 256 | addresses 256 through 11375 |

`PAGED_RECALL` and `PAGED_STORE` expose the same bounded page-aware transport.
`READ_EXTENDED_PARAMETERS` refreshes the complete volatile extended map.
`SET_EXTENDED_PARAMETERS` stages changes and `WRITE_EXTENDED_PARAMETERS`
writes only changed, page-bounded chunks. Each verified chunk is committed to
local state only while the sending PCI generation remains current.

### Error reporting and measurement

The error-reporting getters and setters recall or store these evidenced
gateway memory fields:

| Field | Address | Length |
| --- | ---: | ---: |
| Store option | 521 | 1 |
| Device ID | 556 | 1 |
| Enable group | 632 | 1 |
| Trigger report group | 633 | 1 |
| Resend action selector | 634 | 1 |
| Acknowledge-all selector | 635 | 1 |
| Mode | 636 | 1 |
| Interval | 637 | 1 |
| Network path | 638 | 6 |
| Used-device mask, line A/B | 8800 / 8808 | 8 |

Measurement trigger groups use addresses 558 and 559. Lamp running time is a
four-byte value at line-A base 7424 or line-B base 7680, with a four-byte
stride for each short address. Setters use the verified store path; getters
use the page-aware recall path.

### Commissioning sessions

`NEW`, `END`, `LIST`, `GET`, `MULTIGET`, `SET`, catalogue add/remove, and
`SET_EXT_PARAMS` maintain native-shaped volatile session state. GET and SET use
JXPath-shaped paths over the session JSON model. `SAVE` and `LOAD` store a
gateway-OID-keyed snapshot in cmqttd's atomic JSON database; an active session
itself remains connection-service state.

`EXTRACT ... EXT_ONLY` recalls addresses 256 through 11375 into the session.
`DEPLOY ... EXT_ONLY` writes only dirty extended values with page-bounded,
readback-verified stores. Confirmed chunks are removed from the staged set one
at a time. A reconnect clears cached physical values and ambiguous staged
writes, so a later request cannot replay an outcome-uncertain write.

## Authentication and MQTT continuity

When the optional command gate is armed, catalogue reload, specialized
setters, physical gateway mutations, and session mutations require LOGIN.
Catalogue reads, gateway lists, parameter recalls, and session GET/LIST remain
available at their retained observation boundary.

DALI does not define an MQTT entity or retained DALI state contract. DALI
operations share the daemon transport without blocking its MQTT event loop;
the real-daemon tests send an MQTT lighting command while a DALI gateway
operation is pending and verify that it reaches the fake PCI.

## Known boundary

The build-2001 classes show that typed session extraction/deployment is a
multi-step model workflow rather than an extended-memory alias. cmqttd refuses
these selectors before I/O because their full typed model codec is not yet
evidenced:

- extraction: `DALI_ONLY`, `COND_QUICK`, `COND_EXTENDED`, `FULL`,
  `RESCAN_FAULT`, `REFRESH_STATUS_INFO`, and `RETRIEVE_RECONCILE`
- deployment: `DALI_ONLY` and `FULL`

This selector boundary is narrower than a command-path gap: both SESSION paths
are implemented and `EXT_ONLY` is physical, but unsupported typed plans return
502 without touching the bus. Live gateway and downstream DALI hardware
acceptance also remains separate from loopback protocol acceptance.

## Evidence and tests

- `rust/testdata/fixtures/native_cgate_dali_help.json` pins retained help for
  all 128 paths.
- `rust/testdata/fixtures/native_cgate_dali_specialized.json` records the 60
  specialized paths, class hashes, memory layouts, routing class, and safety
  boundary from the isolated C-Gate 3.4.0.2001 oracle.
- `rust/testdata/vectors/dali.jsonl` pins request/reply and gateway/page wire
  bytes.
- `rust/cbus-cgate/src/service/dali_specialized.rs` contains fixture, dispatch,
  exact-wire, local-session, catalogue, persistence, and pre-I/O refusal tests.
- `rust/cmqttd/tests/system_cgate_dali.rs` and
  `rust/cmqttd/tests/system_cgate_dali_specialized.rs` launch the real daemon
  against a scripted fake PCI and in-process MQTT broker.

Research and tests use loopback fixtures only. They do not contact a real
C-Bus network.
