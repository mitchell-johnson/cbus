# Read-only current-user SESU rollout cohort

On Windows, `update-rollout-current-user` reads the exact SESU 3.0.7 cohort
entry in the **current CLI process user's** HKCU Registry32 view:

```powershell
cbus-toolkit update-rollout-current-user `
  --source-assembly 'C:\Program Files (x86)\Schneider Electric\Software Update\SesuBrick.DAD.dll' `
  --expected-source-sha256 21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c `
  --expected-user-sid 'S-1-5-21-...'
```

Supply the complete SID of the intended account, obtainable with `whoami
/user` in that same account's session. The command checks the ordinary DLL's
exact size and SHA-256 and compares the current process token's user SID
before any registry access. A hash or SID mismatch is an error; it does not
fall back to another key, user or registry view. It opens only
`HKCU\Software\Schneider Electric\Software Update\Persistent`,
`VisibilityExpectedGreaterThan`, using query access and `KEY_WOW64_32KEY`.
It never creates a key, requests write access, changes a value, samples a
cohort, contacts an update service, downloads or installs anything.
An assembly path on a network-mounted filesystem may cause ordinary file
traffic; `network_request_initiated=false` means the CLI starts no updater
HTTP request.

An existing `REG_SZ` value with one or two ASCII decimal digits in 0–99, or
an existing low `REG_DWORD` in 0–99, reports `status=observed`, the typed
cohort and exit 0. A missing key or entry, the original literal `-1`
sentinel, an unsupported type/value, or a registry read error reports
`status=unsupported` and exit 2. The original helper would return false for
an absent key and sample/persist a new cohort for a missing entry or
sentinel. This command deliberately does **not** execute those stateful
branches. A source or user mismatch exits 1 with an error record. Unknown
registry values are not emitted into the report.

The result is one observation, not a claim that the original updater would
offer an update. It does not evaluate a catalogue, rollout comparison, current
publisher or revocation trust, complete machine applicability, version
policy, availability or installation permission. The separate
[`update-rollout-cohort`](toolkit-update-rollout-cohort.md) and
[`update-applicability-cohort-preflight`](toolkit-update-applicability-cohort-preflight.md)
commands still take a **caller-supplied** cohort; their existing outputs do
not become same-process or same-machine receipts just because this command
was run. A future composition must bind the exact source, account, timestamp
and selected node before claiming that relationship.

## Original source evidence

The pinned original `SesuBrick.DAD.dll` has SHA-256
`21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c`.
Its `MultiPlatformUpdate` type initializer (`0x060000E9`) calls string getters
`0x0600009F` and `0x060000A0`, storing their results in fields `0x0400004B`
and `0x0400004C`. Both getters use the shared decoder `0x0600000A` over the
same 9,105-byte FieldRVA blob. The two decoded slices yield the key and
entry above. The [source-bound derivation fixture](../research/fixtures/toolkit-update-rollout-original-registry-identity.json)
records assembly, initializer, getter, decoder, encrypted-blob and decoded
slice hashes. The [offline reproducer](../research/derive_sesu_registry_identity.py)
accepts only the pinned DLL bytes and reconstructs both strings without
loading or executing the assembly. The original rollout helper (`0x0600012C`) loads those fields
when it opens HKCU in `Registry32`.

The [owned reflection probe](../research/NativeSesuRegistryIdentityProbe.ps1)
independently loaded the unchanged installed DLL in an x86 Framework process
on the disposable Windows guest. It verified all five method IL hashes and
observed the same two static field values without calling the rollout
helper or reading/writing the registry. The private raw receipt SHA-256 is
retained in the sanitized fixture. That process ran as **LocalSystem**; it
proves the field identity, not the interactive Toolkit user's current HKCU
value. The earlier 17-case helper and 15-case applicability probes redirected
both fields to owned scratch keys before invocation, so their scratch names
are not evidence of the updater's original location.

The host suite tests source/SID guard order, pinned-file rejection, every
bounded read state, unsupported values, read failures and query-only
Registry32 access. The final installed wheel also ran under the interactive
Mitchell account in session 1 of the disposable Windows guest. The exact
source DLL and process SID checks passed. One HKCU Registry32 read found the
original key but no cohort entry, so the CLI returned `unsupported` with
`read_state=entry_absent` and exit 2. Independent reads immediately before and
after also found the entry absent; the command did not seed or write it.
The sanitized [evidence fixture](../research/fixtures/toolkit-update-rollout-original-registry-identity.json)
records the wheel and private receipt hashes and cleanup. This accepts the
read-only missing-entry branch, not an observed numeric cohort or an original
updater rollout decision. Native original updater behavior for an existing
interactive user's numeric value, RNG persistence, broader `REG_DWORD` and string parsing,
nonempty conditions and end-to-end update policy also remain open under
[issue #62](https://github.com/mitchell-johnson/cbus/issues/62).
