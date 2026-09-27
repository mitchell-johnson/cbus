# Native C-Gate HELP differential

On 27 September 2026 a read-only census sent `HELP <path>` for every one of
the 431 primary paths in the maintained Rust command matrix. Each request used
a fresh loopback connection and a deterministic command tag. `HELP *` was
captured separately. The run sent no login, project, database, network,
programming, application-control or commissioning command.

The existing UTM guest contained the exact staged Toolkit executable but no
running Toolkit GUI process. Its installed C-Gate service was **2.11.10 build
3342**, listening on guest loopback. This is an older comparison profile, not
the project's target server. A second HELP-only capture used the isolated
host oracle for the target **C-Gate 3.4.0 build 2001**, with all listed projects
stopped.

| Profile | Exact identity | HELP 101 | Syntax 400 |
| --- | --- | ---: | ---: |
| Existing Windows guest | `CBusToolkit.exe` 1.18.0.2754 SHA256 `9d01721a…0655ab`; C-Gate 2.11.10 build 3342 JAR SHA256 `a67d6f9c…adb98f` | 241 | 190 |
| Target host oracle | C-Gate 3.4.0 build 2001 JAR SHA256 `3ec48394…ced630` | 393 | 38 |

All 431 requests completed on both profiles. Of the status pairs, 240 were
101→101, 153 were 400→101, 37 were 400→400, and the `//` topic was the sole
101→400 result. Among the 240 shared 101 paths, 34 normalized responses were
byte-identical and 206 changed. A 400 response records only HELP visibility at
that connection's access level; it does not prove that the handler is absent.

The retained high-value commissioning findings are narrow:

- Build 2001 reports `NET UNRAVELUNIT <net-address> <unit-addresses>
  [MATCHDB]`. The older profile's description has the same subset behavior but
  its syntax line incorrectly says `NET UNRAVEL`.
- Build 2001 lists all four `NETWORK LOCATE` selectors: `UNIT`, `APP`, `GROUP`
  and `SERIAL`, with `ON`, `OFF` or 0–255 mode.
- Build 2001 describes `DALI ADDRESS_UNKNOWN` modes `AUTO`, `EXEC`, `POLL`,
  `STATUS` and `CANCEL`, scoped to a CDG and line A or B. It says the operation
  assigns unaddressed devices, returns a 64-bit assigned/discovered mask and
  does not resolve conflicts. The older service returns 400 for this help
  topic.
- `APPLICATIONS GET_CATALOG` has the same two-line help on both profiles.
- Both default HELP sessions return 400 for the PP method topics. This capture
  provides no PP access-level, request-byte, receipt or persistence evidence.

The complete exact commands and responses are retained in
[native-cgate-help-differential-acceptance.json](../research/fixtures/native-cgate-help-differential-acceptance.json).
Only the deterministic `[hcNNNN] ` response prefix was removed. The fixture
also pins the raw-capture hashes, installed artifacts, HELP-star responses,
the target syntax-error set and every status transition. The focused test
recomputes those facts from the 431 rows and fails if the maintained matrix
changes.

To repeat a direct HELP-only capture against an explicitly owned endpoint:

```sh
cd toolkit-cli
python3 research/native_cgate_help_census.py \
  --output research/runtime/native-help-target.json \
  direct --host 127.0.0.1 --port PORT \
  --profile 'owned loopback HELP-only oracle'
```

To repeat it in the configured owned UTM guest, use a new run identifier. The
guest backend refuses any identifier with an existing durable artifact and
never retries an uncertain run:

```sh
cd toolkit-cli
python3 research/native_cgate_help_census.py \
  --output research/runtime/native-help-windows.json \
  windows --run-id unique-lowercase-id
```

This capture adds **zero accepted strict-ledger slots**. The differential
rubric requires original Toolkit workflow executions and, where the workflow
saves, native save/close/load persistence. HELP output is useful executable
census evidence, but it is not a Toolkit workflow execution, original error
oracle, second device/firmware profile or physical-device result. No ledger
status was changed. The locked guest session and absent Toolkit process also
mean this run did not exercise the original GUI; unlocking it requires the
user's Windows credential, which was neither read nor recorded.
