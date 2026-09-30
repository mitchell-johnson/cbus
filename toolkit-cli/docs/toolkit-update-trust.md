# Offline SESU publisher chain and revocation policy

`update-trust` evaluates a supplied SESU metadata-signing chain, its signed
`rv1` revocation lists and the revocation-signer certificates under an
explicit anchor profile and UTC instant. It follows the original Toolkit
1.18 / SESU 3.0.7 policy recovered below. It never fetches a certificate or
list, reads a certificate store or registry, or consults a clock.

```sh
cbus-toolkit update-trust \
  --leaf-certificate leaf.der --issuer-certificate root.der \
  --revocation-list leaf-revocations.json --revocation-list root-revocations.json \
  --revocation-signer revocation-signer.der \
  --node node.json --at-utc 2026-09-15T04:04:00Z
```

Without an anchor option the command uses the two root pins and two
revocation-signer pins embedded in the original `WhiteListCert` initializer.
Other anchors are supplied at runtime, never committed:

- `--anchors pins.json`: a `cbus-toolkit-update-trust-anchors-v1` document
  with `roots` and `revocation_signers` lists of
  `{"thumbprint_sha1": "40 uppercase hex", "public_key_sha256": "64 lowercase hex"}`;
- `--anchor-root-certificate DER` (repeatable) with
  `--anchor-revocation-signer DER` (repeatable): the pins are derived from those
  private files in memory. Only their digests appear in the report.

The public-key digest is SHA-256 of the RSA PKCS#1 public key, the byte value
of .NET `GetPublicKeyString`. The Python API is
`cbus_toolkit.toolkit_update_trust.evaluate_update_trust`, with
`anchor_pins_from_certificates` for pin derivation.

## Stages and result

| Stage | Meaning |
| --- | --- |
| `anchor_profile` | Embedded or supplied pins loaded; the report records the source SHA-256. |
| `certificate_inputs` | Readable RSA chain certificates; bounded, unique inputs. |
| `original_traversal` | The ordered revocation traversal below, ending at a pinned root. |
| `node_signature_revocation` | The `--node` `signatures.v1` token is absent from the accumulated revoked signatures. |
| `chain_policy` | Emulated `X509Chain.Build` with the original policy on the traversed path. |

`status` is `passed` (exit 0), `failed` (exit 1) or `unsupported` (exit 2).
`trusted_under_supplied_anchor_profile` is true only for `passed`. Without
`--node`, the node-revocation stage is `not_run` and
`node_signature_revocation_evaluated` is false. `current_publisher_trust_established`,
`revocation_lists_fetched`, `network_accessed`, `certificate_store_accessed`
and `windows_chain_engine_executed` are always false. A pass is a calculation
under the supplied lists and anchors at the supplied instant. It is not a
statement that the lists are current or that the embedded historical pins
are still Schneider Electric's publishing keys.

## Recovered original policy

Static review of the unchanged `SesuBrick.DAD.dll`
(SHA-256 `21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c`) and owned Mono execution give this policy. The
[sanitized receipt](../research/fixtures/toolkit-update-trust-original.json)
records the RVAs, constants and every observed outcome.

**Anchors.** `WhiteListCert` (RVA `0x5ED0`) holds two root and two
revocation-signer pins, each an uppercase SHA-1 thumbprint plus uppercase
public-key string. The pin predicate (RVA `0x3CD0`) needs both to match. It
checks no signature, date or store. The pins are not configurable. The
maximum traversal is 10 iterations. The node policy excludes five elements
(`$.files[*].url`, `$.signatures`, `$.urls`, `$.header.versionHistory`,
`$.header.revision.author`); `rv1` excludes only `$.signatures`.

**Traversal (RVA `0x39FC`).** For each certificate, starting at the leaf:
obtain its `rv1` list, require `signatures.rv1`, then validate that JWT (RS256
with the `x5t` certificate's key, lifetime with a 300-second skew, and the
`payload_sha256` digest). Next, require the `rv1` signer to match a
revocation-signer pin. Union `revokedSignatures` and `revokedCertificates`
into default ordinal `HashSet<string>` sets. Fail if any certificate traversed
so far is listed. Stop successfully at a pinned root. Fail on a self-signed,
unpinned certificate ("selfsigned without being a CA"). Otherwise resolve the
issuer by `IssuerName.Name`, and fail after 10 iterations.

**Final validator (RVA `0x37E0`).** After the node JWT and digest pass and the
traversal returns, the node token must not be in the accumulated revoked
signatures. The validator then calls `X509Chain.Build(leaf)` with
`RevocationMode.NoCheck`, `VerificationFlags.AllowUnknownCertificateAuthority`
and the traversed certificates in `ExtraStore`. Any exception is logged and
sets `IsMetadataValidated=false`.

