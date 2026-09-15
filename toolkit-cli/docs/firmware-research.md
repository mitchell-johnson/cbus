# eDLT firmware updater research

Complete Toolkit firmware updating remains unfinished. Diagnostic commands, offline DFU tooling, an injected transfer client and a claimed-PyUSB program/erase/readback CLI are now implemented within their documented scopes: [diagnostics](firmware-diagnostics.md), [DFU transport](dfu-transport.md) and [USB DFU](usb-dfu.md). Vendor payload compatibility, NCC installation and physical firmware acceptance remain open.

This earlier investigation records the original installer, including a separate .NET `FirmwareUpdater.exe`, native `dfuprog.exe`, USB DFU drivers and four encrypted firmware archives. Their hashes and archive directory inventories are recorded in [firmware-research.json](firmware-research.json). The investigation below did not access a USB device or extract or transfer a firmware image; subsequent scoped acceptance is linked above.

The unmodified updater was decompiled into the ignored `research/vendor/firmware-updater-decompiled` directory using ILSpy 9.1.0.7988. References below identify original class/method names, not Python implementations. Decompiled source needs original-assembly or bytecode comparison before it becomes behavioral acceptance.

## Observed workflow

`FirmwareUpdater_DoWork` discovers Windows serial ports whose caption contains `eDLT Diagnostic Interface`; it refuses zero or multiple matches. `EdltSerialInterface` uses 9600 baud, 8 data bits, no parity, one stop bit and no handshake. It sends `id\r` and accepts one of three complete identification field sets. It distinguishes `Version` from `FW Version` and supports legacy units without a hardware version string.

`EdltFirmwareUpgradeArgs.HardwareVersion` maps an empty version, `1 (Stellaris)` or `1.0 (Stellaris + PCI)` to Stellaris/PCI. It maps `2 (Tiva)` case-insensitively, or exact `2.0 (Tiva + PCI)`, to Tiva/PCI. Exact `3.0 (Tiva + NCC)` selects Tiva/NCC. Other values remain unknown. These branches, package metadata and diagnostic parsers have now been compared with the original assembly; see [firmware-diagnostics.md](firmware-diagnostics.md).

`UnzipFirmwarePackage` selects names containing `main` and `hwv1`, `hwv2` or `hwv3` for the three variants, and a name containing `font` for font data. An embedded archive credential is used internally; it is not included in this documentation or Python package. `EdltFirmwarePackage` derives the reported package version from the filename after its first underscore. Toolkit 1.18 contains packages 1.3.0, 1.4.0, 1.5.0 and 1.7.0. Only the last contains all three main-image variants.

`UpgradeFirmware` selects offset 0x2000 for Stellaris/PCI or 0x4000 for both Tiva variants. It launches the separate DFU process, with stages for entering update mode, optionally erasing/writing font data, entering update mode again and writing/restarting the main firmware. Its font erase length uses the unusual integer expression `(file_length / 65537 + 1) * 65536`; this must be compared as written before deciding whether a compatible implementation should reproduce or correct it. Font skipping also depends on a version list in the original `EdltFirmware` class and the force-font option.

The NCC branch re-identifies firmware after the main update. It uses `nv\r` to obtain current and embedded NCC versions, may send `nu\r` to update NCC, and may send `rs\r` to restart it. The code waits for specific response keys, including three distinct update-progress lines. A future CLI needs explicit failed/uncertain states and independent final version checks. The GUI's process exit handling and success flags alone do not establish flash contents or recovery behavior.

## Remaining acceptance work

The original-assembly harness for variant classification, package metadata and diagnostic responses is complete within its documented scope. Subsequent [DFU protocol and memory simulator](dfu-protocol.md), [transport](dfu-transport.md), [USB inspection](usb-inspection.md) and [claimed USB transport](usb-dfu.md) acceptance cover bounded command/status decoding, ranges, explicit program/erase/readback, polling and partial failures. These use independent synthetic memory and a fake backend through the actual PyUSB library. Complete vendor updater sequencing, payload compatibility, NCC installation, reboot/recovery across the whole update, driver differences and real hardware remain open. The C-Bus PCI simulator itself does not model the USB interface.
