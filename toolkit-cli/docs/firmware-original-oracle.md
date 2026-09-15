The firmware diagnostic oracle can run through a task-local macOS Mono runtime with `CBUS_FIRMWARE_ORACLE_BACKEND=macos-mono`. Its default remains the existing Docker path. `CBUS_MONO_MACOS_ROOT` must name the extracted `Mono.framework/Versions/6.12.0` directory, and `CBUS_FIRMWARE_UPDATER` must name the original updater bundled with Toolkit 1.18. There is no fallback between platforms.

The runtime came from the [official Mono 6.12.0.206 download](https://www.mono-project.com/download/stable/). The 370,007,450-byte package has SHA256 `80b0dbfa59ba9ed76dbf1393998e6a2ed2d1ccc8f5850c7a46fbe31a2aea88d8`. macOS verified its Microsoft Developer ID Installer signature, trusted Apple notarization and trusted timestamp. `pkgutil --expand-full` extracted it into owned runtime storage; no installer or package script ran. The observed runtime is Mono 6.12.0.206, amd64, with compiler 6.12.0.0. No global framework or system path was changed.

`research/firmware_oracle.py` pins the runtime/compiler/framework and native-library hashes, original updater and four package hashes, and the unchanged `NativeFirmwareProbe.cs`. It checks them before each compile/run and afterward. An instance permits one compile and one run, keeps actual exit/stdout/stderr, and checks its compiled image and input configuration before execution. It removes inherited Mono/DYLD overrides and uses explicit task-local paths. This is research tooling, not a firmware CLI transport.

The original probe still calls `openpty`, `ttyname`, `write` and `close`, then feeds the slave through a real `System.IO.Ports.SerialPort` to the unchanged updater ID/NV handlers. A separate per-executable configuration maps its Linux import names to `/usr/lib/libSystem.B.dylib` on macOS, using Mono's documented [native library mapping](https://www.mono-project.com/docs/advanced/pinvoke/). The C# probe and vendor code are unchanged. An independent load trace confirms the macOS library and task-local Mono serial helper were loaded. No physical serial or USB device is used.

```sh
CBUS_FIRMWARE_ORACLE_BACKEND=macos-mono \
CBUS_MONO_MACOS_ROOT=/absolute/path/to/extracted/Mono.framework/Versions/6.12.0 \
CBUS_FIRMWARE_UPDATER=/absolute/path/to/original/FirmwareUpdater.exe \
CBUS_FIRMWARE_DIAGNOSTIC_REPORT=/absolute/path/to/report.json \
PYTHONPATH=src:tests python -m unittest -v \
  tests.test_firmware_oracle tests.test_firmware_diagnostics
```

Both Python 3.13.14 and 3.10.20 passed 22 tests with no skips. These include six adapter guards, the original 70-row metadata/parser corpus, real Mono pseudo-terminal transport, an independent pyserial peer, and existing failure/partial-input tests. All 90 prior assertion expressions, Docker command construction and environment gates remain unchanged. The reports are identical across interpreters. The original corpus covers 15 hardware variants, five package-name cases, 14 .NET version cases, two original serial handlers, three identification schemas, four package archives and 11 archive entries. Archive metadata is read without extracting or writing firmware.

The initial Python 3.10 attempt skipped the separate pyserial peer because pyserial was missing. Its log is retained; acceptance uses the subsequent complete run after pyserial 3.5 was added only to the owned test dependency directory. Source hashes, runtime provenance, signature/load-trace hashes and final run records are in [the acceptance fixture](../research/fixtures/original-oracle-firmware-macos-acceptance.json). This focused source acceptance does not claim a full installed-wheel run or physical hardware acceptance.
