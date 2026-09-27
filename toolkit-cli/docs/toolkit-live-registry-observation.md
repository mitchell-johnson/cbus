# Live registry condition observation

`ToolkitLiveUpdateConditions` evaluates registry conditions lazily through a
provider. The Python API is implemented and tested with deterministic providers
and retained original results. The production Windows worker now has a bounded
seven-case execution under the VM guest agent's LocalSystem HKCU. Interactive
user-context acceptance is still outstanding, so this is not a completed live
Toolkit parity claim.

The wrapper is available through the Windows command line:

```text
cbus-toolkit update-condition-live conditions.json \
  --file-context file-facts.json \
  --registry-scope registry-scope.json
```

`registry-scope.json` must use `cbus-toolkit-registry-read-scope-v1` and list
one to eight unique HKCU queries, including each query's exact typed default.
The command hashes all three supplied files, uses the captured x86 Framework
compiler by default, and accepts `--compiler`, `--workspace-parent` and
`--timeout` for an explicit worker environment. Both computed Boolean results
exit 0; incomplete, failed or unsupported evaluation exits 1. An interruption
exits 130 and retains partial evaluation, observation and cleanup evidence.
Input files are read as bounded ordinary files before observer construction.

## Explicit HKCU user admission

Use `--expected-user-sid S-1-5-21-...` when the intended Windows user's exact SID
is known. The API equivalent is
`WindowsConditionRegistry(..., expected_user_sid="S-1-5-21-...")`.
The placeholder above is not valid input: supply the complete SID. The constructor
validates a canonical revision-one SID with bounded unsigned components without
Windows calls. The CLI rejects an invalid SID before opening its input files.

After verifying the launched worker's PID, nonce, runtime, provider and executable,
the host independently queries the worker's primary process token through the
original CPython Windows `Popen` handle. It checks the handle's PID and liveness
before and after `OpenProcessToken(TOKEN_QUERY)` / `GetTokenInformation(TokenUser)`.
It never reopens a process by PID. The fixed-size result buffer must contain the
complete SID before any pointer is dereferenced, and the token handle is closed
on success and failure. The borrowed process handle remains owned by `Popen`.
These are standard [Windows token-query APIs](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocesstoken).

The OS token SID, worker-ready SID and requested SID must agree before the first
registry request is published. Access denial, missing handle support, exited
worker, malformed results, mismatch and token-close failure reject the session.
There is no fallback to self-reported identity, retry, alternate hive,
impersonation or automatic user switch. Owned-worker cleanup retains the first
failure. No token handle, privileges or credentials are exported.

The observer evidence's `user_context` separates `observed_user_sid` (worker
ready record) from `process_token_user_sid` (OS query) and
`process_token_user_verified`. `sid_requirement_satisfied` is null when no
requirement was supplied or no valid ready SID was observed; otherwise it is
true only when both sources match the requirement. The verification is an
admission-time primary-token observation, not continuing token monitoring.
Threads can impersonate independently: `interactive_user_context_verified`
and host-attestation claims remain false. This does not prove a desktop login,
thread-token identity, elevation, the identity of the person selecting the SID,
or original Toolkit lazy-wrapper compatibility. With the option omitted, no
OS token query is added and existing process-user behavior remains. The C# worker
and ready-frame format are unchanged.

Portable tests cover malformed SID inputs, mocked Win32 pointer/length bounds,
PID/liveness disagreement, denied APIs, cleanup errors, and a forged ready SID
that disagrees with the OS token. These tests are separate from native Windows
acceptance. Interactive-user/native-wrapper, culture and repeated-read acceptance
remain open.

A [sanitized native smoke receipt](../research/experiments/2026-09-28/registry-primary-token-native-smoke.json)
binds the tested source hashes and private outputs. On Windows 11 ARM64 with
Python 3.13.14 AMD64 and the pinned x86 Framework worker, matching LocalSystem
SID completed successfully, a wrong required SID failed before any query, and
an already-terminated owned process handle was rejected. The synthetic HKCU
fixture was unchanged and removed; no owned processes remained. The disposable
VM was stopped and its original networking restored. This is primary-token
acceptance under LocalSystem, not interactive-user acceptance.

