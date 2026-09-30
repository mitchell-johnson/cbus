# eDLT vendor firmware update plan

`cbus-toolkit firmware update-plan` reproduces the step list of the original
eDLT firmware updater bundled with Toolkit 1.18 (`FirmwareUpdater.exe`
1.16.3.0) for a supplied `eDLTFirmware_<version>.zip`. The plan is
deterministic JSON derived from the ZIP directory alone. It does not run
`dfuprog`, open USB or serial devices, or write firmware.

```sh
cbus-toolkit firmware update-plan eDLTFirmware_1.7.0.zip --variant TivaNCC
cbus-toolkit firmware update-plan eDLTFirmware_1.7.0.zip --hardware-version '2.0 (Tiva + PCI)' --force-font
cbus-toolkit firmware inspect-images eDLTFirmware_1.7.0.zip --package-password-file private/password
cbus-toolkit firmware update-simulate eDLTFirmware_1.7.0.zip --variant TivaPCI --package-password-file private/password
```

`--hardware-version` applies the original `HardwareVersion` mapping; unknown
text fails with the original `Unit variant is unknown.` Exit status 1 means
the plan is refused (`supported=false`, with `issues`).

## Reproduced original behavior

| Item | Original rule |
| --- | --- |
| Selection | Case-sensitive `main`+`hwv1`/`hwv2`/`hwv3` and `font` substrings; the last match wins; other entries are skipped. Every selected entry is extracted, including other variants. A non-file entry clears all selections. |
| Refusal | A missing variant image or font gives `The selected firmware archive is not compatible with the connected eDLT unit.` and no `dfuprog` step. |
| Address | `-a 0x2000` for Stellaris/PCI; `-a 0x4000` for Tiva/PCI and Tiva/NCC. |
| Font skip | Skipped when the filename version is in `EdltFirmware.FontData1Versions` (1.0.0–1.7.0) unless *Force font data installation* is set. |
| Steps | `-m`; if installing fonts: wait 8 s, `-z -c -l N`, `-z -b  -a 0 -f font`, `-m`; then wait 10 s and `-b -a ADDR -r -f main`. |
| Erase length | Literally `(font_bytes / 65537 + 1) * 65536`. Some sizes, such as 131,073 bytes, are erased short; such a plan is refused. |
| Failure | Each step stops the update only when `ExitCode > 0`, with the step's original message. There is no retry. |
| Post-check | PCI variants report success immediately. Tiva/NCC waits 10 s, requires `id` to return the exact package version, waits 0.5 s, sends `nv`, and when the embedded NCC version is newer sends `nu`, `nv` and, for current version `0.0.0`, `rs` followed by `id` after 10 s. |

The font write's `-r` branch is unreachable, `dfuprog` is called without `-s`
(no readback), and no step compares the package with the unit's current
firmware, so downgrades and reinstalls proceed. `native_quirks` lists these.

## Private package reader

Vendor archives use a constant password embedded in the updater: AES entries
(method 99) for 1.3.0–1.5.0 and ZipCrypto for 1.7.0. The CLI never contains,
stores or prints it. Supply it at runtime with `--package-password-file` or
`CBUS_EDLT_PACKAGE_PASSWORD_FILE`. Entries are decrypted in memory only.
ZipCrypto uses the standard library; AES requires the optional `firmware`
extra (`pyzipper==0.3.6`). Without it, AES entries fail with an explicit error.

`inspect-images` and `update-plan --package-password-file` report only entry
sizes, SHA-256, encryption method, the existing DFU container inspection and a
Cortex-M vector-table check at the variant address. All four Toolkit 1.18
packages contain raw binaries (no DFU suffix or TI prefix), so `dfuprog`
downloads them at the `-a` address, and every main image's reset vector lies
inside the image at its variant address. The archives are unsigned: a
successful read establishes ZIP CRC/AES HMAC integrity, not vendor authenticity.

## Original-assembly comparison

`research/firmware_update_oracle.py` runs the unchanged private
`UnzipFirmwarePackage` and `UpgradeFirmware` methods under the owned macOS Mono
6.12.0.206 runtime (see [firmware-original-oracle.md](firmware-original-oracle.md))
with a stub `dfuprog` that records argv and the SHA-256 of each `-f` file.
Unit discovery in `FirmwareUpgrader_DoWork` uses WMI, so its argument
assignments and required-file check are retyped in
`research/NativeFirmwareUpdateProbe.cs`. The sanitized receipt
[original-oracle-firmware-update-plan.json](../research/fixtures/original-oracle-firmware-update-plan.json)
covers 29 executions: all four vendor packages × three variants × forced and
unforced fonts, plus a stub failure at each of the five steps. For each, the
recorded argv sequence equals `update-plan`, file arguments carry the selected
entry's hash and size, the 8 s and 10 s delays are observed, failures stop with
the original message and extracted files are removed. The original extraction
hashes equal the private reader's hashes for every entry. The original
SharpZipLib decrypts both AES and ZipCrypto packages.

