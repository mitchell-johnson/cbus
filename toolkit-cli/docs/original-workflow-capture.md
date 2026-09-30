# Complete original workflow capture

`research/original_workflow_capture.py` captures one complete original Toolkit workflow end to end with one harness. The workflow is an eDLT **Page Control** edit of a database **KEYGL5 / 5055EDL / 5.5.00** unit: the unchanged Toolkit 1.18.0.2754 `CBusLogicModel` opens the unit, applies the edit through its own binding, computes the PP values and CRCs, and saves through its own C-Gate client. The project is then closed, and the original model reopens it and reads the unit back. The Python CLI performs the same workflow on an identically seeded project. The harness compares every stage.

This is the first original result that is not joined from component probes. Earlier eDLT acceptance ran original setters, save hooks and CRC methods against hand-built model objects without I/O. It then replayed their output into C-Gate using Python. In this capture, every C-Gate command in the original stages is issued by the original `SharpCGateCommunicator` in the order chosen by the original model.

## Harness

| Component | Role |
|---|---|
| Owned native C-Gate | `research/local_cgate.py::LocalCGate` starts C-Gate 3.4.0.2001 from the pinned JAR on loopback. It adopts no existing projects and never opens a C-Bus network. |
| Recording relay | `RecordingRelay` is a loopback TCP relay between each client and C-Gate. It records both directions in one global order and forwards bytes unchanged. |
| Original model | [OriginalEdltPageControlWorkflowProbe.cs](../research/OriginalEdltPageControlWorkflowProbe.cs) is compiled with the pinned task-local Mono 6.12.0.206 against the original DLLs. It calls `CBusNetworkGlobalManager.SetCGateConnection`, `GetNetwork`, the `EDLTUnit` database constructor used by `FrmBaseUnit`, and `LoadUnit`. It then sets `KeySetsEnableGroup.PPAttributeValue`, the value written by the Page Control combo box binding. Finally it calls `SaveUnit(true, false, false, false, [])`, the arguments passed by `FrmBaseUnit.SaveUnit` for a database save. |
| CLI | `python -m cbus_toolkit` runs `unit export`, `edlt lifecycle-requirements`, `unit edlt-lifecycle`, `edlt page-control-plan`, `unit edlt-page-control` (with and without `--dry-run`/`--no-first-open`) and `unit show` through the same relay. |

The seed is synthetic: network 254 (CNI `127.0.0.1:1`, never opened), unit 20 KEYGL5, Lighting 56/group 1, Trigger Control 202, and Enable 203/group 42. The group is 42. All variants run sequentially on one fixed project name, so the name-derived `Project` PP and CRCs are reproducible. Each variant is deleted before the next is seeded.

