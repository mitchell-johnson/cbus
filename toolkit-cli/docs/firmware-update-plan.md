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

The journaled, resumable execution over an explicit DFU device and its
fault-injection matrix are described in
[firmware-update-recovery.md](firmware-update-recovery.md).
