# Source and obligation reconciliation

`coverage` can diagnose a declared source-to-obligation bundle while retaining
the existing global parity decision:

```sh
cbus-toolkit coverage --reconciliation-bundle bundle.json \
  --reconciliation-artifact-root ./artifacts --require-complete
```

The output's `reconciliation` is a separate bounded diagnostic.
`complete_for_declared_surface` means the supplied modeled surface resolved
its mappings and required variant gates. It does not complete the repository
census or change global `complete`, `progress.complete`, functional percentages
or the exit decision of `--require-complete`.

A bundle declares source records, obligation profiles and variants, bindings,
receipts and current artifact pins. Source anchors must match the exact current
supplied census or managed-annex bytes. Every member of each verified parent
inventory must be accounted for; omitting a newly discovered control prevents
declared completeness. The collector covers executable forms,
controls and event bindings, help records and explicitly supplied managed
annexes; it does not invent functional profiles from a control name. The
collector treats `OnColor` as a scalar property only on `TLEDStatusIndicator`
and `TFlashLEDStatusIndicator`. Other `OnColor` bindings remain events and
require exact handler evidence. Forwarded commands and test filenames are not
workflow evidence.

The diagnostic reports unmapped sources, unresolved profiles, duplicate or
stale bindings, unknown handlers, missing artifacts and unsatisfied variant
gates. `counts` separates source records and profiles, resolved mappings,
obligation variants, required/satisfied gates, receipt records and verified
artifacts. `counts.discovered_source_records` counts unique source identities
enumerated from verified parent inventories; `counts.omitted_source_records`
counts those absent from the supplied bundle. `inventory_membership` reports
each verified inventory and its exact `omitted_sources` identities and hashes.
These fields describe the supplied inventories, not undocumented Toolkit
completeness.

`input_sha256` hashes the parsed bundle's canonical JSON representation. The
file-based CLI also returns `bundle_artifact.sha256` and `bundle_artifact.bytes`,
which bind the actual raw bundle bytes, including formatting and key order.
Public results exclude artifact document bodies and private filesystem
coordinates.

Without `--reconciliation-artifact-root`, artifact bytes remain unverified.
With it, relative artifact identities must resolve inside the explicitly
selected root. Absolute paths, traversal and links outside that root refuse.
Ordinary modeled/static receipts need matching source, profile, case and
artifact evidence. JSON result strings cannot issue original or physical
acceptance. Those dimensions require independently verified gate capabilities
from the separate read-only manifest/receipt/trace/JUnit verifier.

The packaged Python core and public CLI also run from a fresh installed wheel.
Its tests include independently supplied synthetic bundle expectations and
exact current census collection. They validate the reconciliation mechanism;
they do not supply a complete deduplicated Toolkit denominator. Continue to
use [the global parity register](parity-register.md) for release decisions.
