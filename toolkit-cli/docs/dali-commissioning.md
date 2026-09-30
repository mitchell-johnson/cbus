# Typed DALI commissioning through cmqttd

The Python Toolkit CLI exposes cmqttd's commissioning-session extraction and
deployment plans through `cbus-toolkit cgate dali`. It uses the production
tagged C-Gate client and an owned temporary session. The gateway target is a
physical unit path such as `//PROJECT/254/p/20`; select `A`, `B`, or `BOTH`
explicitly when both DALI lines are intended.

The daemon must advertise the selected plan in `CMQTT CAPABILITIES`. These
workflows use cmqttd's existing shared PCI connection. The server's full DALI
compatibility flag remains false while downstream device behavior, persistence
and the remaining native differences are unverified.

Keep exclusive commissioning ownership while extracting, reviewing and
deploying. Session names are unique, but another C-Gate client can edit a
session; the service does not atomically lock the reviewed model to its write.
The receipt exposes this requirement and the absence of an atomic review-to-write
boundary. Before deployment, the CLI checks that the PCI generation still
matches the initial extraction.

## Extract a commissioning model

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 14400 dali extract \
  //PROJECT/254/p/20 --line A --extract-type DALI_ONLY --ecg 3 --ecg 5
cbus-toolkit cgate --host 127.0.0.1 --timeout 14400 dali extract \
  //PROJECT/254/p/20 --line BOTH --extract-type FULL
```

`EXT_ONLY`, `DALI_ONLY`, and `FULL` read the gateway and selected ECGs.
`REFRESH_STATUS_INFO` and `RETRIEVE_RECONCILE` operate over already known ECGs;
use a read-only `--seed-extract DALI_ONLY` or `FULL` when starting a fresh
workflow that needs that inventory. Repeat `--ecg` to select short addresses,
0 through 63; omission selects the native plan's complete eligible set.

`COND_QUICK`, `COND_EXTENDED`, and `RESCAN_FAULT` can assign short addresses.
They require explicit address-assignment intent and a new client journal:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 14400 dali extract \
  //PROJECT/254/p/20 --line A --extract-type COND_QUICK \
  --allow-address-assignment --journal /operator/dali-address-attempt.json
```

The operation can run for minutes per line because native discovery and
address-assignment steps have long AUTO poll budgets. DALI commands default to
a 14,400-second per-command wait; an explicit `cgate --timeout` overrides it.
A timeout after submitting a
mutation is an uncertain outcome, not permission to repeat the command.

## Preview and deploy edits

An edits file is an ordered JSON array. A `path` edit uses a JSON value at an
existing session-model path. An extended-memory edit uses an integer address
and byte list. For example:

```json
[
  {
    "path": "/cdg/daliLines/0/daliEcgs/3/commonParams102/minimumLevel",
    "value": 10
  }
]
```

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 14400 dali deploy \
  //PROJECT/254/p/20 --line A --ecg 3 --deploy-type DALI_ONLY \
  --edits edits.json --dry-run
cbus-toolkit cgate --host 127.0.0.1 --timeout 14400 dali deploy \
  //PROJECT/254/p/20 --line A --ecg 3 --deploy-type DALI_ONLY \
  --edits edits.json --journal /operator/dali-deploy-attempt.json
