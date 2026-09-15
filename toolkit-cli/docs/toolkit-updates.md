# Toolkit download link and update catalogue

`cbus-toolkit update-link` prints the download-page link used by Toolkit's
original Help → Check for New Version action. It opens no browser. Without a
state file it uses the independently observed constructor preference value and
labels that source; it does not read current host settings. To use an explicit
complete preference-state export:

```sh
cbus-toolkit update-link --state preferences.json
```

The original menu handler calls `ShellExecuteW` with verb `open` and show value1,
then ignores the launch result. It performs no version comparison or update
query. The pure API `toolkit_download_link(values)` validates the existing forty
typed preferences and preserves `CISDownloadsURL` exactly within that schema.
Empty and whitespace-bearing strings remain unchanged. The existing schema
rejects NUL and invalid Unicode; original embedded-NUL pointer truncation is
recorded as an excluded case. A printed link does not establish that a page loaded.

Toolkit1.18 also bundles the separate Schneider Electric Software Update (SESU)
client. Its registration names product ID
`435e4274-3bcf-4f3e-a67a-3008278c539c`. The catalogue command uses the original
active-node/product-assignment request and requires an explicit installed version:

```sh
cbus-toolkit update-catalogue --installed-version 1.18.0 --timeout 15
```

The version string is forwarded unchanged; neither a Python package version nor
an inferred dotted-version ordering is substituted. The catalogue response
contains **unverified candidates**, not a verified list of available updates.
`complete=true` means only that the bounded HTTP exchange and catalogue parsing
completed. `metadata_signature_verified` and `applicability_verified` remain
false; `updates_available`, `latest_version`, and candidate `version` remain null.
Signature presence is reported separately from verification. Server order, names,
localized information URLs and file descriptors are retained. Returned URLs and
condition expressions are never executed. No browser, registry, download,
installation, C-Gate or physical device operation occurs.

The standard-library `HTTPSCatalogueTransport` makes one POST to the fixed
`https://sw.dad.se.com/collections/PackageData/list` endpoint. It verifies TLS
certificates and hostnames, uses no environment proxy, follows no redirect, and
does not retry. The default response cap is2MiB, candidate cap256; the API permits
explicit caps up to16MiB/4096 candidates. Version strings are nonempty valid
Unicode of at most256 characters without NUL. Each candidate is bounded to64
files,128 localization entries and16 signature entries. The timeout is positive,
finite and at most300 seconds per blocking socket operation. It is not a hard
total deadline across DNS, platform setup or cleanup.

HTTP completion, body status, parsing failures and cleanup outcomes are separate.
Retained partial bytes are bounded and hashed. Responses and connections each
receive one explicit close attempt. The first operational error remains primary
when cleanup also fails or interrupts; cleanup failures are preserved separately.
A first KeyboardInterrupt/SystemExit propagates as the same object, with partial
evidence also retained on `ToolkitUpdateCatalogue.last_outcome`. The CLI has an
identity-checked fallback when an interruption rejects evidence attributes.
Operational failures exit1; a first KeyboardInterrupt exits130. No failure or
empty result is presented as “up to date.”

The parser deliberately rejects several ambiguous cases that the original lower
client accepted: duplicate JSON keys, nonfinite numbers, missing/null data, and
HTTP200 with a failed body status. It additionally rejects oversized bodies,
ambiguous Content-Length/Transfer-Encoding combinations, encoded responses,
unsupported data types and duplicate node/file identifiers. These are documented
boundaries, not claims of exact behavior for arbitrary original-client input.

Original evidence includes36 unchanged EXE menu executions with intercepted OS
calls and20 original SESU collection-client cases using an injected HTTP handler.
The latter covers exact serialized version strings, the captured seven-node
response, body failure, redirects, malformed/duplicate JSON, unknown data types
and injected HTTP/cancellation errors. Three of those cases additionally pin the
original escaping of Unicode line separators, controls and emoji. The original menu probe can be rerun with
the exact Toolkit EXE via `CBUS_TOOLKIT_EXE`; catalogue differential cases are
pinned captured fixtures. The promoted C# source is `research/NativeToolkitCatalogueProbe.cs`.

One read-only vendor query captured on2026-09-15 at01:07:33UTC returned seven
candidates named1.18.1 through1.19.5 for input1.18.0. This is historical response
evidence, not a current latest-version claim. All seven payload digests also match
their unverified JWT claims under the original PayloadGenerator; that establishes
canonicalization consistency only. Signature-chain/revocation validation, Windows
platform selection, percentage visibility and local condition evaluation remain
outside this API. Full SESU Check for Updates parity is not claimed.

Evidence: [original vectors](../research/fixtures/toolkit-updates-vectors.json),
[acceptance](../research/fixtures/toolkit-updates-acceptance.json).
Primary vendor context: [Toolkit1.18 release](https://www.se.com/au/en/download/document/C-Bus_Toolkit_V1_18_0/)
and [SESU product registration](https://www.se.com/us/en/faqs/FA315432/).
