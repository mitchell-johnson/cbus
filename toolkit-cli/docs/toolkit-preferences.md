# Toolkit preferences

The CLI now exposes all 40 registered preference definitions, the five display settings, explicit control plans, and Windows registry load/save. This is a bounded Toolkit 1.18 implementation. The current acceptance checkpoint passes **94 tests on Python 3.13.14 and 3.10.20**, with **21 actual Windows registry cases in each run**.

```sh
cbus-toolkit preferences schema
cbus-toolkit preferences initial-state > seed-preferences.json
cbus-toolkit preferences controls current-preferences.json
cbus-toolkit preferences plan current-preferences.json \
  --edit chkLoadChangePort=true \
  --edit chkApplicationLog=false \
  --edit 'cmbJavaHeapMax="512"' \
  --edit spnFeedbackLogSize=2000 \
  --edit rdoTagNamesUseHex=true
cbus-toolkit preferences registry-save current-preferences.json --dry-run
```

A state file is a JSON object with exactly `format`, `values`, and `display_values`. The format is `cbus-toolkit-preferences-state-v1`. `values` contains all 40 names and typed values listed by `preferences schema`; `display_values` contains `tag_hex`, `tag_override`, `sort_applications`, `sort_groups`, and `sort_levels`. Use `preferences initial-state` to obtain a complete seed without registry access. It contains the observed registration-stage values and five display fallbacks. These are not installer defaults, current machine settings, or recommended runtime configuration. For example, its JavaHeapMax is 0; load the stored settings or explicitly edit that control to a supported heap size before planning a save. [Initial-state evidence](toolkit-preferences-initial-state.md) describes the exact constructor and layout scope.

`plan` returns the resulting state in its `state` field, alongside the 19 original OK-handler assignments and the ordered control edits. Preserve that state object in a file before passing it to `registry-save`. The other 21 preference values are retained. Plans perform no registry or C-Gate operations.

## Control behavior

Edits run in the order supplied, including repeated edits to the same control. Disabling the load change port also clears and disables the application-log checkbox. Enabling it checks that box again. Shutdown Ask takes precedence during load; choosing another shutdown mode clears the C-Gate checkbox, and changing that checkbox selects Close Projects. Unit dialog selection supports remembered, simple, and advanced modes. The three tag-display choices and three sort selections update the separate display state.

The original SpinEdit setter clamps feedback-log size to 100–9,900 KB. The planner fixes JavaHeapMin to 32 and defaults to canonical JavaHeapMax text from `"64"` through `"9999"`. Temperature selection accepts indices 0 and 1. The explicit lower-level save projection can retain other signed integer getter values observed outside this constrained selection API.

Original FormShow assignments, the SpinEdit setter/clamp, and OK-handler assignments were executed unchanged against explicit fixtures. The portable model compares 48 load cases and 22 successful save-handler cases. Original click-handler evidence supports the modeled effects, but VCL form construction and automatic event dispatch are not claimed. Same-value `set_control` requests deliberately apply the modeled handler; this is an explicit ordered operation API.

The `controls` output, including the nested controls in `plan`, also contains `address_preview`. The original fixed examples are `Level 10`, `010 - Level 10`, and `010 (0Ah) - Level 10`. All four initial flag combinations and twelve original tag-click paths were executed, including the original integer formatter and concatenation. String allocation/copy/release and the label setter were explicit fixtures; actual VCL rendering remains unverified.

## Windows storage

On Windows:

```sh
cbus-toolkit preferences registry-load current-preferences.json
cbus-toolkit preferences registry-save updated-preferences.json
```

`registry-load` follows the original manager's copy/default behavior and **can write missing preferences and unnamed values**. It requires the full retained input state because the original loader sometimes keeps an existing in-memory value. For example, a first empty-store load can write `ShowProjectManager=True` while retaining supplied `False` until a subsequent load. Its output includes a `state` object and every attempted operation.

`registry-save` writes the five display DWORDs, unnamed key values, and 35 named preference values in original order. Five preferences excluded from save remain untouched. A machine-hive write failure permits the original single user-hive fallback. The save preview shows the primary path assuming machine writes succeed and describes that conditional fallback. It accesses no registry and is available on other platforms.