```

The workflow validates the input edits, reads a fresh baseline, stages the
ordered changes in its owned session, and returns the staged model.
`--dry-run` performs the physical baseline read and temporary staging but
does not issue `DEPLOY`. Deployment admits `EXT_ONLY`, `DALI_ONLY`, and
`FULL`. `FULL` includes the daemon's extended-memory writer and retains its
pre-I/O refusal after catalogue edits until native proxy serialization is
implemented.

Physical typed edits use leaf paths under
`/cdg/daliLines/L/daliEcgs/E/`, where `L` is 0 for A or 1 for B and `E` is
the selected short address. Supported fields are:

| Structure | Writable fields |
| --- | --- |
| `commonParams102` | `groupMembershipBitmask16`, `sceneMembershipBitmask16`, `minimumLevel`, `maximumLevel`, `recoveryLevel`, `failureLevel` |
| `scene/0` through `scene/15` | `level`, when the scene membership bit is enabled |
| `ledParams207` | `dimmCurve`: `LINEAR` or `LOGARITHMIC`, for LED devices |
| `emergencyParams202` | `emergencyLevel`, `prolongTime`, `timeout`, for emergency devices |

Bitmasks accept integers 0..65535; other numeric fields accept 0..255.
Edits outside the selected line or ECG set are rejected before commands are
sent. The staged model must identify an eligible known ECG at that short
address, with the required device type and scene membership. Whole objects
and other metadata can be staged in a dry run with an explicit
`session-only-metadata` disposition; they are refused as physical edits.
Extended-memory edits accept 1..16 bytes per edit at addresses 256..11375,
with no overlapping edits.

Typed deployment writes all eligible fields in the selected native plan, not
just one changed JSON property. Bound the ECG set with `--ecg` when
only selected devices are intended. The service validates the complete typed
plan before sending it, then stops at the first fault. Earlier writes remain
in place. No command is automatically retried, resumed, or rolled back.

## Attempt receipts and recovery

Before submitting a mutation, the client exclusively creates and fsyncs the
requested journal. An existing filename prevents another attempt through that
path. The journal records the target, selection, baseline, staged edits and
whether submission may have occurred. It supplements cmqttd's separate
`<cgate-state>.dali-journal/` records, which track individual physical writes.
Retain both after any interruption.

`operation_completed` records a successful extraction or deployment separately
from `complete`, which also requires successful session cleanup. Cleanup
failure records `cleanup_error` in the durable journal when possible; it does
not erase an earlier confirmed write or turn an uncertain write into a safe
retry.

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 14400 dali recover \
  --journal /operator/dali-deploy-attempt.json
```

Recovery performs fresh read-only extraction and classifies representable
edited fields as expected, unchanged, mixed, or unreadable. It never deploys,
assigns addresses, or resumes the prior plan. A source-correlated gateway
readback can describe the observed fields; it does not prove downstream
ballast state, rendering, atomic multi-device state, or power-cycle
persistence. Address-assignment and unrepresentable fields retain their
explicit uncertainty rather than being resolved by inference.

## Evidence and limits

The native plans, bytes, progress rows and deliberate service differences are
documented in [the DALI service guide](../../docs/cgate-dali.md). The owned
native transcripts use a scripted `SYS_DAL2` gateway and are not a physical
gateway acceptance result. Focused API/CLI tests cover validation, capability
refusal, session cleanup, exclusive attempt journals, definite failures and
uncertain replies. The real-daemon interop module independently scripts
gateway replies and checks native wire order through the production Python
transport. These checks use synthetic projects and ephemeral loopback ports.

On 2026-09-30 the combined focused run of `test_dali_commissioning.py` and
`test_cmqtt_dali_commissioning_interop.py` passed 44 tests and 36 subtests,
with no skips. It covers all eight extraction modes and all three deployment
modes. The extended-memory peer independently checks page selection, tagged
STORE bytes and mutable readback; the typed peer checks the captured native
setter order, partial failures and lost-reply uncertainty. Recovery runs after
a daemon restart and proves that no mutation is replayed. Unit regressions
cover cleanup-journal failures, generation changes after seed reads, edit
selection and device eligibility. No physical network was used.

To repeat this focused check from `toolkit-cli/` with freshly built `cmqttd`:

```sh
PYTHONPATH=src:tests CBUS_CMQTTD_BIN=/absolute/path/to/cmqttd \
  .venv/bin/python -m pytest -q \
  tests/test_dali_commissioning.py \
  tests/test_cmqtt_dali_commissioning_interop.py
```

The full local suite was not run for this slice, following the requested
focused-test policy. CI retains the broader source and installed-wheel gates;
their results must be checked separately for the integrated revision.
