# Owned-registry SESU rollout branch

On Windows, `update-rollout-owned-registry` evaluates one selected, untrusted
catalogue node through a caller-named **CLI-owned scratch** HKCU Registry32
key:

```sh
cbus-toolkit update-rollout-owned-registry \
  --catalogue-response raw-catalogue-response.json \
  --node-id 'selected node ID' \
  --owned-namespace my-rollout-study \
  --ensure-owned-key
```

The namespace must be a lowercase ASCII letter/digit followed by at most 63
lowercase letters, digits or hyphens. The only reachable key is
`HKCU\Software\CBusToolkitCli\Tests\<namespace>\SESUVisibility` in the
32-bit registry view, with entry `Cohort`. By default the command does not
create a key: an absent key returns `failed` without sampling. The explicit
`--ensure-owned-key` option creates this scratch key before the read and
preserves any existing entry. It leaves the key and sampled cohort in place
for a subsequent call; this is a persistence study, not an automatic cleanup
probe. Remove only a namespace you own when finished.

The command checks the source, unique node, empty condition dictionary and
explicit 0–99 visibility profile **before** registry access. It retains exact
raw-catalogue, normalized selected-node and canonical-node SHA-256 receipts.
With an existing ASCII `REG_SZ` or nonnegative signed-range `REG_DWORD`
cohort, it parses the captured bounded Int32 subset and returns `passed`
exactly when visibility is strictly greater. High-bit DWORD values are
unsupported because the retained fixture does not establish whether their
.NET `ToString()` enters the `-1` sentinel branch.
An absent entry or literal `REG_SZ` `-1` samples a fresh 0–99 integer, writes
its canonical decimal `REG_SZ` form, and compares only after the write
returns successfully. A malformed stored integer or absent key returns
`failed`; an unsupported type, provider error, invalid sample or write error
returns `unsupported` with no asserted gate outcome. After a write error,
`cohort_persisted=null` and `write_outcome_uncertain=true`: the write might
have committed before the error, and the command does not retry it. Exit
codes are 0, 1 and 2 for these three outcomes. Input errors return nonzero
JSON errors. The Python API
`inspect_rollout_owned_registry` accepts an injected typed provider and sampler
for deterministic testing.

The receipt distinguishes the exact typed registry read, sampled integer,
write attempt and provider-acknowledged persistence outcome. It does not
claim an independent readback or durable flush, and injected Python providers
are not independently attested as Windows registry providers. It never emits
a package URL or grants installation. A passing scratch-key comparison does
**not** prove that the
current user belongs to the original updater's rollout cohort, that the
publisher or catalogue is trusted, or that any update is applicable or
available. All results keep `original_updater_registry_identity_verified=false`,
`full_machine_applicability_evaluated=false`, `updates_available=null`, and
`install_permitted=false`. The random sampler uses Python's `secrets.randbelow`
for an in-range sample; it does not reproduce .NET `System.Random` sequences.

## Original evidence and remaining boundary

The retained original `SesuBrick.DAD.dll` SHA-256 is
`21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c`.
The helper is method token `0x0600012C` / RVA `0x5190`, with pinned IL hash
`f6dd553c61e7af5a6d216422a6040102de46330e1bc7dad3dc7259f25bfead56`.
The [17-case original fixture](../research/fixtures/toolkit-update-rollout-cohort-original.json)
includes absent-key, present decimal/DWORD, malformed, missing-entry and
literal sentinel outcomes from a disposable offline Windows guest. Its
[probe](../research/NativeSesuRolloutProbe.cs) **overwrote both original static
registry key and entry fields** before each call. Neither that probe nor its
sanitized fixture established their original values. A later
[source-bound static and native reflection derivation](toolkit-update-rollout-current-user.md)
identified the original key and entry; this adapter still addresses only its
owned scratch key and does not source-bind them. Native execution of
this Python adapter passed six guarded branch checks in a disposable Windows
11 ARM64 guest under the UTM guest agent's **LocalSystem** HKCU. The run used
the official Python 3.13.14 ARM64 embeddable package after SHA-256 verification;
it checked absent key, missing entry with sampled write/readback, existing
string, literal sentinel with sampled write/readback, malformed string and
unsupported high-bit DWORD. The owned registry key and temporary runtime were
removed, and the guest's two default routes remained present. The exact
[native acceptance receipt and scripts](../research/experiments/2026-09-28/sesu-owned-registry/native-system-acceptance.json)
record the source hashes and limits. The interactive user's scratch-key branch
was **not** tested. A separate [read-only current-user command](toolkit-update-rollout-current-user.md)
accepted only the original key's absent-entry branch. A populated interactive
current-user cohort, original helper sample sequence and exception behavior,
concurrent registry modification, nonempty conditions, complete applicability
and update trust
remain open in [issue #62](https://github.com/mitchell-johnson/cbus/issues/62).

The supplied-number [rollout command](toolkit-update-rollout-cohort.md) remains
available as a pure offline comparison. The separate
[combined applicability preflight](toolkit-update-applicability-cohort-preflight.md)
still uses an explicit caller-supplied cohort; this owned-key command does not
claim to compose live date/file/media/URI gates into an updater workflow.
