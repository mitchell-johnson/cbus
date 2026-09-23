# Toolkit database report projection and CSV export

`toolkit-database-csv` exports an explicit captured report, the bounded original-backed cached-object projection, or one admitted native XML snapshot. Portable UTF-8 without a BOM is the default; an explicit Windows mode reproduces Toolkit's native text conversion. `cgate database-csv` acquires the snapshot directly from a live C-Gate database. Both preserve the original Toolkit 1.18.0.2754 row serializer's column order, serial text, quoting and unavailable-group placement. They do not accept arbitrary project profiles.

```sh
cbus-toolkit toolkit-database-csv capture.json --output report.csv
cbus-toolkit toolkit-database-csv capture.json --output names.csv --columns address tag_name serial
cbus-toolkit toolkit-database-csv capture.json --output native.csv --toolkit-native-encoding
cbus-toolkit toolkit-database-csv capture.json --output saved.csv --toolkit-column-selection
cbus-toolkit toolkit-database-csv capture.json --output names.csv --columns address tag_name serial --save-toolkit-column-selection
cbus-toolkit toolkit-database-csv cached.json --cached-projection --output relay.csv
cbus-toolkit toolkit-database-csv project.xml --native-xml-unit //PROJECT/254/p/4 --output native.csv
cbus-toolkit cgate --host 127.0.0.1 database-csv //PROJECT/254/p/4 --output live.csv
cbus-toolkit cgate --host 127.0.0.1 database-csv //PROJECT/254/p/4 --apply-missing-area --backup-project BACKUP --output live.csv
```

`--columns all` is the visible CLI default. Available names are `address`, `part_name`, `tag_name`, `unit_type`, `catalog`, `serial`, `firmware`, `primary`, `secondary`, `area`, and `group_1` through `group_16`. Selections are unique and always emitted in that original order. Unit order is the capture's order.

The capture has this exact schema; every unit field is required:

```json
{
  "format": "cbus-toolkit-database-report-v1",
  "units": [
    {
      "address": 7,
      "part_name": "KEYGL5",
      "tag_name": "Living",
      "unit_type": "KEYGL5",
      "catalog": "5055EDL",
      "serial": "1.2",
      "firmware": "5.00",
      "primary": "Lighting",
      "secondary": "",
      "area": null,
      "groups": [{"tag": "Ceiling", "interaction": true}]
    }
  ]
}
```

`primary` and `secondary` are captured display strings. `interaction` is the captured result of the unit's interaction-group predicate. The original base class and subclasses can provide different Area/group behavior; this API does not infer those values. Groups are ordered slots, with at most 16 entries; absent trailing slots are unavailable. Address is an integer from 0 through 255, with no inferred physical identity. All strings are limited to 256 UTF-16 code units and exclude NULs and unpaired surrogates. Captures contain at most 4,096 units and 8 MiB of strict UTF-8 JSON. Unknown or duplicate keys, floating-point numbers and unsupported nesting are rejected.

`--cached-projection` accepts one exact retained unit plus its complete retained group cache, two ordered Area provider observations where the admitted class needs them, and an explicit group-save outcome only when missing group 255 must be created. The root schema is:

```json
{
  "format": "cbus-toolkit-database-cached-projection-v1",
  "unit": {
    "identity": "unit", "address": 4, "part_name": "Owned part",
    "tag_name": "Owned unit", "unit_type": "RELAY4", "catalog": "OWNED",
    "serial": "", "firmware": "4.4", "primary": "Lighting",
    "secondary": "Secondary",
    "group_identities": ["group-1", "group-2", "group-3", "group-4",
                         "group-5", "group-6", "group-7", "group-8"]
  },
  "group_cache": [
    {"identity": "group-1", "address": 1, "tag": "G1",
     "oid": "OID-group-1", "references": []}
  ],
  "area_observations": [
    {"raw": "12", "completed": true},
    {"raw": "12", "completed": true}
  ],
  "group_save": null
}
```