Mono does not raise `SerialPort.DataReceived`, so the Tiva/NCC run proves only
that the original sends `id\r` after the main write and then times out. The
remaining NCC sequence is static source evidence. An unconstructed WinForms
`CheckBox` holds the force option because constructing one needs GDI+.

The bounded Python [NCC transcript evaluator](firmware-ncc-transcripts.md)
now makes that remaining static branch callable without a serial port. The
restart predicate uses the **post-update** `nv` current version, and the
original accepts three `nu` progress keys without requiring their order.
Its modeled success is separate from independent transcript checks and never
establishes execution or physical acceptance.

To regenerate (vendor files and password stay private):

```sh
CBUS_MONO_MACOS_ROOT=/abs/Mono.framework/Versions/6.12.0 \
CBUS_FIRMWARE_UPDATER=/abs/toolkit/app/FirmwareUpdater.exe \
python research/firmware_update_oracle.py --output report.json --package-password-file private/password
```

`tests/test_firmware_update_plan.py` replays the committed receipt offline
against same-shaped packages and covers every plan branch with synthetic
packages in `research/fixtures/firmware-update-packages/` (built by
`research/build_firmware_update_fixtures.py` with a synthetic password).
`tests/test_firmware_update_oracle.py` reruns four original cases when
`CBUS_FIRMWARE_ORACLE_BACKEND=macos-mono`, `CBUS_MONO_MACOS_ROOT` and
`CBUS_FIRMWARE_UPDATER` are set.

## Memory simulator run

`update-simulate` executes a supported plan against the independent memory DFU
peer through the existing strict client. Each `dfuprog` step opens a fresh host
session (the vendor DLL's block counter restarts per process). Mode switches
are no-ops because the peer is already in DFU mode, the target reset is not
sent, and every write is read back, unlike the original. The first failed step
stops execution. Tests use synthetic images only. This is development evidence:
DETACH, reset, bootloader auto-erase, re-enumeration and the NCC serial path are
unmodeled, and no physical device or vendor payload has been installed.

## Bounded package and payload binding

`load_selected_images` reproduces the selected package metadata, version,
variant, font policy and original argv before decryption. It hashes the same
immutable archive bytes that supply the directory records and decrypted
entries. `open_package_snapshot` reads a bounded regular file once through a
nonblocking/no-follow descriptor, checks its identity/size/timestamps around
the read, then retains only immutable bytes. The CLI captures a fresh snapshot
after planning and checks its SHA-256 against the reviewed plan before any
directory parser, decryption reader or USB opener is initialized. Full plan
comparison includes the entry sizes and CRC records. There is no package
path reopen after that check; later replacement cannot change selected bytes.
If a decrypted inspection is attached, selected entry
sizes and SHA-256 values must match it. Duplicate ZIP names, missing selected
entries, nonregular inputs, more than 1024 directory entries, inputs over
512 MiB, entries over 64 MiB and selected plaintext totaling over 64 MiB are
refused. The aggregate bound is an added software limit, not a vendor rule.

The default loader used by `update-run`, `update-resume` and `update-simulate`
accepts raw images only. Valid DFU containers and recognizable damaged
containers are refused before a device opener can be constructed. The
physical runner has no normalized-container contract; a valid suffix alone
must not let it write the suffix as firmware. No CLI or physical transport
capability is expanded by this change.

For explicit offline analysis, use
`firmware_payload.resolve_download_payload(data, address=..., external=...)`
and `plan_download_payload(payload, flash_size=..., application_start=...)`.
The receipt hashes the original input and effective payload separately. A
valid suffix-only image strips its suffix; a TI-prefixed image strips both
prefix and suffix and takes its address from the prefix. The original
`dfuprog` wrapper at `0x402400` supplies no external-flash argument to
`LMDFUDownload`, so a TI-prefixed font would select internal flash even with
`-z`: that role is explicitly refused. VID/PID mismatches, unsupported suffix
shapes and recognizable damaged-container raw fallback are also refused.
These are bounded offline interpretations, not package authenticity or
bootability checks; source hashes are included in each payload receipt.

An offline caller may explicitly pass `allow_containers=True` to
`load_selected_images` and supply those bytes to `simulate_plan`. The memory
peer then receives normalized payload bytes at the effective address, and
the returned region identifies both `matches_payload` and `matches_image`.
TI prefix packet grouping is not reproduced; this tests resulting memory
content only. The default loader continues to refuse these inputs.

`describe_external_check_addresses(address=..., length=...)` exposes both
original external CHECK encodings: standalone BlankCheck divides the address
by 65536 while Erase's verification path divides it by 1024. Nonzero external
execution remains unsupported; describing both headers does not resolve the
device-side interpretation. Native `patchset.zip`, authenticity, physical
payload acceptance and nonzero external device behavior remain open.

The journaled, resumable execution over an explicit DFU device and its
fault-injection matrix are described in
[firmware-update-recovery.md](firmware-update-recovery.md).
