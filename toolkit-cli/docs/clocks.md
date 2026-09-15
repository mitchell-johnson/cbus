# Clock outcomes

`NativeClocks` wraps the actual `NET CLOCKS network [1..10|R]` command and
distinguishes the action reply from a fresh observation. This concerns the
C-Bus network clock generators, not the separate CLOCK date/time application.

```python
from cbus_toolkit.clocks import NativeClocks

clocks = NativeClocks(client)
report = clocks.inspect("//PROJECT/254")
result = clocks.configure("//PROJECT/254", 2)
assert result.complete
assert result.observed_enabled == result.requested_enabled
```

The CLI uses the same outcome checks:

```sh
cbus-toolkit cgate network clocks //PROJECT/254
cbus-toolkit cgate network clocks //PROJECT/254 --target 2
cbus-toolkit cgate network clocks //PROJECT/254 --recover
```

Configure sends one action and one fresh `NET CLOCKS` inspection. `complete`
requires a native 200 action response, no reported failures, a complete fresh
inspection, and an observed enabled-clock count equal to the requested target.
An unreachable target is incomplete even if the native action has no failure
message. A per-unit failure remains incomplete even if the observed count
coincidentally matches. The CLI returns nonzero for incomplete outcomes.

C-Gate can report these failures before a final `200 OK.`:

```text
120-Failed to obtain output unit summary from address 4.
120-Clock at address 17 could NOT be enabled: Set clock failed: Failed to set parameter.
120-FAILED - Operation already in progress.
```

The parser records summary failures, enable/disable failures, operation
failures and error statuses separately, preserving their original messages
and response. No failed mutation is retried or compensated. After a complete
native error reply, one fresh inspection can still report the resulting state.
Transport, framing and action-parser failures stop further I/O. The outcome
retains the available `action_response` and `inspection_response`; missing
responses remain unknown rather than being reconstructed.

`recover` enables the gateway clock if it is disabled. It does not request one
enabled clock across the network, and `requested_enabled` is therefore `None`.
The native response contains the gateway's **old** summary; when changed, it
also includes a gateway-enabled message. Already-enabled recovery has no such
message. The helper identifies the gateway from that summary, cross-checks any
success message, and verifies that address has an enabled clock in the fresh
inspection. Other clocks may remain enabled. Native acceptance currently
covers a directly attached gateway, without bridged-network recovery evidence.

## Summary format and bounds

`parse_clock_report(CGateResponse)` handles the exact `bJ.a(dD)` format:

```text
120-address=16 output_units=1 clocks_enabled=1 clocks_active=1 burdens_enabled=0
120-address=4 output_units=0
200 OK.
```

Counters omitted for `output_units=0` remain `None`; their contribution to
totals is zero. Counts are numbers of replies at that address, not booleans.
The parser does not impose an invented relationship between active and enabled
clocks; each count must fit the observed output-unit count. A response without
any address rows cannot establish a complete inspection.

Duplicate addresses or fields, missing or extra fields, malformed numbers,
inconsistent final status and impossible counts are rejected. Address and
count fields are bounded to 0–255, replies to 2048 lines and 1 MiB, and each
line to 8192 UTF-8 bytes. Wildcard or comma-separated network selections are
rejected because the native rows contain unit addresses without network IDs.
`ClockParseError` preserves the response and any rows already parsed.

The implementation follows the unmodified C-Gate 3.4.0 build 2001 classes
`kD` (command grammar and range), `dz` (clock selection, recovery and per-unit
failures) and `bJ` (summary fields), plus the installed command help. The
24 deterministic tests include literal responses captured by native acceptance.
The independent native clock fixture also verifies target changes, an
unattainable target, disabled-gateway recovery, persisted clock/burden bytes,
and a deliberately rejected unit STORE that still produces final 200.

The result's `device_verified=false` distinguishes these native reports from
physical hardware verification. Simulator acceptance establishes transport and
configuration behavior; it does not model electrical loading, actual clock
arbitration or clock loss. See the value-free
[native clock acceptance fixture](../research/fixtures/native-clocks-acceptance.json).
