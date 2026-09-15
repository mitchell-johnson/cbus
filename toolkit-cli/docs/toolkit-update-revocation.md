# Offline signed revocation stages

`update-revocation-stages` evaluates a supplied SESU `rv1` signed revocation list and signer certificate. It checks the historical signer identity embedded in the Toolkit 1.18 bundle and reports each cryptographic stage separately. It does not establish current publisher trust, complete certificate-chain revocation status or update availability.

```sh
cbus-toolkit update-revocation-stages revocations.json \
  --signer-certificate signer.der --at-utc 2026-09-15T04:04:00Z

# Select the data object from a captured successful API response:
cbus-toolkit update-revocation-stages response.json --response \
  --signer-certificate signer.der --at-utc 2026-09-15T04:04:00.1234567Z
```

The direct file contains the complete RevocationList data object, with `id`, `signatures`, `revokedCertificates` and `revokedSignatures`. `--response` requires an object `data`, literal boolean `success: true` and integer `statusCode: 200`. These response guards are explicit CLI admission policy. Selected data is normalized JSON, with its own SHA256; the report also preserves the original file SHA256. It is not an original byte slice.

All input is supplied explicitly. No clock, HTTP request, registry read, certificate store, issuer-name lookup or installation discovery occurs. Cryptography is loaded lazily from the existing `research` extra (`pip install '.[research]'` from a checkout). Certificate DER is never modified; subject/issuer display strings are not accessed.

The stages are:

1. Original typed `rv1` canonicalization within the finite domain below.
2. Bounded compact JWT parsing for `pol=rv1`.
3. JWT `x5t` compared with the supplied certificate's raw SHA1 thumbprint.
4. Exact historical embedded revocation-signer identity: both thumbprint and native raw RSA public-key bytes.
5. RSA/SHA256 JWT signature for the supplied key.
6. JWT lifetime at the explicit UTC instant, including the original 300-second skew.
7. Canonical SHA256 compared with the JWT `payload_sha256` claim.

Each is `passed`, `failed`, `unsupported` or `not_run`. Exit0 means all seven requested stages passed; exit1 means a failed stage or invalid input; exit2 means unsupported or incomplete stages without a failure. These exit codes do not approve an update. A valid owned-key signature can pass stage5 while failing the historical embedded identity at stage4.

The output retains claimed certificate/token lists, order, duplicates and case. It does not emit `not_revoked`. The original traversal combines lists for multiple certificates before testing membership; that complete operation is outside this helper. It also associates responses with request thumbprints through its cache without independently comparing the returned `id`. This helper does not infer such a request association from a standalone file.

## Supported input domain

JSON and DER are bounded to 2MiB and64KiB respectively. Files must be nonempty regular files; symlinks, FIFOs and devices are rejected. JSON has bounded depth/member/value counts and rejects duplicate keys, nonfinite numbers, malformed UTF8, unpaired surrogates and oversized integer text before large integer conversion.

`id` is a40-digit hexadecimal string or omitted/null. The two lists are at most1,024 entries. Revoked certificate entries are40-digit hexadecimal strings; revoked signature entries are bounded three-component unpadded base64url token strings. Entries are retained without case normalization. Missing lists become `[]`; explicit null lists remain null in the canonical bytes. Null is not represented as a successfully interpreted empty list. Unknown model fields and the original model's broader coercions are unsupported. The excluded `signatures` property is still required to have a bounded string-map shape when nonnull.

The canonical context is explicitly `culture=invariant`, `timezone=UTC`. JWT support matches the earlier metadata helper's finite RS256/RSA2048..8192 profile, signed Int64 lifetime claims and UTC timestamps with up to seven fractional digits. Date-like arbitrary strings, culture-dependent sort equivalence, broad Newtonsoft coercions and additional algorithms are excluded.

## Evidence and limits

The fixed fixture [toolkit-update-revocation-vectors.json](../research/fixtures/toolkit-update-revocation-vectors.json) contains43 original typed-list cases, both actual signed documents and all original pin maps. The first local Mono probe ran47 method/stage cases:27 canonical cases (21 completed/six original errors),14 pin cases and six JWT cases. The expansion ran16 nonempty/default cases plus the same14 pin cases; those repeated pins are not new semantic coverage. The finite Python domain admits22 of the43 canonical cases, with exact original canonical bytes/digests, and reports the other21 unsupported.

Raw inputs, source, executable, full stdout/stderr and pre/post hashes are archived under `research/runtime/toolkit-update-revocation`. The unchanged original code ran with an enforced network-denial profile and a denied owned loopback witness. No VM, shared C-Gate or public-network call was used. Captured certificate bytes and public-key encodings were checked independently. No chain build ran in these new probes.

The original identity predicate is MultiPlatformUpdate RVA0x3CD0, and embedded maps come from WhiteListCert RVA0x5ED0. The maps contain two historical signer pairs. Captured DER and actual positive signatures exercise signer85CAABAC10E725ED52593159E9B3E6AB5FFD70E2; the second pair is original initializer evidence only. The helper does not turn the historical pin into current certificate validity, publisher trust or Windows chain-policy equivalence.

The existing `update-metadata-stages` command retains its six-stage result and meaning. Its complete reports for all seven captured candidates are regression-checked against the archived accepted implementation. Future chain/list composition requires a separate explicit contract.

## Accepted checks

The [acceptance fixture](../research/fixtures/toolkit-update-revocation-acceptance.json) records53 tests passing on each of Python3.13 and3.10, with no failures or skips. This comprises16 new API/CLI tests,25 existing metadata regressions, and12 About/incoming-route/JSON CLI regressions. All139 captured files were stable; the exact input archive is retained on the owned external volume. The seven complete legacy/current metadata report byte strings also match independently. Prior draft temporary-directory errors and the corrected diagnostic import failure remain recorded separately.
