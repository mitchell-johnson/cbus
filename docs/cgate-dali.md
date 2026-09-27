# DALI commands in the embedded C-Gate service

cmqttd exposes all 128 maintained DALI command paths registered by C-Gate
3.4.0.2001. The inventory has 103 physical leaves and 25 local paths: six
group-help roots, 62 core/emergency physical leaves, 41 specialized physical
leaves, and 19 specialized catalogue/session/database leaves. No complete DALI
path falls through to the generic unimplemented-command response.

This is command-path coverage, not a claim that every commissioning selector
has full native parity. `DALI SESSION EXTRACT` implements `EXT_ONLY` and all
four source-pinned read-only typed plans: `DALI_ONLY`, `FULL`,
`REFRESH_STATUS_INFO`, and `RETRIEVE_RECONCILE`. `DALI SESSION DEPLOY`
implements `EXT_ONLY`. The three extraction selectors that reach the native
`ADDRESS_UNKNOWN` short-address assignment execute only their evidenced
non-remediating prefix and then stop before that operation. The two typed
deployment selectors listed under [Known boundary](#known-boundary) refuse
before PCI I/O.
`CMQTT CAPABILITIES` therefore keeps `dali_full_compatibility` false.

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
at a time, and only when each staged byte still equals the byte that was sent.
Session-instance and extended-map revision guards reject stale extraction or
deployment commits after an edit, load, or END/NEW replacement; a newer staged
byte remains dirty. EXT-only extraction does not clear typed-model dirtiness.
A reconnect clears cached physical values and ambiguous staged writes, so a
later request cannot replay an outcome-uncertain write.

`EXTRACT ... REFRESH_STATUS_INFO` follows the retained three-step plan over
known ECGs on the selected line and optional address set: discover status,
read the common read-only structure, then read the emergency status structure
for devices typed `EMERGENCY`. `EXTRACT ... RETRIEVE_RECONCILE` follows the
retained six conditional steps: it fills only absent common read-only,
emergency, LED, GTIN and serial structures, with the native discovery step
before missing GTIN/serial reads. Unsupported GTIN/serial replies remain
warnings as they are in build 2001.

`EXTRACT ... DALI_ONLY` follows the exact retained 15-step plan:

```text
CHECK_FOR_UNKNOWN, POLL_KNOWN, BROKEN, MISSING, CONFLICTING,
DISCOVER_KNOWN_TYPE_INFO, DISCOVER_KNOWN_FULL_INFO,
DISCOVER_STATUS_INFO_ECG, GET_KNOWN_TYPE_INFO_ECG,
GET_COMMON_PARAMS_ECG, GET_COMMON_READ_ONLY_PARAMS_ECG,
GET_SCENE_VALUES_ECG, GET_LED_PARAMS_ECG,
GET_EMERGENCY_PARAMS_ECG, GET_EMERGENCY_STATUS_ECG
```

The executor expands each selected line to the native 64 short-address slots,
decodes the little-endian 64-bit known/broken/missing/conflicting/full masks,
and applies an optional ECG-address range without changing unselected slots.
Broken discovery copies the prior value to `isPreviouslyBroken` before it
applies the new mask, and full discovery applies the same bit to both
`isKnown` and `isFullyKnown`.
It decodes supported and unmatched device types, group and scene masks,
minimum/maximum/recovery/failure levels, all 16 scene values, common read-only
status, LED curve/status, and emergency parameters/status. Device-type-gated
steps run only for the retained LED and emergency types.

`EXTRACT ... FULL` follows the exact retained 18-step plan. It has the same
line discovery and typed reads as `DALI_ONLY`, omits `CHECK_FOR_UNKNOWN`, adds
GTIN/serial discovery and reads, then recalls the complete gateway extended
map as `READ_GATEWAY_EXT_FULL`. The typed model and all 11,120 extended bytes
are staged together and published only after the last reply succeeds.

The typed gateway exchanges use DALI device type `0xDA`; line B sets operation
bit `0x80`. The retained base operations and decoded model fields are:

| Operation | Base opcode | Decoded session field |
| --- | ---: | --- |
| Check for unknown | 13 | line `containsUnaddressed` |
| Poll known | 7 | `isKnown` 64-bit line mask |
| Broken | 10 | `isBroken` 64-bit line mask |
| Missing | 11 | `isMissing` 64-bit line mask |
| Conflicting | 9 | `isConflicting` 64-bit line mask |
| Discover known type/full | 3 / 4 | type-discovery status / `isFullyKnown` mask |
| Discover status | 26 | status-only prerequisite |
| Known type info | 16 | supported/unmatched `deviceTypes` |
| Common parameters | 17 | `commonParams102` |
| Common read-only | 18 | `commonReadOnlyParams102` |
| Scene values low/high | 19 / 20 | 16 `scene` levels and recomputed scene mask |
| Emergency status | 24 | `emergencyStatus202` |
| Emergency parameters | 23 | `emergencyParams202`, including derived `switched` and `maintained` flags |
| LED parameters | 25 | `ledParams207` |
| Discover GTIN/serial | 27 | status-only prerequisite |
| GTIN | 21 | six-byte little-endian `gtinSerial.gtin` |
| Serial | 22 | eight-byte little-endian `gtinSerial.serial` |

All typed read-only plans capture one PCI generation, validate status, echoed
ECG addresses, and native payload sizes, and stage all decoded JSON. They
update the session only after every required exchange succeeds, the same PCI
is still connected, and the source session has not changed. `FULL` applies the
same comparison to the extended map. A malformed or partial plan leaves the
previous session snapshot intact. The plans never send DALI configuration
writes, resume a partial plan, or replay an uncertain exchange. Known-ECG,
`A`/`B`/`BOTH`, and comma-separated address selection follows the retained
session executor.

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
multi-step model workflow rather than an extended-memory alias. cmqttd now
implements every bounded read-only typed extraction plan. For the remaining
selectors it executes only the retained read-only prefix, stages the returned
masks, and discards them when the plan reaches operation 2,
`ADDRESS_UNKNOWN`:

- `COND_QUICK`: `ADDRESS_UNKNOWN` is step 3
- `COND_EXTENDED`: `ADDRESS_UNKNOWN` is step 3
- `RESCAN_FAULT`: `ADDRESS_UNKNOWN` is step 4, after `RESCAN`

`COND_QUICK` and `COND_EXTENDED` issue one source-correlated operation-4 poll
followed by non-destructive `MISSING` operation 11. `RESCAN_FAULT` first runs
the documented non-remediating `RESCAN` operation 14. Every exchange is sent
exactly once on the captured PCI generation. Failure, reconnect, or the final
502 commits no session fields and never replays an exchange.

The retained operation-2 request is fully known at the CAL boundary: line A is
`E381DA02`, line B is `E381DA82`, and neither carries payload bytes. The
request cannot name a free short address, selected range, or one physical
device. Its successful data is only an eight-byte assigned/discovered address
mask; it has no device identity, serial-to-address mapping, newly-assigned
marker, allocator ordering proof, or post-assignment model receipt. cmqttd
therefore does not send operation 2 from these selectors and does not infer
allocation semantics from the mask.

The remaining typed deployment selectors also refuse before I/O because their
complete configuration-write plans are not implemented:

- deployment: `DALI_ONLY` and `FULL`

Both selectors still perform the safe local preflight: they require an
existing session, validate the selected known ECG addresses and optional
range, and resolve one configured `SYS_DAL2` gateway. Retained help and the
generic command codecs establish individual operations 32/34/35/38/40 and
their 17/19/20/23/25 getters, but that is not a deployment plan. The retained
evidence has no ordered `DALI_ONLY` or `FULL` step list, no rule assigning
dirty model fields to per-address versus many-address setters, and no
per-field readback acceptance receipt. `FULL` also lacks an atomic ordering
and failure boundary joining typed writes to the separately evidenced
`EXT_ONLY` chunks. Running `EXT_ONLY` first would leave a partial physical
deployment if a later typed write failed, so cmqttd sends no PCI command for
either selector.

This selector boundary is narrower than a command-path gap: both SESSION paths
are implemented, five extraction selectors and `EXT_ONLY` deployment are
physical, and mutation-bearing selectors have a bounded physical preflight but
return 502 before address assignment. Unevidenced deployment plans still
return 502 without touching the bus.
Live gateway and downstream DALI hardware acceptance also remains separate
from loopback protocol acceptance.

## Evidence and tests

- `rust/testdata/fixtures/native_cgate_dali_help.json` pins retained help for
  all 128 paths.
- `rust/testdata/fixtures/native_cgate_dali_specialized.json` records the 60
  specialized paths, class hashes, memory layouts, routing class, exact typed
  plan sequences, and safety boundary from the isolated C-Gate 3.4.0.2001
  oracle. It pins the plan-map, executor, selector, step-enum, operation,
  command-type, typed-model, bit-helper and integer-helper class hashes.
- `rust/testdata/vectors/dali.jsonl` pins request/reply and gateway/page wire
  bytes.
- `rust/cbus-cgate/src/service/dali_specialized.rs` contains fixture, dispatch,
  exact-wire, local-session, catalogue, persistence, and pre-I/O refusal tests.
- `rust/cmqttd/tests/system_cgate_dali.rs` and
  `rust/cmqttd/tests/system_cgate_dali_specialized.rs` launch the real daemon
  against a scripted fake PCI and in-process MQTT broker. The specialized
  system transcript exercises the three-step status plan and the 15-step
  `DALI_ONLY` executor, reads typed values back through `DALI SESSION GET`, and
  proves each mutation-bearing selector refuses without a PCI frame.

Research and tests use loopback fixtures only. They do not contact a real
C-Bus network.
