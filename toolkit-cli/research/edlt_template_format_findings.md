# eDLT template format recovery, 2026-09-30

This is independent fresh inspection of the owned Toolkit managed assemblies,
plus execution of unchanged original static checksum methods on synthetic data.
It is not execution of the original TemplatesDialog or its parent lifecycle.
No project, C-Gate endpoint, VM, physical unit, or vendor unit specification is
used or distributed by this probe.

The [literal runtime vectors](fixtures/edlt-template-original-vectors.json)
record 73 cases, including malformed inputs. The original methods were loaded
from `CBusLogicModel.dll` SHA-256
`34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`.
The eDLT assembly inspected was `eDLT.dll` SHA-256
`75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3`.
Metadata token, RVA, byte extent and method IL digest appear in the fixture.
The private disassembly and assemblies stay outside the repository.

## Export structure

`TemplatesDialog.BtnSaveClick` (token `060001e6`, RVA `f024`) writes the
declaration `<?xml version="1.0" encoding="utf-8"?>`, `UnitTemplate` root and
these children, in order:

1. `Description` from the unit property.
2. `UnitType` from the unit property.
3. `FirmwareVersion` from the unit property.
4. `CRC` in decimal.
5. `Application` as primary and secondary application `ValueAsInt` values,
   in decimal, separated by exactly one space.
6. `FirmwareVersion` from the unit property again.
7. `UnitName` from the unit property.
8. `UnitType` from the unit property again.
9. Every entry in `PPAttributes`, preserving its enumeration order, except
   these exact, case-sensitive names: `UnitAddress`, `Application`, `Project`,
   `NetworkAddress`, `UnitName`, `SerialNumber`.

The exclusions are constructor token `060001e5`, RVA `efb8`. The PP enumeration
does not exclude `UnitType` or `FirmwareVersion`; if present in `PPAttributes`,
they produce third occurrences. The unit identity property getters use separate
backing fields and `PPAttributes` is a mutable independent `BindingList`.
This does not prove that every normal native KEYGL5 load includes these identity
PP entries. A caller must retain the actual ordered source list rather than
inventing catalogue membership or deduplicating it.

Each raw string is interpolated with `String.Format`, without XML escaping.
The checksum input is the raw string for every child after the CRC, in the
same order. `StreamWriter(string).WriteLine` writes one line per constructed
string and a final line ending; its default encoding/newline behavior comes
from the runtime. The original Windows GUI writer was not run, so this evidence
does not claim a captured Windows byte-for-byte export file.

The unescaped writer can produce invalid XML, or XML that changes when read as
`InnerXml`. For example, literal `>` is serialized back as `&gt;` by the reader,
and numeric references become characters. CRC generation over raw strings then
disagrees with CRC validation over `InnerXml`. A safe bounded writer should
refuse values that do not survive the required raw-to-InnerXml round trip,
rather than silently escaping them and claiming original export equivalence.

## Checksum

`PPHelper.CalcTemplateCrc` (token `0600066e`, RVA `18fd0`) performs these steps:

1. Allocate a fixed 65,536-byte buffer.
2. For each ordered input string, initially use `Trim()`.
3. Test `StartsWith("0x")` on the **original, untrimmed** string. This is the
   culture-sensitive string overload, not an ordinal overload. The retained
   runtime probe explicitly uses invariant culture.
4. If that test succeeds, split the **original** string on literal space,
   retaining empty tokens; parse each as `Convert.ToInt32(token, 16)`; format
   its signed Int32 value in invariant decimal; join with single spaces.
   This means `0x80000000` becomes `-2147483648` and `0xffffffff` becomes `-1`.
5. Append the low byte of each UTF-16 code unit. There is no separator between
   strings. Supplementary characters contribute two bytes, one per surrogate.
6. Call `CalculateCrcForTemplate(buffer, 0, byteCount)`.

`CalculateCrcForTemplate` (token `0600066f`, RVA `190d4`) initializes `0xFEED`,
uses polynomial `0x1021`, feeds each byte least-significant bit first into bit
15 while shifting the CRC left, and performs no final XOR. Its loop is
`index = start; index < len - 1; index++`. With the wrapper's `start=0`, the
last byte is always omitted. With nonzero start, `len` remains an index bound,
not a count relative to start. Empty and one-byte inputs both yield `65261`.

Selected literal original results:

| Inputs | CRC / failure |
| --- | --- |
| `AB`, `AC`, or ordered `A`, `B` | 21019 |
| `ABC` | 2353 |
| `0x30 0xca` or `48 202` | 53109 |
| ` 0x30 0xca` | 11695 |
| `0X30 0xca` | 60521 |
| `0x30  0xca` | ArgumentOutOfRangeException |
| U+0141 followed by `B` | 21019, equal to `AB` |
| U+1F600 followed by `Z` | 18221, equal to `=`, NUL, `Z` |
| 65,536 repetitions of `A` | 21019 |
| 65,537 repetitions of `A` | IndexOutOfRangeException |

