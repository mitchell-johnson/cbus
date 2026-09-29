# Native loading of Python-repaired XML

This acceptance checks generated fixtures against the original C-Gate 3.4.0
build 2001 XML repository. It does not change the portable repair result's
general `native_load_verified: false` flag: arbitrary repaired documents still
need their own load observation.

`research/fixtures/project-repair-native-vectors.json` pins five original input
documents and their independent native repair outcomes. Their source was a
generated closed project containing network 254, application 56, duplicate
groups 1/255 and OIDs. They are not user projects. Four original repaired outputs
are retained as literal UTF-8; the mismatched closing-tag case was rejected.

The Python outputs are checked in two separate ways:

1. Compare the full parsed structure with those literal original repair outputs.
   Only the generated formatting whitespace between elements is ignored;
   attributes, nonblank text, comments and processing-instruction order remain
   significant. This is not an identical-serialization claim.
2. Stage the Python bytes unchanged in a new owned C-Gate process, select its
   observed `file` repository, and issue PROJECT LOAD followed by database XML
   readback and PROJECT CLOSE. The child has six verified loopback listeners,
   its own project directory and `Clipsal` fixture access. No running service or
   project directory is adopted.

The three current-format cases—duplicates, repairable bracket defects, and the
source used for the prior-backup fixture—load successfully. Network/application
addresses and group tags match, group 255 remains `<Unused>`, and the native
model generates 61 unique OIDs that are absent from the source. All named fields
are preserved. Native readback places group 255's TagName before Address, whereas
the repair stylesheet appended TagName after Address. The test records this
exact permutation and permits no other difference in the full ordered tree once
new OIDs are removed. It does not broadly disregard child order.

The bare legacy Project input repairs to Installation DBVersion 2.2. Original
C-Gate then rejects loading it with 408 because it requires DBVersion 2.3 and a
separate TRANSFORM PROJECT operation. The test records that rejection without
performing the transform. The unrepairable closing-tag case fails in Python
before the native service or socket is created.

All successful and rejected native loads leave the staged Python bytes
unchanged. Closing successful projects leaves no open project or native backup/
temporary file. Each child is terminated and its owned working directory is
removed. The tests never send PROJECT REPAIR or TRANSFORM against Python output,
never send NET OPEN, and never access the shared native service or real hardware.

The initial draft is preserved under
`research/runtime/project-repair-native-acceptance-v1/draft-313`: its extra strict
readback assertion failed on the observed group-field ordering. No portable
implementation was changed to satisfy that assertion. The corrected test records
the ordering distinction explicitly.

Final acceptance is pinned in
`research/fixtures/project-repair-portable-native-acceptance.json`: all four tests
passed on Python 3.13.14 and 3.10.20 with no skips. Each run exercised three
successful modern loads and one rejected legacy load in four fresh child
processes; all eight processes cleaned up. Four package source files and four
test/helper/fixture inputs matched between runs and are archived with their
hashes. The original literal fixtures are included in those archives.

The integration checkpoint is
`research/fixtures/project-repair-combined-acceptance.json`: 31 tests passed on
each Python version, combining 13 portable/original tests, these four native-load
tests and 14 file/CLI tests. Each run replayed 3,195 original Java cases and used
four fresh C-Gate children. All 122 captured input files and the 35 loaded package
sources stayed unchanged; the exact snapshot was archived before execution.

## Newly admitted encoding, internal-DTD and XML 1.1 cases

The newer transform fixtures are intentionally small bare-`Project` inputs. Three
representative outputs were staged **unchanged** in a fresh original C-Gate
3.4.0 build-2001 XML repository: `windows1252-utf8-full`, `one-text-repair`,
and `c1-text-full`. Each output is well-formed XML but wraps the fragment as an
Installation with DBVersion 2.2 and no `Project/Address`. Each `PROJECT LOAD`
returned 408, specifically requiring DBVersion 2.3 and `TRANSFORM PROJECT`.
No transform was requested. That is the native load result for those exact
captured bytes; it is not a verdict on the admitted parser feature in a valid
current-format project. A nonempty internal DTD also has no successful **full**
repair output in the captured cases: the lexical step damages its declaration.
Only its direct `repair` stage output can be staged.