**Revocation consumption.** The signed `rv1` lists are the only revocation
source; Windows CRL/OCSP checks are disabled. Revoked certificate entries match
uppercase thumbprints by exact ordinal comparison, so a lowercase entry does
not revoke. Revoked node tokens match by exact string. The original associates
a list with the requested thumbprint through its cache and does not compare
the list `id`.

**Expiry handling.** Only `X509Chain.Build` checks certificate validity
periods. `NotTimeValid` is not ignored, and the chain uses its default
`DateTime.Now`. JWT keys are `RsaSecurityKey` objects without certificate-date
checks. The revocation-signer certificate is never date-checked; only its pin
applies. `rv1` and `v1` token lifetimes use the 300-second skew. Cached lists
live until `min(ValidTo, UtcNow + 1 hour)`. Subject-resolved certificates are
cached for seven days, and thumbprint-resolved ones for the process lifetime.

**Toolkit application certificates.** The installed `cacert.pem`,
`publicclient.pem` and `client.p12` are referenced by `CBusToolkit.exe` and
`SharpCGateCommunicator.dll`, not by any SESU assembly. Their keys match no
SESU pin, so they are not update-signature anchors. The receipt records only
their SHA-256 digests and roles.

## CLI differences from the original

- Lists and certificates are supplied, not fetched. A missing list, issuer
  or revocation signer fails closed (`revocation_list_not_supplied`,
  `issuer_not_supplied`, `revocation_signer_certificate_not_supplied`).
- A list binds to a certificate only through its `id`. This is a CLI
  admission rule; the original's `revocation-list-id-mismatch` case accepted a
  wrong `id`. Supplied certificates or lists that the traversal did not use
  fail as `unbound_supplied_input`.
- Issuer and self-signed comparisons use raw DER names rather than the
  original's rendered `X500DistinguishedName.Name` strings. No name is
  rendered, so the captured T61String names are never re-encoded.
- `chain_policy` evaluates validity at the explicit instant (inclusive
  bounds), RSA PKCS#1 SHA-2 link and root signatures, and CA basic constraints
  on intermediates. The anchor may omit basic constraints. A critical
  extension other than basic constraints, a non-SHA-2 signature or an anchor
  marked `CA=false` is `unsupported`. The only tolerated status is
  `UntrustedRoot`. It is an emulation of the Mono-observed statuses, not
  Windows CryptoAPI.
- A `null` revoked list is `failed`, following the original `UnionWith(null)`
  exception. It is outside the captured-case evidence.

## Evidence

The committed probe [`NativeSesuTrustPolicyProbe.cs`](../research/NativeSesuTrustPolicyProbe.cs)
and runner [`probe_sesu_trust_policy.py`](../research/probe_sesu_trust_policy.py)
generate fresh synthetic RSA certificates for each run. They sign `v1` and `rv1`
tokens with the original `PayloadGenerator` digests, and add the synthetic
anchors only to the in-memory `WhiteListCert` maps of the probe process. The
unchanged original traversal and final validator then run under owned Mono
6.12. A macOS sandbox denies networking, and a denied owned loopback
connection witnesses it. Every certificate, subject and list lookup is
preseeded, so no cache-miss path runs. Keys and certificates stay in the
private run directory. The fixture keeps only case semantics and outcomes,
with thumbprints replaced by role names.

The 27 original cases cover:

- a valid chain;
- expired, not-yet-valid and wrong-key leaves, and an expired root;
- an unpinned root;
- leaf revocation from the root's and the leaf's own lists;
- a lowercase revoked entry, which does not revoke;
- root self-revocation and a revoked node token;
- an unpinned revocation signer, and an expired but pinned signer, which is
  accepted;
- an expired `rv1` token and one within the skew;
- a list with a mismatched `id` (accepted) and missing `rv1` on the leaf and
  root lists;
- an expired node token;
- intermediates without basic constraints (rejected by Mono's chain with
  `InvalidBasicConstraints`), with `CA=true` (valid) and expired;
- a CA-marked root;
- chains of 10 (accepted) and 11 (too long) certificates.

`tests/test_toolkit_update_trust.py` regenerates each case with new synthetic
certificates. It requires the Python stage to agree with every original
traversal decision, reason, revoked-token result and Mono chain status. The
only exception is the documented `id` admission rule. The expired node token
is rejected by the metadata stage's `jwt_lifetime`, not here. The captured
product chain passes under the embedded pins at its capture instant, like the
original full validator's earlier Mono result. It fails after its lists
expire and under other anchors.

Two initial probe attempts failed before producing outcomes: a C# compile
error, and a missing `System.Text.Encodings.Web` dependency when writing JWTs
through IdentityModel. Their run directories are retained next to the
accepted run. The accepted probe assembles compact JWTs directly and uses the
original library only to validate them.

Limits: no Windows CryptoAPI chain engine, Windows time zone or original
constructor ran. Server-side list freshness and the original subject-name
resolution were not exercised. Current Schneider Electric publisher identity
is not established.