.NET Trim removes U+0085, U+00A0 and U+2003 in the recorded cases; it does not
remove U+001C or U+200B. Python `str.strip()` would incorrectly remove U+001C.
The fixture keeps exact exception types observed under owned Mono, without
asserting cross-runtime exception-type equivalence.

The culture-sensitive prefix overload matters even under invariant culture:
`0`, U+200D (zero width joiner), then `x30 0xca` enters the hex branch and
fails token conversion, whereas an ordinal prefix test would process it as
ordinary text. Leading or intervening NUL and intervening U+200C behave the
same way in the retained cases. Leading U+200B (zero width space) and U+00AD
(soft hyphen) do **not** enter the branch on this runtime and yield 65036 and
29157 respectively. A conservative portable refusal for format/control/mark
characters that obscure a possible `0x` prefix deliberately rejects those
two successes too; it does not claim to emulate all locale/runtime collation.

## Import structure and assignment semantics

`TemplatesDialog.BtnLoadClick` (token `060001e7`, RVA `f368`) uses a new
`XmlDocument` and `Load(filename)`, leaving `PreserveWhitespace` at its default.
The document root's `Name` must be exactly `UnitTemplate`. Child nodes are
iterated in document order, without an element-only filter.

Before the first child named `CRC`, every `UnitType` and `FirmwareVersion`
replaces the corresponding header variable. The first `CRC` is parsed by
`Convert.ToInt32(string)` and switches to checksum collection. Every subsequent
child contributes its `InnerXml`, including another CRC, duplicate names,
comments, and processing instructions. The header type must equal `KEYGL5`.
Checksum equality is checked, then both headers must be nonempty. There is no
firmware equality comparison and no validation that later identity entries
match the pre-CRC headers.

The assignment loop subsequently visits **all** children, including the
pre-CRC headers. A nonempty `Application` is split on literal space with empty
tokens retained, converted through signed base-10 Int32, then formatted with
lowercase `0x{value:x}` and one separator. `48 202` becomes `0x30 0xca`;
`-1` becomes `0xffffffff`. Repeated/leading/trailing spaces can fail conversion.
The original does not enforce two tokens or the byte range in this conversion.
An empty application remains empty.

For each node it sets `PPAttribute.bInitialiseMode=true`, looks up a PP
attribute by the exact node name, and, if present and different, assigns
`InnerXml` (or converted Application), then marks `HasBeenChanged=true`.
Missing attributes are skipped. `bInitialiseMode=false` is set after that
iteration, but not in a setter-protecting finally. Failure can leave partial
model changes and the static initialization flag set. Deduplication would
erase original sequential assignment behavior; a safe preview can preserve
the sequence while refusing ambiguous mutation.

## XML framework observations

The synthetic XML cases use the same `XmlDocument.Load(filename)` and
`InnerXml` APIs on the owned Mono runtime. They are framework-operation probes,
not calls to the original dialog. The recorded behavior is:

- `A&amp;B&#x41;&quot;&apos;` becomes `A&amp;BA"'`.
- Literal `>` and `&gt;` both become `&gt;`.
- Literal CRLF, lone CR and LF remain distinct in text. `&#13;` becomes CR and
  `&#10;` becomes LF. A parser that normalizes all line endings can change CRC.
- A whitespace-only element has empty `InnerXml` with default preservation.
- Nested empty elements gain a space before `/>`.
- CDATA remains a CDATA lexical section in `InnerXml`.
- Root-child comments and processing instructions have empty `InnerXml`.
- `xml:space="preserve"` retains significant whitespace nodes; their
  `InnerXml` is empty.
- A declared general entity reference is retained lexically in `InnerXml`.

Rejecting DTD, namespaces, nested content, attributes, CDATA or otherwise
unproved forms is an explicit safe scope restriction, not original equivalence.

## Parent lifecycle boundary

After successful format/CRC checks, the original performs `ResetUnit(true)`
and ignores its Boolean return, calls `PopulateWidgetPanels`, enters
`BeforeChangePpAttributes`, runs ordered assignments, and finishes with
`AfterChangePpAttributes`. Persistence is deferred to the parent Apply/OK.
A generic PP overlay is not this workflow. A callable format/preview layer can
be complete within its declared bounds while apply refuses until reset,
refresh, bindings, application dependencies and failure transactions are
established together. Building an immutable preview and refusing all target
mutation is a deliberate safety difference from the original; no rollback is
claimed or needed by this layer.

## Reproduction

Run `edlt_template_original.py` with explicit `--logic-dll`, `--mono-root` and
a **new** `--output` directory. Add `--verify-fixture
toolkit-cli/research/fixtures/edlt-template-original-vectors.json` to compare
every fresh input/observation with the retained literals. The runner pins the
owned compiler/runtime/assembly, verifies actual loaded assemblies and method
IL hashes, applies a network-denying sandbox, retains command stdout/stderr,
and verifies inputs remain unchanged. It invokes no constructor of a Toolkit
model or control. The compiler and helper run on macOS Mono64; Windows CLR,
the WinForms dialog and full parent execution remain separate acceptance gaps.
