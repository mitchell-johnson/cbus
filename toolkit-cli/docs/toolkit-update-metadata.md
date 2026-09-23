# Offline Toolkit metadata stages

`update-metadata-stages` evaluates six independent diagnostics against a supplied, **untrusted** DER certificate. It does not establish publisher trust, revocation status, machine applicability or update availability. It reads no platform clock, registry, certificate store or network endpoint.

Install the existing optional research dependencies to enable the cryptographic stages:

```sh
python -m pip install 'cbus-toolkit-cli[research]'
```

Evaluate a complete node JSON file at an explicit UTC instant:

```sh
cbus-toolkit update-metadata-stages node.json \
  --certificate publisher-certificate.der \
  --at-utc 2026-09-15T02:34:07.1234567Z
```

Select one node from a saved raw catalogue response:

```sh
cbus-toolkit update-metadata-stages catalogue-response.json \
  --node-id 2398558e-aa7e-4777-b4a8-f1e8f21704ea \
  --certificate publisher-certificate.der \
  --at-utc 2026-09-15T02:34:07Z \
  --culture invariant --timezone UTC
```

The selected node is normalized UTF-8 JSON, not an original byte slice. The result retains the source-file SHA-256, selected node ID and normalized node SHA-256. A node cannot be reconstructed from the existing `update-catalogue` display summary, because that summary deliberately omits signed fields. In Python, the complete raw response is available as `CatalogueOutcome.reply.body`.

The files must be regular files within the declared bounds. Empty files, directories, symlinks and FIFOs are rejected. On Unix, no-follow/nonblocking open flags and a descriptor check also reject ordinary file-to-pipe replacement races. The evaluator never follows any metadata download or certificate URL. Excluded URLs are not authenticated by this metadata signature.

## Result and exit codes

Each diagnostic reports `passed`, `failed`, `unsupported` or `not_run`:

| Stage | Meaning |
| --- | --- |
| `canonicalization` | Original-compatible typed model projection, UTF-8 canonical payload and SHA-256 within the declared finite domain. |
| `jwt_parsing` | Bounded, unique-key compact JWT with the supported v1 claim/header shape. |
| `certificate_identity` | Supplied exact DER thumbprint matches the header's original hexadecimal x5t representation. |
| `jwt_cryptographic_signature` | RS256 signature is valid for the public key in the supplied certificate. |
| `jwt_lifetime` | Signed integer timestamps meet the original required-expiration and300-second-skew rules at the explicit instant. |
| `payload_digest_claim` | Canonical digest equals the token's single string payload_sha256 claim. |

Certificate identity and signature validity are independent. A token can have a valid signature for the supplied key but a mismatched x5t. Lifetime and digest diagnostics contain `claims_signature_valid_for_supplied_key`; a matching digest or valid lifetime with a false/null qualifier is an unauthenticated claim diagnostic. Every report explicitly leaves publisher trust, revocation and applicability `not_evaluated`. There is no positive aggregate metadata-verification, latest-version or update-availability field.

Exit 0 means all six diagnostics passed. Exit 1 means at least one diagnostic failed, or ordinary input/operation handling failed. Exit 2 means no stage failed but a stage was unsupported or not run. These codes say nothing about publisher trust or whether software should be installed. KeyboardInterrupt follows the existing CLI 130 path and retains same-operation partial-stage evidence, including source selection. The Python evaluator preserves the original KeyboardInterrupt/SystemExit object and keeps a `last_report` fallback even when exception attributes cannot be attached. If evidence serialization or export itself fails, bounded fallback evidence retains the original error instead of replacing it with the reporting error.

## Supported canonical domain

The implementation follows the pinned original Node/PackageData serialization. It applies the five original exclusions: top-level URLs, signatures, file URLs, header version history and revision author. It preserves array order and the original modeled default/null distinctions. It supports the seven captured package shapes and ordinary declared-field values; matching captured bytes is not itself a trust decision.

The public NodeHeader/Revision models do not declare `versionHistory` or `author`. The original deserializer ignores these unknown members before canonicalization. Thirteen additional original cases confirm that objects, arrays, integers, booleans, nulls, strings and nested values at those two names leave the digest unchanged. Typed excluded fields such as file URLs and signature dictionaries still require their supported model shapes.

The finite profile supports:

