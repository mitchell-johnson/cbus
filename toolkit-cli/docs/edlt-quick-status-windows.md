# Quick Status: original Windows binding evidence

The original Windows controls preserve omitted stored colours when a mode change removes those colours from the palette. Their nested `BindingSource` objects refresh correctly on Windows. An out-of-palette colour remains in the model while its ComboBox shows no selection. This supports the Python helper's existing preservation behavior; no programming policy changed as a result of this research.

The [acceptance report](../research/fixtures/edlt-quick-status-windows-acceptance.json) and [complete raw vectors](../research/fixtures/edlt-quick-status-windows-vectors.txt) keep the Windows results separate from the earlier Mono and native PP tests. These are controlled original-model and WinForms observations, not a physical-device test or a complete Toolkit-dialog test.

## Tested states

The [exact tested palette harness](../research/NativeEdltQuickStatusPaletteProbe.cs) creates all three original colour bindings with independent nested sources. It uses the original form's type-placeholder-to-model initialization, `FormattingEnabled=true`, and colour 2 → 1 → 3 construction and validation order. Normal edits use `PPAttribute.bInitialiseMode=false`.

| Dimension | Coverage |
| --- | --- |
| Properties | `QuickStatusColour1`, `QuickStatusColour2`, `QuickStatusColour3` |
| Initial mode | Every stored mode 0–7 |
| Requested mode | Off 0, page-key 1, background 2, text 3 |
| Initial colour | Every code 0–9, plus 39, 254 and 255 |
| Cases | 416 forms, observing 1,248 property transitions |
| Observation stages | Initial binding, mode change, then `Validate` and explicit binding `WriteValue` |

All three colours start at the sampled value in each broad case. Every observed model colour stays unchanged through all stages. Modes 0/1 expose codes 0–8; other stored modes expose 0–7. A code outside the current palette yields `SelectedIndex=-1` and `SelectedValue=null`. Returning to a palette containing the stored code restores its selection without changing the stored value.

For example, stored orange 8 in mode 1 remains 8 when mode 2 is assigned, while its selection becomes blank. Changing mode 2 to mode 1 restores selection 8. Stored 255 remains 255 and unselected in both palettes. Explicit validation does not replace these stored values with zero or another colour.

The current Python planner was independently run for all 416 cases. Its three final colour values matched all 1,248 original Windows observations. The implementation's preservation rule required no change.

`tests.test_edlt_quick_status_windows` retains this comparison as two local tests using the pinned captured vectors, with no VM or vendor runtime required. They also compare all 217 linked threshold vectors. Both tests passed without skips on Python 3.13.14 (27.791s) and Python 3.10.20 (35.014s). The companion vector `.txt` and acceptance JSON must accompany that test in isolated test snapshots.

## Other original controls

The unchanged [earlier probe](../research/NativeEdltQuickStatusProbe.cs) also ran as a Windows x86 executable. Its nine actual cached-group ComboBox cases, 49 low-then-high threshold cases and 168 single LevelControl cases matched the recorded Mono results exactly. Its 60 palette cases were repeated with the original formatting/initialization order and produced identical Windows outcomes.

The group control excludes address 255 from its displayed choices; missing cached groups can normalize to 255. These observations do not change the Python helper's numeric group assignment policy or establish project group metadata.

## Provenance and limits

The jobs ran through the owned Windows file-job bridge using exact Toolkit 1.18.0.2754 assemblies, including CBusLogicModel 7.14.0.0 and eDLT 7.16.0.0. Fresh hashes matched all 25 pinned original files and all 24 original DLL copies used by the isolated probe. The report pins the source, executable/job output and raw-vector hashes. The process was x86 under CLR `4.0.30319.42000`; the guest reported build 26100, version 24H2.

A later [read-only runtime probe](../research/NativeEdltQuickStatusRuntimeProbe.cs) on that guest hashes actual loaded assembly locations and `clr.dll`. Its [literal transcript](../research/fixtures/edlt-quick-status-windows-runtime.txt) records mscorlib and CLR 4.8.9345.0, Windows Forms 4.8.9325.0, System 4.8.9340.0 and System.Core 4.8.9347.0, plus the same original model/control DLL hashes. This is a separate provenance observation; these files were not hashed inside the earlier palette processes.

No Toolkit installation, existing project, native C-Bus connection, controller or live device was used by these probes. The model fixture initializes only the fields needed for the original controls, and the cached-group fixture explicitly prevents creation or network work.

This remains a finite sample: colours 10–253 other than 39 were not tested, and requested transitions to raw modes 4–7 were not tested. The complete Toolkit form, every control interaction and physical display rendering remain outside this evidence. The existing global `windows_palette_transition_verified` flag has therefore not been changed to an unconditional true value.