Every identity referenced by the unit must occur in `group_cache`; the abbreviated example therefore needs groups 2 through 8 and Area group 12 before it will validate. Cached group identities and addresses are unique. Nonempty OID values are unique, while an empty OID is retained for legacy native projects that do not store OIDs. Unit group identities are ordered associations and may repeat: Toolkit adds every resolved programming block, including repeated group 255, to the unit group manager.

The v1 projection admits `OWNED_UNKNOWN` firmware 4.4 and case-insensitive `RELAY4` with the captured firmware values 0, 4.4, 9, 9.1 and 10. Firmware 0 through 9 selects the relay class for those captured points; 9.1 and 10 select the generic class. Relay projection uses the first six group slots, performs both ordered Area observations even when the Area column is omitted, treats invalid raw Area text as 255, moves the unit reference between Area groups, and can create missing group 255 as `<Unused>` after an explicitly successful save. Generic projection uses the first eight group slots and does not perform Area loads. `KEYE1`, `KEYE2` and `KEYE3` firmware 2.5.00 select the original `TKEYEx` class, perform both input-unit Area loads and expose the first eight of nine ordered group slots; the ninth and remaining report columns are `<N/A>`. For KEYE units, each of those first eight slots is resolved through the primary or secondary application selected by its `SecondApplicationBlocks` bit; the ninth slot always uses the primary application because the original stored mask is one byte. Same-address groups in the two applications remain distinct by OID or canonical path, and the report includes the secondary application tag. `DIMDN8` and `RELDN12` firmware 2.7.00 select `TDIMDN8` and `TRELDN12`, perform both DIN-output Area loads and retain all 16 ordered slots. Their original shared interaction predicate compares the slot to the class channel count, so DIMDN8 exposes eight and RELDN12 exposes twelve; later configured slots remain `<N/A>`. `SENPIROA` firmware 2.4.00 selects the registered `TST7SENPIROA` class, performs both input-unit Area loads and exposes all eight ordered sensor group slots through the inherited Neo interaction predicate. Provider refusal returns a partial projection in error evidence and creates no output file.

`--native-xml-unit` removes the manual cache transcription for the captured native profiles. Its input is one bounded C-Gate `DBGETXML //PROJECT` Installation snapshot and an exact unit path. It validates the project/network/unit association, optional canonical OIDs, primary application, group cache and stored PP values before invoking the same projector. When a legacy project omits unit/group OIDs, the adapter uses canonical selected paths for in-memory identity and retains an empty OID value.

The admitted RELAY4 4.4 shape has applications `56 255`, groups 1 through 8 followed by eight unused slots, and an existing Area group 12, 13 or 255. The admitted `OWNED_UNKNOWN` 4.4 shape has one application, no stored PP records and groups 1 through 8 in its application cache. The admitted KEYE1/2/3 2.5.00 shape has Area255 and nine stored group slots; its secondary application may be unused or may identify an existing application used by any mask-selected block. A nonzero mask with application255 is rejected. The admitted DIMDN8/RELDN12 2.7.00 shape has an unused secondary application, Area255 and 16 stored group slots. The admitted SENPIROA 2.4.00 shape has an unused secondary application, `SecondApplicationBlocks=0`, Area255 and eight stored group slots. Every slot is retained, so repeated unused references remain in their original positions. Other profiles are rejected. The mode is read-only and performs no network I/O; a missing Area group is rejected because the original workflow would mutate and save the database.

`cgate database-csv` validates the selected unit path and columns before connecting. It issues exactly one `DBGETXML //PROJECT` command, retains both repeated-347 and statusless tagged XML continuation lines, applies the same bounded native profile in memory, closes the C-Gate connection and only then creates the output exclusively. It does not open a C-Bus network or access a physical device. Unsupported profiles and the missing Area13 fixture stop without creating an output file. TLS and the standard C-Gate host, port and timeout options are available through the parent `cgate` command.

