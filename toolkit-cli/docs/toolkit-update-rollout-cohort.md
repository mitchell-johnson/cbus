# Supplied-cohort SESU rollout gate

`update-rollout-cohort` evaluates one narrow, source-bound part of the SESU
3.0.7 update decision:

```sh
cbus-toolkit update-rollout-cohort \
  --catalogue-response raw-catalogue-response.json \
  --node-id 'selected node ID' \
  --stored-cohort 41
```

The command reads one unique node in a successful status-200 **untrusted** raw
catalogue. It records SHA-256 digests of the exact response, normalized
selected node and typed canonical node. It requires `PackageData`, an empty
original client-condition dictionary, explicit integer
`visibilityInPercent` in 0–99 and a **caller-supplied** stored cohort in
0–99 expressed as one or two ASCII decimal digits. Within that profile it
returns `passed` exactly when `visibilityInPercent > stored_cohort`; equality
fails. Exit codes are 0 for this gate passing, 1 for this gate failing and 2
for an unsupported node/profile. Malformed or ambiguous input is an error.
The pure Python API is
`cbus_toolkit.toolkit_update_rollout.inspect_rollout_cohort`.

The number is not read from this host's registry. Neither a passing gate nor
matching source digests establish that this machine belongs to the cohort, that
the catalogue or publisher is trusted, or that an update is applicable or
available. The result always reports `registry_accessed=false`,
`cohort_generated=false`, `cohort_persisted=false`,
`full_machine_applicability_evaluated=false`, `updates_available=null` and
`install_permitted=false`.

## Original decision and finite evidence

The retained `SesuBrick.DAD.dll` SHA-256 is
`21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c`.
Its `MultiPlatformUpdate` applicability method is RVA `0x4F74`; when the
earlier gates pass and visibility is below 100, it calls the private rollout
helper at method token `0x0600012C`, RVA `0x5190`. The helper opens HKCU in the
32-bit registry view, then opens its visibility key writable. An absent key
returns false. For a present entry other than the `-1` sentinel, it calls
`ToString`, parses an Int32 and compares `visibility > parsed_value`; a parse
failure returns false. A missing entry or an entry containing the literal
string `-1` causes `Random.Next(100)`, persistence of the sampled decimal
string and comparison against that new cohort. This stateful branch is **not**
executed or simulated by this CLI. The direct helper also accepts `+41`,
surrounding spaces and a DWORD cohort, but these are outside the admitted
caller-supplied ASCII stored-string profile. Visibility 100 was observed only
by direct helper invocation; the earlier coordinator bypasses this helper at
100. Other condition dictionaries, registry errors and host
identity/provenance remain outside the CLI profile.

The owned [reflection probe](../research/NativeSesuRolloutProbe.cs) calls only
that pinned original helper on a disposable Windows guest. It redirects the
original static registry key/entry names to a fresh owned HKCU Registry32 key,
verifies the redirect before any helper call, and removes the key afterward.
Its [sanitized 17-case outcome fixture](../research/fixtures/toolkit-update-rollout-cohort-original.json)
records seven cases inside the CLI's comparator subset, original assembly and
helper IL hashes, zero default routes, and separately observed key-absent,
malformed, DWORD, sentinel and seed/persistence branches. The probe does not call the updater constructor, HTTP client,
metadata validator, package downloader or installer. It does not establish
current publisher trust or complete SESU rollout.

The earlier [applicability preflight](toolkit-update-applicability-preflight.md)
still admits only 100% visibility and does not consume this independent gate.
Combining two reports does not establish one trusted, same-machine updater
workflow. Issue [#62](https://github.com/mitchell-johnson/cbus/issues/62)
remains open for original current-user registry provenance, random persistence,
nonempty conditions, publisher chain/current revocation, complete source and
version policy, availability and installation acceptance.
