# Firmware package snapshot and execution admission

Firmware package inspection, selection and image loading use `PackageSnapshot`
in `firmware_diagnostics.py`: a filename, immutable captured bytes and their
SHA-256. Archive metadata and decrypted images therefore refer to the same
captured package. Reusing a snapshot performs no further path reads.

Capture opens one regular file, bounds the archive to 512 MiB and reads at most
the bound plus one byte. It compares descriptor metadata before and after the
read: device, inode, mode, size, modification time and change time, together
with the actual byte count. Nonregular files, oversize inputs and observable
changes during capture are refused. Available platform flags also prevent
following a final symlink and avoid blocking on nonregular inputs.

An expected digest must be lowercase SHA-256. Its comparison happens before
archive parsing or construction of the decryption reader. A replacement package
with the same filename and size is still rejected when its bytes differ from
the expected digest. Once admitted, a later replacement of the mutable filename
does not alter the snapshot consumed by later readers. This is a byte-identity
contract; it does not make filesystem mutation atomic or authenticate a vendor.

## ZIP and selected image bounds

Archive readers refuse more than 1,024 directory entries and duplicate entry
names. Requested entries must exist and be files. Each selected image is bounded
to 64 MiB, and selected plaintext together is bounded to 64 MiB. Directory sizes
are checked before reading; each read is bounded and its actual length must match
the directory record. Plaintext stays in memory.

The ZIP reader verifies entry CRC where applicable; the optional `pyzipper`
reader supplies AES support and verifies its integrity check. Password, CRC,
AES HMAC, truncation and unsupported-format failures stop image admission.
Every selected compression method is now admitted before the first entry
opens: Stored and Deflate are supported, including AES's normalized inner
method; BZIP2, LZMA and unknown codecs are refused before decoder construction.
Tiny forged-header/interception tests cover the boundary without executing
a resource-exhaustion payload. This follow-up has separate focused acceptance
from the earlier snapshot identity receipt; neither is a blanket allocation
or vendor authenticity guarantee.
The shared updater password and archive checks establish integrity only: the
archive has no vendor signature, and neither an admitted digest nor a successful
decryption proves authenticity, bootability or suitability for a physical unit.

`load_selected_images` first binds the snapshot to the reviewed package digest,
then reproduces package identity, variant, selected entries, addresses, font
options, erase metadata, native step arguments and post-check selection. It
refuses a differing plan before decrypting selected entries. Attached image
inspection is also checked against the loaded bytes.

## Resume before package parsing

The public `firmware update-resume` command validates the real update journal
and takes its bound package SHA-256 before constructing the first package
parser. It captures and admits that package once, rebuilds the plan using the
journal's variant and font option, and supplies the same snapshot to selected
image loading. A missing or invalid digest or a different package stops before
package parsing, decryption and creation of the USB opener.

The focused root regression selection uses an actual interrupted update journal.
Its negative case supplies a same-size changed package and checks refusal before
parser, decryption and USB admission, while preserving journal bytes. Its positive
case admits the matching snapshot, replaces the filename later and checks that
subsequent readers still receive the admitted bytes and journal selection. These
are synthetic regression cases; the integration receipt records their final
execution results separately.

## Integrated validation

The [source and installed-wheel receipt](firmware-package-snapshot-acceptance.json)
records **167 tests and 234 subtests** passing in each environment, with zero
failures or skips. The identical scope includes package admission, payload/NCC
models, fake-PyUSB release/fault behavior, the owned pseudo-terminal diagnostics
and four DALI preconnection guards for the shared CLI. One original assembly
execution node was excluded by a checked collection gate before either run.
There was no original runtime/JIT, native C-Gate or physical hardware execution.
Repeated source/wheel cases are not additional unique feature coverage.

The [root validation](firmware-package-snapshot-root-validation.json) independently
matches all **277 package files** and 26 harness inputs to the tested wheel.
Its final seven-method/nine-subtest resume regression file also reproduced
the defect against the exact pre-fix CLI: 12 failing and four passing pytest
outcomes. The fixed file passes within the aggregate scope. A further focused
source check passed 56 register/census tests and 550 subtests. Raw test output
remains private; public derivatives preserve source and result fingerprints.

The receipt's Git HEAD identifies its import baseline. Exact package hashes
also bind the then-uncommitted root resume fix and ledger updates. Later
documentation and these validation records do not alter those tested bytes.
The functional denominator remains incomplete; firmware and Toolkit parity
remain in progress.

## Containers and NCC remain bounded offline work

`firmware_payload.py` describes the original raw, DFU-suffix and TI-prefix
dispatcher in memory. A valid TI prefix replaces the requested address and
selects internal flash, even when the caller requested external flash. The
offline model validates suffix version/length, identifiers, reserved fields and
address bounds. Recognizable damaged containers are refused rather than accepted
through the original raw fallback.

Physical update image loading accepts raw images only: valid DFU containers
require the offline payload planner, and recognizable invalid containers are
refused. The offline normalized transfer plan does not reproduce native
TI-prefixed packet grouping. Nonzero external CHECK address interpretation also
remains unaccepted because the recovered native host encodings disagree.

`firmware_ncc.py` models the original NCC post-update branch using caller-supplied
command-delimited transcripts, bounded to six exchanges and 65,536 response bytes
per exchange. It describes identify, version, update and restart ordering and
keeps native branch outcomes separate from extra transcript checks. It opens no
port and performs no update, restart, delay or physical verification. The actual
NCC post-check is not sent by the journaled DFU runner.

Fresh physical, vendor-payload, original runtime/JIT and Windows acceptance remain
open. Snapshot regression, archive integrity, offline payload/NCC modeling and
synthetic USB recovery do not establish those outcomes. The hardware procedure
remains in [usb-dfu-hardware-runbook.md](usb-dfu-hardware-runbook.md), and journal
semantics remain in [firmware-update-recovery.md](firmware-update-recovery.md).
