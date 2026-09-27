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
registry key and entry fields** before each call. Neither its sanitized
fixture nor the accessible local source records their original values. This
adapter therefore addresses only its owned scratch key. Native execution of
this new Python adapter on Windows, exact current-user updater key identity,
the original sample sequence and exception behavior, concurrent registry
modification, nonempty conditions, complete applicability and update trust
remain open in [issue #62](https://github.com/mitchell-johnson/cbus/issues/62).

The supplied-number [rollout command](toolkit-update-rollout-cohort.md) remains
available as a pure offline comparison. The separate
[combined applicability preflight](toolkit-update-applicability-cohort-preflight.md)
still uses an explicit caller-supplied cohort; this owned-key command does not
claim to compose live date/file/media/URI gates into an updater workflow.
