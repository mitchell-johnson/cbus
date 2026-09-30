# DALI commands in the embedded C-Gate service

cmqttd exposes all 128 maintained DALI command paths registered by C-Gate
3.4.0.2001. The inventory has 103 physical leaves and 25 local paths: six
group-help roots, 62 core/emergency physical leaves, 41 specialized physical
leaves, and 19 specialized catalogue/session/database leaves. No complete DALI
path falls through to the generic unimplemented-command response.

This is command-path coverage, not a claim that every commissioning selector
has full native parity. `DALI SESSION EXTRACT` implements `EXT_ONLY` and all
seven source-pinned typed plans: the read-only `DALI_ONLY`, `FULL`,
`REFRESH_STATUS_INFO`, and `RETRIEVE_RECONCILE`, and the conditional
`COND_QUICK`, `COND_EXTENDED`, and `RESCAN_FAULT`, which send the native
`ADDRESS_UNKNOWN` short-address assignment. `DALI SESSION DEPLOY` implements
`EXT_ONLY` and the typed `DALI_ONLY` and `FULL` plans. Owned native C-Gate
transcripts against a scripted gateway confirm their wire order and payloads
(see [Native transcripts](#native-transcripts)); downstream DALI device state
remains unverified.
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

## Conditional extraction

`COND_QUICK`, `COND_EXTENDED`, and `RESCAN_FAULT` run the recovered plans
listed under [Conditional extraction plans](#conditional-extraction-plans)
with the native per-step AUTO budgets. `POLL_FINISH_DISCOVER_KNOWN_FULL_INFO`
starts with POLL and allows 57 polls 3 seconds apart, `DISCOVER_KNOWN_TYPE_INFO`
allows 17 polls 1 second apart, `RESCAN` allows 60 polls 5 seconds apart, and
`ADDRESS_UNKNOWN` allows 67 polls 3 seconds apart, so one line can take more
than three minutes. The read-only `DALI_ONLY` and `FULL` plans use the same
overrides for operations 3 and 4.

`ADDRESS_UNKNOWN` (operation 2, `E381DA02` or `E381DA82`) is sent exactly once
per selected line. Its request has no payload, and its successful reply is
only an eight-byte address mask. As in native build 2001, cmqttd sets the
line's `containsUnaddressed` to false and each selected ECG's
`isAddressKnown` to its mask bit. A non-success status, including
`IN_PROGRESS` after the 67th poll, is only the warning
`300-[WARN] address unknown incomplete`, and the plan continues.
`RESCAN` failure is likewise the warning `300-[WARN] rescan replyStatus
ignored`. The two conditional discovery steps print
`125-[COND] discovery1:` and `discovery2:` with the native predicate result
and run only when it is true.

Before the first `ADDRESS_UNKNOWN`, cmqttd creates and fsyncs a record in the
[DALI commissioning journal](#dali-commissioning-journal). Nothing that can
change a device is sent before that point, so a failure there keeps the
atomic read-only rule: nothing is committed. Once operation 2 has been sent,
the bus may have changed. Native updates its session model step by step, so
cmqttd then commits the model staged so far, on the captured PCI generation,
when a later step fails. It reports that in the final line. A reconnect or
lost reply during operation 2 leaves the outcome uncertain; cmqttd never
resends it.

## Typed deployment

`DALI_ONLY` and `FULL` deployment run the recovered plans listed under
[Typed deployment plans](#typed-deployment-plans). cmqttd builds and validates
every payload from one session snapshot before it sends anything. That is a
deliberate deviation: native evaluates each ECG as it reaches it, so a model
fault after the first ECG would stop native with earlier ECGs already
written. cmqttd refuses the whole plan instead, with the native progress
lines, the native `501-` warning, and a final
`501 gateway model mismatch: <warning>; no bus command was sent`. Native's
final text is `501 gateway model mismatch: null`.

Each setter uses the default AUTO budget: EXECUTE, then at most 10 polls
1.5 seconds apart. The plan stops at the first fault:

- A non-success status returns
  `502 reply status error: error response: <status>`, as native does, with
  the step and ECG appended. A gateway still reporting `IN_PROGRESS` or
  `FAIL_BUSY` after the budget is recorded as outcome uncertain.
- A lost reply or reconnect returns 503 and is recorded as outcome
  uncertain.
- Earlier writes are neither rolled back nor resumed, and no write is ever
  replayed. The final line names how many planned writes were confirmed,
  the last confirmed write and the write where the plan stopped.

`FULL` then runs the verified `EXT_ONLY` writer on the dirty extended bytes.
With none, it prints native's `126-no dirty bytes detected`. Native
re-serializes its typed extended proxy first. cmqttd has no such serializer,
so `FULL` refuses before I/O while the session has unsaved catalogue edits
(`DALI SESSION CATALOG ADD/REMOVE` or a `SET` below `/catalog`). As in native,
the command's gateway becomes the session target once the plan starts. A
completed plan clears `modelDirty` when the session was not edited during the
deploy; a failed plan leaves it set. Neither native nor cmqttd reads the
written fields back.

## DALI commissioning journal

Typed deployment and conditional extraction change devices one exchange at a
time. Before the first such exchange cmqttd exclusively creates and fsyncs a
`cmqttd-dali-commissioning-journal-v1` record in
`<cgate-state>.dali-journal/`. The record lists every planned write in order:
step, operation, line, ECG or extended address and payload. It is replaced
atomically after each confirmed reply and at the end. After a crash,
`planned[confirmed_writes]` is the only write whose outcome is unknown, and
no later entry was sent. The terminal `state` is `complete`, `failed` (a
definite gateway reply or a journal fault stopped the plan) or
`outcome_uncertain`. `rolled_back` is always false. If the record cannot be
created, the command returns 503 without sending anything. The journal is
operator evidence only: it does not block later commissioning, and cmqttd
never resumes a plan from it. The newest 32 complete records are kept.

## Native transcripts

`toolkit-cli/research/native_dali_commissioning.py` runs owned loopback
C-Gate 3.4.0.2001 against a research-only scripted `SYS_DAL2` gateway at
unit 20 with two synthetic ECGs (3 is `EMERGENCY` and 5 is `LED`). It records
eight cases in `rust/testdata/fixtures/native_cgate_dali_commissioning.json`:
deployment of an empty session, `DALI_ONLY`, `DALI_ONLY` with a rejected
scene write, `FULL`, `FULL` with a missing common structure, `COND_QUICK`,
`COND_EXTENDED` with the conditional discovery branch, and `RESCAN_FAULT`
with a rejected `ADDRESS_UNKNOWN`. A cmqttd unit test replays the same
synthetic gateway and requires identical gateway exchanges and replies in the
same order, the same status, the same progress, warning and `[COND]` lines,
and native's final line as a prefix. The 501 model refusal is the documented
exception. The capture also showed that the gateway status byte names are
`3` `FAIL_INVALID_DEVICE_TYPE`, `4` `FAIL_INVALID_COMMAND`, `5`
`FAIL_INVALID_PARAMETER` and `6` `FAIL_INCORRECT_LENGTH`; cmqttd's DALI
replies now use those names.

cmqttd omits native's per-exchange debug rows (`120-DaliCommand=`,
`100-SendCommand=`, `300-Response=`, `320-ResponseStatus=`), its `125-`
decode rows other than `[COND]`, and the `124-`/`126-progress` rows of
extended-memory reads. The replies are fixture choices, not gateway or
ballast behavior.

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

### Conditional extraction plans

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

### Typed deployment plans

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

- Physical acceptance needs a real gateway with an unaddressed ballast for
  `ADDRESS_UNKNOWN`, and live ECGs for typed deployment. No downstream DALI
  device state, persistence, or behavior after a partial deploy is evidenced.
- `FULL` refuses after catalogue edits until cmqttd can re-serialize the
  native typed extended proxy.
- The recovered colour steps (operations 99 and 100) are in no native plan
  and are not implemented.
- cmqttd does not emit native's per-exchange debug rows during session plans.
- The Python Toolkit CLI has no typed DALI workflow.

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
- `rust/testdata/fixtures/native_cgate_dali_commissioning.json` holds the
  owned native transcripts described under
  [Native transcripts](#native-transcripts), bound to the SHA-256 of its
  capture script.
- `rust/cmqttd/tests/system_cgate_dali.rs` and
  `rust/cmqttd/tests/system_cgate_dali_specialized.rs` launch the real daemon
  against a scripted fake PCI and in-process MQTT broker. The specialized
  system transcript exercises the three-step status plan, the 15-step
  `DALI_ONLY` executor, `COND_QUICK` with an MQTT lighting command delivered
  while `ADDRESS_UNKNOWN` is pending, a typed `DALI_ONLY` deployment with an
  MQTT command delivered mid-plan, and a rejected scene write that stops the
  plan without repeating or continuing it.
- Unit tests in `dali_specialized.rs` cover the 67-poll budget, a reconnect
  during `ADDRESS_UNKNOWN`, the commit after a later failure, payload
  construction and model refusal, a fault at every deploy write, and `FULL`.

Research and tests use loopback fixtures only. They do not contact a real
C-Bus network.
