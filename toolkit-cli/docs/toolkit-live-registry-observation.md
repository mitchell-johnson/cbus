# Live registry condition observation

`ToolkitLiveUpdateConditions` evaluates registry conditions lazily through a
provider. The Python API is implemented and tested with deterministic providers
and retained original results. The production Windows worker still needs fresh
Windows acceptance; this is not a completed live Toolkit parity claim or a new
CLI command.

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

Validation on Python 3.13.14 and 3.10.20 passed **108 tests each**, with no failures,
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

Remaining work is to verify a fresh Windows runner and runtime, execute the
production Python observer against newly owned HKCU fixtures, and compare its
typed results with the original leaves and same-provider witnesses. Original
callback/cache ordering must also be checked with controlled value changes, and
owned-process/key cleanup independently verified. CLI exposure, broader registry
hives/value domains, culture-sensitive comparisons and complete update
applicability/selection remain outstanding. Existing supplied-fact behavior and
its limitations are documented in
[toolkit-update-registry-conditions.md](toolkit-update-registry-conditions.md).