The adapter explicitly requests the 32-bit registry view. Reads retain the bytes returned by `RegQueryValueExW`. String writes require valid terminated UTF-16 before any key is opened, including two terminators for `REG_MULTI_SZ`. This follows the [Microsoft write contract](https://learn.microsoft.com/en-us/windows/win32/api/winreg/nf-winreg-regsetvalueexw); existing malformed strings can still be observed through the raw adapter, as allowed by the [query contract](https://learn.microsoft.com/en-us/windows/win32/api/winreg/nf-winreg-regqueryvalueexw).

Stored preference decoding accepts terminated Unicode strings, ASCII boolean spellings, and canonical signed decimal integers by default. `controls`, `plan`, and `registry-load` also accept `--numeric-locale dot` or `--numeric-locale comma` to select the bounded original JCL conversion. This does not infer the machine locale. For example, heap text `"64.5"` converts to 64 with `dot` and 645 with `comma`. Plans preserve the entered text and report the conversion, including any original signed 32-bit wrap.

The optional converter accepts at most 64 ASCII characters without NUL; signed 64-bit truncation overflow remains unsupported. A successful registry fallback copies the exact original string bytes. For a known original numeric conversion error, the user-hive copy happens before conversion fails, and the outcome records that completed prefix. Unsupported data stops before copying that value. Earlier default writes may already have occurred. See [numeric conversion](toolkit-numeric.md) for the exact filtering and rounding behavior.

Operations are sequential. A failed or interrupted write can leave a completed prefix, including a write whose reply was lost. Results retain the attempted operations and original interruption evidence; no transaction, automatic rollback, or replay is implied. Logging controller changes, C-Gate restart effects, actual GUI rendering, and the update workflow are not implemented by these commands.

CLI error reporting treats attached exception evidence as optional. If reading it raises another exception, reset and storage commands retain the original error and fall back to the current coordinator's evidence only when it belongs to that exact error object. Evidence from a prior operation is not reused. The [focused getter-guard acceptance](../research/fixtures/toolkit-preferences-evidence-getter-acceptance.json) records this later correction separately from the historical expanded suite.

## Reset suppressed prompts

```sh
cbus-toolkit preferences reset-dont-ask-again --dry-run
cbus-toolkit preferences reset-dont-ask-again
```

The reset deletes only the original HKCU Toolkit `DontAskAgain` subtree, using the 32-bit registry view and the original descending traversal. It needs no state file. The default bounds are 256 keys, depth 32, and 1,024 UTF-16 units per child name; `--max-keys`, `--max-depth`, and `--max-name-units` can raise them. A bound or interrupted operation stops with a recorded prefix and releases owned handles. There is no replay or rollback.

`target_delete_succeeded` reports the Windows deletion call’s status; `absence_verified` remains false because another process may still hold the key open. The original completion notice can be requested even when deletion fails or the key is missing. The CLI reports these separately and returns nonzero for an incomplete reset. Native tests independently verify absence in owned test subtrees. See [reset semantics and evidence](toolkit-preferences-reset.md).

## Acceptance

The Windows tests use Python 3.13.14 x86 in the authorized VM. Both logical registry hives are redirected into separate, disposable HKCU test subtrees. They verify 36 valid raw roundtrips, separate logical hives, unnamed writes, all 40 settings, five display values, skip-save preservation, unsupported inputs, 32-bit access flags, and an independent-process reload. The numeric extension also checks both explicit locales, exact fallback bytes, copy-before-conversion-error behavior, unsupported overflow without copying, and independent-process reloads. The reset suite adds eight native cases per run for recursive Unicode deletion, scope and handle guards, configurable bounds, and interrupted deletion. All twenty-one test namespaces per run are removed and absence is checked. Actual HKLM permission/elevation behavior, 64-bit Python execution, and the user's Toolkit registry are outside this native test scope.

The first native test exposed an invalid assumption about unterminated `REG_SZ` roundtrips. Its failed result is retained. A later diagnostic recorded one Windows API observation; it is not treated as a portable normalization rule. The accepted adapter rejects those malformed writes before opening a key.

- [Historical expanded 94-test acceptance](../research/fixtures/toolkit-preferences-expanded-acceptance.json)
- [Later focused CLI evidence-getter correction](../research/fixtures/toolkit-preferences-evidence-getter-acceptance.json)
- [Separate AMD64 Windows compatibility](windows-preferences-compatibility.md)
- [Earlier numeric and Windows acceptance](../research/fixtures/toolkit-preferences-numeric-cli-acceptance.json)
- [Earlier canonical acceptance](../research/fixtures/toolkit-preferences-acceptance.json)
- [Original storage behavior and API](toolkit-preferences-store.md)
- [Control vectors](../research/fixtures/toolkit-preferences-controls-vectors.json)
- [Windows native test cases](../research/windows_preferences_native_cases.py)
