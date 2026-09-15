# Original-oracle harness inventory

This inventory covers live top-level test/research Python harnesses, excluding ignored vendor/runtime trees and immutable wheel acceptance snapshots. It distinguishes process dependencies from Docker-specific hostnames. It does not claim that changing a runner proves an original-model expectation on the new platform.

The 27 model-harness counts describe the initial shared-adapter audit. Subsequent updates identify General, five migration batches, Quick Status and Firmware diagnostics. The final read-only census below also includes newer live files; the initial hashes are historical rather than a claim about their current contents.

## Compatible .NET model patterns

There are **27 model test harnesses**: **26 eDLT** files and **one FirmwareUpdater** file. The accompanying `original-oracle-inventory.json` lists each file, source probes, and special requirements.

The common eDLT patterns are:

1. Compile one C# probe against `CBusLogicModel.dll` and framework references, then compare scalar/literal output.
2. Compile once and invoke repeatedly with explicit KEYGL5 XML plus synthetic PP/settings TSV files, compare all PP fields/five CRCs, and independently stage/save/reload through native C-Gate.
3. Compile a widget-specific probe and the generic `NativeEdltProbe.cs` CRC probe separately. These are multiple **single-source invocations**, not an invitation to concatenate or interpret arbitrary shell commands.
4. Add `eDLT.dll` and Windows Forms/Drawing for original UI selectors. These require actual Windows behavior to be compared before claiming parity with an earlier Mono result.

Page Control and Lifecycle already have explicit Windows paths owned by their respective agents. General is the focused pilot for the shared adapter. The first follow-up batch adds explicit branches for Display, Standby, Colours, Measurement icons and Activation. Quick Status is a special **two-source** compiler invocation with an explicit entry point and Xvfb on its Docker path; its separate adapter now compiles both unchanged sources with a validated explicit entry point. The earlier Windows nested-control transition evidence remains distinct. No changes were made to Page Control, Lifecycle or Clear files for these migrations.

The second batch adds Normalization, MRA normalization, Time/Date and MRA without changing the shared adapter, probes or production. It retains the existing Docker helper functions and uses byte-valued files for MRA's text settings. The third adds HVAC, Measurement, Measurement Standby and Room Courtesy. Its one probe extension accepts a strict UTF-8 HVAC label file, with prior source preserved and old/new output comparisons; the shared argument grammar stays unchanged. The fourth migrates Shutter, Timer, Fan and Enable using separate widget and generic CRC probes, with original assertions and source unchanged. The fifth migrates Lighting, Scene widgets, Scene tables, MultiLevel and Navigation. Navigation uses two independent single-source probes; Lighting composes the actual return statuses of two independent probes, preserving its prior shell short-circuit behavior. Detailed counts and scope are in the batch fixtures.

`research/original_oracle.py` exposes `OriginalModelOracle(source, app, backend=..., references=..., gui=...)`. Backend selection is explicit `CBUS_ORIGINAL_MODEL_BACKEND=docker|windows`, defaulting to Docker. Unknown values fail. There is no fallback when Windows, Docker, compilation, or a native probe fails. It compiles lazily after validating the complete input-file/argument request. It accepts typed literal arguments and byte-valued basename mappings, and prevents reserved Windows names, case collisions, path traversal, and code/executable replacement through data files.

Windows uses the existing `WindowsModelProbe`, exact staged vendor references and x86 execution. Docker compiles/runs using structured argv, a pinned Mono image, read-only original assemblies, no network, and a private work directory. `gui=True` preserves the explicit `xvfb-run -a mono` invocation on Docker; it does not install Xvfb or silently substitute an image. `run_result` preserves native stdout, stderr and nonzero exit information; `run` raises on nonzero process exit. Calls are sequential per instance; independent instances have separate files.

The initial pilot changes only the two original/native test methods in `tests/test_edlt_general.py`; its previous Docker branches and environment gates remain intact. The follow-up batch uses the same explicit branches in five test files, with separate report paths for each Python run. All six production implementations and original C# sources are unchanged. Standby's `mono(...)` helper, imported by Navigation, remains unchanged. `tests/test_original_oracle.py` verifies explicit selection, no execution on invalid input, no silent fallback, preserved failure output, typed Xvfb commands and a narrow canonical `@0` through `@64` literal extension using mocks. The actual `@64` sentinel is additionally exercised by the Measurement native case. These local mock tests do not claim Docker or physical acceptance.

## Separate dependencies

