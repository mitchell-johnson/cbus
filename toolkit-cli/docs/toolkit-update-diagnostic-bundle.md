# Linked update diagnostic provenance

`update-diagnostic-bundle` composes four already-generated diagnostic reports
for one catalogue node. It reads and parses the exact bytes of each report. To
establish cross-report links, also supply the exact source documents used to
generate them. Report-only input remains useful as independent provenance, but
its links and `diagnostics_complete` stay false: matching hashes written in two
reports do not prove that either report describes the source bytes.

```sh
cbus-toolkit update-diagnostic-bundle \
  --catalogue catalogue-report.json \
  --metadata metadata-report.json \
  --revocation revocation-report.json \
  --conditions condition-report.json \
  --catalogue-response raw-catalogue-response.json \
  --revocation-input raw-revocation-input.json \
  --conditions-input raw-condition-data.json \
  --context-input supplied-context.json \
  --node-id 435e4274-3bcf-4f3e-a67a-3008278c539c
```

The input files are outputs from `update-catalogue`,
`update-metadata-stages`, `update-revocation-stages`, and
`update-condition-stages`. The metadata command must have selected its node from
the complete raw catalogue response with `--node-id`; its source-file digest is
then compared with `catalogue.http.body_sha256` and the supplied raw response.
`--revocation-input` is the same complete data file or raw API response selected
by `update-revocation-stages`; the bundle uses that report's selection mode.
`--conditions-input` and `--context-input` are the two exact files passed to
`update-condition-stages`. Each source file is read as a bounded regular file.

## Proven links

The v3 bundle reports three links independently:

- `catalogue_metadata` requires a complete catalogue HTTP body receipt, one
  unambiguous candidate ID, a metadata source receipt for that exact response,
  exact candidate summaries derived from its raw nodes, the selected-node input
  digest, and canonical metadata reconstructed from the selected raw node. Both
  canonicalization digest receipts (`sha256_hex` and `sha256_base64`) must match
  those canonical UTF-8 bytes; missing or contradictory receipts leave the link
  incomplete. The
  report's fixed catalogue endpoint and request digest must agree with the
  deterministic request for its declared installed version. This checks the
  report's internal request context; it does not attest to an actual network
  destination or request. The HTTP receipt must report an attempted request,
  consistent received and retained byte counts, no error, and successful cleanup
  before it can be linked. The response message must have the same bounded text
  shape accepted by the catalogue reader.
- `metadata_conditions` requires the condition and context exact-file receipts
  to agree with the evaluator's input digests and the supplied source bytes.
  The report's decoded condition and context models must match those sources;
  the condition model must equal `clientConditionData` in the selected metadata
  node. Decoded JSON comparisons preserve types: a reported `1` cannot stand
  in for source `true`, even though Python normally compares those values equal.
- `metadata_revocation` requires the exact revocation source file to match its
  receipt, the selected revocation data and its reconstructed canonical list,
  including both canonicalization digest receipts.
  The list subject ID must equal the metadata certificate thumbprint. This
  associates the standalone list report with the *reported* metadata
  certificate; the bundle does not re-read the certificate or prove complete or
  current revocation status.

`diagnostics_complete` is true only when all three links hold, all retained
metadata, revocation, and condition stages passed, and the condition calculation
produced a Boolean. A computed false condition remains a complete calculation;
it is not an applicability decision.

A missing source, missing receipt, incomplete response, source hash mismatch,
changed catalogue endpoint or installed version, same-ID cross-version node,
unrelated revocation subject, or different condition model remains visible under
`links` and keeps `diagnostics_complete` false.
Duplicate JSON keys, duplicate candidate IDs, malformed stage sets, and forged
trust or availability claims are rejected. Candidate summaries also require
type-exact decoded JSON agreement with the catalogue source, including Boolean
flags. Reports and catalogue/revocation sources are limited to 2 MiB each;
condition and context sources to 128 KiB each.
All JSON uses a bounded, finite-number, unique-key decoder. `input_sha256`
records report-file digests and `source_sha256` records source-file digests, with
null for omitted sources.

## Claim boundary

This command performs no network, registry, certificate-store, download,
browser, or installer operation. A complete bundle means only that these
bounded diagnostic reports are linked to their supplied source documents. Stage
assertions are retained from the input reports, not replayed by this composer.
It does not establish:

- publisher identity or certificate-chain trust;
- complete or current revocation status;
- rollout, machine, or package applicability;
- version ordering or update availability;
- download integrity, permission to install, or installation success.

The corresponding output fields remain false or null. Exit status 0 requires a
complete linked diagnostic bundle. A structurally valid but unlinked or failed
bundle exits 1 and is printed as evidence. Invalid input also exits nonzero with
an error object.

## Acceptance

The focused API and public CLI tests cover valid source-linked and report-only
input, a false computed condition, exact report and source hashes, substituted
report or source bytes, duplicate keys, same-ID/different-version nodes,
catalogue summary/canonical/request/endpoint mismatch, missing metadata and
condition receipts,
contradictory HTTP error/count/cleanup receipts, invalid response messages,
raw revocation response selection, Boolean/number substitutions in candidate
and context reports, unrelated revocation and condition reports,
missing or substituted canonicalization digests (including a same-ID other
version), failed stages, and forged trust/availability flags. These are portable offline
tests; they do not add native Windows, publisher-trust, network, or installer
evidence.
