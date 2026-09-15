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