- **FirmwareUpdater:** `research/firmware_oracle.py` adds the explicit `CBUS_FIRMWARE_ORACLE_BACKEND=macos-mono` path. It uses the unchanged `NativeFirmwareProbe.cs`, separately pinned original updater/packages, a signed task-local Mono runtime and per-executable native library mapping. Both original serial handlers use a real macOS pseudo-terminal. Docker remains the default. See [its dedicated acceptance](../docs/firmware-original-oracle.md).
- **C-Gate service lifecycle:** `research/local_cgate.py` supplies the explicit `CBUS_NATIVE_SERVICE_BACKEND=local` path with owned state and verified loopback listeners. `research/oracle.py` remains a Docker-only standalone launcher; its sole live test-path import is the image constant in the scene helper.
- **Network research runner:** `research/verify_network.py` has an explicit local service branch that returns before Docker inspection and uses a loopback simulator.
- **TLS:** `research/verify_tls.py` has a local branch using the selected Java runtime's `keytool`, generated disposable PKI, owned loopback service and cleanup evidence. Its Docker certificate/service commands remain confined to the other branch.
- **Filesystem scenes:** `research/verify_scenes.py` has a local branch using explicitly selected `javac/java`, the unchanged native parser probe and an isolated service. Set `CBUS_CGATE_JAVAC` as well as `CBUS_CGATE_JAVA`; a JRE alone does not provide the compiler.

The initial **20 files** mentioning `host.docker.internal` comprise **18 native tests with `CBUS_CGATE_SIMULATOR_HOST`** and the two now-converted network/scene helpers. Set `CBUS_CGATE_SIMULATOR_HOST=127.0.0.1` for those tests; the local service helpers select loopback themselves. This changes simulator routing, not assertions or physical scope.

## Migration boundary

All 26 initial eDLT harnesses have explicit Windows paths, and the initial Firmware harness has its separate macOS Mono path. Earlier immutable Docker acceptance records remain unchanged. Focused platform evidence is recorded in the General, batch, Quick Status and Firmware fixtures; [original-oracle-adapters.md](../docs/original-oracle-adapters.md) describes their different contracts. No full test suite was run as part of these migrations.

## Final read-only readiness check

The final census classified 58 top-level live test/research files containing Docker references. No full-suite test requires an actual Docker process when the following selectors are explicit:

- `CBUS_ORIGINAL_MODEL_BACKEND=windows`, `CBUS_EDLT_LIFECYCLE_ORIGINAL_BACKEND=windows`, `CBUS_WINDOWS_BRIDGE=1`, and `CBUS_WINDOWS_PROVENANCE_ROOT` for the separately verified bridge/runtime evidence.
- `CBUS_NATIVE_SERVICE_BACKEND=local`, `CBUS_NATIVE_TLS_TEST=1`, `CBUS_SCENE_NATIVE=1`.
- `CBUS_FIRMWARE_ORACLE_BACKEND=macos-mono` and the pinned extracted `CBUS_MONO_MACOS_ROOT`.
- The owned `CBUS_CGATE_TEST_HOST`/`CBUS_CGATE_TEST_PORT`, loopback `CBUS_CGATE_SIMULATOR_HOST`, and explicit `CBUS_CGATE_JAVA`, `CBUS_CGATE_JAVAC`, `CBUS_LOCAL_CGATE_VENDOR`.
- Original `CBUS_TOOLKIT_EXE`, `CBUS_TOOLKIT_HELP_DIR`, `CBUS_UNITSPEC_DIR`, `CBUS_DFU_DLL`, `CBUS_FIRMWARE_UPDATER` and `CBUS_CATALOG_PATH`.

Read-only `unittest` discovery imported identical 1,377 test IDs from 148 modules on Python 3.13.14 and 3.10.20. There were no loader errors, import-time skips or attempted process/socket operations; an audit hook rejected any such operation during discovery. The native calculator's method-time catalogue precondition was checked separately because discovery cannot evaluate it. This validates imports and routing prerequisites, not test behavior or future service availability.

Install the wheel's `research,serial,usb` extras in each isolated acceptance interpreter. The observed dependencies were cryptography 50.0.1, pefile 2024.8.26, Unicorn 2.1.4, PyUSB 1.3.1 and pyserial 3.5. Both `lsof` and `openssl` resolve locally. The Homebrew Python 3.10 base lacked cryptography and pyserial: pyserial is in the owned `research/runtime/python310-usb-deps`, while cryptography and its dependencies are in the separate `research/runtime/python310-research-deps`. Source runs add both directories to `PYTHONPATH`; installed-wheel runs should install the extras directly and avoid adding `src`.

The exact local paths and source-level evidence are retained under ignored runtime in `research/runtime/mono-macos-owned/full-suite-environment.json` and `research/runtime/full-suite-readiness/{census.json,discovery-313.json,discovery-310.json}`. Their hashes are recorded in the accompanying inventory JSON. The active Windows bridge has a fixed expiry; a full run must finish before it or coordinate a safe new runner before starting. This readiness check did not start or replace any backend.

The discovery reports are historical inputs to readiness, not execution acceptance for subsequent changes. The installed-snapshot review then identified ignored local Lifecycle/Restore provenance inputs; their separate adapter now takes an explicit provenance root. Six original/native test files also gained parent-directory creation before their output writes. Both interpreters compile those changes; an AST comparison preserves all 395 assertions, decorators and subprocess calls. Full installed acceptance will exercise the final harness versions. The earlier environment is retained separately as `environment-at-discovery.json`.
