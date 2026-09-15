# eDLT Quick Status

`EdltQuickStatus` configures Quick Status for **KEYGL5 / 5055EDL / firmware 5.5.00**. It edits a database programming session and verifies its complete PP snapshot against the planned result. These are settings for the whole unit; applying a plan does not save it or transfer it to hardware.

```python
from cbus_toolkit.edlt_quick_status import EdltQuickStatus

editor = EdltQuickStatus(spec)
plan = editor.plan(session.values(), mode='page-key', group=42,
                   low_threshold=85, high_threshold=170,
                   low_colour='red', middle_colour='yellow', high_colour='green')
result = editor.apply(session, plan)
session.save_to_source()  # explicit database persistence
```

`plan(current, *, mode=None, group=None, low_threshold=None, high_threshold=None, low_colour=None, middle_colour=None, high_colour=None)` returns an immutable `QuickStatusPlan`. `snapshot`, `crcs`, `apply` and `configure` follow the other eDLT helpers. The plan includes raw values, effective values, palette and threshold metadata, save normalizations and changed parameters.

| Option | Explicit values | Original PP layout |
| --- | --- | --- |
| `mode` | `off`, `page-key`, `background`, `text` = 0..3 | `QuickStatusMode`, bits 3..5 of `0x116` |
| `group` | Integer 0..254 | `QuickStatusGroup`, `0x125`, on `PrimaryApplication` |
| `low_colour`, `middle_colour`, `high_colour` | Names from the resulting mode's palette | `QuickStatusColour1/2/3`, `0x126..0x128` |
| `low_threshold`, `high_threshold` | Integer byte requests 0..255, using linked control behavior below | `QuickStatusLevel1/2`, `0x129..0x12A` |

Defaults are off, group 255, red/yellow/green, and thresholds 85/170. The original labels describe the first colour as applying below the low threshold, the second below the high threshold and the third otherwise. This helper does not simulate the display firmware.

Off and page-key use `none, white, red, green, blue, cyan, magenta, yellow, orange` (codes 0..8). Background and text use `black, white, red, green, blue, cyan, magenta, yellow` (codes 0..7). Explicit colour selections are validated against the resulting mode. The group, colour and threshold controls remain editable in off mode; only the mode selector itself has the original enabled-checkbox binding. The original checkbox's enabled=true setter always sets mode 1, including when another active mode was previously selected.

## Linked threshold edits

The helper executes requests in **low-then-high order**, matching successive calls to the original `LevelControl.SetValue`. A changed low request is clamped to 0..254, and a changed high request to 1..255. Each can adjust the other control. An equal request returns before clamping. If the controls were equal before an edit, the original attempts to move them together. Consequently the helper does not sort stored values or enforce a new strict-order rule.

| Starting low/high | Requested edits | Result |
| --- | --- | --- |
| 85 / 170 | low=170 | 170 / 171 |
| 85 / 170 | high=85 | 84 / 85 |
| 85 / 170 | low=255, then high=0 | 0 / 1 |
| 85 / 85 | low=86 | 86 / 86 |
| 85 / 85 | low=85, then high=170 | 170 / 170 |
| 170 / 85 | low=170 | 170 / 85 |
| 255 / 255 | low=255, then high=255 | 255 / 255 |

The plan reports effective thresholds, differing requested values, whether they are strictly ordered and whether they fit the individual controls' bounds. Tests compare 168 single-edit and 49 sequential-edit vectors from the unchanged original WinForms controls, including values outside the CLI's accepted byte request range for source characterization.

## CLI

```sh
cbus-toolkit edlt quick-status-plan parameters.json \
  --mode page-key --group 42 --low-threshold 85 --high-threshold 170 \
  --low-colour red --middle-colour yellow --high-colour green

cbus-toolkit cgate --host 127.0.0.1 --port 20023 unit \
  --lock-address //MYPROJ/254 --source /db//MYPROJ/254/p/20 \
  edlt-quick-status --mode off --group 42
```

`--dry-run` on `unit` performs planning and PP verification without saving the database source. Normal execution saves and reports the resulting parameters. Threshold edit order is low then high regardless of CLI flag order. All seven settings are optional; an omitted threshold can still move when its linked control is edited. Invalid palettes and group 255 are rejected before applying changes. Physical destinations are rejected.