- PackageData with omitted, `normal` or `critical` severity; strict booleans; signed Int32 visibility/file sizes and Int64 change IDs; no numeric coercion.
- Localized string dictionaries with the tested `default`/`en` keys; string-valued architecture/mediatype metadata and sha1 security entries. Unknown fields or dictionary keys are unsupported.
- Exact UTC typed dates with up to seven fractional digits, preserving100ns precision; original Guid normalization for revision IDs, while node IDs remain strings.
- Product→node/ProductVersionData and parent→collection/PackageData assignments, preserving order. Duplicate assignments are explicitly unsupported; duplicate files remain ordered List entries.
- The observed missing/null/default forms, empty conditions and textual expressions as signed data. Expressions are not executed or evaluated.

The original generator sorts with a current-culture string comparer. Its later `JObject.Parse` also converts some date-looking *text* according to local timezone. Therefore this API accepts only `culture=invariant` and `timezone=UTC`, and rejects unproved key-ordering and date-like text domains. It does not read the host locale or change its timezone. Unknown model types, coercions, arbitrary metadata numbers and unsupported date forms are reported as unsupported rather than silently canonicalized with Python defaults.

JSON is bounded to2MiB,32 levels,32,768 structural tokens/values and1,024 members per object. Decimal integer token length is checked before conversion; finite floating tokens have a bounded text length but remain outside typed integer/string canonical fields. Duplicate keys, non-finite values, invalid UTF-8 and unpaired surrogates are rejected before cryptographic work. DER is limited to65,536bytes. JWTs are limited to256,000characters with separate bounded JSON parsing.

## Signature and lifetime boundaries

The first cryptographic slice supports RS256 with an RSA key of 2048..8192 bits, exact `typ=JWT`, `pol=v1`, `crit=["pol"]`, and the original uppercase hexadecimal x5t. kid is not a resolver. Duplicate claims, timestamp strings/fractions/booleans, array digest claims and unknown header/claim shapes are outside the profile. Other algorithms, including an unknown DER public-key algorithm, are reported as unsupported. Lifetime and digest diagnostics can still run with an explicit unauthenticated-claims qualifier. No certificate subject/issuer string rendering is required, so the known original DER T61String name-parsing issue does not cause a rewrite of signed certificate bytes.

`--at-utc` is mandatory and uses `YYYY-MM-DDTHH:MM:SS[.fffffff]Z`. The Python API also accepts an explicitly UTC-aware datetime. There is no implicit current-time default. Internal comparison uses100ns ticks, not floating timestamps or truncation to seconds. The original five-minute skew uses strict greater-than/less-than boundaries; equality passes. Missing exp fails; missing nbf/iat and future iat follow the original behavior. Nonpositive Unix values clamp to the Unix epoch; excessive positive signed-Int64 values saturate to DateTime.MaxValue, including the captured exp253402300800. Certificate validity dates are part of future trust/path evaluation, not a hidden gate in this supplied-key diagnostic.

These are independent stage results. The original combined JWT routine can report expiry after a failed signature attempt through its `ValidateAfterSignatureFailed` path. The evaluator reports both diagnostics rather than pretending to reproduce that aggregate exception order.

## Python API and evidence

```python
from cbus_toolkit.toolkit_update_metadata import ToolkitUpdateMetadataStages

report = ToolkitUpdateMetadataStages().evaluate(
    raw_node_json,
    certificate_der=exact_untrusted_der,
    at_utc="2026-09-15T02:34:07.1234567Z",
    culture="invariant",
    timezone="UTC",
)
print(report.as_dict())
```

The fixed original evidence is in [toolkit-update-metadata-vectors.json](../research/fixtures/toolkit-update-metadata-vectors.json). It preserves108 original canonical input/context cases and48 original JWT/lifetime cases, with the unchanged DER and exact input/output provenance. The implementation compares52 supported canonical cases byte-for-byte;55 are explicitly unsupported and one non-finite JSON fixture is rejected. All seven actual signatures and canonical digests pass the supported diagnostics. Twenty-eight original lifetime cases overlap the strict claim domain and compare directly; deterministic owned-key tests cover100ns skew boundaries, tampering and unauthenticated-stage qualifiers. The owned key is test material and never a publisher identity.

The combined 56-test suite passed on Python 3.13 and 3.10 without skips. It includes 25 metadata tests, the existing update commands, routing CLI, JSON output and percentage CLI regressions. Exact source archives, the additional header-member probe and the preserved draft/review findings are recorded in [toolkit-update-metadata-acceptance.json](../research/fixtures/toolkit-update-metadata-acceptance.json). Full update authenticity, live revocation freshness, arbitrary Windows culture/timezone parity, file integrity, machine conditions, rollout cohort persistence and installation remain outside this feature.
