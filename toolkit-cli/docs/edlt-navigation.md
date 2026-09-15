# eDLT navigation settings

`EdltNavigation` implements navigation page modes, the nine display variants, temperature references and four page-label references for **KEYGL5 / 5055EDL / firmware 5.5.00**. It uses the caller's original `KEYGL5.xml` and a native database PP session. It preserves hidden functional widgets and reports dynamic-label metadata separately from physical verification.

```python
from cbus_toolkit.edlt_navigation import EdltNavigation

editor = EdltNavigation(spec)
plan = editor.plan(values, page_mode='multiple', variant='page-names',
                   page_names={1: 'Kitchen', 2: 'Living', 3: '', 4: 'Upstairs'})
result = editor.apply(session, plan)  # verifies staged PP state
session.save_to_source()             # explicit database save
```

`.configure(session, **options)` checks identity, reads, plans and applies. `.snapshot(values)` and `.crcs(values)` use the shared bounded profile codec. All plan arguments are optional:

| Argument | Original field(s) | Values and dependencies |
|---|---|---|
| `page_mode` | `NavWidgetType` | `single=0`, `multiple=1` |
| `variant` | `NavWidgetVariant` | `time=0`, `date=1`, `time-date=2`, `time-temperature=3`, `date-temperature=4`, `logo=5`, `page-names=6`, `dynamic-labels=7`, `blank=15` |
| `temperature_source` | `TemperatureApplication` | `measurement=0`, `hvac=1`; variants 3/4 |
| `device_or_group` | `NavDevIDZoneGroup` | Measurement device 0..255 or HVAC application 172 group reference 0..255; variants 3/4 |
| `channel_or_zone` | `NavChannelZoneNumber` | Measurement channel 0..255 or HVAC zone 0..4; variants 3/4 |
| `dynamic_group` | `DynamicGroup` | Primary-application group reference 0..255; logo/dynamic-label variants |
| `page_names` | `PageNameIndex1..4`, shared strings | Mapping of pages 1..4 to text; page-names variant |
| `page_name_indices` | `PageNameIndex1..4` | Static index 0..63 or blank 255; dynamic index 0..3 requires supplied metadata |
| `metadata` | No PP field | Caller-supplied cached group/variant evidence; schema below |

Navigation controls are available on the multiple-page navigation row. To edit them from single-page mode, select `page_mode='multiple'` in the same plan. Mode-only changes preserve stored widget records and restore levels, including the functional widgets hidden by single-page mode. The original `MultiPage` getter normalizes stored values above 1 to 0; this navigation workflow reproduces that getter before editing. Existing unoffered navigation variant codes are preserved when omitted and reported with `variant_ui_canonical=false`.

Changing to `page-names` clears all four indexes to **255** before requested selections. Changing to `dynamic-labels` resets all four to **0**. Reassigning the same variant preserves indexes; other variant changes preserve them. Requested text/index changes execute in ascending page order. The original allocator reuses an exact string or chooses the highest unused slot while counting current references, including the current page reference until its setter completes. Whitespace-only names clear the reference; other text must be valid UTF-8, contain no NUL and fit 63 UTF-8 bytes. Different text and index instructions for the same page are rejected.

Temperature, dynamic-group and label fields remain unchanged when their controls are hidden and omitted. Switching the temperature source alone preserves the stored channel/zone, as the original model setter does; a stored HVAC zone above 4 is reported with `temperature_channel_ui_canonical=false`. An explicit zone edit must be within 0..4. This targets the original model/property stage rather than instantiating every WinForms data binding.

## Dynamic metadata

A plan may receive this JSON object directly or through `NavigationMetadata.from_dict(...)`:

```json
{
  "format": "cbus-edlt-navigation-metadata-v1",
  "groups": [
    {"application": 56, "group": 42, "dynamic_variants": [0, 1, 2, 3]},
    {"application": 172, "group": 7, "dynamic_variants": []}
  ]
}
```

Records are unique by application/group, with strict integer addresses 0..255, at most 512 records and at most four unique variant indexes 0..3. Unknown fields and malformed records are rejected. Group 255 requires an empty variant list. A matching metadata record is evidence supplied by the caller; it is not refreshed or authenticated by the helper.

Explicit dynamic page-index selections require a matching current primary-application/group record, a group other than 255 and availability of each requested index in that record. Missing metadata, another group/application, an empty list or unavailable index causes a preflight failure. Group-reference edits and original reset/default preservation can proceed without metadata, with an explicit `unverified` status. Omitted stored indexes are retained even when metadata is unavailable. No groups, tags, images or labels are created or uploaded.

