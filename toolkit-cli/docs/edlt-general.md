# eDLT general settings

`cbus_toolkit.edlt_general.EdltGeneralSettings` edits key timing, status reporting, Tools Page access and power restore mode for **KEYGL5 / 5055EDL / firmware 5.5.00**. It plans and verifies database PP changes against the original Toolkit model. It does not program or power-cycle a physical unit.

```python
editor = EdltGeneralSettings(spec)
plan = editor.plan(
    session.values(), long_press_ms=400, debounce_ms=75,
    status_report_seconds=3, tools_page_locked=True,
    power_restore='previous',
)
result = editor.apply(session, plan)  # complete PP readback; no save
session.save_to_source()             # explicit database persistence
```

The API is `plan(current, *, long_press_ms=None, debounce_ms=None, status_report_seconds=None, tools_page_locked=None, power_restore=None)`. `snapshot`, `crcs`, `apply` and `configure` follow the other eDLT helpers. Every omitted option preserves its stored field value. These settings apply to the whole unit.

| Option | Accepted explicit values | Native field and layout |
| --- | --- | --- |
| `long_press_ms` | 25..6375 milliseconds, in steps of 25 | `LongPressTime`, byte `0x114`; milliseconds divided by 25 |
| `debounce_ms` | 0..6375 milliseconds, in steps of 25 | `DebounceTime`, byte `0x115`; milliseconds divided by 25 |
| `status_report_seconds` | Integer 3..255 seconds | `StatusRequestInterval`, byte `0x112` |
| `tools_page_locked` | Boolean | `ToolsPageLocked`, bit 4 of byte `0x11A` |
| `power_restore` | `previous` or `preset` | `EnableLevelStore`, bit 1 of byte `0x116`; previous = 1, preset = 0 |

The original UI lists long-press codes 1..255 and debounce codes 0..255, displaying each code multiplied by 25 ms. Its status-report control has minimum 3 and maximum 255. Schema defaults are 400 ms, 75 ms, 3 seconds, an unlocked Tools Page and widget preset levels.

Stored long-press code 0 and status intervals 0..2 are accepted only when their options are omitted. They remain unchanged and are reported through `long_press_ui_canonical=false` or `status_report_ui_canonical=false`. An explicit status value below 3 is rejected. This avoids the original model setter's conditional behavior: an equal existing value is left alone, while a changed value below 3 is clamped to 3.

## CLI

```sh
cbus-toolkit edlt general-plan parameters.json \
  --long-press-ms 400 --debounce-ms 75 --status-report-seconds 3 \
  --tools-page-locked --power-restore previous

cbus-toolkit cgate --host 127.0.0.1 --port 20023 unit \
  --lock-address //MYPROJ/254 --source /db//MYPROJ/254/p/20 \
  edlt-general --power-restore preset --no-tools-page-locked
```

`--dry-run` on the `unit` command validates native PP changes and leaves the database source unchanged. The normal command saves and reports the database result. A physical destination is rejected.

## Preservation and failure behavior

Selecting previous or preset levels preserves all existing widget RestoreLevel values. The original save hook can independently normalize blank and terminator widget types; when that changes a functional widget's type, its RestoreLevel resets to zero. Plans expose these normalization changes. Existing MRA siblings receive the original first MRA widget's shared zone and multiplexer bits, including stored placements that are unavailable for new widget creation.

The helper preserves unrelated bit fields, static text, scenes and widget data apart from those explicit save normalizations. It updates the two-byte Application mirror and calculates all five original CRCs. Before mutation it checks the exact profile and field layouts, validates whole-unit references, reconstructs the canonical plan and rejects a stale complete PP snapshot. Applying reads back the entire resulting PP snapshot.

An ordinary failure restores attempted parameters in reverse order while the C-Gate session remains synchronized. Lost synchronization stops recovery I/O and reports an unsaved partial outcome. KeyboardInterrupt and SystemExit stop immediately and retain `edlt_general_evidence`, including attempted parameters, uncertain PP state and `automatic_retries=0`. An interruption during rollback also retains the original failure and previous rollback errors. The CLI exposes this evidence and does not save after an interrupted apply.

## Original-model evidence and scope

[NativeEdltGeneralProbe.cs](../research/NativeEdltGeneralProbe.cs) invokes the unchanged original timing lists, scalar properties, complementary restore-mode properties, save hook and CRC routine. It verifies 773 output rows, including every timing choice, raw scalar code and both restore modes. The independent source audit also checks the original `FrmBaseUnit` UI bindings and `KEYGL5.xml` layouts.

The native test compares complete PP snapshots with the original DLL for 32 combinations of timing, interval, lock and restore-mode boundaries, three omitted noncanonical cases and a stored-MRA normalization case. Each case checks the nine raw bytes beginning at `0x112` and all five CRCs. Database save/close/load equality and CLI preview preservation are checked against exact C-Gate 3.4.0.2001. The test projects remain closed with network `state=new`.

This comparison covers explicit field setters and the save stage. It does not invoke the original `AfterLoadPPData` lifecycle, which can initialize configuration version 255 to 1.0 and change InvertDisplay 1 to 0. Native test fixtures use configuration version 1.0 to keep those independent load-time effects outside this contract.

The original `AddMandatoryPpParamsForSavingToNetwork` includes all 16 functional widget RestoreLevel parameters when preset mode is selected. That is a separate physical transfer rule; changing this database setting does not demonstrate that transfer or a power-cycle result. The helper also does not edit individual preset levels or implement the UI's slider synchronization action. Results retain `physical_device_verified=false` and `power_cycle_verified=false`.

Run `tests.test_edlt_general` and `tests.test_cli_edlt_general` with `CBUS_CGATE_TEST_HOST`, `CBUS_CGATE_TEST_PORT`, `CBUS_UNITSPEC_DIR` and `CBUS_TOOLKIT_EXE` set for an isolated native oracle and local vendor files. Original-model tests use the pinned Mono container. Detailed successful native reports are written to ignored `research/runtime/edlt-general-report.json` and `research/runtime/edlt-general-cli-report.json`; the compact [acceptance fixture](../research/fixtures/edlt-general-acceptance.json) records interpreter results, literal raw bytes, CRCs and artifact hashes. Vendor assemblies are not distributed with the CLI.

Final focused acceptance passed **11 tests with zero skips** on Python 3.13.14 (65.828s) and Python 3.10.20 (75.829s). The 36 native case reports and the CLI report were identical across both interpreters.
