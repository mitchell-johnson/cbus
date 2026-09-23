# Toolkit database report projection and CSV export

`toolkit-database-csv` exports either an explicit captured report or the bounded original-backed cached-object projection as UTF-8 without a BOM. It preserves the original Toolkit 1.18.0.2754 row serializer's column order, serial text, quoting and unavailable-group placement. It does not read arbitrary project XML or cold-load a Toolkit database.

```sh
cbus-toolkit toolkit-database-csv capture.json --output report.csv
cbus-toolkit toolkit-database-csv capture.json --output names.csv --columns address tag_name serial
cbus-toolkit toolkit-database-csv cached.json --cached-projection --output relay.csv
cbus-toolkit toolkit-database-csv project.xml --native-xml-unit //PROJECT/254/p/4 --output native.csv
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

Every identity referenced by the unit must occur in `group_cache`; the abbreviated example therefore needs groups 2 through 8 and Area group 12 before it will validate. Cached group identity, address and OID values must be unique. The v1 projection admits `OWNED_UNKNOWN` firmware 4.4 and case-insensitive `RELAY4` with the captured firmware values 0, 4.4, 9, 9.1 and 10. Firmware 0 through 9 selects the relay class for those captured points; 9.1 and 10 select the generic class. Relay projection uses the first six group references, performs both ordered Area observations even when the Area column is omitted, treats invalid raw Area text as 255, moves the unit reference between Area groups, and can create missing group 255 as `<Unused>` after an explicitly successful save. Generic projection uses the first eight group references and does not perform Area loads. Provider refusal returns a partial projection in error evidence and creates no output file.

`--native-xml-unit` removes the manual cache transcription for the captured native profile. Its input is one bounded C-Gate `DBGETXML //PROJECT` Installation snapshot and an exact unit path. It validates the project/network/unit association, canonical OIDs, primary application, group cache and stored PP values before invoking the same projector. The admitted RELAY4 4.4 shape has applications `56 255`, groups 1 through 8, and an existing Area group 12 or 255. The admitted `OWNED_UNKNOWN` 4.4 shape has one application, no stored PP records and groups 1 through 8 in its application cache. Other profiles are rejected. The mode is read-only and performs no network I/O; a missing Area group is rejected because the original workflow would mutate and save the database.

The original quirks are deliberate:

- Every selected header and field has a trailing comma. Each row ends in CRLF; the original handler adds a final empty line.
- Quoting is triggered only by a comma. When triggered, double quotes are doubled. A quote or newline without a comma remains unquoted, so some original outputs are not valid conventional CSV.
- Unavailable/noninteraction selected groups are appended as `<N/A>` fields after all available selected groups. Their placeholders can therefore shift relative to the headers.
- A missing Area (`null`) becomes `<Unused>`; an empty Area stays empty.
- Serial text retains ASCII digits and dots. The first dot separates an eight-character left part and four-character right part, padded with zeros but not truncated. Undotted text pads to 12 characters. `000000000000` and `010485754095` display as `No serial #`.

The pure serializer API is `document_database_csv(tuple_of_CSVUnitValues, *, columns=tuple_of_names)`. `loads_cached_projection(bytes, columns=...)` validates and executes the bounded cached projection; `project_cached_csv_unit(...)` is its typed API. Columns are mandatory. Inputs and results are immutable snapshots, and projection results include ordered events, terminal group/reference state, the selected original class and any stop reason. The package requires no original binaries for these operations.

File export validates the complete capture and bounded output before exclusive destination creation. It rejects existing output files and requires a regular source whose pre-open, opened-handle and post-open identities agree. It writes at most 32 MiB, handles partial writes, flushes with `fsync`, and closes once. An error after creation leaves the file in place with explicit possible-partial-output evidence; there is no replay or cleanup deletion. Evidence retains confirmed write counts and the first exception through secondary close/report failures. Parent-directory durability and native Windows file behavior are not established by this macOS acceptance.

