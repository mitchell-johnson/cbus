# eDLT display preferences and DLTP icon index

Two eDLT inputs live outside the project `DBGETXML` snapshot: the registry
display/sort preferences that shape application, group and level lists, and
Toolkit's local DLTP icon index that gives `ICON` dynamic labels an image.
`edlt_display_model.py` and `edlt_dltp_index.py` model both from the retained
Toolkit 1.18 `CBusLogicModel` source. Neither module reads the Windows
registry, decodes or renders an image, or programs a unit.

## Display and sort preferences

`GlobalSoftwareParameters.UpdateValues` reads five DWORDs from
`HKCU\Software\Clipsal Integrated Systems\Global\Preferences\`:
`DisplayHexAddress`, `DisplayAddressValue`, `SortModeApplications`,
`SortModeGroups` and `SortModeLevels`. A flag is true only when its value
exists and the C# `(int)` cast of the DWORD is greater than zero, so
`0x80000000` and `0xFFFFFFFF` are false. When the key is absent, all five
flags keep their static default of false.
`EdltDisplayPreferences.from_registry` applies exactly these rules.
`from_toolkit_display_values` adapts the five display values from the Toolkit
preference store.

`CBusBaseObject.ReadXmlData` builds `FormattedDisplay` as follows:

1. With `DisplayAddressValue`, it appends the stored address text left-padded
   with `0` to three characters.
2. With `DisplayHexAddress`, it appends `" (" + AddressAsInt.ToString("X")`
   left-padded to two digits `+ "h)"`. `AddressAsInt` is `int.TryParse`, or
   zero.
3. A nonempty prefix is trimmed and followed by `" - "`. `TagName` is then
   appended.

For example, address 10 produces `Kitchen`, `010 - Kitchen`, `(0Ah) - Kitchen`
or `010 (0Ah) - Kitchen`.

`CBusNetwork`, `CBusApplication` and `CBusGroup` sort their application, group
and level lists with the matching `SortMode*` flag. When the flag is true, the
lists are sorted by ascending `AddressAsInt`. When it is false, `List.Sort()`
uses `CBusBaseObject.CompareTo`, which compares `TagName` values with
`OrdinalIgnoreCase`. That comparison upper-cases characters first, so `_`
sorts after `Z`. After sorting, the group list prepends the in-memory
`<Unused>` group 255. This object bypasses `ReadXmlData` and always displays
`<Unused>`. `CBusLevel.Compare` exists but is not used by `List.Sort()`.
`List.Sort` is unstable, and the source does not fix the relative order of
names that are equal apart from case. The model keeps such ties in DBGETXML
order and lists them in `case_insensitive_name_ties` in the plan evidence.
ASCII case comparison is exact. Other characters use a one-character
uppercase mapping.

The automatic `parent-transaction-plan --project-xml`, `edlt-parent-transaction
--auto-metadata`, `scene-manager-plan`/`scene-manager-state --project-xml` and
`edlt-scene-manager --auto-metadata` workflows accept
`--display-preferences FILE`. The file uses this format:

```json
{"format": "cbus-edlt-display-preferences-v1",
 "registry_key_present": true,
 "values": {"DisplayHexAddress": 1, "SortModeGroups": 1}}
```

An omitted value means that the registry value is absent.
`"registry_key_present": false` requires an empty `values` object.
Supplied preferences recompute `formatted_display` and list order from each
cached address and exact `TagName`, including projected creations. The
original also re-reads and re-sorts objects after an auto-add. Lifecycle facts,
identities, completeness and plan values are unchanged.

When `--display-preferences` is omitted, the current behavior remains the
default. The workflow uses the `TagName` view in DBGETXML child order and
reports `toolkit_display_preferences_supplied=false`. This is not the
original's absent-registry view, which sorts names case-insensitively. To use
that view, supply a document with no values. Evidence always reports
`toolkit_registry_display_and_sort_preferences_observed=false` because the CLI
never reads a registry.

`cbus-toolkit edlt display-lists --project-xml FILE --network N
[--display-preferences FILE]` is a read-only view of one network's application
list, group list for each application and level list for each group. Without a
document, it applies the original's absent-registry defaults.

## DLTP icon index

`CBusNetwork.LoadChineseCharacterImages` reads
`Images\DLTP\Index.txt` under the application directory. It parses lines as
`N,Name,file.bmp` and stops at the first error, but keeps the rows already
read. `TagDLT.PopulateImage` gives an `ICON` variant an image when the index
key's `ToString()` equals `TagValue` exactly, so `07` or ` 7` does not match
key 7.

`load_dltp_index(app_dir, expected_sha256=...)` binds the index bytes to a
caller-supplied SHA-256. It resolves `Images`, `DLTP`, `Index.txt` and every
image name case-insensitively and requires exactly one regular, non-symlink
match for each. The pinned Toolkit install stores `index.txt` in lowercase.
The loader is stricter than the original's partial-prefix behavior. It rejects
the following inputs:

- a BOM, NUL or invalid UTF-8;
- empty lines or rows that do not have three fields;
- keys that are not canonical non-negative Int32 values;
- empty names or names containing control characters;
- file names that are not bare `.bmp` names;
- duplicate keys or case-insensitively duplicate files; and
- missing images or images that do not start with `BM`.

Image hashes are recorded, but the images are not decoded.

The automatic workflows accept `--toolkit-dltp-dir APP_DIR
--toolkit-dltp-sha256 HEX` as a pair. When they are supplied, `ICON` variants
resolve into the four-variant `image_present` facts for parent groups and
SceneManager action levels. Plans report `icon_dynamic_labels_resolved` and
the `toolkit_dltp_index` hash, row count and keys. Native managers retain the
same index for stale-source checks, creation verification and rollback
reloads. `DYNAMIC` and `FONT` variants still depend on project image downloads
and still fail closed when consumed. The model assumes the original's
image-loading path, in which the eDLT editor loads project and DLTP images.

The Toolkit 1.18.0.2754 index has SHA-256
`c6cca64deaed7bb5ad814b2aaf4c37b580396bf38c057aae8bd616fadfd26310`, 91 rows and
keys 1..91. Tests pin only that fact and skip it when the private install is
absent. The vendor index and BMP files are never committed.

## Evidence

`tests/test_edlt_display_model.py` covers the following cases:

- all 32 flag combinations against hand-written strings and orders;
- registry DWORD edge cases;
- case-insensitive ties and stable ordering;
- idempotent cache presentation;
- the read-only list command; and
- threading through the parent and SceneManager resolvers and CLI.

When the private decompiled source is present, the tests also pin the SHA-256
hashes of the modeled source files and their line ranges.

`tests/test_edlt_dltp_index.py` covers the following cases with a synthetic
index:

- strict parsing, SHA binding and case-insensitive resolution;
- exact `TagValue` matching;
- parent and SceneManager `ICON` resolution;
- continued `DYNAMIC`/`FONT` refusal; and
- a native-manager apply that keeps the index through reload verification.

No original Toolkit UI list, rendered icon or physical display was observed
for this slice.
