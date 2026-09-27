# Linked update diagnostic provenance

`update-diagnostic-bundle` composes four already-generated diagnostic reports
for one catalogue node. It reads the exact bytes of each report and parses those
bytes internally. There is no separate parsed-object argument, so bytes recorded
in `input_sha256` are the same bytes whose fields were validated.

```sh
cbus-toolkit update-diagnostic-bundle \
  --catalogue catalogue-report.json \
  --metadata metadata-report.json \
  --revocation revocation-report.json \
  --conditions condition-report.json \
  --node-id 435e4274-3bcf-4f3e-a67a-3008278c539c
```

The input files are outputs from `update-catalogue`,
`update-metadata-stages`, `update-revocation-stages`, and
`update-condition-stages`. The metadata command must have selected its node from
the complete raw catalogue response with `--node-id`; its source-file digest is
then compared with `catalogue.http.body_sha256`. The displayed catalogue summary
does not contain enough signed node fields to recreate that raw response.

## Proven links

The v2 bundle reports three links independently:

- `catalogue_metadata` requires a complete catalogue HTTP body receipt, one
  unambiguous candidate ID, a metadata source receipt for that exact response,
  the selected-node input digest, and the same node ID in the metadata
  canonicalization result.
- `metadata_conditions` requires the condition and context exact-file receipts
  to agree with the evaluator's input digests. The condition evaluator's decoded
  model must equal `clientConditionData` in the selected metadata node.
- `metadata_revocation` requires a self-consistent revocation source receipt and
  equality between the revocation-list subject ID and the metadata certificate
  thumbprint. This equality associates the standalone list report with the
  supplied metadata certificate. It does not prove a complete or current
  revocation result.

`diagnostics_complete` is true only when all three links hold, all retained
metadata, revocation, and condition stages passed, and the condition calculation
produced a Boolean. A computed false condition remains a complete calculation;
it is not an applicability decision.

A missing receipt, an incomplete source, a source hash mismatch, unrelated
revocation subject, or different condition model remains visible under `links`
and keeps `diagnostics_complete` false. Duplicate JSON keys, duplicate candidate
IDs (including same-ID version variants), malformed stage sets, and forged trust
or availability claims are rejected. Reports are limited to 2 MiB each and use
the same bounded, finite-number, unique-key JSON decoder as the metadata tools.

## Claim boundary

This command performs no network, registry, certificate-store, download,
browser, or installer operation. A complete bundle means only that these
bounded diagnostic reports are internally linked. It does not establish:

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

The focused API and public CLI tests cover valid linked input, a false computed
condition, exact report hashes, substituted report bytes, duplicate keys,
same-ID/different-version candidates, catalogue-source mismatch, missing
metadata and condition receipts, unrelated revocation and condition reports,
failed stages, and forged trust/availability flags. These are portable offline
tests; they do not add native Windows, publisher-trust, network, or installer
evidence.