## Groups and stored values

The actual original `ComboBoxAddEdit`, bound to QuickStatusGroup, excludes group 255 from its choices. The synthetic cached list `[255, 0, 254, 7]` yields `[0, 254, 7]`. With the original binding's disabled value -1, the control remains enabled when its PP value is 255. A missing cached group can normalize the bound getter to 255; the original normal lookup can also create applications or groups.

The Python helper deliberately provides numeric group assignment without cached lookup or group creation. It preserves an omitted 255, reports `primary_application`, and leaves group metadata unverified. It does not claim a requested address exists in the project.

Omitted mode codes 4..7 and omitted out-of-palette colours are preserved by the original model and save-stage comparison. Plans mark these as noncanonical UI values. An explicit mode change does not invent a replacement colour for an omitted stored orange 8. Subsequent [original Windows control probes](edlt-quick-status-windows.md) confirm preservation across all three colour properties in 416 sampled cases: the palette refreshes, while an out-of-palette stored value produces a blank selection and survives validation. The earlier isolated Mono harness did not refresh its nested source automatically. The existing global `windows_palette_transition_verified` flag remains false because the new Windows evidence is explicitly bounded to the recorded values and transitions; the preservation policy is unchanged.

## Validation, preservation and failures

The helper checks the exact device profile and parameter layouts, all static references, a canonical reconstruction of the plan and the complete current PP snapshot before editing. It preserves other programming fields except original save-stage normalization: blank/terminator placement, associated changed-type RestoreLevel resets, the Application mirror and propagation of existing MRA globals. Stored MRA multiplexer bits and standby placements are preserved. All five original CRCs are recalculated. The plan exposes these changes separately.

Applying verifies the complete PP readback. An ordinary error rolls back attempted parameters while the C-Gate connection remains synchronized. A lost connection stops recovery I/O. KeyboardInterrupt or SystemExit preserves the original interruption, attaches `edlt_quick_status_evidence` and performs no retry. An interruption during rollback retains the preceding error. A physical session is rejected and `physical_device_verified` remains false.

## Evidence and reproducibility

[NativeEdltQuickStatusProbe.cs](../research/NativeEdltQuickStatusProbe.cs) calls the unchanged original EDLT model, linked WinForms controls, cached group control, save hook and CRC routine. The cached objects come from the explicit, network-free [cached-group fixture](../research/NativeEdltCachedGroupProbe.cs); its no-create settings are fixture policy. No network or hardware is available inside the probe container.

The exact local source audit uses `EDLTUnit.cs` Quick Status properties and binding construction; `FrmBaseUnit.cs` control bindings, palette sources and control linkage; `LevelControl.cs` SetValue; `ComboBoxAddEdit.cs`; and `KEYGL5.xml`. Vendor files are not distributed. The pinned Xvfb Mono image is `sha256:23a8bfba16d732eff819f71edeec551e84e576eab40a15ec9e97018f649fb568`. The harness supplies the initialized model before constructing child BindingSources because Mono fails the original form's type-placeholder-to-instance initialization order; this difference is explicitly excluded from Windows UI equivalence claims. Normal edits use `PPAttribute.bInitialiseMode=false`, allowing original property notifications; initialization mode is limited to initial full-PP setup. Palette probes with either initialization setting retain the same Mono limitation.

Run `tests.test_edlt_quick_status` and `tests.test_cli_edlt_quick_status` with `CBUS_CGATE_TEST_HOST`, `CBUS_UNITSPEC_DIR` and `CBUS_TOOLKIT_EXE` pointing at an isolated native oracle and local vendor files. The native test uses a unique closed database network, compares all 874 PP fields and five CRCs for mode/colour boundaries, linked edits, omitted raw values and MRA propagation, then checks raw bytes and database save/close/load equality. It does not invoke the separate AfterLoad initialization lifecycle and uses configuration version 1.0. The [compact acceptance artifact](../research/fixtures/edlt-quick-status-acceptance.json) records source hashes, literal raw results and interpreter runs.

Final focused acceptance passed **11 tests with zero skips** on Python 3.13.14 (68.210s) and Python 3.10.20 (73.998s). All 26 native case records, original-control output and CLI reports were identical across both interpreters.
