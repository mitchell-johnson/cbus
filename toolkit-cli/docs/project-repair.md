# Portable XML project repair

`project repair` runs the original C-Gate repair algorithms in Python and writes
to a new file. It does not open a C-Gate connection or modify the source file.

```sh
cbus-toolkit project repair damaged.xml --dry-run
cbus-toolkit project repair damaged.xml --output repaired.xml
cbus-toolkit project repair damaged.xml --output repaired-windows.xml --line-ending crlf
```

The API is `repair_project_xml(data: bytes) -> ProjectRepairResult` in
`cbus_toolkit.project_repair`. `preprocess_project_xml` exposes the lexical step;
`transform_project_repair_xml(..., stage="repair" | "tidy")` exposes each XML
transform separately. The result contains detached preprocessed/repaired bytes,
hashes, the observed database version and explicit unverified native-load state.

The three steps reproduce these original operations:

1. Read UTF-8 with Java's malformed-sequence replacement behavior. Insert `>`
   before `<` when already inside a tag, discard `>` outside a tag, and normalize
   CR/LF/CRLF line endings. Nonempty unterminated final lines receive a newline.
   This state machine does not understand quotes, comments or CDATA and does
   not add a missing bracket at EOF. It can make otherwise valid XML invalid.
2. Apply `repair.xslt` semantics: wrap a bare unnamespaced `Project` in the
   original fixed Installation/DBVersion2.2 envelope, remove unnamespaced OID
   elements, and retain/canonicalize the first matching group at address255.
3. Apply `tidyduplicategroups.xslt` semantics: keep the first group per exact
   address string within each unnamespaced Application. Both special group
   templates drop ordinary Group attributes. Namespace declarations survive.

Keys use the first Address child's complete descendant text, without trimming
or numeric conversion. A missing Address shares the empty-string key. Each
stylesheet builds keys on its own original input, so OID removal can change
keys between stages. Namespaced Project/OID/Application/Group elements do not
match the unnamespaced stylesheet patterns. Other elements, attributes, text,
comments and processing instructions retain their XML meaning.

The serializer preserves character-reference distinctions across stages,
including carriage returns in group addresses and TAB/LF/CR in attributes and
namespace declarations. Python3.10 and3.13 produce equivalent XML semantics.
Declaration spelling, namespace placement, empty-element spelling and bytes
need not match the vendor serializer. CDATA becomes ordinary text.

Direct `repair` and `tidy` now accept bounded internal DTDs. The original
transforms expand internal general entities in text, attributes and markup,
apply DTD default attributes, and omit the DOCTYPE from their result. The
[36-case original capture](../research/fixtures/project-repair-dtd-vectors.json)
compares exact bytes for 26 direct/full successes and records ten full-pipeline
failures. These include nested and duplicate entity declarations, a character
reference in an entity, a declaration-only DTD and an attribute default. The
full pipeline succeeds for a DOCTYPE with no or an empty internal subset. Its
lexical step inserts an extra `>` before nested declarations in the captured
nonempty subsets, so those ten native full calls fail after changing the
temporary source. Python reports the repair-stage failure without writing an
output file. This is a bounded original observation, not a rule for every DTD.

The first XML parse rejects external DTDs and entities, parameter entities,
notations and unparsed entities before DOM construction. It permits at most
256 internal general entity declarations. Expanded text, element and attribute
names and values, comments and processing instructions share `max_bytes`;
expanded nodes and depth retain their existing caps. The second DOM parse runs
only after those checks. Expat may reject a recursive or amplified entity even
earlier. The original's external-entity behavior is not probed, and even its
accepted unused parameter declarations remain outside this safe subset.

