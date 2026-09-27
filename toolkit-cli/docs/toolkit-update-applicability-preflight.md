# Offline SESU applicability preflight

`update-applicability-preflight` evaluates one bounded original SESU 3.0.7
date/file/media branch for a selected node in an **untrusted** raw catalogue.
It uses an explicit UTC instant and Windows platform supplied by the caller:

```sh
cbus-toolkit update-applicability-preflight \
  --catalogue-response raw-catalogue-response.json \
  --node-id 'selected node ID' \
  --platform windows_x86_64 \
  --at-utc 2026-09-15T02:04:45Z
```

The equivalent Python API is
`cbus_toolkit.toolkit_update_applicability.inspect_update_applicability`.
`passed` (exit 0) and `failed` (exit 1) describe only
`applicability_under_supplied_context`; `unsupported` (exit 2) means the
selected model or rule is outside this finite profile. Malformed or ambiguous
input also exits nonzero with an error. None of these outcomes authenticates a
catalogue, approves a download, or says an update is available.

The command accepts exactly one node ID from a successful status-200 raw
catalogue response and retains SHA-256 digests of the exact response bytes,
normalized selected node and canonical typed node. It does not emit download
URLs. It scans file descriptors in source order, using the original
case-sensitive `architecture.Contains(platform)` rule. The first matching
file whose ID is a key in `node.urls` wins, even if that URL is empty; a later
valid file is not a fallback. Within the admitted profile, the supplied UTC
instant must satisfy `startDate <= at_utc <= expireDate`; selected
`singleFileExecutable` media and a selected
nonempty HTTPS URI must pass. An empty selected URL or no selected file is a
negative result. The URI is admitted only with an ASCII DNS hostname (valid
labels), a valid dotted IPv4 address, or a bracketed IPv6 address; any explicit
port must be 1–65535 in at most five decimal digits. Userinfo, percent-encoded
authority, empty or malformed ports, fragments, controls and backslashes are
outside this profile. The returned status is `unsupported` for those URI
forms, even if a different URI parser might accept them. URL parsing does not
open the URL. The retained native cases use DNS authorities; the IPv4/IPv6 and
explicit-port syntax cases are local boundary tests, not original-method
differential acceptance.

The profile requires an empty original condition dictionary and exactly
`visibilityInPercent=100`. With no conditions, the original applicability
method ignores even a nonempty expression such as literal `false`. Any reached
nonempty conditions, lower visibility, other media type, ambiguous URI,
unproved date form or model coercion is `unsupported` here. The original
method uses two `DateTime.Now` samples and compares their wall-clock ticks to
the parsed dates. This preflight uses one explicit UTC comparison instant;
its equality boundaries are calculations under that supplied context. On a
Windows machine with a non-UTC local zone, the original result can differ
around a date boundary by the zone offset, as well as by the two sampling
times. It is not a live-machine applicability decision.
Only the caller-supplied x86 or x64 platform is considered; host architecture
is never inferred.

The original `SesuConnect.GetUpdates` path first applies a server-side
product/version assignment filter and its own separate
`IsMetadataValidated` gate. It then appends passing nodes in server order; it
does not perform a client-side latest-version comparison. This preflight does
not execute that coordinator, its signature/certificate-chain/current
revocation policy, registry cohort, installer, or any update-server request.
Its explicit `publisher_trust_evaluated=false`,
`package_applicability_evaluated=false`, `updates_available=null` and
`install_permitted=false` fields must remain false or unassessed even when
the supplied-context preflight passes. Reading a caller-supplied catalogue
path may use a network-mounted filesystem; no updater HTTP request is
initiated by this command.

## Source and comparison evidence

The retained original `SesuBrick.DAD.dll` has SHA-256
`21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c`.
Its file-selection method is RVA `0x3FC8`; applicability is RVA `0x4F74`;
the collection coordinator is RVA `0x57F4`. The
[sanitized 20-case fixture](../research/fixtures/toolkit-update-applicability-preflight-vectors.json)
pins matching original-method results on Mono and Windows 11, plus both
probe-output SHA-256 digests. The retained probe executable was built from
our own reflection harness. Its private Windows copy had only the CLR
`32BITREQUIRED` flag set so it could load the original x86 assembly; that
copy's SHA-256 is also pinned in the fixture. The disposable VM was Host Only
with zero IPv4 default routes, and the harness injected the captured response
into its only allowed HTTP handler. It made no updater HTTP request. After the
probe, the VM was stopped and its original Shared Network and MAC restored.
The seven captured, empty-condition, 100%-visibility nodes passed x64 and failed
x86; future start, expiry, missing selected URI and unsupported media failed;
null condition data threw; and an empty-map literal `false` expression passed.
The Python tests compare these outcomes using the same seven catalogue nodes
and a fixed UTC instant. The original probe used dynamic `Now +/- 365 days`
for its date variants and forced missing URI and Unknown media after file
selection; the Python tests compose raw inputs that reach those same gate
states. These variants are branch-equivalence comparisons, not byte-identical
input replay. The native method probe
did not run the full updater constructor, publisher chain, registry rollout
or Windows UI. Its reported zero network/registry/condition calls are harness
scope markers, not instrumentation of every host API. Vendor binaries, raw
traces and private files are not in Git.

The original metadata path also validates a v1 JWT against its resolved
certificate, signed revocation lists and historical root/revocation-signer
pin pairs before a separate `X509Chain.Build` call. The already available
metadata and revocation diagnostics test narrower pieces, and the
[exact-source package bundle](toolkit-update-package-bundle.md) links an
untrusted catalogue descriptor to local bytes. None currently reproduces
the complete original publisher and current Windows chain policy. A digest,
historical pin match, or passing preflight must not be promoted to publisher
trust. Issue [#62](https://github.com/mitchell-johnson/cbus/issues/62)
remains open for that composition, nonempty conditions, stateful rollout,
version policy and original Windows end-to-end acceptance.
