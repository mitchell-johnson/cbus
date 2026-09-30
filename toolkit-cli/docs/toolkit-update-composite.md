# Same-source SESU update report

`update-composite-report` evaluates one supplied input set through every
offline SESU stage, in this order:

catalogue → metadata → revocation → conditions → applicability → trust →
download eligibility.

It refuses the whole report when any stage's source digest disagrees with
the catalogue selection. It never downloads, installs, reads the registry or
consults a clock.

```sh
cbus-toolkit update-composite-report \
  --catalogue-report catalogue-report.json --catalogue-response raw-response.json \
  --node-id 'selected node ID' --file-id 'selected file ID' \
  --platform windows_x86_64 --at-utc 2026-09-15T04:04:00Z \
  --leaf-certificate leaf.der --issuer-certificate root.der \
  --revocation-list leaf-revocations.json --revocation-list root-revocations.json \
  --revocation-signer revocation-signer.der
```

Anchor options match [`update-trust`](toolkit-update-trust.md): the embedded
original pins by default, `--anchors`, or pins derived at runtime from private
DER files. `--condition-context` supplies facts
([context v1/v2](toolkit-update-conditions.md)) for a node with nonempty
conditions. `--stored-cohort` supplies an already-stored 0–99 cohort for
visibility below 100. The Python API is
`cbus_toolkit.toolkit_update_composite.compose_update_report`.

## Stages

| Stage | Source and rule |
| --- | --- |
| `catalogue` | [`update-download` binding](toolkit-update-download.md): the report reproduces from the exact response, and the node, file and HTTPS URL are unique. A signed model outside the canonical domain is `unsupported`, and the remaining stages still run as diagnostics. |
| `metadata` | All six [metadata stages](toolkit-update-metadata.md) for that selected node against the supplied leaf. |
| `revocation` | The trust traversal and node-token revocation check, using the node's own `signatures.v1`. |
| `conditions` | The node's own `clientConditionData`. An empty map passes without evaluation, as in the original. A nonempty map uses the supplied facts. A missing expression (needs original synthesis) or missing context is `unsupported`. |
| `applicability` | [Applicability preflight](toolkit-update-applicability-preflight.md) on the same response, node, platform, instant and cohort. A nonempty condition result gates at the original position after the date, file, media and URI checks and before rollout. |
| `trust` | The `chain_policy` stage of that same trust evaluation. |
| `download_eligibility` | Passes only when every earlier stage passed. It records the bound host, output name and declared size; no request is made. |

These source bindings must all match, or `status` is `refused`:

- the catalogue report describes the response, and the selection matches;
- the metadata input node, and the metadata `x5t` naming the supplied leaf;
- the trust leaf is the metadata certificate;
- the trust node token is the selected node's token;
- the evaluated conditions are the node's own;
- the applicability response and node digests;
- the applicability-selected file is `--file-id`;
- `urls[file].url` equals the bound `files[].url`.

## Result

`status` is `eligible` (exit 0), `failed` or `refused` (exit 1), or
`unsupported` (exit 2). `download_eligible_under_supplied_evidence` is true
only for `eligible`. `network_request_initiated`, `downloaded`, `installed`,
`install_permitted`, `registry_accessed`, `certificate_store_accessed` and
`current_publisher_trust_established` stay false, and `updates_available`
stays null. The report does not say that the original Windows client would
offer the package now. Its instant, platform, cohort, condition facts,
revocation lists and anchors are caller-supplied. Use `update-download` for an
actual transfer.

The signed canonical form of nonempty `Condition` models is not recovered, so
such nodes remain `unsupported` in `catalogue` and `metadata`. The composite
can still show their supplied-fact condition and applicability outcome. The
original synthesized expression for a nonempty map without one is also
unrecovered.

## Tests

`tests/test_toolkit_update_composite.py` uses a captured catalogue node
re-signed by an in-test synthetic chain. It covers:

- an eligible same-source set;
- a leaf from another chain (refused);
- a catalogue report from another response;
- an expired leaf, a revoked leaf and a wrong anchor (failed);
- a file other than the applicability-selected one (refused);
- a selected URI that differs from the bound download URL (refused);
- true, false and missing supplied facts for nonempty conditions;
- the public CLI with runtime-derived pins, and default pins rejecting the
  synthetic signer.

These are offline tests. They add no original Windows workflow, publisher or
installer acceptance.