`--apply-missing-area` is the explicit mutation path for the exact archived B03 shape only: one RELAY4 4.4 unit, one Lighting application at 56, stored applications `56 255`, interaction groups 1 through 8, stored Area13, and existing groups 1 through 8, 12 and 255 with their captured tags. `--backup-project` is mandatory and must name a distinct new project. The manager saves and copies the source before mutation, rechecks the complete network fingerprint, creates only application-56 group13 as `Group 13`, verifies its returned OID and the absence of any other network change, saves, closes, reloads and verifies persistence before rendering the CSV. A failed target save removes the created group and verifies the original network; a lost connection leaves the named backup for recovery. If file creation or writing fails after persistence, error details explicitly report the completed mutation and backup project.

## Toolkit column selection

`--toolkit-column-selection` loads the original Toolkit form preference from the 32-bit HKCU view at `Software\Clipsal Integrated Systems\C-Bus Installation Software\3.0\Forms\frmCSVSelection`, value `CSVSelection`. A missing value uses the original `SelectAll` sentinel. Stored values are interpreted exactly like Toolkit 1.18: each of the 26 English display labels is selected when the case-sensitive substring `label + ","` occurs anywhere in the value. Unknown text is ignored, selection always returns to original ordinal order, and a value with no recognized label is rejected before source-file or C-Gate access because the original OK button is disabled for mask zero.

`--save-toolkit-column-selection` writes the effective selection to the same `REG_SZ` value before source-file or C-Gate access. The value is the original OK-handler representation: every selected display label followed by a comma. Saving all columns writes the complete label list rather than the read-time `SelectAll` sentinel. It can be combined with explicit `--columns` or with `--toolkit-column-selection` to normalize the stored value. Registry access is explicit; the default command remains registry-free and selects all columns. Both flags require Windows and force the 32-bit registry view.

The source evidence pins all 15 named selection-form methods, its module initializer, the application-manager registry-root assignment, the binary DFM form name and all 26 registered labels. The form reads before building nodes, recomputes a 26-bit mask after every node change, enables OK only for a nonzero mask, and writes the preference before the report action opens its file dialog. The Python CLI preserves that persistence-before-file/network ordering. [Review evidence](../research/experiments/2026-09-24/csv-selection-review.json) records those facts and the owned Windows registry acceptance.

## Toolkit-native Windows encoding

`--toolkit-native-encoding` is available on both offline and live commands. It requires Windows and resolves the encoder before source-file or C-Gate access. The default remains portable UTF-8. Native mode writes no BOM and uses `WideCharToMultiByte(CP_ACP, 0, ...)` with null default-character pointers, matching Toolkit 1.18's no-encoding `TStrings.SaveToFile` overload, `TEncoding.GetDefault` and `TMBCSEncoding` path. Unrepresentable text therefore follows the active Windows ANSI code page. Under the accepted CP1252 VM, one non-BMP character becomes two `?` bytes because Delphi passes its explicit two-unit UTF-16 length.

Output evidence records the active code-page number, zero conversion flags, byte count and SHA-256. Encoding happens before exclusive file creation. If encoding fails after an explicit live database mutation, the error retains the completed mutation and backup evidence without retrying the save. [Encoding review evidence](../research/experiments/2026-09-24/csv-native-encoding-review.json) pins the original writer methods and the three-test native Windows acceptance.

The original quirks are deliberate:

- Every selected header and field has a trailing comma. Each row ends in CRLF; the original handler adds a final empty line.
- Quoting is triggered only by a comma. When triggered, double quotes are doubled. A quote or newline without a comma remains unquoted, so some original outputs are not valid conventional CSV.
- Unavailable/noninteraction selected groups are appended as `<N/A>` fields after all available selected groups. Their placeholders can therefore shift relative to the headers.
- A missing Area (`null`) becomes `<Unused>`; an empty Area stays empty.
- Serial text retains ASCII digits and dots. The first dot separates an eight-character left part and four-character right part, padded with zeros but not truncated. Undotted text pads to 12 characters. `000000000000` and `010485754095` display as `No serial #`.

