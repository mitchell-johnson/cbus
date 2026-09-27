# Exact-source package and diagnostic join

`update-package-bundle` links one already-present package file path to the exact raw
catalogue response used by a diagnostic bundle. It re-runs both offline
producers from their inputs, then type-exactly compares the supplied diagnostic
bundle and package-file receipt with the reproduced results. A report cannot
establish the link merely by repeating another report's hash.

First produce `update-diagnostic-bundle` and `update-package-file` outputs from
the same raw catalogue response. Keep their four diagnostic reports, four JSON
source files and both exact signer certificate DER files. Then run:

```sh
cbus-toolkit update-package-bundle \
  --catalogue catalogue-report.json \
  --metadata metadata-report.json \
  --revocation revocation-report.json \
  --conditions condition-report.json \
  --diagnostic-bundle diagnostic-bundle.json \
  --package-receipt package-receipt.json \
  --catalogue-response raw-catalogue-response.json \
  --revocation-input raw-revocation-input.json \
  --conditions-input raw-condition-data.json \
  --context-input supplied-context.json \
  --metadata-certificate metadata-signer.der \
  --revocation-signer-certificate revocation-signer.der \
  --node-id 'selected node ID' \
  --file-id 'selected file ID' \
  --package-path already-downloaded-package.exe
```

The corresponding Python API is
`cbus_toolkit.toolkit_update_package_bundle.compose_update_package_bundle`.
`--max-package-bytes` lowers the default signed-Int32 read bound. The command
initiates no updater HTTP request, registry or certificate-store query,
download or installer action. It does read every caller-supplied file path;
on a network-mounted filesystem or UNC path that read may use network transport.
`updater_network_request_initiated=false` does not attest to filesystem
transport. The command does not print the package path or file URL.
The certificate files are optional when preserving an incomplete diagnostic
bundle; without both, `diagnostics_complete` and joined completion remain false.
Their digests and thumbprints are checked against the metadata and revocation
reports, without re-running signature stages or trusting the publisher.

`links.source_package.linked` checks the source-to-file byte relationship independently: the
package receipt must reproduce from the unique selected file descriptor and a
fresh safe-open read, and observed size and SHA-1 must match that untrusted
descriptor. `links.diagnostic_package.linked` additionally requires the
supplied diagnostic bundle to reproduce and its catalogue-to-metadata
provenance link to hold for the same raw source, selected node and canonical
node. An incomplete HTTP receipt or absent metadata selection receipt leaves
this diagnostic-to-package link false even if the source-to-file byte check is
true. The output pins exact catalogue, selected and canonical node SHA-256
digests and observed package SHA-256. Duplicate file IDs and unsafe files fail
closed. Substituted reports, same-ID other-version nodes, different catalogue
bytes and changed package file bytes leave the relevant link false.

Both links are independent of `diagnostics_complete`: a failed or unsupported
metadata stage can coexist with a valid source-to-file relationship, and a
noncanonical stage failure can leave diagnostic-to-package provenance linked.
`joined_diagnostics_complete` requires the diagnostic-to-package link and all
diagnostic stages. Exit code zero means joined diagnostic completion. Exit one
means `joined_diagnostics_complete=false`, including a failed or unsupported
diagnostic stage when either package link remains true; inspect both links in
the JSON receipt. Malformed input also exits nonzero with an error object.

This is an **exact-source and byte-to-descriptor receipt**, not authenticity.
The catalogue and its SHA-1 claim remain untrusted. Stage results are retained
from the diagnostic reports rather than replayed against an original publisher.
The command does not establish publisher identity, certificate-chain/current
revocation trust, host applicability, version ordering, rollout, permission to
install, or installation success. Those remain open under
[#62](https://github.com/mitchell-johnson/cbus/issues/62).

The focused portable API and public CLI tests cover a matching join, failed
and unsupported stage preservation, same-ID cross-version bundle and package
receipt substitution, raw-source substitution, changed package bytes, duplicate
file IDs, forged trust and JSON type changes, and duplicate-key rejection.
These tests do not replace original Windows or current publisher-chain evidence.
