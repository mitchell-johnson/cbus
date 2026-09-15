# Registry conditions under supplied facts

The existing `update-condition-stages` command also accepts context v2 with explicitly supplied registry query results. It reads the two JSON inputs; it does not read the machine registry or determine whether an update applies.

```sh
cbus-toolkit update-condition-stages conditions.json --context registry-facts.json
```

For example, `conditions.json` can contain:

```json
{
  "expression": "configured",
  "conditions": {
    "configured": {
      "whatToCheck": "registryEntryIntegerContent",
      "howToCheck": "isEqual",
      "fileOrRegistryKeyPath": "HKCU\\Software\\Example",
      "registryEntryNameOrProductCode": "Value",
      "comparisonRightSideValue": "-2147483648"
    }
  }
}
```

Its companion `registry-facts.json` is:

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
      "default": {
        "kind": "System.String",
        "value": "23021957-xxx-yy-z-27331bfa-adf0-46be-8d44-18b1a831affe"
      },
      "result": {"kind": "System.Int32", "value": -2147483648}
    }
  ]
}
```

The provider profile declares the modeled x86 Framework `Registry.GetValue` call with its process-default view. It is caller input, not verified live state. It does not select the separate rollout implementation's `Registry32` view. Results are tagged CLR primitives: `null` with JSON null, `System.String` with text, or `System.Int32` with a signed 32-bit integer. A raw DWORD is not accepted as an unsigned substitute: the captured provider returned `-2147483648` for DWORD `0x80000000`.

Query identity includes the exact expanded path, exact entry name, and typed default. Key existence requests entry `Test` with `{"kind":"System.Int32","value":1}`. Entry existence and content request the named entry with the exact string sentinel shown above. A record with the wrong default does not satisfy the query. The evaluator never infers one query result from another. Repeated identical records are rejected; the same path/entry with different defaults is distinct.

Omitting a requested record means unknown and produces an unsupported stage when reached. An explicit null is a known provider result. Missing entries and a present value equal to the exact sentinel are indistinguishable to the original leaf. Empty strings remain present. In a content comparison, null or the exact sentinel returns true only for not-equal, before validating the RHS or comparator. By contrast, a present empty string enters integer parsing: a valid RHS then yields false; an invalid RHS raises the original RHS error.

The API remains `ToolkitUpdateConditions().evaluate(condition_json_bytes, context=context_json_bytes)`. The same five stages, detached report, `last_report`, interruption evidence and CLI exit codes apply. Exit 0 means either Boolean result was computed; exit 1 means a failed or unsupported stage; argument errors use exit 2. The result never becomes an update-availability or publisher-trust claim.

## Bounded domain

V2 preserves the file facts and Boolean grammar described in [the v1 documentation](toolkit-update-conditions.md). Existing v1 inputs and complete report bytes remain unchanged. V2 reports profile `toolkit-1.18-sesu-3.0.7-condition-facts-v2`, with the provider explicitly unverified.

The context has exactly the five top-level fields shown above. It permits at most eight file records and eight registry records. Existing JSON bounds remain 128 KiB per file and depth 12, with duplicate keys, nonfinite values, unpaired surrogates and excessive integer tokens rejected. Definitions are limited to eight, expressions/names to 256 characters, and paths to 1024. Registry entry, result and RHS text is bounded to 256 ASCII characters without NUL. Integers must have their exact JSON type; Boolean values are not integers.

Condition paths admit exact `HKCU\\` or `HKEY_CURRENT_USER\\` prefixes with nonempty printable ASCII components. Records require the expanded `HKEY_CURRENT_USER\\` form. Other hives, lowercase or malformed aliases, empty components and control characters are unsupported. There is no case-insensitive path matching or normalization. Entry names must be nonempty printable ASCII.

Supported leaves are:

| Leaf | Comparisons |
| --- | --- |
| `registryKeyExists` / `registryEntryExists` | `isTrue`, `isFalse` |
| `registryEntryStringContent` | `isEqual`, `isNotEqual`, `contains` |
| `registryEntryIntegerContent` | Equal/not-equal and the four numeric order comparisons |

String content lowercases both sides in the declared invariant ASCII domain. Equality and contains require printable ASCII. String ordering and `beginsWith` remain unsupported when reached because the original uses culture-sensitive overloads. The single captured original `Z > a` result remains evidence, without being generalized into a lexical ordering implementation.

Integer content parses the RHS before the LHS. It accepts signed decimal Int32 text, optional leading plus/minus, leading zeros, and outer space/tab/CR/LF. It checks range before converting to a Python integer. Ordinary malformed text and overflow retain the original errors. Other control-character spellings, including vertical tab and form feed, remain unsupported when the operand is reached. A missing-content shortcut can finish before that operand is inspected.

Schema and bounds checks are eager. Leaf observation requests, semantic exclusions and comparisons are lazy. A fresh successful-result cache preserves repeated-name and short-circuit behavior. Trace records distinguish raw definition path, expanded typed query, supplied result, derived lowercase text and numeric parse order. They describe this pure calculation; they do not count live calls or claim interception of original calls.

Provider errors, arbitrary objects, QWORD, binary/multi-string values, expansion of environment variables, other hives/views, current-machine capture, full candidate selection and rollout/install/date/media providers remain outside this profile. Metadata's six stages and revocation's seven stages are unchanged.

## Evidence

The registry v2 pilot executed 12 unchanged original leaves and 12 separate same-provider witness reads on owned Windows scratch keys. All 47 ordered records matched the plan: ten Boolean results and two expected original errors. Eleven issued child keys, the owned root and all handles were cleaned. Original MemberRef `0x0a000054` and the witness resolved to the same Framework mscorlib method `0x060000f3`; the staged Registry 5.0 assembly is a type-forwarding facade, not a replacement implementation.

The earlier v1 pilot stopped at its first original call because that exact facade dependency was absent. Its failed result and verified cleanup remain preserved. The separately admitted v2 used a new root and added only the inspected staged dependency and explicit provider-identity guard.

The compact [registry vectors](../research/fixtures/toolkit-update-registry-conditions-vectors.json) retain all 12 original results, witnesses, full raw records, runtime identity and cleanup. Tests compare 11 supported results and explicitly exclude the collation case. They separately compare all 107 previously captured direct CompareInt calls, including 31 original errors; these helper observations do not replace the outer registry-content checks. The [v1 report baseline](../research/fixtures/toolkit-update-conditions-v1-report-baseline.json) checks all bytes of 248 pre-change reports, including 99 completed calculations and typed, context, definition, grammar and leaf failures.

Source anchors: registry key existence RVA `0x2980`, entry existence `0x2aa0`, entry content `0x2b8c`, CompareInt `0x2de0`, alias expansion `0x2a14`. Existing original callback/cache and Boolean grammar evidence remains unchanged. The first local baseline-generator draft omitted path fields and produced invalid contexts; its archive is retained as an unaccepted draft. The corrected baseline was captured before any production edit.

Focused acceptance passed 78 tests on each of Python 3.13 and 3.10, with zero failures, errors or skips: 17 new registry core/CLI tests and 61 existing conditions/metadata/revocation regressions. Exact source, fixture and runtime inputs were archived before both runs and remained unchanged. [The acceptance fixture](../research/fixtures/toolkit-update-registry-conditions-acceptance.json) records the runs, raw original evidence, exclusions and preserved failed attempts.
