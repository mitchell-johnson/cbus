# Secondary authorization audit, 2026-09-30

This audit covers C-Gate 3.4.0 build 2001 access-level checks that run
**outside** handler entry. The 431 handler-entry floors are covered by the
earlier `*-authorization-review-*.md` sweeps. The source was a private,
case-sensitive CFR 0.152 decompile of the pinned `cgate.jar`
(`3ec48394…ced630`). It was mounted read-only and detached after use. No
decompiled text is committed.

- [Inventory](secondary-authorization-inventory.json): 28 curated sites and
  1,014 generated object-model rows. Each row records the class, method,
  required level, effect, classification, and SHA-256 hashes of the owning
  source file and anchor statement.
- [Generator](secondary_authorization_audit.py): regenerates the inventory from
  the private decompile with `--decompile <src> --output <json>`.
- [Native capture](../../testdata/fixtures/native_cgate_secondary_authorization_probe.json)
  and its [reproducer](native_secondary_authorization_probe.py): four owned
  IPv4-loopback children, with no C-Bus endpoint, project, or site credential.
  Every child's cleanup is recorded as complete. The reproducer writes only
  the probe output. The committed fixture also includes
  `advisory_lock_earlier_run`, which is the same LOCK sequence from an earlier
  run of the same probe.
- Replays are in `rust/cbus-cgate/src/service/tests/secondary_authorization.rs`
  (eight tests).

The sweep enumerated every use of the level holder `Cb`, `AccessContext`,
`Command.enforceAccess/canAccess`, and the exposed-object security classes
`Ck` (parameter read/write) and `Ch` (method). The following table summarizes
the curated sites.

| Site | Native rule | cmqttd classification |
| --- | --- | --- |
| Event port (`BF.run`) | A new peer needs a live ACCESS level of at least Monitor. Lower peers are closed and logged as `805 null - Access control refused event connection from /IP` (level 4). | **Implemented now**. Captured at Connect, Monitor, a None row, unmatched and Operate. An existing event peer is not re-evaluated. |
| Load-change / config-change ports (`BM`, `BB`) | Same Monitor rule, with events 805/806. | Not applicable: cmqttd has no such listeners. |
| Command address list (`oG.run`) | `accept-connections-from`, silent refusal, event 806. | Partial: admission is implemented, but the 806 event is not emitted. |
| Command session level (`oE`) | The level is the highest matching interface/remote row at connect. With no match, the level is None: the peer gets `421` and event `805 cmdN`. | **Implemented now** (805 event). Loopback fallback and recovery token are deliberate deviations. |
| TLS promotion (`AccessContext.a`) | A Program+ TLS peer is promoted to Clipsal when its root carries a vendor authority key. | Not applicable: cmqttd never maps certificates. |
| LOGIN/LOGOUT dispatch (`oI.a`) | Both bypass `checkRunCommand` and work at None. | Implemented and replayed. |
| LOGIN lookup (`oT.a`) | Exact-case user and password. A mismatch or unknown user returns 422, and a missing password returns `400 Syntax Error.`. A successful login can be above the interface level or at None. | **400 now implemented**; the rest is replayed. |
| LOGOUT (`oU`) | The live table is re-read. Existing sessions keep their level until then. | Implemented and replayed, including a deleted user row. |
| ACCESS row visibility (`u.a(AccessContext)`) | LIST shows, and DELETE numbers, only rows at or below the session level. | Implemented. |
| Command trace (`Command.sendCommandEvent`) | 761/766 only when the root floor is at most Debug. ACCESS, LOG, PP, SAVE_TO_NVM and START_BACKGROUND_JOB leave no trace. | **Implemented now** and replayed. |
| Advisory LOCK owner (`BN`) | Weak reference to the replaced context. | Implemented deterministically; the native release time varies. |
| Root `cgate` parameters (`Ck`) | KCount read requires Clipsal; EventLevel write requires Operate; every other root parameter writes only at Max. | **Implemented now**. Native SET success is not implemented in cmqttd (502). |
| DO methods (`Ch`) | Sync/PSync require Admin; Unravel and FactoryDefault require Program. | Implemented from the generated table. The capture confirms the network Sync and unit PSync denial text. |
| DALI plan re-checks (`ka`, `kc`, `mG`) | Program re-checks against the context retained at plan start. | Redundant with the Program entry floors. |
| PROGRAMMER ADD_INSTRUCTION (`mu`) | Base `lk` declares Clipsal. | Unreachable: the obfuscated enum constants make every type fail parse first. |
| HELP below the floor (`displayHelp`) | Syntax error. | Missing and not compared. |

