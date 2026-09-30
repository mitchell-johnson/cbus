# Offline NCC post-check transcripts

`cbus_toolkit.firmware_ncc.evaluate_ncc_post_check(expected_version, exchanges)`
evaluates the serial branch of the original eDLT firmware updater against an
already supplied transcript. It is a callable Python helper. It never opens a
port, sends a command, sleeps, restarts a device or writes firmware. No CLI or
physical executor is introduced.

Each exchange is a dictionary with `command` (`id`, `nv`, `nu` or `rs`),
`response` (bytes, default empty), and `outcome` (default `response`). Reads also
admit explicit `timeout` or `io-error` outcomes. Restart accepts `write-ok`,
`timeout` or `io-error` and requires an empty response because the original
does not wait for an acknowledgement. These are caller-supplied outcomes, not
measured timings or observed I/O. A response exchange represents the complete
bytes delivered to the original handler before the command's completion check;
event scheduling, chunk boundaries and polling races are outside this model.

For example, begin a plan without any transcript bytes:

```python
from cbus_toolkit.firmware_ncc import evaluate_ncc_post_check

receipt = evaluate_ncc_post_check('1.7.0')
assert receipt['next_step']['command'] == 'id'
assert receipt['next_step']['request_hex'] == '69640d'
assert receipt['next_step']['execution_supported'] is False
```

Append each captured or synthetic exchange and evaluate again. A missing
exchange returns `awaiting-transcript` plus the next original command, delay and
timeout. Nothing executes that plan. Inputs are limited to six exchanges,
65,536 bytes per response, ASCII, 4,096 characters per line and 256 parser
fields; progress responses also have at most 256 distinct trimmed lines.
Unsupported byte profiles, wrong command order, extra exchanges after a terminal
branch and unknown input fields raise `ValueError`. No retries are synthesized.

## Recovered decisions

The original branch waits 10 seconds, identifies the eDLT, and requires exact
string equality between its firmware version and the package version. After a
500 ms delay it reads NCC versions. `System.Version` comparison, including
missing build/revision components and nonnegative Int32 limits, determines
whether the embedded version is newer. Both version constructors run before
the blank-value fallback, so unsupported/empty/invalid initial versions fail.

An update requires all three trimmed, case-sensitive CRLF lines:
`Updating NCC Firmware..`, `Update Started`, and `Update Complete`. The original
checks set membership, so line order and repeated lines do not matter. A colon
suffix does not match. Its timeout is 60 seconds; `id` and `nv` use 10 seconds.

After `nu`, a second `nv` response is logged without version validation or
comparison. `COMMAND NOT VALID` before a complete version pair returns both
native output strings empty even when one version field was present. The
restart predicate uses the **second** current-version output and tests the
exact text `0.0.0`. It does not match numeric equivalents such as `0.0` or
`0.0.0.0`. After a successful restart write the original waits 10 seconds and
identifies again. A failed identification is represented by the original's
`SuccessFlag=true` exception and manual-restart success message. A successful
identification is not compared with the expected version or earlier identity.
The original never reads NCC versions after restart.

The helper retains those outcomes in `native_outcome` and `native_success`.
Additional checks independently require an unambiguous usable Tiva/NCC
identity, unambiguous responses, the post-update current version matching the
initial embedded target, an unchanged embedded target, and matching identity
and firmware after restart when applicable. Partial trailing lines remain
verification gaps. A restart path always retains the missing final NCC read as
a gap. `transcript_checks_passed` refers only to these supplied-data predicates.

## Evidence and limits

Source: Toolkit 1.18 `FirmwareUpdater.exe`, assembly version 1.16.3.0,
SHA-256 `f54ea945167436b8a3e95decb1d146d01d60e4af1badcd34f4bad626df1e54d5`.
The private IL capture has SHA-256
`a76d6fef297d74dc2429dbee68252c46b46820c53ad8a2d5add8fe60eeafddfd`.
Both original and capture hashes were checked against the retained provenance
on 2026-09-30. The relevant recovered methods are `UpgradeFirmware`
`IL_04f1..IL_07e0`, `SendIdentifyNccCommand`, `SendUpdateNccCommand`,
`SendRestartCommand` and `NuCommandDataReceived`. The original binaries and IL
remain private and are not packaged.

Focused synthetic tests cover progressive planning, every original branch,
all six progress permutations, missing and malformed input, version quirks,
restart failures, duplicate/ambiguous replies, bounds and sanitized reporting.
The existing ID/NV diagnostic parser remains the shared parsing dependency.
This is static-source plus synthetic evidence. It does not extend the earlier
original-updater execution oracle beyond its first-ID timeout, prove original
event timing, or establish physical NCC flashing/recovery.

Receipts retain only response byte counts and SHA-256 digests, fixed step
metadata and comparison predicates. Raw responses, serial numbers, unit
addresses and arbitrary fields are never reported. `native_execution`,
`physical_acceptance`, `firmware_contents_verified` and
`destructive_execution_supported` remain false even when all transcript checks
pass. Package authenticity, main-firmware transfer, reboot persistence and
independent physical acceptance remain separate unresolved gates.
