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

The XML stages require XML1.0 and UTF-8, reject DTD/entity declarations and
UTF-16, and default to an8MiB byte limit,100,000 nodes and128 element levels.
API limits can be selected explicitly up to64MiB/1,000,000/256. The node limit
counts attributes and parser text/comment/PI events before DOM allocation;
adjacent text events are counted conservatively even if the DOM merges them.
Input, intermediate and output byte bounds all apply. The lexical-only API
accepts malformed UTF-8; successful lexical processing does not imply valid XML.

The [portable acceptance](../research/fixtures/project-repair-portable-acceptance.json)
passes13 tests on each of Python3.13.14 and3.10.20 with zero skips. Each run
executes3,036 lexical and159 transform cases against unchanged original
C-Gate3.4.0.2001 Java methods and exact vendor stylesheets. Of the transform
cases,144 compare supported outcomes and15 establish explicit XML-version or
encoding exclusions. The Windows newline cases set the original Java process's
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