The original executable is pinned to SHA-256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`. The [literal fixture](../research/fixtures/toolkit-database-csv-original-vectors.json) retains 88 original observations: 73 row cases and 15 quote cases. Seventy row cases and 13 quote cases are within the public API's domain; empty/high masks and NUL behavior remain research evidence. The fresh original probe executes 18 allowlisted, byte-checked instruction spans with explicit cached providers and string-runtime fixtures. It does not execute the PE entrypoint, constructors, native imports, database projection, original exception unwinding or the Windows file writer.

Original `TStrings.SaveToFile` selects the Windows default code page. UTF-8 here is an explicit portable export choice; it is not a claim of identical native file bytes. This feature also does not establish the original form's registry choices, network-scan admission, or automatic project-to-row projection.

The [focused acceptance fixture](../research/fixtures/toolkit-database-csv-acceptance.json) records 23 tests passing without skips on Python 3.13.14 and 3.10.20, including a fresh 88-case original observation in each run. Exact source/test/runtime inputs were archived before execution. File tests cover Unicode, no-overwrite behavior, source-path replacement, partial writes, lost creation return, `fsync`/close failure and first-interruption preservation. The research launcher retains partial process output on timeout/interruption and records process reaping. The first Python 3.10 attempt stopped before original execution because its environment lacked Capstone; that attempt and earlier successful source versions remain preserved.

Fresh original tests require the optional `research` extras (including pinned `capstone==5.0.7`) and `CBUS_TOOLKIT_EXE` naming the exact original executable. Their current native-library pins and network-denial harness are macOS-specific. Portable formatter and file tests do not require an original executable.

## Database projection research

The backend research now has [eight completed original cases](../research/experiments/2026-09-24/csv-original8-analysis.json) and [four completed native database captures](../research/experiments/2026-09-24/csv-native4-analysis.json). The native captures check all 21 RELAY4 parameters, exact whole-project XML preservation and 30 literal path/OID reads across three relay fixtures; a fourth fixture covers generic scalar metadata without programming. Missing Area group 13 remains absent during read-only native observation. All 473 archived inputs were unchanged; the owned C-Gate process and temporary storage were removed with no CNI connections.

The first current native attempt exposed a path-key mismatch after the vendor directory moved. The corrected harness resolves that path, validates the distinct GET_UNIT_SPEC framing and checks its exact SourceSpec provenance field before comparing the remaining parameter definitions. The failed attempt is preserved.

The [first original replay of those native captures](../research/experiments/2026-09-24/csv-replay-partial.json) completed the existing-group B01/B02 cases. B03 stopped at an unadmitted original method and B04 was not attempted. The failed capture, 77 stable archived inputs and confirmed child cleanup remain preserved.

The [successor replay](../research/experiments/2026-09-24/csv-replay-complete.json) closed that bounded path with five byte-pinned original methods and a source-backed standard-application descriptor for application 56 / group label `Group`. All four native fixtures were captured through 27,661 approved original instruction entries. B01 resolved Area12, B02 resolved existing `<Unused>` Area255, and generic B04 returned nil without QuickGet or storage activity. Missing-group B03 allocated exactly one group at address13, assigned `Group 13` through the original lookup path and stopped at the explicitly refused `GroupSave`; it is not presented as a successful persisted save. The launcher verified all 473 historical native archive inputs, kept inputs and loaded runtime sources unchanged, denied network access and made no native or VM call.

The production cached projector now implements the separate twelve-case cached-object pilot: ten completed original outcomes and two declared provider stops. It covers class selection at the captured firmware boundaries, six-versus-eight interaction groups, two ordered Area loads, changes between getters, invalid Area fallback, reference movement, group255 creation/save and selected-column behavior. The native XML adapter then projects B01, B02 and B04 from the unchanged archived C-Gate snapshots; B03 stops before output because Area13 is absent. Five adapter tests and two public-CLI tests extend the current host CSV set to 33 tests. The compact [cached implementation review](../research/experiments/2026-09-24/csv-cached-projection-review.json) and [native XML review](../research/experiments/2026-09-24/csv-native-xml-projection-review.json) pin the source analyses and admitted limits.

Live C-Gate snapshot acquisition, missing-Area-group creation/save, association construction and arbitrary unit profiles remain outstanding. So do selection preferences, native Windows output encoding and physical behavior. The cached-input mode still begins after cache records and provider outcomes have been captured explicitly; the native XML mode covers only the three read-only archived shapes above.