1. **original**: seed. The original model opens, edits and saves the unit. The harness issues only `PROJECT CLOSE`. The original model runs again; its `useProject` receives `401` and issues `PROJECT LOAD` itself. It then reloads the unit and reports the Page Control value.
2. **cli**: seed, then run the CLI equivalent of opening, editing and saving in the Toolkit. `edlt-lifecycle` uses a cache derived from one `DBGETXML` snapshot. `edlt-page-control` follows. The harness runs project save/close/load before `show`.
3. **cli_first_open**: seed, then run only `edlt-page-control`, first with `--dry-run` as the plan and then applied. The CLI detects the never-opened unit (`ConfigVersionMajor`/`Minor` 255), derives the lifecycle cache from one `DBGETXML` of the network, and stages [first open](edlt-lifecycle.md#first-open-in-direct-helpers) before the edit. It then issues one PP save.
4. **cli_direct**: seed, then run `edlt-page-control --no-first-open`. This variant records how far the direct edit alone is from the original workflow on a never-opened unit.

After each variant, the harness reads the complete database PP memory with `PP GET_RAW_DATA` (`??` marks bytes that C-Gate reports as invalid). It also reads all parameters, the network document without OIDs, and network state.

## Receipt

The compact, sanitized receipt is [original-workflow-page-control-receipt.json](../research/fixtures/original-workflow-page-control-receipt.json). It binds:

- The inputs: the seed and its hash, the seeded database document, initial raw image, initial parameters, the KEYGL5 specification hash, and the probe and harness source hashes.
- The original runtime and assemblies: pinned Mono file hashes, the compiled probe hash, and the hash of every original assembly loaded from the application directory. These are `CBusLogicModel.dll`, `SharpCGateCommunicator.dll`, `SharpLogger.dll`, `log4net.dll` and `CustomControls.dll`.
- The original C-Gate command transcript. It contains 75 edit/save commands and 17 reopen commands. Each entry lists its response codes, final status line and a hash of its reply lines. The project name is replaced by `{PROJECT}`. A run-independent `command_sequence_sha256` covers commands, codes and final lines.
- The PP values changed by the original, its load and save-stage normalization, all five CRCs, the Page Control byte at `0x131`, and the final raw image hash.
- The CLI steps, lifecycle cache, 104-command transcript and final raw image hash.
- The single-command `cli_first_open` step, its detected version, derived cache and first-open changes, its 161-command transcript (preview and apply), final raw image hash and an empty parameter difference list.
- The `cli_direct` parameter differences.

The full private report can be written with `CBUS_ORIGINAL_WORKFLOW_REPORT`, or as `<receipt>.raw.json` by the script. It contains raw stdout/stderr, complete transcripts and both hex images. It stays under ignored runtime paths.

## Result

All five original stages passed: open, edit through the binding, save, reopen after close, and reopened Page Control value 42. Both CLI stage checks passed. All 15 comparisons passed:

- identical seeded inputs across variants
- original saved PP equal to C-Gate readback
- CLI plan equal to the original saved PP
- CLI and original readbacks equal
- all 874 C-Gate parameters equal
- all five CRCs equal
- identical 8,703-byte raw images, including the same 3,558 invalid positions
- database documents equal except for the original's literal `"null"` writes described below
- for `cli_first_open` (Page Control alone): dry-run preview equal to the original saved PP, readback and all 874 parameters equal, all five CRCs equal, identical raw image and database documents equal on the same terms
- network state `new`

The final raw image SHA-256 is `bf48d7af…8b9c92` for the original, `cli` and `cli_first_open`.

Original behavior captured by this workflow:

- **First open normalizes the unit.** `AfterLoadPPData` changes ConfigVersion 255→1/0 and widget types. The save stage writes SceneCount 8, the eight scene start addresses, eight default `02 00 FF FF FF` scene records, Widget6 terminator `0xFF`, `Application` and the CRCs. The original issued 40 `pp set` commands, although the user changed only `KeySetsEnableGroup`.
- **The direct edit alone is not the whole workflow.** With `--no-first-open`, `cli_direct` differs from the original in 35 parameters on a never-opened unit. These are ConfigVersionMajor/Minor, 20 widget types (not Widget6, which already held `0xFF`), SceneCount, eight scene start addresses, SceneBucket, WidgetsCRC, ScenesCheckSum and OverallCRC. They are the `AfterLoadPPData` and first `BeforeSavePPData` normalization. By default the CLI now applies that first open itself, so `edlt-page-control` alone equals the original with one PP save. The explicit `edlt-lifecycle` then `edlt-page-control` sequence remains equal too, with two PP saves.
- **Database fields.** Before the PP save, the original sets unit `Description`, `UnitName`, `SerialNumber`, `Serial`, `CatalogNumber` and `TagName`. It writes C-Gate's `null` display back as the literal string `"null"` into `Description` and `SerialNumber`. `Serial` returns `401` and is ignored. It saves the project before and after the PP save and ends with `PP CANCEL_LOCK 20`, which returns `427` and is ignored. Neither CLI variant makes these writes. The comparison accepts only these literal-`null` differences, and only when they appear as original `dbset` commands.
- **Reload.** Reopening reads Widget6 `0xFF` as blank in the model view, while the stored byte remains `0xFF`. Eight scene lookups request `add-level 202/255/255` from the host.

## Boundaries

- **Platform adaptation.** `SharpCGateCommunicator` splits replies on `Environment.NewLine` and skips two characters. Mono on macOS reports `\n`, so the unchanged client hangs on its first reply. Before any original code runs, the probe sets Mono's private newline field to the Windows value `\r\n`. No original method is patched.
- **Host callbacks.** The Delphi Toolkit host normally answers the model's metadata requests. The probe subscribes to the application, group and level requests, records them and creates nothing. The edit run made no requests. The reopen requests are listed in the receipt. The seed pre-creates application 202 because, without a host, the original scene lookup otherwise throws `NullReferenceException` in `EDLTScene.get_TriggerGroup`. Without application 203, `AfterLoadPPData` fails in `BindingListCBusObject`.
- **Not executed:** the WinForms `FrmBaseUnit` dialog, its progress and background threads, and the Delphi executable. Mono's 64-bit Carbon WinForms driver is unavailable; `CustomControls.dll` loads without constructing a form. Also not executed: network (`saveNw`) saves, DLT label saving, global programming and any physical unit. This capture covers one database workflow and one group value (42). The first-open path of the other direct helpers is covered offline only. It is not physical eDLT acceptance, Windows acceptance or rendering evidence.
- **Pinned inputs.** The unit specification and original binaries remain private and are identified by hashes only. The committed receipt contains no specification content or project name.

## Running

```sh
CBUS_MONO_MACOS_ROOT=/absolute/path/mono.pkg/Payload/Library/Frameworks/Mono.framework/Versions/6.12.0 \
CBUS_TOOLKIT_EXE=/absolute/path/toolkit/app/CBusToolkit.exe \
CBUS_LOCAL_CGATE_VENDOR=/absolute/path/cgate/app \
CBUS_CGATE_JAVA=/absolute/path/jdk-11/Contents/Home/bin/java \
CBUS_UNITSPEC_DIR=/absolute/path/unitspec-plain \
PYTHONPATH=src:tests:. python -m unittest -v tests.test_original_workflow_capture
```

`python research/original_workflow_capture.py [receipt.json]` writes a new receipt and its raw report. The gated test requires macOS and all five variables. Without them it skips with that reason. With them, it reruns the whole capture and requires every stage and comparison. It also requires `cli_first_open` to show no parameter differences, the original's image hash and database-derived metadata. The reproducible input, assembly, PP, CRC, image and command-sequence hashes must match the committed receipt for `original`, `cli` and `cli_first_open`. Seven offline tests cover the relay, transcript correlation, probe parsing, cache derivation, database differences and receipt sanitization.

On 2026-09-30, on Python 3.13.14 with the owned Mono, C-Gate and Java 11 runtimes, all **8 tests passed with no skips** (8.2 s). Two separate capture runs produced identical reproducible hashes. After the first-open change, the receipt was regenerated with the four variants. A separate gated rerun then passed all **8 tests with no skips** (10.1 s) against it.
