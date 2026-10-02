# Document a loaded database

`cbus-toolkit cgate database-document` writes the Toolkit-style HTML report
from one fresh complete project snapshot. It works through cmqttd's embedded
C-Gate service or another server that exports the admitted native XML shape.

```sh
cbus-toolkit cgate --host HOST --port 20023 database-document \
  --project //PROJECT --output project.html
cbus-toolkit cgate --host HOST database-document \
  --project //PROJECT --network 254 --generated-at 2026-10-02T12:00:00Z \
  --output local.html
```

Replace HOST and PROJECT with the selected endpoint and loaded project. The
selector must be `//` followed by 1–8 letters, digits or underscores. The
project's display TagName and its Address are independent: Address must match
the requested selector, ignoring case, while TagName supplies the report title
and default output filename. `--network` selects a numeric network from that
same snapshot. `--catalog` supplies an optional private calculator catalogue.

The command sends exactly one `DBGETXML //PROJECT`. It requires a complete
343 opener, 347 payload records and exact 344 XML terminal receipt, bounds the
UTF-8 snapshot to 16 MiB, and uses the strict
[saved native XML adapter](project-documentation.md). Duplicate scalar fields,
typed or hidden unsupported collections, namespace shadows, unsafe XML and
missing Level Value attributes refuse before creating output. It sends no
network OPEN, scan, programming LOAD, database edit or project SAVE.

The HTML uses UTF-8 BOM and CRLF. Existing files and dangling symlinks are
protected, publication uses an exclusive create, and a failed flush removes
only the newly created incomplete file. A lost XML terminal creates no output
and is never retried. `--generated-at` makes the header reproducible; its
default is command start time in UTC. Otherwise the default filename is
`<project TagName>.html`, subject to the existing safe-name checks.

JSON identifies the source command, one request, terminal code, exact snapshot
SHA-256/size, output SHA-256/size, selected networks, per-unit documentor status
and unresolved items. `physical_programming_loaded`, `network_open_requested`,
`native_database_mutated` and `project_save_requested` are false. Missing saved
programming remains visible as unresolved report markers.

Metadata is limited to the fields actually exported in this snapshot. Current
Rust Application XML omits Description even when its separate scalar property
was set; this command does not fetch omitted scalar properties or claim their
report parity. [Issue 75](https://github.com/mitchell-johnson/cbus/issues/75)
tracks the original XML comparison and implementation needed to close that gap.

The original Document Project workflow can load physical programming before
rendering. This snapshot command does not implement that loading/progress/cancel
history. Full original-page byte/visual parity, printing, Windows registry/locale
ordering and physical acceptance remain unassessed. The additional light-level,
WHAA and DALI tables have literal saved-PP/source comparisons, described in the
device profile documentation; those are separate from whole-page acceptance.

`tests/test_native_project_documentation.py` covers literal wire framing,
identity binding, ambiguous inputs, large single-line snapshots, exclusive
output and interrupted reads. `tests/test_cgate_project_documentation_interop.py`
exercises the public subprocess CLI against owned `cgate-mock` and `cmqttd`,
checks all ten literal device-body fixtures, whole-project preservation and
zero closed-interface trap contacts, and tests the saved native XML command.
No site endpoint, original program or physical device is used by those tests.
