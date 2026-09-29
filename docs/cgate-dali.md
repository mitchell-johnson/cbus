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
multi-step model workflow rather than an extended-memory alias. cmqttd
implements every read-only typed extraction plan. For the three
mutation-bearing extraction selectors it executes only the retained read-only
prefix, stages the returned masks, and discards them when the plan reaches
operation 2, `ADDRESS_UNKNOWN`:

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
mask; it has no device identity, serial-to-address mapping, or newly-assigned
marker. Native build 2001 merges only that mask into the model, as described
under
[Source-recovered native plans](#source-recovered-native-plans). cmqttd does
not yet send operation 2 from these selectors.

Typed `DALI_ONLY` and `FULL` deployment also refuse before I/O. Both still
perform the safe local preflight: they require an existing session, validate
the selected known ECG addresses and optional range, and resolve one
configured `SYS_DAL2` gateway. The native step order, payload ownership and
failure boundary are now source-recovered, but cmqttd has not implemented the
typed setters. The 502 refusal text predates that recovery: it still says the
order, ownership and readback receipts are missing. Treat it as "not
implemented", not as a statement about native evidence.

This selector boundary is narrower than a command-path gap: both SESSION paths
are implemented, five extraction selectors and `EXT_ONLY` deployment are
physical, and mutation-bearing selectors have a bounded physical preflight but
return 502 before address assignment. The two typed deployment selectors
return 502 without touching the bus.
Live gateway and downstream DALI hardware acceptance also remains separate
from loopback protocol acceptance.

## Source-recovered native plans

An earlier private decompilation was unpacked on a case-insensitive
filesystem. There, `ka.java` and `kc.java` held the unrelated Command classes
`kA` and `kC`, so the executor and selector bodies were missing. The pinned
`cgate.jar` (SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`) was
decompiled again with CFR 0.152 into a private case-sensitive APFS volume with
`--caseinsensitivefs false`. The obfuscated enum fields are named from the
constructor strings in each class constant pool. The facts below come from
that source. No decompiled code is committed.

| Class | Role | Class SHA-256 | Decompiled source SHA-256 |
| --- | --- | --- | --- |
| `ka` | Extraction executor | `12aebdff…80bebd` | `52cd5293…36a6b4` |
| `kc` | Line/ECG selector and command loop | `f6754706…ef31a1` | `fc07031f…df41f6` |
| `jY` | Extraction plan map | `5f6308a2…455e49` | `4ef96ed8…437c8e` |
| `fu` | `SESSION EXTRACT` command | `f83c4a39…534f15` | `deead016…40ab8e` |
| `gq` | Deployment executor | `bf8ba469…255dc6` | `de9a356f…7aa943` |
| `go` | Deployment plan map | `8b877959…9f61ab` | `5e7ffca4…5a6e91` |
| `fs` | `SESSION DEPLOY` command | `22e21c0b…e46d87` | `4b9b0465…6781eb` |
| `oL` | Extended-CAL DALI command base | `a57bb54f…d8c99b` | `b6b6dacb…18a381` |
| `DaliSyncSteps` | Extraction step enum | `726ef597…c3b940` | `0176edf2…fcfe5d` |
| `DaliDeploySteps` | Deployment step enum | `25ad0769…249ab9` | `1e09f648…7213c6` |
| `DaliDeployTypeEnum` | `EXT_ONLY`, `DALI_ONLY`, `FULL` | `7145c9c2…b3c8da` | `ad43dc8e…03d975` |
| `DaliEcg` | Status flags and scene bytes | `50dd3d30…e00f13` | `8a6d10f4…5be7fe` |
| `gu` | Extended dirty-chunk writer | `1c2906e3…8de663` | `e2e2d8d6…567315` |

Full 64-digit hashes for these and 28 further command, model and enum classes
are in `safety_boundary.recovered_native_source.classes` of
`rust/testdata/fixtures/native_cgate_dali_specialized.json`.

### Native CAL sequences

Every DALI command uses the base class sequence: send the first mode, then
POLL while the gateway reports `IN_PROGRESS` or `FAIL_BUSY`. The default is
EXECUTE followed by at most 10 polls, 1.5 seconds apart. Several extraction
steps override that budget:

| Step | Operation | First mode | Polls | Interval |
| --- | ---: | --- | ---: | ---: |
| `POLL_FINISH_DISCOVER_KNOWN_FULL_INFO` | 4 | POLL | 57 | 3 s |
| `DISCOVER_KNOWN_FULL_INFO`, `COND_DISCOVER_KNOWN_FULL_INFO` | 4 | EXECUTE | 57 | 3 s |
| `DISCOVER_KNOWN_TYPE_INFO`, `COND_DISCOVER_KNOWN_TYPE_INFO` | 3 | EXECUTE | 17 | 1 s |
| `RESCAN` | 14 | EXECUTE | 60 | 5 s |
| `ADDRESS_UNKNOWN` | 2 | EXECUTE | 67 | 3 s |

`POLL_KNOWN` sends a single POLL. Native extraction changes the live session
model after each step; it has no staged or atomic commit.

### Conditional extraction

The three conditional plans are:

```text
COND_QUICK     POLL_FINISH_DISCOVER_KNOWN_FULL_INFO, MISSING, ADDRESS_UNKNOWN,
               COND_DISCOVER_KNOWN_TYPE_INFO, COND_DISCOVER_KNOWN_FULL_INFO,
               BROKEN, CONFLICTING, GET_KNOWN_TYPE_INFO_ECG,
               COND_GET_COMMON_READ_ONLY_PARAMS_ECG, GET_EMERGENCY_PARAMS_ECG,
               COND_BROKEN_GET_COMMON_READ_ONLY_PARAMS_ECG,
               COND_BROKEN_GET_EMERGENCY_STATUS_ECG,
               READ_GATEWAY_EXT_COND_QUICK
COND_EXTENDED  COND_QUICK, then GET_COMMON_PARAMS_ECG
RESCAN_FAULT   RESCAN, then COND_QUICK
```

Line steps run once per selected line. ECG steps run once per ECG that is
known and inside the optional address set. The source establishes these
effects:

- `RESCAN` ignores a non-success status with the warning
  `[WARN] rescan replyStatus ignored` and continues.
- `POLL_FINISH_DISCOVER_KNOWN_FULL_INFO` first clears all seven status flags
  on each selected ECG: `isKnown`, `isFullyKnown`, `isAddressKnown`,
  `isBroken`, `isPreviouslyBroken`, `isMissing`, and `isConflicting`. It then
  sets `isKnown` and `isFullyKnown` from the mask bit.
- `ADDRESS_UNKNOWN` sends no payload. A non-success status is only the
  warning `[WARN] address unknown incomplete`; no mask is applied, and the
  plan continues. On success the line's `containsUnaddressed` becomes false,
  and each selected ECG's `isAddressKnown` becomes its mask bit.
- `COND_DISCOVER_KNOWN_TYPE_INFO` (operation 3) and
  `COND_DISCOVER_KNOWN_FULL_INFO` (operation 4) each run only when some ECG
  on a selected line has `isFullyKnown` exactly false and `isAddressKnown`
  true. The address filter does not apply to that test, and it is evaluated
  again before the second step. The type step changes no field. The full
  step sets `isKnown` and `isFullyKnown` without clearing the other flags.
- `BROKEN`, `CONFLICTING` and `GET_KNOWN_TYPE_INFO_ECG` behave as they do in
  `DALI_ONLY`. The type read also clears the emergency, LED and colour
  structures for each reported type.
- `COND_GET_COMMON_READ_ONLY_PARAMS_ECG` (operation 18) and
  `GET_EMERGENCY_PARAMS_ECG` (operation 23) read only ECGs typed `EMERGENCY`.
- `COND_BROKEN_GET_COMMON_READ_ONLY_PARAMS_ECG` (operation 18) reads ECGs
  with `isBroken` or `isPreviouslyBroken` true that are not `EMERGENCY` or
  have no read-only structure. `COND_BROKEN_GET_EMERGENCY_STATUS_ECG`
  (operation 24) reads broken or previously broken `EMERGENCY` ECGs.
- `READ_GATEWAY_EXT_COND_QUICK` recalls the half-open extended ranges
  256–258 and 512–516, plus 7040–7168 and 8800–8816 for `BOTH`, 7040–7104
  and 8800–8808 for line A, or 7104–7168 and 8808–8816 for line B.
- `GET_COMMON_PARAMS_ECG` reads operation 17, as in `DALI_ONLY`.

Apart from `RESCAN` and `ADDRESS_UNKNOWN`, a non-success status aborts the
command with `502 reply status error`.

### Typed deployment

`go` maps the three deployment types to these plans:

| Type | Steps |
| --- | --- |
| `EXT_ONLY` | `WRITE_GATEWAY_EXT_FULL` |
| `DALI_ONLY` | `SET_COMMON_PARAMS_ECG`, `SET_SCENE_VALUES_ECG`, `SET_LED_PARAMS_ECG`, `SET_EMERGENCY_PARAMS_ECG` |
| `FULL` | The four `DALI_ONLY` steps, then `WRITE_GATEWAY_EXT_FULL` |

The executor `gq` also has colour-temperature, colour-power and colour-fail
steps (operations 99 and 100), but no plan uses them. The command records its
CDG as the session target; extraction reads from the session source instead.

Each typed step visits the selected lines in model order, then each line's
ECGs in model order. It writes an ECG only when `isKnown` is true, `isMissing`
and `isConflicting` are not true, and the ECG is in the optional address set.
Each setter uses AUTO with the default 10 polls at 1.5 seconds:

| Step | Operation | Device type | Payload after the short address |
| --- | ---: | --- | --- |
| `SET_COMMON_PARAMS_ECG` | 32 | Any | Group byte 0 (bit *i* is group *i*), group byte 1 (bit *i* is group *i* + 8), minimum, maximum, recovery and failure levels |
| `SET_SCENE_VALUES_ECG` | 34, then 35 | Any | Eight scene bytes: scenes 0–7, then 8–15 |
| `SET_LED_PARAMS_ECG` | 40 | `LED` | Dimming curve: 0 for `LOGARITHMIC`, 1 for `LINEAR` |
| `SET_EMERGENCY_PARAMS_ECG` | 38 | `EMERGENCY` | Emergency level, prolong time and timeout |

The scene step sends operation 34 to every eligible ECG before it sends
operation 35 to any ECG. A scene byte is the stored level only when
`commonParams102` exists, the scene exists, and its scene-membership bit is
set; otherwise it is `FF`. Scene bytes never abort the plan.

Typed steps write every eligible ECG, whether or not its fields were edited.
Only `WRITE_GATEWAY_EXT_FULL` filters dirty bytes: it serializes the typed
extended proxy into target values, writes dirty non-excluded bytes in 12-byte
chunks, and makes each written chunk the current value. Native deployment
performs no per-field readback. A setter is accepted on the `SUCCESS` status
of its AUTO sequence.

Failures stop the rest of the plan:

- A non-success status returns `502 reply status error`.
- Missing `commonParams102`, missing `ledParams207` or curve, an unsupported
  curve, or a missing emergency sub-type returns `501 gateway model
  mismatch` after a 501 warning. The emergency sub-type requires both
  `emergencyParams202` and `commonReadOnlyParams102`.
- Network and synchronization failures return 503 and 504.
- Earlier setters and extended chunks are neither rolled back nor resumed.

`FULL` has no atomic boundary: a typed failure prevents the extended write,
and an extended failure leaves every typed write in place. A step with no
eligible ECG emits the warning `no commands sent - no known ecgs` and
continues.

The source therefore determines the native deployment wire order and payload
ownership. It does not establish downstream device acceptance, persistence, or
the state of a device after a partial plan.

## Outstanding

The following work remains for the three conditional selectors and typed
deployment. No step below is implemented.

Conditional extraction plan:

1. Add per-step poll budgets and a POLL-first AUTO sequence to the DALI
   transport in `cbus-transport`. It currently uses a fixed EXECUTE and 10
   polls at 1.5 seconds. The existing read-only plans use that fixed budget
   for operations 3 and 4, and the prefix sends one POLL for
   `POLL_FINISH_DISCOVER_KNOWN_FULL_INFO`. Both differ from native.
2. Match the native prefix. `RESCAN` accepts a non-success status as a
   warning; cmqttd currently rejects it. `POLL_FINISH_DISCOVER_KNOWN_FULL_INFO`
   must clear the seven flags before it applies the mask.
3. Send `ADDRESS_UNKNOWN` exactly once per selected line with the 67-poll
   budget. That can take more than three minutes. Never replay it after an
   uncertain outcome or reconnect, because it can change DALI addresses.
4. Evaluate the conditional discovery predicate over the staged model for all
   ECGs on the selected lines, then run the remaining steps with the existing
   decoders and the partial extended-map ranges.
5. Decide the commit rule. Native commits step by step. cmqttd's atomic
   snapshot would discard the address-known state after a later failure even
   though the bus may have changed. Document the chosen rule as a deliberate
   deviation, or commit through `ADDRESS_UNKNOWN` explicitly.
6. Add operation-2 vectors and scripted-peer system tests for success,
   non-success, `IN_PROGRESS` polling, both conditional branches, reconnect
   during operation 2, and `RESCAN` failure. Physical acceptance requires a
   real gateway with an unaddressed ballast.

Typed deployment plan:

1. Replace the 502 refusal with the native step lists above. Keep the local
   preflight and resolve one PCI generation before the first write.
2. Build payloads from the session JSON. `groupMembershipBitmask16` becomes
   two little-endian bytes, and the scene byte uses `scene` levels with
   `sceneMembershipBitmask16`. `dimmCurve` maps to 0 or 1. The emergency
   fields need both the emergency and read-only structures.
3. Apply the eligibility filter and device-type gates, and send operation 34
   to all ECGs before operation 35.
4. Use the default AUTO sequence. Return 502 on the first non-success status
   and 501 on a missing field, with a completed-write count. Never roll back,
   resume, or replay.
5. For `FULL`, run the existing verified `EXT_ONLY` writer after the typed
   steps. Confirm that cmqttd's staged extended bytes match native's
   serialization of the typed extended proxy.
6. Native performs no readback. Any cmqttd readback through operations
   17/19/20/23/25 would be a deliberate extension with its own acceptance
   rule, and it should be documented as one.
7. Add exact-wire vectors and scripted-peer system tests for ordering,
   filters, missing fields, a mid-plan failure, and reconnect. Downstream DALI
   device state and persistence still need hardware evidence.

## Evidence and tests

- `rust/testdata/fixtures/native_cgate_dali_help.json` pins retained help for
  all 128 paths.
- `rust/testdata/fixtures/native_cgate_dali_specialized.json` records the 60
  specialized paths, class hashes, memory layouts, routing class, exact typed
  plan sequences, and safety boundary from the isolated C-Gate 3.4.0.2001
  oracle. It pins the plan-map, executor, selector, step-enum, operation,
  command-type, typed-model, bit-helper and integer-helper class hashes.
  `safety_boundary.recovered_native_source` records the case-sensitive
  re-decompilation: class and private-source hashes, poll budgets, the
  conditional step effects, and the typed deployment plans. A unit test binds
  its executor, selector, plan-map, step-enum and operation-2 hashes to the
  existing plan evidence.
- `rust/testdata/vectors/dali.jsonl` pins request/reply and gateway/page wire
  bytes.
- `rust/cbus-cgate/src/service/dali_specialized.rs` contains fixture, dispatch,
  exact-wire, local-session, catalogue, persistence, and pre-I/O refusal tests.
- `rust/cmqttd/tests/system_cgate_dali.rs` and
  `rust/cmqttd/tests/system_cgate_dali_specialized.rs` launch the real daemon
  against a scripted fake PCI and in-process MQTT broker. The specialized
  system transcript exercises the three-step status plan and the 15-step
  `DALI_ONLY` executor, and reads typed values back through
  `DALI SESSION GET`. For each mutation-bearing extraction selector, it
  answers the prefix exchanges, then proves that no operation-2 frame is sent
  and the session is unchanged. Typed `DALI_ONLY` and `FULL` deployment refuse
  without a PCI frame.

Research and tests use loopback fixtures only. They do not contact a real
C-Bus network.
