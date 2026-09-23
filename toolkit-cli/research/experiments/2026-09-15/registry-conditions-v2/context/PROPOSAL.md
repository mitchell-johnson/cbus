# Supplied registry facts: context v2 implementation boundary

The separately admitted registry Windows v2 pilot passed 12 original calls, 12 same-provider witness reads, and 47 ordered records. Ten calls returned their expected Boolean and two returned their exact expected original error. All 11 created child keys, the owned root, and all handles were cleaned; all 53 sealed inputs remained unchanged. This proposal uses those captured results and the existing 107 direct CompareInt observations. It requests no additional original execution.

Evidence: `../registry-pilot-v2/pilot-v2/report.json` SHA256 `df5b5d74892cf4ac9d7935a71179b6c42486796f015a3b5697b0be2a753a213f`; independent `audit.json` SHA256 `3a30eb24788565f3b60ba421164867c20764e3e733cb6aa3a904cdee0fa3f03b`. The earlier registry v1 dependency failure and its successful cleanup remain separate failed evidence. The original assembly references the staged Microsoft.Win32.Registry 5.0 facade, which forwards Registry to mscorlib. The actual original MemberRef `0x0a000054` and witness resolved to the same x86 Framework method `0x060000f3`, mscorlib SHA256 `93d46bdac1664dba87641925572c789d71a21bb01dc7c7e5aa99c0eca8335e5e`.

## API and exact context shape

Keep `ToolkitUpdateConditions.evaluate(condition_json: bytes, *, context: bytes)` and the existing `update-condition-stages FILE --context FILE` command. No new CLI arguments, live adapter, dependencies, registry/clock/network access, or shared CLI changes are needed. Keep v1 input admission and complete result JSON byte-for-byte unchanged. V2 retains the same five stages and first-error/export fallback; it uses profile `toolkit-1.18-sesu-3.0.7-condition-facts-v2` and explicitly reports caller-supplied, unverified file and registry facts.

Example exact-key v2 context:

```json
{
  "format": "cbus-toolkit-condition-context-v2",
  "culture": "invariant-ascii",
  "files": [],
  "registry_provider": "framework-registry-getvalue-x86-process-default-v1",
  "registry_reads": [
    {
      "path": "HKEY_CURRENT_USER\\Software\\Example",
      "entry": "Value",
      "default": {"kind": "System.String", "value": "23021957-xxx-yy-z-27331bfa-adf0-46be-8d44-18b1a831affe"},
      "result": {"kind": "System.Int32", "value": -2147483648}
    }
  ]
}
```

The provider identifier declares the modeled capture boundary, not verified live state or proof that this caller captured the values. All records use that same declared provider. Each read has exactly four keys. The lookup key is the exact expanded path, exact entry, and tagged default. No case folding of query keys, extra hive matching, path canonicalization, or registry emulation occurs. Duplicate exact keys are rejected; records with different defaults are distinct.

Result tags are exactly `null` with JSON null, `System.String` with bounded text, or `System.Int32` with an exact signed 32-bit JSON integer (Boolean and arbitrary integer coercions rejected). Defaults are limited to the two actual original query constants: tagged Int32 1, or the exact tagged string sentinel above. The evaluator selects its required default from the leaf; the caller cannot override it. A missing matching record is unknown and stops only when requested. Explicit null is a known provider return. Provider exceptions, byte arrays, QWORD, multi-string, and unstable/custom ToString objects remain unsupported.

Keep both JSON byte bounds at 128 KiB and depth 12, eight definitions, expression/name 256, and the unchanged maximum eight file records. Admit at most eight registry records; path is at most 1024 characters, entry/result/RHS text at most 256. The global ASCII/no-NUL rules remain. Schema/type/bounds validation is eager; leaf comparator and observed-value semantic exclusions are lazy.

