# eDLT standby and nightlight settings

`EdltStandby` implements the original Toolkit standby timeout, destination and nightlight controls for **KEYGL5 / 5055EDL / firmware 5.5.00**, using a caller-supplied original `KEYGL5.xml`. It edits a native database PP session. It does not claim physical standby timing, indicator output, hardware programming or full eDLT dialog parity.

```python
from cbus_toolkit.edlt_standby import EdltStandby

editor = EdltStandby(spec)
plan = editor.plan(values, enabled=True, after_seconds=30,
                   destination='standby', nightlight_user_keys=True,
                   nightlight_colour='off-colour')
result = editor.apply(session, plan)  # verifies PP state; does not save
session.save_to_source()             # explicit database save
```

All six arguments are optional. Omitted arguments preserve stored settings, subject to the shared original save normalization described below. `.configure(session, **options)` checks identity, reads, plans and applies. `.snapshot(values)` and `.crcs(values)` expose the same bounded profile codec as the other eDLT helpers.

The CLI distinguishes the standby destination from the programming destination:

```sh
cbus-toolkit edlt standby-plan parameters.json --enabled --after-seconds 30 \
  --timeout-page standby --nightlight-user-keys --nightlight-colour off-colour
cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run edlt-standby \
  --enabled --after-seconds 30 --timeout-page standby
```

Remove `--dry-run` to apply and save through the database workflow. The unit command's `--destination` is the programming destination; `--timeout-page` selects the page shown after inactivity. Plan JSON uses `timeout_page`, `timeout_page_raw` and `timeout_page_ui_canonical` to keep these meanings distinct.

## Exact field mapping and ordering

| Argument | Original PP field | Byte / bits | Offered values |
|---|---|---|---|
| `enabled` | `ActivityDuration` via `EnableStandByPage` | `0x11B / 0..7` | boolean; see setter behavior below |
| `after_seconds` | `ActivityDuration` | `0x11B / 0..7` | integer 1..255 |
| `destination` | `TimeoutPage` | `0x11A / 5..6` | `current=1`, `page-1=0`, `standby=2` |
| `nightlight_user_keys` | `EnableNightlightUserKey` | `0x116 / 6` | boolean |
| `nightlight_page_key` | `EnableNightlightPageKey` | `0x116 / 7` | boolean |
| `nightlight_colour` | `NightlightColour` | `0x117 / 3..4` | `off-colour=0`, `on-colour=1`, `page-key-colour=2`, `quick-status-colour=3` |

`enabled=True` calls the original setter semantics first: if the stored delay differs from integer 1, it becomes **3 seconds**; a stored delay of 1 stays 1. `enabled=False` sets zero. An explicit `after_seconds` then overrides the enabled delay. Thus `enabled=True, after_seconds=30` produces 30; `enabled=True` against stored 30 produces 3. Omit `enabled` to preserve an existing delay while editing another field. JSON `after_seconds=0` means disabled.

The original disabled standby group hides all five dependent controls. The helper rejects dependent edits while the resulting standby state is disabled, including an explicit delay without enabling an initially disabled source. The colour chooser is enabled only if either resulting nightlight key flag is true. The page-key checkbox has no multipage dependency. The colours select existing colour sources; they are not RGB values.

Stored `TimeoutPage=3` is representable in memory but absent from the original options. Omitted destination preserves it and reports `timeout_page=null`, `timeout_page_raw=3`, `timeout_page_ui_canonical=false`. Explicit selections accept only the three supported destinations. Disabled nightlight flags, colour selection, standby brightness and other hidden settings are preserved when omitted.

## Save behavior and failure outcomes

The helper targets the original **direct `BeforeSavePPData(true,false)` stage**. It does not invent configuration-version initialization or instantiate all WinForms bindings. It synchronizes `Application` from the two application fields, performs the original shared functional-widget terminator/restore normalization and MRA global propagation, and calculates all five original CRCs. This includes original stored MRA standby placements and raw multiplexer 3. These changes are listed in the plan; all other parameters are preserved.

Plans carry the complete expected PP state and validated options. Apply rejects forged plan/result fields, boolean/integer substitutions, changed snapshots, incompatible identity/schema and non-database sources before writing. A successful apply reports `verified=true`, `saved=false`, `physical_device_verified=false`. Ordinary failures attempt and verify restoration only while the connection remains available. Interrupted operations retain the same `KeyboardInterrupt` or `SystemExit` object with `edlt_standby_evidence`, attempted parameters and uncertain-state details; no recovery I/O follows a direct interruption. An interruption during rollback retains the original failure in that evidence. No operation retries automatically.

## Evidence and reproduction

Original evidence is executable in [NativeEdltStandbyProbe.cs](../research/NativeEdltStandbyProbe.cs). Its 84-line getter/setter/options probe invokes the unchanged original model. Standby assertions cover the original duration list, nightlight colour list, timeout choices, twelve enable cases, twenty radio mappings and four colour-enabled combinations. Related navigation rows remain research evidence and do not imply navigation production support.

The native acceptance compares **34 full original before-save transformations**, **29,716 parameter values** and **170 CRC values**, then checks raw bytes and native PP save/close/load equality. Cases include all three timeout selections at both duration endpoints, all twelve enabled nightlight flag/colour combinations, omitted defaults, all twelve enable setter cases, disabled hidden-state retention, stored timeout 3 and MRA save normalization. The staged fixture has no device connection and remains `state=new`. Its default raw six-byte window at `0x116` is `04 29 11 E1 41 1E`; a source with both nightlight flags, quick-status colour, page 1 and 255 seconds preserves neighboring bits as `C4 39 11 E1 01 FF`.

Run the package and CLI checks with the original artifacts supplied locally:

```sh
PYTHONPATH=src:tests \
CBUS_CGATE_TEST_HOST=127.0.0.1 CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
python -m unittest tests.test_edlt_standby tests.test_cli_edlt_standby -v
```

The probe compiles and runs under pinned Mono image `mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5`, with Docker networking disabled and read-only vendor mounts. C-Gate tests create unique disposable closed database projects. Gates absent from an environment produce explicit skipped tests, never acceptance passes. Versioned counts, hashes, final Python results and local evidence paths are in [edlt-standby-acceptance.json](../research/fixtures/edlt-standby-acceptance.json). Vendor assemblies and specifications are not redistributed.
