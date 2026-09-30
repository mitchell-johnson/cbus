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
`FULL`. `FULL` compiles the complete recalled native extended proxy before
its extended-memory writes. Catalogue edits remain independent session
metadata: they do not project into the physical CDG proxy. The CLI refuses a
catalogue edit as a physical deployment request while allowing explicit
session-only staging in a dry run.

Global gateway settings use leaf paths below `/cdg/extParams/proxy/`. The
service advertises the exact 133-field schema across 21 families, which the
CLI verifies before admitting an edit. For example:

```json
[
  {"path": "/cdg/extParams/proxy/deviceID/id", "value": 42},
  {"path": "/cdg/extParams/proxy/frontPanelUiControl/localToggleDisabledA", "value": true}
]
```

Use `--deploy-type EXT_ONLY --extract-type EXT_ONLY` for gateway-only settings,
or `FULL` for a combined gateway/device plan. An extended-memory baseline is
required before staging these controls. Whole recalled families are compiled
in native order, including unchanged values and reserved-bit normalization;
the physical writes may therefore extend beyond the explicitly edited leaves.
The native dirty-byte exclusions still apply. A requested excluded field,
an unknown source family, or overlapping raw and typed ownership is refused
before deployment. Restore levels and error-reporting mode have conditional
exclusions depending on their staged enable settings.

The service also decodes and serializes all 15 native line families. Physical
CLI admission currently covers the global leaves; line edits, whole proxy
replacement and computed utility edits remain outside that admission. A
literal raw-only `EXT_ONLY` operation retains its direct-byte behavior without
implicitly serializing the proxy.

Physical typed edits use leaf paths under
`/cdg/daliLines/L/daliEcgs/E/`, where `L` is 0 for A or 1 for B and `E` is
the selected short address. Supported fields are:

| Structure | Writable fields |
| --- | --- |
| `commonParams102` | `groupMembershipBitmask16`, `sceneMembershipBitmask16`, `minimumLevel`, `maximumLevel`, `recoveryLevel`, `failureLevel` |
| `scene/0` through `scene/15` | `level` in 0..254, when the scene membership bit is enabled; a nullable slot can be created as `{"level": N}` |
| `ledParams207` | `dimmCurve`: `LINEAR` or `LOGARITHMIC`, for LED devices |
| `emergencyParams202` | `emergencyLevel`, `prolongTime`, `timeout`, for emergency devices |

Bitmasks accept integers 0..65535; other numeric fields accept 0..255 except
scene levels, which require 0..254. Native scene byte 255 removes that scene.
Enabling a membership bit requires a representable level in the staged scene;
a mask-only activation with a null slot or level 255 is refused. Create the
scene object and set the membership bit in the same ordered edits file.
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
For proxy edits, recovery reads a fresh extended-memory baseline. Its result
compares the explicit operator edits; matching those fields does not prove
that every implicit proxy normalization or every chunk of an interrupted
plan completed. The original incomplete attempt journal is retained.

Edits and recovery journals must be bounded regular files. Nonblocking inode
checks reject FIFOs, symlinks and files substituted during reading before any
C-Gate connection.

## Evidence and limits

The native plans, bytes, progress rows and deliberate service differences are
documented in [the DALI service guide](../../docs/cgate-dali.md). The owned
native transcripts use a scripted `SYS_DAL2` gateway and are not a physical
gateway acceptance result. Focused API/CLI tests cover validation, capability
refusal, session cleanup, exclusive attempt journals, definite failures and
uncertain replies. The real-daemon interop module independently scripts
gateway replies and checks native wire order through the production Python
transport. These checks use synthetic projects and ephemeral loopback ports.

On 2026-09-30 installed-wheel acceptance included all 35 tests in
`test_dali_commissioning.py` and all 25 tests in
`test_cmqtt_dali_commissioning_interop.py`, with 308 unit subtests and no
skips. The combined DALI/sensor/display/fixture selection passed 150 tests and
861 subtests. The [acceptance receipt](dali-senll-merged-acceptance-summary.json)
retains the initial failures, their corrections and exact source/wheel hashes;
later metadata-only wheel acceptance is identified separately. It covers all
eight extraction modes and all three deployment modes, all 133 global proxy
leaves, null-scene creation and pre-I/O refusals. The extended-memory peer
independently checks page selection, tagged
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

A subsequent [scene-level admission correction](dali-scene-level-acceptance-summary.json)
adds preconnection regressions for both a direct scene level and a complete
scene object when membership is already enabled. Explicit level 255 is refused
because the original protocol uses it for removal; level 254 remains valid.
That correction has separate focused source and installed-wheel evidence and
does not relabel the preceding broad acceptance run.
