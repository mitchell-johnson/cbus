# Supplied-cohort SESU applicability preflight

`update-applicability-cohort-preflight` evaluates one source-bound original
SESU 3.0.7 empty-condition applicability path for 0–99% visibility:

```sh
cbus-toolkit update-applicability-cohort-preflight \
  --catalogue-response raw-catalogue-response.json \
  --node-id 'selected node ID' \
  --platform windows_x86_64 \
  --at-utc 2026-09-15T02:04:45Z \
  --stored-cohort 41
```

The catalogue and cohort are **untrusted caller inputs**. The command reads
one unique `PackageData` node from a successful status-200 raw response and
retains SHA-256 digests of the exact response bytes, normalized selected node,
and typed canonical node. It accepts only an empty client-condition dictionary,
explicit integer `visibilityInPercent` from 0 to 99, and an already-stored
cohort supplied as one or two ASCII decimal digits from 0 to 99. It does not
read, generate, or persist a cohort in HKCU. The Python API is
`cbus_toolkit.toolkit_update_applicability.inspect_update_applicability` with
`stored_cohort=` set; omitting it preserves the separate 100% visibility
[preflight](toolkit-update-applicability-preflight.md).

Within this admitted profile, the command applies the original date,
source-order architecture/file, selected media and HTTPS URI rules described
in the [100% preflight](toolkit-update-applicability-preflight.md). Only when
all earlier gates pass does it compare
`visibilityInPercent > supplied_stored_cohort`. The output distinguishes a
reached rollout gate from an earlier failure with
`checks.rollout_gate_reached_under_supplied_context` and sets
`checks.rollout_gate_under_supplied_cohort` to null if the gate was not reached.
`passed` exits 0, `failed` exits 1, and an unsupported model/profile exits 2.
Malformed or ambiguous input is an error. The command emits no download URL.

The UTC instant and platform are explicit caller facts, not the original
updater's two local `DateTime.Now` samples or current host architecture. The
cohort is not attested to the current user. A passing result is only an
applicability calculation under supplied facts; it does **not** establish
publisher/source trust, current certificate-chain or revocation status,
machine applicability, version/assignment policy, update availability,
download safety, or permission to install. The report leaves
`full_machine_applicability_evaluated=false`, `registry_accessed=false`,
`cohort_persisted=false`, `updates_available=null`, and
`install_permitted=false` regardless of status.
Reading a caller-supplied catalogue path on a network-mounted filesystem may
cause filesystem traffic; `network_request_initiated=false` means the command
does not start an updater HTTP request.

## Original method evidence and boundary

The retained original `SesuBrick.DAD.dll` SHA-256 is
`21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c`.
The original applicability method is token `0x0600012B`, RVA `0x4F74`;
the called rollout helper is token `0x0600012C`, RVA `0x5190`. The method IL
tests dates, media and selected URI, then condition evaluation when its
dictionary is nonempty, and invokes the rollout helper only if those earlier
gates passed and visibility is below 100. The earlier
[17-case helper probe](toolkit-update-rollout-cohort.md) establishes the strict
cohort comparison; the earlier [20-case applicability probe](toolkit-update-applicability-preflight.md)
establishes source-order file selection and the 100% branch.

An owned [direct-method probe](../research/NativeSesuApplicabilityCohortProbe.cs)
set an uninitialized original method target's package, selected URI and media
fields, and redirected its registry names to a fresh owned HKCU Registry32 key
in a disposable Windows guest. UTM was Host Only before boot, and the wrapper
verified zero IPv4 and IPv6 default routes immediately before execution.
The [sanitized 15-case fixture](../research/fixtures/toolkit-update-applicability-cohort-original.json)
records ten stored-cohort outcomes and five missing-entry witnesses. The
baseline 42/41 case passed while 41/41 failed; 1/0 passed while 0/0 failed;
99/98 passed while 99/99 failed. Future start, expired, missing selected URI
and unknown media all failed. With a missing cohort entry, a passing earlier
path persisted a sampled 0–99 decimal string, while each of those four earlier
failures left the entry absent. That side effect and the original IL establish
the gate ordering; the CLI never executes that stateful branch.

The probe injected selected URI/media fields rather than calling the original
file selector, and varied dates relative to Windows local `Now`. Python tests
use raw catalogue changes and a fixed UTC instant that reach equivalent gate
states, not byte-identical original inputs. The probe did not construct the
updater, validate metadata signatures, contact HTTP, invoke the coordinator,
download, or install. The original publisher, current Windows chain/revocation,
nonempty conditions, actual HKCU cohort provenance, same-machine composition,
server assignment/version policy and end-to-end installation remain open in
[issue #62](https://github.com/mitchell-johnson/cbus/issues/62).

To reproduce the native matrix, compile the retained owned probe as an x86
.NET Framework executable and verify its source/executable hashes against the
fixture. Boot the disposable VM with UTM **Host Only** already selected; check
that both default-route families are absent and that the installed original
assembly matches the pinned SHA-256. Run the probe from the installed updater
directory so its dependencies resolve, capture stdout and stderr separately,
and compare the 15 rows and IL hashes with the fixture. The probe deletes its
fresh registry key in `finally`; remove the owned executable copy, stop the
disposable VM and restore its saved UTM network mode. The fixture is sanitized:
vendor binaries, raw guest output and private VM files are not in Git.
