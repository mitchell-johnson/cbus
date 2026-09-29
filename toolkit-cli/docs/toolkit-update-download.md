# Verified catalogue-bound package download

`update-download` downloads one SESU package file named by an exact catalogue
response. It never opens, executes or installs the file.

```sh
cbus-toolkit update-catalogue --installed-version 1.18.0 > catalogue-report.json
# Keep the exact raw response body described by that report, then:
cbus-toolkit update-download \
  --catalogue-report catalogue-report.json \
  --catalogue-response raw-catalogue-response.json \
  --package 'selected catalogue node ID' \
  --file-id 'selected file ID' \
  --output downloads/
```

The Python API is
`cbus_toolkit.toolkit_update_download.download_update_package`.

## URL binding

Before any network access, the command reproduces the report from the raw
response using the same catalogue checks as
[`update-diagnostic-bundle`](toolkit-update-diagnostic-bundle.md):

- a complete, error-free report whose HTTP receipt, body digest, endpoint,
  request digest and body status match the exact response bytes;
- type-exact candidate summaries derived from the raw response nodes;
- no trust, applicability, availability, download or install claims.

The package node and file IDs must each be unique. Size and `security.sha1` come
from the same selection used by [`update-package-file`](toolkit-update-package-file.md).
The URL must be the selected file's absolute `https` URL without credentials or
a fragment. The output name is the URL's final path segment. It must be a plain
name without separators, `..`, trailing dots/spaces or reserved Windows device
names. Unbound, ambiguous or unsafe input fails with an error object and no
network request.

This binding prevents substitution of a URL that is absent from the reported
response. It does not authenticate that response: a caller who fabricates both
the report and the response can name any HTTPS URL. The catalogue's size and
SHA-1 remain unauthenticated claims. SHA-1 is not a modern authenticity
primitive.

## Transfer policy

- TLS 1.2 or later with certificate and hostname verification. Trust is the
  platform default store, or only the exact certificates in `--ca-file`. The
  report records the CA file SHA-256, TLS version, cipher and peer-certificate
  SHA-256. Verification cannot be disabled.
- One `GET` with `Accept-Encoding: identity`. No proxy, cookies, credentials,
  retries or resume.
- Same-origin HTTPS redirects are followed, at most five. A redirect to another
  host, port or scheme is refused.
- Status 200 is required. Encoded or ambiguously framed responses are refused.
  Any `Content-Length` must equal the catalogue size.
- The catalogue size is a hard bound, capped by `--max-package-bytes` (default
  2,147,483,647). Truncated or oversize bodies fail.
- `--timeout` applies to each blocking socket operation. It is not a total
  deadline.

Bytes stream into a new exclusive hidden file in `--output`
(`.NAME.TOKEN.download`, mode 0600). SHA-1, SHA-256 and size are computed while
streaming. After the socket closes, the file is flushed, and a fresh
`update-package-file` read must reproduce the size, SHA-1 and SHA-256. Only then
is it published under `NAME` by a no-overwrite link (POSIX) or rename (Windows).
An `NAME` that already exists is refused before network access. One that
appears during the transfer is left untouched, and the download fails.

## Failure artifacts

Every failure after binding returns exit status 1. The report is printed and
also written exclusively as `NAME.TOKEN.failed.json`. Any received bytes are
kept as `NAME.TOKEN.failed.partial`, never under the final name. The record
states the failing stage and type (for example `tls`, `redirect`,
`http_status`, `response_headers`, `response_body` or `verify`), the received
byte count and the partial digests. An interruption keeps the same artifacts
before it propagates. The command does not resume or delete these files.

## Report

`format` is `cbus-toolkit-update-download-v1`. `provenance` records the report
and response SHA-256, endpoint, installed version, request digest, selected
and canonical node digests, IDs and the URL. `http.requests` lists each
request's host, port, target, status and redirect location. Success adds the
full package-file receipt and `output_file_name`. `executed`, `installed`,
`install_permitted`, `publisher_trust_evaluated`,
`metadata_signature_verified`, `package_applicability_evaluated` and
`catalogue_claims_trusted` remain false.

## Original behavior

The [static review](../research/fixtures/toolkit-update-download-source-review.json)
of the original SESU 3.0.7 `DownloadBrick.DownloadChannel` records where this
command differs from the original. The original uses .NET default TLS
validation after enabling TLS 1.2, and it never disables automatic redirects.
Its file name can come from `Content-Disposition`. It resumes a `.partial` file
with a range request and treats a zero-byte read as the end without comparing
the byte count to `Content-Length`. It moves the result over the destination
before its integrity check. That check applies only when the directory name
equals a security-dictionary key, and a failed file is deleted. An existing file
with matching server size and time is accepted without that check.
[`research/decode_sesu_download_brick.py`](../research/decode_sesu_download_brick.py)
reproduces the pinned string table from a local copy of the DLL. Runtime .NET
redirect, proxy and premature-close behavior is unresolved.

## Acceptance

Focused tests use an owned TLS server with an ephemeral CA generated in the
test (`tests/test_toolkit_update_download.py`,
`tests/test_cli_toolkit_update_download.py`). They cover:

- success and a same-origin redirect;
- wrong hash, oversize body and `Content-Length`, and the hard cap;
- a truncated connection, HTTP error status and redirect loop;
- a refused cross-origin redirect;
- an untrusted CA, hostname mismatch and system trust without the owned CA;
- an existing output, and an output that appears during the transfer;
- an unbound report or response, a non-HTTPS URL and unsafe file names.

These are offline loopback tests. They do not add vendor-server,
original-client or Windows installer evidence.
