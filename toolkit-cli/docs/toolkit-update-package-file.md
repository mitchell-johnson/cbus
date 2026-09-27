# Offline SESU package-file receipt

`inspect_update_package_file` compares one **already-local** regular file with
the size and `security.sha1` descriptor in one selected raw SESU catalogue node.
It never follows a catalogue URL, contacts an update server, runs the package,
or grants permission to install. The CLI emits a JSON receipt and exits zero
for a byte-to-descriptor match, one for a mismatch or invalid input.

```sh
cbus-toolkit update-package-file \
  --catalogue-response catalogue-response.json \
  --node-id 'selected catalogue node ID' \
  --file-id 'selected file ID' \
  --package-path already-downloaded-package.exe
```

`--max-package-bytes` can lower the default 2,147,483,647-byte bound. A valid
mismatch emits a negative receipt to stdout; malformed or unsafe inputs emit a
JSON error to stderr. The same check is available through the Python API:

```python
import json
from pathlib import Path

from cbus_toolkit.toolkit_update_package_file import inspect_update_package_file

receipt = inspect_update_package_file(
    Path("catalogue-response.json").read_bytes(),
    node_id="selected catalogue node ID",
    file_id="selected file ID",
    package_path=Path("already-downloaded-package.exe"),
)
print(json.dumps(receipt.as_dict(), indent=2))
```

The caller selects both IDs explicitly. The source must be a bounded,
unique-key raw catalogue response with exact Boolean `success: true` and integer
`statusCode: 200`. The selected node must be unique and fit the existing finite
`PackageData` canonicalization profile. The selected file ID must be unique,
its signed-field `size` must fit a nonnegative Int32 and its `security.sha1`
must contain exactly 40 hexadecimal digits. Missing, ambiguous and unsupported
metadata fails closed. The original client's automatic platform/file choice is
**not** inferred from this explicit selection.

On POSIX, the file is opened through a no-follow, nonblocking, close-on-exec
descriptor and checked as a regular file. On supported Windows hosts (tested
on the disposable Windows 11 VM), a Win32 `CreateFileW` handle opens the final
path component without following a reparse point, denies concurrent
write/delete opens, and checks disk-file type, attributes, size, file ID and
timestamps around a read from that same handle. The Windows path fails closed
if the filesystem cannot provide those handle details. Parent-directory
junctions are outside this command's current containment contract; callers
must not infer a trusted source path from the receipt. The default maximum is
2,147,483,647 bytes; callers can lower it. A changed file, FIFO,
symlink/reparse point or oversized file is rejected. A complete read with a
wrong declared size or digest returns a negative receipt. The report retains
SHA-256 digests for the exact catalogue source, normalized selected node, canonical
node and observed package bytes, as well as the legacy SHA-1 comparison. It
does not expose the local path or catalogue URL.

**A match is only a byte-to-descriptor relationship.** Catalogue SHA-1 alone is
not sufficient for modern package authenticity, and neither the catalogue
source nor its publisher identity is authenticated by this helper. The output
keeps metadata signature, publisher trust, complete revocation, applicability,
installation permission, download and installation flags false. A source file
claimed to come from HTTPS is not independently attested by this API.

The [official Toolkit 1.18 release](https://www.se.com/nz/en/download/document/C-Bus_Toolkit_V1_18_0/)
identifies setup build 1.18.0.2754 with C-Gate 3.4.0.2001. The retained
original Toolkit / SESU method inventory shows file
selection at `MultiPlatformUpdate` RVA `0x3fc8`, file-security dictionary copy
at `0x41d8`, and `MustCheckSignatureAfterDownload(false)` in the constructor at
`0x35b8`. The captured seven-node catalogue has `security.sha1` and size in
each file descriptor. The metadata canonicalizer includes these fields while
excluding file URLs. The helper checks only that documented finite shape; it
does not mimic or approve the original download path. The exact private
binary/archive and committed fixture hashes, method hashes, and observations
are in [the sanitized evidence](../research/fixtures/toolkit-update-package-file-source-evidence.json).

An offline call to the original signed SESU 3.0.7
`DownloadChannel.IntegrityCheck` accepted a synthetic file with a correct SHA-1
and rejected a wrong SHA-1 when the security-dictionary key matched the
destination folder. It accepted a wrong SHA-1 when that key did not match the
folder. This bounded oracle shows why the CLI requires a unique, explicit
catalogue file ID and digest/size comparison. It does not establish parity with
the original signature-chain, revocation, download or installer gates. Windows
Python 3.13.14 lacks `O_NOFOLLOW`, `O_NONBLOCK` and `O_CLOEXEC`; its native
Win32 handle path is tested separately from POSIX.

Issue [#62](https://github.com/mitchell-johnson/cbus/issues/62) still needs
one verified source-to-package chain with current publisher/path trust and
revocation, host applicability, product/version policy, stateful rollout,
download/installer outcomes, and native Windows acceptance. This receipt
provides only the local file-byte relationship for an explicitly selected ID.
