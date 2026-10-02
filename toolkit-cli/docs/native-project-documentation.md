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
and default output filename. `--network` selects the exact database Network
Address from that same snapshot. For example, `--network RoomA`, `--network
0254` and `--network 254` select distinct stored identities; spelling and case
remain significant. Physical NetworkNumber does not select a database network.
`--catalog` supplies an optional private calculator catalogue.

The command sends exactly one `DBGETXML //PROJECT`. It requires a complete
343 opener, 347 payload records and exact 344 XML terminal receipt, bounds the
UTF-8 snapshot to 16 MiB, and uses the strict
[saved native XML adapter](project-documentation.md). Duplicate scalar fields,
typed or hidden unsupported collections, namespace shadows, unsafe XML and
missing Level Value attributes refuse before creating output. It sends no
network OPEN, scan, programming LOAD, database edit or project SAVE.

The native adapter preserves numeric, named and lexical Network identities,
including the original captured `0254`, `254`, `256`, `0xff`, `CustomA` and
`Customa` profiles. Address must be one nonempty XML-safe path component; it
cannot contain `/` or control characters. Application, Group, Level and Unit
addresses retain their canonical decimal-byte profile.

Toolkit's report Address accessor is a separate integer projection. Headings
and links therefore render `0254` as `254`, `256` as `256` and an unparseable
name such as `RoomA` as `255`. The source also treats exact `NA` as zero and
accepts signed i32 decimal and `$`, `x` or `0x` hexadecimal spellings. JSON
selection and per-unit network identities remain exact. Distinct database
identities can share HTML anchors; that source behavior is preserved without
claiming complete original-page or manager-order acceptance.

An explicit NetworkNumber is independent of Address and may use a canonical
decimal byte or hexadecimal byte. An absent Number stays unknown. Thermostat
masters, wireless gateways and bridges resolve their consumed physical
references through that property. A unique explicit match works even if
unrelated networks have missing or duplicate Numbers. A duplicate consumed
Number refuses that body rather than choosing manager order; an unresolved
reference also refuses if missing Numbers prevent proving absence. Address is
never substituted for a missing native Number. Unrecovered raw Number states
remain refused. A bridge requesting a remote destination uses the last resolved
forwarding-prefix Number; if none resolved, its source loader consumes Number
255. That sentinel lookup has the same consumed ambiguity and absence guards.

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
`tests/test_project_documentation_native_addresses.py` compares exact native
identities, source integer projections, consumed-only Number resolution and
distinct action Address/Value anchors against independent literals and the
retained original native materialization. Its matching public interop module
uses both owned Rust backends for named-network selection, thermostat and
gateway references, saved XML output and whole-project preservation. The new
static receipt records only read-only source checks; it does not rebind any
historical original execution to current code. No site endpoint, original
program or physical device is used by those tests.

The owned-backend public fixture has a separate complete provisioning profile:
its master Number is decimal `42` and the originally absent unrelated Number
is explicitly `255`. Rust's current archive admission requires Number and
admits decimal bytes or literal `0xff`; the fixture records those changed
fields. That inserted `255` is a known sentinel. Live tests validate the actual
exported profile and do not claim interchange for absent Number or general
hexadecimal Number spellings. The independent saved-snapshot tests cover those
adapter inputs separately.