The first provider path domain is deliberately HKCU only: condition paths beginning exactly `HKCU\\` or `HKEY_CURRENT_USER\\`, with one or more nonempty printable ASCII components. Expand only the exact `HKCU\\` prefix into `HKEY_CURRENT_USER\\`. Facts must use the expanded form. Other hives, lowercase aliases, malformed alias prefixes, empty components and control characters remain unsupported when the leaf reaches path expansion. This covers both actual pilot path forms without treating source-only HKLM/HKU/HKCR expansion as Windows-proved. Entry names use nonempty printable ASCII; the key-existence query always requests literal `Test`, ignoring the definition's entry field as the original does.

## Original ordering and supported comparisons

Registry key existence (what 3): validate nonempty path; expand path; request `Test`/Int32 1; compare result against null; evaluate how 1/2 or return the original invalid-comparator error. An unknown fact therefore takes precedence over invalid how.

Registry entry existence (what 4): validate path then nonempty entry; expand and request entry/string-sentinel; null or exact primitive ToString equal to the sentinel means absent; evaluate how 1/2 or original invalid-comparator error. Empty string is present. The sentinel comparison is case-sensitive before any lowercasing.

Registry content (what 5/6): validate path then entry; expand and request the sentinel-default fact. Null or exact sentinel immediately returns `how == 11`, before RHS validation, numeric parsing, or comparator-domain exclusion. Otherwise derive the stable primitive ToString, lowercase LHS in the invariant ASCII domain, reject null RHS, then lowercase RHS. Preserve this outer order rather than calling CompareInt first.

String content supports lowered string equality/inequality (10/11) and the original ordinal string Contains overload (17), with printable ASCII text. String ordering 12..15 and culture-sensitive StartsWith 16 remain unsupported when reached. Pilot case 8 records original invariant `Z > a` as true, but is deliberately an unsupported production case; it is not generalized into ASCII lexical collation. Unknown how outside the original enum reaches its original error after the preceding work.

Integer content reuses the existing original CompareInt contract for how 10..15 and its exact failure ordering: parse RHS; null/empty/sentinel LHS returns false; parse LHS; compare or raise original unexpected-how. Syntax admits bounded ASCII digits, optional leading +/-, leading zeros, outer space/tab/CR/LF, and exact signed Int32 limits. Overflow or ordinary malformed numeric text reproduces the captured error. Vertical-tab/form-feed and other unproved control-character numeric spellings are unsupported only if that operand is reached; no Unicode or unrestricted Python int parsing. Comparison RHS is checked before an invalid or empty LHS. The direct 107 vector tests are distinct from the outer content shortcut tests.

Events preserve raw definition path, expanded query, exact typed default/result, derived text/lowercased text, and ordered observation requests. These are evaluator trace records under supplied primitives, not claims of live registry calls or interception of original calls. The successful-result cache remains fresh per evaluation and caches only completed leaves. Unknown/unrequested leaves preserve short-circuit behavior and prior cache evidence.

## Implementation and validation plan

Use a separate private registry helper for schema/query/leaf logic and a narrow optional registry-facts branch in the existing conditions evaluator. V1 continues through its unchanged file-facts branch and unchanged report fields. Keep source, raw typed data, normalized proof and supplied context distinct.

Before modifying shared code, capture the current v1 complete reports for all accepted vector cases and a representative error/unsupported/lazy/context matrix; require exact document equality after the addition. Test the 12 Windows observations (11 supported, one explicitly excluded collation observation), all 107 CompareInt observations, typed default identity, null/empty/sentinel/case distinctions, signed DWORD provider return, RHS and comparator order, unknown facts, repeated cached conditions, invalid paths, schema/JSON bounds, bool-as-int and interruption/export failures. Run the existing 61-test accepted selection plus new core/CLI tests on both Python versions with exact source/fixture input archives. No original rerun is required; archived raw outputs remain the oracle.

The extension does not evaluate full machine applicability, candidate selection, current trust, revocation, rollout, installation, media/date providers or update availability. It performs no Registry32 selection, live capture, environment expansion, RNG, clock read, or arbitrary provider callback. Metadata's six stages and revocation's seven stages are unchanged.
