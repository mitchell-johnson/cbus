# Update conditions under supplied facts

`update-condition-stages` evaluates a bounded subset of Toolkit1.18's SESU conditions using facts supplied in a JSON file. It does not inspect the machine, contact the update server, read registry values, or establish package applicability or update availability.

```sh
cbus-toolkit update-condition-stages conditions.json --context facts.json
```

`conditions.json` uses the original condition model:

```json
{
  "expression": "installed AND current",
  "conditions": {
    "installed": {
      "whatToCheck": "fileExists",
      "howToCheck": "isTrue",
      "fileOrRegistryKeyPath": "C:\\Apps\\Toolkit.exe"
    },
    "current": {
      "whatToCheck": "fileVersion",
      "howToCheck": "isGreaterOrEqual",
      "fileOrRegistryKeyPath": "C:\\Apps\\Toolkit.exe",
      "comparisonRightSideValue": "1.18.0.2754"
    }
  }
}
```

The companion facts are explicit, unverified input:

```json
{
  "format": "cbus-toolkit-condition-context-v1",
  "culture": "invariant-ascii",
  "files": [
    {
      "path": "C:\\Apps\\Toolkit.exe",
      "exists": true,
      "file_version": "1.18.0.2754"
    }
  ]
}
```

Paths are matched exactly and never opened. Omitting `exists` or `file_version` means unknown. A null or empty `file_version` means a known absent version string. An absent file returns false for every file-version comparison, including not-equal. Its version fact is not requested. The context admits at most eight unique paths; duplicate records and wrong Boolean/null types are rejected.

The command exits0 when it computes either Boolean true or Boolean false. It exits1 for failed or unsupported stages and2 for command-line syntax errors. `condition_result_under_supplied_context` is the calculation, not update availability. `updates_available` remains null; applicability, metadata admission and publisher trust remain unevaluated.

The Python entry point is `ToolkitUpdateConditions().evaluate(condition_json_bytes, context=context_json_bytes)`. The returned immutable `ConditionStageReport` provides `as_dict()`, `computed`, `result` and `cause`; the evaluator retains `last_report`. Each export is detached. Unexpected exceptions and interruptions retain their first object and partial evidence. A CLI result-export failure retains an already computed true/false through a separate fallback rather than reporting successful command completion.

## Supported profile

Both input files are bounded regular files of at most128KiB. JSON has a depth limit12, bounded integers before conversion, unique keys, finite numbers and paired Unicode escapes. The admitted model is ASCII without NUL, at most eight definitions, expression/name length256, path length1024, and version/RHS/registry-field length256. Non-ASCII culture behavior and broader Newtonsoft coercions are unsupported. Unknown original model members remain in decoded `raw_typed_data`; modeled values and observed primitive string coercions appear separately in `typed_model`. Exact original input hashes remain distinct from lowercase `normalized_expression` and normalized lookup names.

Boolean grammar supports identifiers, true/false, parentheses, AND/OR/NOT and `&&`/`||`/`!`. Operators and lookup names use ASCII lowercase. AND precedes OR. One NOT may precede a primary expression, so `NOT NOT A` fails and `NOT (NOT A)` is permitted by the original recursive grammar. Parenthesized recursive NOT is source-composed evidence; no additional original vector is claimed for it. Arithmetic, functions, comparisons, quoted literals, dates, ternaries and other NCalc syntax are unsupported.

Reached leaves support fileExists with isTrue/isFalse, and fileVersion with isEqual/isNotEqual/isGreater/isGreaterOrEqual/isLess/isLessOrEqual/beginsWith/contains. Canonical enum spellings or Int32 enum values are accepted; other converter spellings remain outside the profile. Version ordering follows the observed System.Version2–4 component rules: `1.2` sorts before `1.2.0`. Leading zeros and surrounding spaces are admitted; signs, component whitespace and other unproved version formats are unsupported. Prefix/contains require printable ASCII when the comparison is reached and use the raw version string.

In context v1, special-folder substitutions, registry/product checks, rollout, RNG, clocks and other providers are unsupported when reached. [Context v2](toolkit-update-registry-conditions.md) adds bounded registry leaves under supplied typed facts. Unused typed definitions may remain unrequested. The result cache starts empty: the seeded caches used by research probes are not a public bypass. Evaluation records ordered leaf lookups, supplied/unknown fact requests, successful cache insertions, reuse and partial failure. Short-circuited branches consume no facts. Requested version validation precedes file observations; fileExists observes existence before rejecting an invalid comparator, matching the original order.

## Original evidence

The sealed Stage A extension contains364 cases,386 case-arms and106 original processes. Every arm executed once. It preserves both failed initial expectation runs: two diagnostic wording differences and the real adjacent-NOT grammar rejection, followed by a separately reviewed pending trace expectation. The final40-arm continuation passed. No historical failure was rewritten as a pass.

The compact `toolkit-update-conditions-vectors.json` retains all386 observations and their source hashes. Production differential tests cover279 typed/validation/version/file/expression arms; the remaining107 Int32 helper observations stay as research evidence without adding a registry or integer-comparison API. Direct original expression calls and22 observational callback-wiring arms remain separately identified. The probes used unchanged original methods on network-denied owned Mono and four confined file fixtures; they did not invoke public Evaluate, full update constructors or candidate collection. Callback ordering/cache transitions are evidenced, while operating-system syscall counts, Windows/concurrency behavior and whole-applicability parity are not claimed.

Source anchors are ClientConditionChecker validation RVA0x2330, callback0x2210, private NCalc wrapper0x21bc, fileExists0x25e4 and fileVersion0x26a8; original NCalc unary grammar is RVA0x6e74. Existing metadata's six stages and revocation's seven stages are unchanged.

Focused acceptance passed61 tests on each of Python3.13 and3.10, with zero skips:20 condition/core/helper/CLI tests and41 unchanged metadata/revocation regressions. Each run checked279 captured-original stage arms. The exact347 source, fixture and runtime inputs were archived before execution and remained unchanged; `research/fixtures/toolkit-update-conditions-acceptance.json` records reports, hashes, limits and preserved failures.