The wrapper uses the existing condition parser and successful condition-name
cache. In `A AND A AND B`, where A and B refer to the same registry value, A is
read once, the second A uses its cached result, and B reads again. B therefore
observes a value changed between the two reads. Short-circuited definitions
perform no reads. Supplied file facts remain unverified caller input.

`WindowsConditionRegistry` is an inert, single-use observer until its first
query. It compiles the authored C# worker into a new directory and verifies the
captured x86 Framework compiler/runtime, loaded provider method, child PID,
session nonce and executable hash. The worker calls the exact Framework
`Microsoft.Win32.Registry.GetValue(string, string, object)` provider directly.
Request/response correlation retains typed null, string and signed Int32 values.
Explicit scope validation happens before reads; observations are never retried.
The worker performs no application registry writes. Its evidence is operational
process provenance, not host attestation or an atomic machine snapshot.

The current scope admits up to eight exact HKCU query identities and eight
ordered observations, using the original typed defaults. The wrapper rejects an
already used Windows observer before issuing another query. Complete captures
can export the existing v2 supplied-facts format only when query identities are
unique. Exported facts remain unverified; repeated observations cannot be
collapsed into a snapshot.

The review after the repository changes preserved the user's atomic
no-overwrite publication and clean-result reporting fixes. It also fixed three
failure cases: rejected wrapper reuse no longer deletes its retained report;
already used Windows sessions are rejected before an extra read; and termination
errors still lead to a bounded wait/reap attempt on the exact owned process,
without replacing the first error.

The historical validation on Python 3.13.14 and 3.10.20 passed **108 tests each**, with no failures,
errors or skips. This includes the existing 78 conditions/registry/metadata/
revocation tests and 30 live-wrapper/host-transport tests. The latter cover lazy
ordering, changing repeated queries, short-circuiting, original null/RHS order,
all twelve retained registry vectors (including the unsupported collation case),
typed frame correlation, scope preflight, atomic publication races, forged
receipts, timeouts, and first-error preservation during cleanup/export. Direct
leaf vector errors use the wrapper's condition alias when comparing messages.
These runs executed no Windows worker or original Toolkit methods. Their 155
archived source/test/fixture files were unchanged before/after, and imported
package paths resolved to this worktree. The [host test report](../research/experiments/2026-09-24/registry-host-review.json) records these results; the full archive remains under
`/Volumes/external/cbus-toolkit-registry-live-review-20260924/`.

The current Python 3.13 focused suite adds five CLI boundary tests and passes
**113 tests** in total. The CLI tests cover true and false results, exact source
hashes, scope and regular-file admission before observer construction, invalid
timeouts, retained interruption evidence, report-export failure recovery and
single-close ownership. They substitute a deterministic observer and perform no
Windows, registry or network operation. The [CLI review report](../research/experiments/2026-09-24/registry-cli-review.json)
records the current source hashes and result.

The later [Windows system-context acceptance](../research/experiments/2026-09-24/registry-windows-system-acceptance.json)
executed the current production adapter and its compiled x86 Framework worker on
Windows 11 with Python 3.13.14. Seven observations distinguished an existing key
with the original Int32 default, a missing key, a missing string entry, a literal
sentinel string, an empty string, mixed-case ASCII and DWORD `0x80000000` as
signed Int32 minimum. The captured compiler/runtime hashes, method token, method
IL, helper hash, request/response correlation and typed values all passed.
Production cleanup reaped the compiler and worker; an independent read-only
query found the newly owned registry root absent and no owned worker or driver
processes. The single execution was not retried after an initial output-file
sharing violation. It made no network, C-Gate or CNI call.

Remaining work is to repeat production acceptance in the interactive Toolkit
user context and compare the typed results with the original leaves and
same-provider witnesses. Original callback/cache ordering must also be checked
with controlled value changes, along with short-circuiting, unsupported binary
values and bounded interruption. Broader registry hives/value domains,
culture-sensitive comparisons and complete update applicability and
selection remain outstanding. Existing supplied-fact behavior and its limitations are documented in
[toolkit-update-registry-conditions.md](toolkit-update-registry-conditions.md).