The pure serializer API is `document_database_csv(tuple_of_CSVUnitValues, *, columns=tuple_of_names)`. `loads_cached_projection(bytes, columns=...)` validates and executes the bounded cached projection; `project_cached_csv_unit(...)` is its typed API. Columns are mandatory. Inputs and results are immutable snapshots, and projection results include ordered events, terminal group/reference state, the selected original class and any stop reason. The package requires no original binaries for these operations.

File export validates the complete capture and bounded encoded output before exclusive destination creation. It rejects existing output files and requires a regular source whose pre-open, opened-handle and post-open identities agree. It writes at most 32 MiB, handles partial writes, flushes with `fsync`, and closes once. An error after creation leaves the file in place with explicit possible-partial-output evidence; there is no replay or cleanup deletion. Evidence retains confirmed write counts and the first exception through secondary close/report failures. Parent-directory durability remains outside this acceptance.

The original executable is pinned to SHA-256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`. The [literal fixture](../research/fixtures/toolkit-database-csv-original-vectors.json) retains 88 original observations: 73 row cases and 15 quote cases. Seventy row cases and 13 quote cases are within the public API's domain; empty/high masks and NUL behavior remain research evidence. The fresh original probe executes 18 allowlisted, byte-checked instruction spans with explicit cached providers and string-runtime fixtures. It does not execute the PE entrypoint, constructors, native imports, database projection, original exception unwinding or the Windows file writer.

Original `TStrings.SaveToFile` selects the Windows default code page. Static analysis pins the complete report action, both `SaveToFile` and `SaveToStream` overloads, `TEncoding.GetDefault`, the CP_ACP constructor, byte-count/conversion methods and empty preamble. Native Windows execution verifies the production path against CP1252, including the surrogate-pair replacement edge. UTF-8 remains the portable default. This feature does not establish network-scan admission or automatic project-to-row projection.

The [focused acceptance fixture](../research/fixtures/toolkit-database-csv-acceptance.json) records the historical 23 tests passing without skips on Python 3.13.14 and 3.10.20, including a fresh 88-case original observation in each run. Exact source/test/runtime inputs were archived before execution. The current host selection passes 63 serializer/projection/Area/CLI tests. Five separate adapter tests on macOS execute two platform guards and declare three native cases skipped. The owned Windows VM passes two native registry and three native encoding tests on Python 3.13.14, including missing-value default, 32-bit `REG_SZ` roundtrip, wrong-type rejection, CP1252 conversion, exact production output evidence and cleanup. File tests cover Unicode, no-overwrite behavior, source-path replacement, partial writes, lost creation return, `fsync`/close failure and first-interruption preservation. The research launcher retains partial process output on timeout/interruption and records process reaping. The first Python 3.10 attempt stopped before original execution because its environment lacked Capstone; that attempt and earlier successful source versions remain preserved.

Fresh original tests require the optional `research` extras (including pinned `capstone==5.0.7`) and `CBUS_TOOLKIT_EXE` naming the exact original executable. Their current native-library pins and network-denial harness are macOS-specific. Portable formatter and file tests do not require an original executable.

## Database projection research

The backend research now has [eight completed original cases](../research/experiments/2026-09-24/csv-original8-analysis.json) and [four completed native database captures](../research/experiments/2026-09-24/csv-native4-analysis.json). The native captures check all 21 RELAY4 parameters, exact whole-project XML preservation and 30 literal path/OID reads across three relay fixtures; a fourth fixture covers generic scalar metadata without programming. Missing Area group 13 remains absent during read-only native observation. All 473 archived inputs were unchanged; the owned C-Gate process and temporary storage were removed with no CNI connections.

The first current native attempt exposed a path-key mismatch after the vendor directory moved. The corrected harness resolves that path, validates the distinct GET_UNIT_SPEC framing and checks its exact SourceSpec provenance field before comparing the remaining parameter definitions. The failed attempt is preserved.

The [first original replay of those native captures](../research/experiments/2026-09-24/csv-replay-partial.json) completed the existing-group B01/B02 cases. B03 stopped at an unadmitted original method and B04 was not attempted. The failed capture, 77 stable archived inputs and confirmed child cleanup remain preserved.

The [successor replay](../research/experiments/2026-09-24/csv-replay-complete.json) closed that bounded path with five byte-pinned original methods and a source-backed standard-application descriptor for application 56 / group label `Group`. All four native fixtures were captured through 27,661 approved original instruction entries. B01 resolved Area12, B02 resolved existing `<Unused>` Area255, and generic B04 returned nil without QuickGet or storage activity. Missing-group B03 allocated exactly one group at address13, assigned `Group 13` through the original lookup path and stopped at the explicitly refused `GroupSave`; it is not presented as a successful persisted save. The launcher verified all 473 historical native archive inputs, kept inputs and loaded runtime sources unchanged, denied network access and made no native or VM call.

The production cached projector now implements the separate twelve-case cached-object pilot: ten completed original outcomes and two declared provider stops. It covers class selection at the captured firmware boundaries, six-versus-eight interaction groups, two ordered Area loads, changes between getters, invalid Area fallback, reference movement, group255 creation/save and selected-column behavior. Static VMT and agent analysis adds `TKEYEx`: KEYE1/2/3 firmware 2.5.00 retain all nine group associations, including repeated unused slots, use the inherited eight-slot interaction predicate and run the input-unit Area getter. The secondary-association analysis pins the original one-byte block mask, primary/secondary group-manager selection and ordered append; the native adapter now retains colliding group addresses from both applications as distinct identities and projects the selected application tag and group label. A read-only sweep projected all 22 matching units in the unchanged GRENACHE VM snapshot, including its legacy OID-less records. Static class, VMT and DIN-agent analysis also admits DIMDN8/RELDN12 firmware 2.7.00. Their loader retains all 16 group associations; the inherited interaction predicate calls each class's 8/12-channel maximum. A read-only sweep projected all four matching GRENACHE units, including configured values in RELDN12 slots 13 and 14 that correctly remain unavailable in the report. SENPIROA factory, VMT and inherited load-chain analysis admits firmware 2.4.00 as `TST7SENPIROA`; it retains eight ordered group associations and uses the inherited input Area getter and eight-slot Neo interaction predicate. The one matching GRENACHE unit projects read-only. The native XML adapter also projects B01, B02 and B04 from unchanged archived C-Gate snapshots. The guarded live manager completes B03 by backing up, creating `Group 13`, saving, reloading and exporting Area `Group 13`. The original column preference is implemented with explicit 32-bit HKCU access, and the original file conversion is available through explicit native encoding. The current core/CLI CSV set passes 65 tests, the two host Windows guards pass, five owned Windows native tests pass, and the separate owned C-Gate acceptance passes against the pinned 3.4.0.2001 service with zero CNI connections and complete cleanup. The compact [secondary-association review](../research/experiments/2026-09-24/csv-keye-secondary-application-review.json), [SENPIROA review](../research/experiments/2026-09-24/csv-senpiroa-profile-review.json), [DIN review](../research/experiments/2026-09-24/csv-din-profile-review.json), [KEYE review](../research/experiments/2026-09-24/csv-keye-profile-review.json), [cached implementation review](../research/experiments/2026-09-24/csv-cached-projection-review.json), [native XML review](../research/experiments/2026-09-24/csv-native-xml-projection-review.json), [live C-Gate review](../research/experiments/2026-09-24/csv-live-cgate-review.json), [missing-Area review](../research/experiments/2026-09-24/csv-missing-area-review.json), [selection review](../research/experiments/2026-09-24/csv-selection-review.json) and [encoding review](../research/experiments/2026-09-24/csv-native-encoding-review.json) pin the source analyses and admitted limits.

Secondary-application group association is implemented for the admitted KEYE1/2/3 profile. Secondary association for other unit families, remaining unit profiles and physical behavior remain outstanding. The cached-input mode still begins after cache records and provider outcomes have been captured explicitly. Native XML admits only the documented RELAY4, generic, KEYE, two DIN and SENPIROA shapes, and mutation is limited to exact B03 with an explicit backup.