The original cached-object probe confirms the dynamic selector exposes variants 0..3 for a known group. Missing and unused groups expose no variants. The original navigation group lists include `<Unused>` 255, although its dynamic selector is empty; HVAC's list also includes 255. Logo references use variant 0 only. Dynamic-label references do not imply that text or image content exists on a device.

JSON reports `metadata_provenance='caller-supplied-cache'`, group status (`caller-cache-match`, `missing-from-caller-cache`, `unused` or `unverified`) and available variants. `physical_dynamic_labels_verified` and `physical_device_verified` remain false. Time, temperature, logos and rendered labels are not observed by this database workflow.

## CLI

```sh
cbus-toolkit edlt navigation-plan parameters.json --page-mode multiple \
  --variant page-names --page-name 1 Kitchen --page-name 2 Living

cbus-toolkit cgate unit --lock-address //PROJECT/254 \
  --source /db//PROJECT/254/p/20 --dry-run edlt-navigation \
  --page-mode multiple --variant dynamic-labels --dynamic-group 42 \
  --page-name-index 1 3 --page-name-index 2 0 --metadata group-cache.json
```

Remove `--dry-run` to apply and save through the native database workflow. Other options are `--temperature-source`, `--device-or-group` and `--channel-or-zone`. Repeated page options reject duplicate page numbers; the metadata file rejects duplicate JSON keys and is limited to 256 KiB. A programming `--destination` remains restricted to database targets. The CLI validates option and metadata syntax before loading a programming session.

## Save normalization and failures

Plans include the complete expected PP state, immutable selections, individual static allocations and all changes. Apply re-derives the canonical plan, rejects forged result types (including boolean/integer substitutions), stale PP values, incompatible schema/identity and non-database sources. It verifies full native PP readback after staging changes. An apply result says `verified=true`, `saved=false` until an explicit save is performed.

The workflow synchronizes `Application`, applies the shared original functional terminator/restore normalization and MRA global propagation, and calculates all five original configuration CRCs. Other widgets, scenes, opaque bits and unrelated globals are preserved. The native differential uses canonical stored scene records and the original model's direct before-save stage; it does not claim every whole-dialog loading or scene-compaction side effect.

Ordinary staging failures attempt and verify restoration only while the connection remains available. Direct `KeyboardInterrupt`/`SystemExit` retains the same exception object and `edlt_navigation_evidence`, listing attempted parameters and uncertainty, with no recovery I/O. An interruption during rollback retains the original failure too. There is no automatic retry or save after failure.

## Independent evidence

[NativeEdltNavigationProbe.cs](../research/NativeEdltNavigationProbe.cs) invokes unchanged original model methods, including the real variant-change notifications, shared allocator, scene loader, before-save stage, memory serializer and CRC methods. [NativeEdltCachedGroupProbe.cs](../research/NativeEdltCachedGroupProbe.cs) constructs owned original cache objects and invokes original selectors with automatic additions disabled. Both execute under pinned Mono with Docker networking disabled; no physical endpoint is opened.

The model probe emits 84 option/getter/setter rows. Navigation assertions cover mode normalization and all nine conversion/same-variant cases. Two independent capacity vectors prove that 61 real references plus Measurement sentinel 64 and unused 255 allow allocation at 63, while 62 real references plus both sentinels reject it. The cached fixture emits 46 rows, including the group lists, measurement 0..255 choices, HVAC zones 0..4, dynamic choices and missing/unused cases.

The native differential compares **30 full transformations**, **26,220 parameters** and **150 CRC values**, checks the raw navigation window `0x200..0x208`, and saves/closes/reloads the database. The fixture contains eight canonical empty scene records `02 00 FF FF FF` and explicit cached Trigger metadata. Those scene values remain equal throughout. Sixteen valid Time widgets in slots 6..21 prove single/multiple changes retain hidden widgets, restore values and an opaque final byte.

On the original native fixture, Kitchen already occupies static slot 26. Pages Kitchen / Unique B / Unique B / Unique D produce indexes 26/63/63/62 and raw bytes `01 06 00 00 00 1A 3F 3F 3E`. Same-variant reuse and clearing produce `01 06 00 00 00 3E FF 3F 3E`. These literals are compared against the original assembly and native PP state, not generated from the helper as the sole oracle.

```sh
PYTHONPATH=src:tests \
CBUS_CGATE_TEST_HOST=127.0.0.1 CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
python -m unittest tests.test_edlt_navigation tests.test_cli_edlt_navigation -v
```

Missing artifact gates are explicit skips, never acceptance passes. Final dual-Python results, hashes, scope and local report paths are recorded in [edlt-navigation-acceptance.json](../research/fixtures/edlt-navigation-acceptance.json). Vendor binaries and specifications are not redistributed. This helper does not establish full Toolkit parity or physical navigation/display behavior.