A separate generated composition places each captured feature in the group-1
TagName of the already accepted, generated DBVersion-2.3 `RPDUP` project shape.
The Windows-1252 case uses the captured UTF-8 source bytes for `é` under a
Windows-1252 declaration, resulting in `Ã©`; the direct DTD repair expands the
captured `safe` entity and removes the DOCTYPE; the XML 1.1 full repair turns
`&#x7f;` into `&#127;`. For all three compositions, the Python output bytes
matched a fresh call to the pinned original Java transform method exactly.
Unchanged Python bytes then loaded with 200 in one new owned C-Gate child;
`DBGETXML` returned 344 and preserved each group name. After omitting
formatting whitespace and generated OIDs, its ordered tree matched the input
apart from the previously observed group-255 field order; it generated 61
unique OIDs. Each project closed with no project left open. The child exposed
only six verified loopback listeners and cleaned its temporary directory; no
network was opened.

A fourth current-format composition uses the captured XML 1.1 restricted C0
reference. Direct `repair` matches the original method exactly but serializes
`&#x1f;` as `&#31;` under an XML 1.0 declaration. Native `PROJECT LOAD`
rejects it with 408 and a SAX invalid-character message; `PROJECT LIST`
remains empty. The full Python pipeline rejects the same source at `tidy`, so
it never claims a complete repaired project for this case.

The focused [test](../tests/test_project_repair_native_admitted.py) and
[P8.01 receipt](../research/fixtures/project-repair-admitted-native-load-receipt.json)
bind the captured fixture hashes, generated source/output hashes, original
method pins, native command codes and readback checks. They establish three
specific loadable current-format compositions, one rejected current-format
direct-stage output, and three rejected legacy fragments. Arbitrary repaired
project documents still report
`native_load_verified: false`; broader Toolkit workflow acceptance remains
separate work.

A review rerun after protecting the pre-start setup with owned-service cleanup
again passed all three focused tests with no skips. The receipt keeps the initial
run's source hash and records the reviewed source hash, command statuses and
cleanup result separately.

## Subsequent DBVersion 2.2 conversion

The [bounded conversion checkpoint](project-legacy-transform.md) subsequently
ran `TRANSFORM PROJECT` on the generated `RPMAL` repaired output and the three
captured bare fragments above. All four transformed files loaded and returned
`DBGETXML` 344 in an owned original XML repository. The separate portable
`project transform-legacy` command produced exactly the native transformed
bytes for those four files. The earlier rejection observations remain the
pre-transform results; they do not imply that conversion fails.

## Migration-template census

The [template census](../research/fixtures/project-legacy-transform-template-census.json)
lists every `xsl:template` in the three original migration stylesheets with a
stable ID (stylesheet, ordinal and match/name/mode hash), the stylesheet
SHA-256s, a coarse classification and a `portable_coverage` flag. The flag
comes from the `NATIVE_TEMPLATE_COVERAGE` table in the portable module, and a
test checks both against each other and against the module's rule constants.

| Stylesheet | Templates | Portable coverage | Full | Bounded |
| --- | ---: | ---: | ---: | ---: |
| `v2tov21.xslt` | 57 | 57 | 55 | 2 |
| `v21tov22.xslt` | 19 | 19 | 16 | 3 |
| `v22tov23.xslt` | 2 | 2 | 1 | 1 |
| Total | 78 | 78 | 72 | 6 |

"Bounded" means the portable command rejects part of that template's input
instead of reproducing it. This applies to the three identity copies
(canonical source bytes only), the `cis:Unit` addition (each unit must carry
its own exact `cis` declaration) and the two firmware renames (Units with
attributes are rejected). The census omits `repair.xslt` and
`tidyduplicategroups.xslt`; it hashes them and records them as out of scope.
Coverage of a template is not evidence of native loadability for arbitrary
projects. The [legacy transform page](project-legacy-transform.md) lists the
native receipts.
