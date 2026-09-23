# Captured Toolkit database report to CSV

`toolkit-database-csv` exports an explicit captured report as UTF-8 without a BOM. It preserves the original Toolkit 1.18.0.2754 row serializer's column order, serial text, quoting and unavailable-group placement. It does not read project XML, query a database, or construct original unit objects.

```sh
cbus-toolkit toolkit-database-csv capture.json --output report.csv
cbus-toolkit toolkit-database-csv capture.json --output names.csv --columns address tag_name serial
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

The original quirks are deliberate:

- Every selected header and field has a trailing comma. Each row ends in CRLF; the original handler adds a final empty line.
- Quoting is triggered only by a comma. When triggered, double quotes are doubled. A quote or newline without a comma remains unquoted, so some original outputs are not valid conventional CSV.
- Unavailable/noninteraction selected groups are appended as `<N/A>` fields after all available selected groups. Their placeholders can therefore shift relative to the headers.
- A missing Area (`null`) becomes `<Unused>`; an empty Area stays empty.
- Serial text retains ASCII digits and dots. The first dot separates an eight-character left part and four-character right part, padded with zeros but not truncated. Undotted text pads to 12 characters. `000000000000` and `010485754095` display as `No serial #`.

The pure API is `document_database_csv(tuple_of_CSVUnitValues, *, columns=tuple_of_names)`. Columns are mandatory. `CSVUnitValues`, `CSVGroupValue` and the resulting `DatabaseCSV` are immutable snapshots; the result provides `rows`, `csv_text`, `utf8_bytes` and a detached metadata `as_dict()`. `loads_capture(bytes)` validates and detaches the exact capture schema. The package requires no original binaries for these operations.

File export validates the complete capture and bounded output before exclusive destination creation. It rejects existing output files and requires a regular source whose pre-open, opened-handle and post-open identities agree. It writes at most 32 MiB, handles partial writes, flushes with `fsync`, and closes once. An error after creation leaves the file in place with explicit possible-partial-output evidence; there is no replay or cleanup deletion. Evidence retains confirmed write counts and the first exception through secondary close/report failures. Parent-directory durability and native Windows file behavior are not established by this macOS acceptance.

The original executable is pinned to SHA-256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`. The [literal fixture](../research/fixtures/toolkit-database-csv-original-vectors.json) retains 88 original observations: 73 row cases and 15 quote cases. Seventy row cases and 13 quote cases are within the public API's domain; empty/high masks and NUL behavior remain research evidence. The fresh original probe executes 18 allowlisted, byte-checked instruction spans with explicit cached providers and string-runtime fixtures. It does not execute the PE entrypoint, constructors, native imports, database projection, original exception unwinding or the Windows file writer.

Original `TStrings.SaveToFile` selects the Windows default code page. UTF-8 here is an explicit portable export choice; it is not a claim of identical native file bytes. This feature also does not establish the original form's registry choices, network-scan admission, or automatic project-to-row projection.

The [focused acceptance fixture](../research/fixtures/toolkit-database-csv-acceptance.json) records 23 tests passing without skips on Python 3.13.14 and 3.10.20, including a fresh 88-case original observation in each run. Exact source/test/runtime inputs were archived before execution. File tests cover Unicode, no-overwrite behavior, source-path replacement, partial writes, lost creation return, `fsync`/close failure and first-interruption preservation. The research launcher retains partial process output on timeout/interruption and records process reaping. The first Python 3.10 attempt stopped before original execution because its environment lacked Capstone; that attempt and earlier successful source versions remain preserved.

Fresh original tests require the optional `research` extras (including pinned `capstone==5.0.7`) and `CBUS_TOOLKIT_EXE` naming the exact original executable. Their current native-library pins and network-denial harness are macOS-specific. Portable formatter and file tests do not require an original executable.

## Database projection research

The backend research now has [eight completed original cases](../research/experiments/2026-09-24/csv-original8-analysis.json) and [four completed native database captures](../research/experiments/2026-09-24/csv-native4-analysis.json). The native captures check all 21 RELAY4 parameters, exact whole-project XML preservation and 30 literal path/OID reads across three relay fixtures; a fourth fixture covers generic scalar metadata without programming. Missing Area group 13 remains absent during read-only native observation. All 473 archived inputs were unchanged; the owned C-Gate process and temporary storage were removed with no CNI connections.

The first current native attempt exposed a path-key mismatch after the vendor directory moved. The corrected harness resolves that path, validates the distinct GET_UNIT_SPEC framing and checks its exact SourceSpec provenance field before comparing the remaining parameter definitions. The failed attempt is preserved. Original replay and cold metadata/class loading still need verification before these observations can support an automatic database-to-report CLI.

The [first original replay of those native captures](../research/experiments/2026-09-24/csv-replay-partial.json) completed the existing-group B01/B02 cases. B03 stopped at an unadmitted original method on the missing-group path; B04 was not attempted. The failed capture, 77 stable archived inputs and confirmed child cleanup are preserved. This is partial research evidence, not successful end-to-end CSV projection.