The XML stages now admit the captured XML 1.0 and 1.1 cases with UTF-8,
ISO-8859-1, ISO-8859-15, US-ASCII or Windows-1252 declarations. Each original
transform first reads the file as UTF-8 with Java replacement, then the XML
parser interprets those bytes under the declaration. The full pipeline adds
its separate lexical UTF-8 read before either transform. The committed original C-Gate cases
`iso-declaration-repair`, `iso-declaration-tidy` and `iso-declaration-full`
establish this distinction: source bytes `C3 A9` under the ISO declaration
become UTF-8 `C3 83 C2 A9` (`Ã©`) in the output. The Python stages and the
integrated `project repair` command now match all three literal native outputs;
the command also preserves the source file and verifies the new output bytes in
its focused test. The [scoped receipt](../research/fixtures/project-repair-iso8859-scoped-receipt.json)
binds those stable case IDs, source hashes, focused command, skips and remaining
scope. The new [72-case original encoding and version capture](../research/fixtures/project-repair-encoding-vectors.json)
has 51 admitted positive and 12 admitted negative results for direct repair,
direct tidy and full repair. Literal XML 1.1 NEL and line separators become LF
after declared decoding; numeric character references remain distinct. A literal
high byte under an ISO or Windows declaration undergoes UTF-8 replacement
before the declared decode. Undefined Windows-1252 bytes become U+FFFD, as in
the original Java parser. A UTF-8 BOM is consumed before the declared decode.
The public file command has exact XML 1.1 and Windows-1252 full-output
tests. [The scoped receipt](../research/fixtures/project-repair-encoding-scoped-receipt.json)
binds the fixture, original source hashes, focused test outcome and limits.
These captured cases do not prove that every document using those encodings
loads into a native repository. The three internal-entity cases in that matrix
are now admitted by the separate DTD checkpoint: two direct successes and one
full-pipeline failure. A [separate 57-case original XML 1.1 capture](../research/fixtures/project-repair-xml11-vectors.json)
now covers restricted numeric character references and namespace-prefix
undeclarations across direct repair, direct tidy and the full pipeline. Direct
transforms admit C0 references in text, attributes and namespace URIs and write
decimal references. Their output declares XML 1.0, so the full pipeline rejects
those C0 references at tidy. C1 references survive all three operations; the
original serializer uses decimal references in text and literal C1 characters
in attributes. It omits an empty prefix declaration when that prefix is unused,
accepts a later rebind or sibling use outside the reset scope, and rejects a
prefix used inside the reset scope. Numeric-reference spelling inside comments,
CDATA and processing instructions remains literal. The [XML 1.1 scoped receipt](../research/fixtures/project-repair-xml11-scoped-receipt.json)
records the source pins, focused validation and remaining limits. External
entities, UTF-16 and unsupported XML versions remain rejected. The
[nine-case intersection capture](../research/fixtures/project-repair-dtd-xml11-vectors.json)
pins XML 1.1 documents with internal entities, including a quoted `>` and a
restricted C0 reference inside an entity. All six direct repair/tidy outputs
match the original bytes; the three full pipelines fail during repair after
the lexical step alters the nonempty DTD. The
[integration test](../tests/test_project_repair_dtd_xml11.py) also replays the
pinned original when Java and vendor software are provisioned. The
[scoped integration receipt](../research/fixtures/project-repair-dtd-xml11-scoped-receipt.json)
records the merged source hashes, focused gates, and remaining acceptance.
Intermediate UTF-8 read
and declared-decode growth are checked against the same byte limit before DOM
allocation.
The byte limit defaults to8MiB, with100,000 nodes and128 element levels.
API limits can be selected explicitly up to64MiB/1,000,000/256. The node limit
counts attributes and parser text/comment/PI events before DOM allocation;
adjacent text events are counted conservatively even if the DOM merges them.
Input, intermediate and output byte bounds all apply. The lexical-only API
accepts malformed UTF-8; successful lexical processing does not imply valid XML.

The historical [portable acceptance](../research/fixtures/project-repair-portable-acceptance.json)
passes13 tests on each of Python3.13.14 and3.10.20 with zero skips. Each run
executes3,036 lexical and159 transform cases against unchanged original
C-Gate3.4.0.2001 Java methods and exact vendor stylesheets. Of the transform
cases,144 compare then-supported outcomes and15 record then-excluded XML-version
or encoding inputs. The three ISO-8859-1 and three XML 1.1 rows are now admitted
from those unchanged native captures; the earlier receipt's counts and hashes remain
historical. The Windows newline cases set the original Java process's
line separator to CRLF on the Mac; they do not claim a Windows Java run.
Exact accepted sources, fixtures and tests are archived. CLI filesystem and
native-load acceptance are recorded separately.

The subsequent [combined checkpoint](../research/fixtures/project-repair-combined-acceptance.json)
passes all31 algorithm, file/CLI and native-load tests together on both Python
versions. Each run executes the3,195 original cases and four isolated native
C-Gate processes. The same122 captured files and35 loaded package sources are
archived; all child processes were removed. See the [file boundary](project-repair-files.md)
and [native readback](project-repair-native.md) for their exact evidence limits.

Repair and native loading are separate outcomes. The original XML repository
accepts `PROJECT REPAIR`; its SQLite repository returns408. A repaired bare
Project has DBVersion2.2 and needs a separate format transform before C-Gate3.4
can load it. The Python result therefore does not infer loadability from
well-formed XML or a database-version string. It does not perform that format
transform automatically.

`cgate repositories` lists the observed repository types, paths and current
flags; see [repository inventory](repositories.md). Native repository selection
is server-global, despite its original help text describing a session. The CLI
does not silently change a supplied server's repository. The existing
`cgate project repair NAME` still sends the native command directly and retains
the server response.
