# SCNCTL5 scene-controller documentation

The offline projector implements `TCustomSceneControllerDocumentor.DocumentHTML`
and `ActionSelectorUse` for the pinned `SCNCTL5` → `TSCNCTL5` /
`TCustomSceneControllerCGateAgent` registration, firmware `0–9`. It also projects
the inherited input scene dependencies, empty output dependencies and area-group
other dependency. An explicit matching firmware identity is required.

The report prints the control group, master-off selector and ramp, then each used
scene in its original order. Each scene contains three shared primary groups and
six secondary commands. Duplicate commands remain duplicate rows; group255
commands are omitted, and a scene containing only group255 commands is omitted.
The final table has no appended break line. Selector lookup uses `Level.Address`,
independently of `Level.Value`. Ordinary trigger links retain raw names, as the
common original formatter does.

The master-off selector is a special case: the native code calls `Level.AsString`,
which resolves to `GetExtendedTagName`. This projector uses the original fresh
`DisplayAddressValue=false` default, producing its raw tag. A Toolkit registry
preference can prepend a formatted decimal or hexadecimal address; that session
preference is not present in a saved project and is not inferred here.

The complete body requires these explicit PP arrays:

| Field | Consumed values |
| --- | --- |
| `Application` | Primary application at index0 |
| `ControlAppGroupAddress` | One group in Trigger application202 |
| `MasterOffTriggerLevel` | One selector address |
| `MasterOffRampRate`, `MasterOffCustomRampRate` | One each |
| `PrimaryGroupAddress` | Three groups shared across five scenes |
| `PrimaryGroupAddressLevel` | Fifteen levels, scene-major then primary command |
| `SceneTriggerLevel`, `SceneRampRate` | Five each |
| `SceneCustomRampRate` | One generic rate for primary commands |
| `Scene1SecondaryGroupTable` … `Scene5SecondaryGroupTable` | Six triples each: flags/rate, group, level |
| `SecondaryMasterOffEnabled` | Thirty Boolean values, scene-major |

The primary command report reads its generic `RampRate` attribute, loaded from
`SceneCustomRampRate`. The separately loaded `SceneRampRate`/Dragan attribute does
not replace that getter. The master-off rate does apply the Dragan conversion:
codes0–4 map to generic rates0,1,3,7,13; code5 uses the custom rate;255 maps to1.
The secondary generic rate is `(flags >> 3) & 15`. Primary master-off is always
enabled; secondary flags use the corresponding Boolean array entry.

`ActionSelectorUse` first emits `Scene Master Off` for a matching selector, then
`Triggers Scene N` for every matching used scene, joined with `<br />`. It does
not independently exclude control group255. Input group dependencies emit
`Scene N` for each matching command, retaining duplicates and group255 matches;
the parent group formatter changes the native `|` separators into `<br/>`.
These dependency helpers require only fields consumed by their own lookup.

Missing or short arrays, invalid values, unresolved displayed groups/selectors,
and unsupported firmware remain explicit incomplete results. The original loader
can create missing model objects and applies defaults to omitted array elements;
this read-only snapshot adapter does neither. Invalid Dragan rates enter original
exception/default paths and remain outside admission. No scene editor or physical
control support is added.

The [static receipt](../research/experiments/2026-09-30/project-documentor-scene-controller-static.json)
pins the factory, VMT methods, PP fields, indexing, conversions and formatting
branches. The [original-instruction receipt](../research/fixtures/project-documentor-scene-controller-original.json)
contains four synthetic scene models and 48 report/action/input calls. It executes
the report methods, `IsSceneUnused`, and the master-selector representation chain,
with explicit standard-format preference and synthetic leaf accessors. It does
not execute the PP loader or original GUI and is not a generated-page capture.

Run focused checks with `PYTHONPATH=src python -m pytest -q
tests/test_project_documentation_scene_controller.py` from `toolkit-cli/`.
Static reproduction uses explicit `CBUS_TOOLKIT_EXE` and `CBUS_TOOLKIT_MAP`.
Original instruction reproduction additionally requires
`CBUS_RUN_DOCUMENTOR_ORIGINAL=1` and an environment that permits Unicorn memory
execution. No bus, network service, project or hardware is accessed.