## Object-model rows

The generated rows classify 1,014 parameter read/write and method levels. The
generator follows each registering class's `extends` chain to the cmqttd object
kind it backs: root `cgate`, project, network, application (`N`), group (`bV`)
or unit (`CBusUnit`). `Bo` backs every kind. Each concrete class takes a name's
level from the most derived class in its chain. The resulting
`object_levels` (530 rows) are rendered by `--rust-table` into
`src/object_access_table.rs`. cmqttd enforces that single table for
`GET`/`SET`/`DO` before dispatch, mutation or PCI I/O (`service::object_access`).

- **Implemented: 875 object rows.**
- **Partial: 4.** These are the `ClockGenActive` reads that need Operate on
  `CBus3DinDigOutputUnit` and `CBusDinProOutputUnit`, but Monitor on the other
  unit classes. cmqttd cannot resolve the native unit subclass, so it applies
  the lower level.
- **Not applicable: 135.** These are child classes that cmqttd does not model,
  such as unit terminals, measurement channels and aircon periods. Terminal
  paths take their unit's levels.
- **Missing: 0.**

The [object capture](../../testdata/fixtures/native_cgate_object_authorization_probe.json)
comes from an owned loopback child with the synthetic PCI from
`toolkit-cli/research/unit_diagnostics_fixture.py`, and its
[reproducer](native_object_authorization_probe.py). It records 22 commands, 38
role responses, a writable parameter, a read-only parameter or restricted read,
and a method for each object kind. The native denial names the object path as
sent. For a missing object, native returns 401 before the level check. cmqttd
keeps that behavior for `GET` only; `SET` and `DO` fail closed. The capture is
replayed in `src/service/tests/object_authorization.rs`, which also pins the
inventory counts.

## Dispositions of the 11 paths without a native floor

The final sweep found no gradient for these paths. The capture adds a
fresh-child role sweep of the native `ACCESSCONTROL` spelling, which returns
400 at all nine roles because the root is not registered. The
`unobserved_paths_keep_documented_dispositions` test pins the following
dispositions.

| Path | Disposition |
| --- | --- |
| `#`, `//` | Parser level, with no floor. 400 at every role. |
| `CONFIRM` | No floor of its own. Natively it re-checks the pending SHUTDOWN, and with nothing pending it returns 400 at every role. cmqttd now returns 400 instead of 408. |
| `LOGIN`, `LOGOUT` | No floor by design (`oI.a`). |
| `ACCESS_CONTROL CLOSE/LOCK` (and `ACCESSCONTROL`) | cmqttd floor of Operate, from source `Cb(3)`. They send physical application 213. |
| `UNIT IDENTIFY` | cmqttd floor of Operate, following native IDENTIFY. |
| `UNIT READMEM` | cmqttd floor of Program, following the Program memory/programming families. |
| `CMQTT LABELS` | cmqttd floor of Monitor, following GET. |
| `CMQTT CAPABILITIES` | cmqttd floor of Connect. |

These floors are cmqttd decisions, not native observations. They are kept
separate from the 431 native floors in `access::CMQTT_DEFINED_FLOORS`.

## Not established

The following were not established by this audit:

- IPv6 peers, native name-resolution refresh, and the 806 event text.
- Load-change and config-change ports.
- Native subclass-specific levels beyond the captured representative matrix
  (source-derived only).
- Physical success at any level.

This audit does not close issue #26.
