# Toolkit preference storage

`toolkit_preferences_store.py` implements a bounded version of Toolkit 1.18.0's original registry load/save sequence. It requires an explicit backend and a full snapshot of all **40 current preference values**. It does not select or access the host registry, infer startup defaults, or apply logging, C-Gate, or GUI effects.

The shared API exports:

- `PREFERENCE_DEFINITIONS`: immutable definitions in original registration order, including type, machine/user precedence, save exclusion, alternate key and boolean default.
- `validate_values(mapping)`: validates and detaches exactly the 40 typed values.
- `RegistryValue(win32_type, data)` and the `PreferenceRegistry` protocol.
- `ToolkitPreferencesStore(registry, *, numeric_locale=None).load(initial_values)` and `.save(values, display_values)`.
- `validate_numeric_locale(value)`: validates an optional explicit dot/comma tuple without I/O.
- `StoreOutcome.as_dict()`, plus `last_outcome`, `last_error` and `last_evidence` on the store.
- `UnsupportedPreferenceEncoding` for stored data outside the supported decoding boundary.

Display names are `tag_hex`, `tag_override`, `sort_applications`, `sort_groups` and `sort_levels`. Inputs accept booleans or byte integers; the original save routine masks each value with `0x7F`. Loading a DWORD produces a boolean based on whether it is nonzero.

## Storage and ordering

The 40 preference values use UTF-16LE `REG_SZ` data, including `True`/`False` and decimal integers. Most use `Software\Clipsal Integrated Systems\C-Bus Installation Software\3.0`. `JavaHeapMin` and `JavaHeapMax` use `Software\Schneider Electric\C-Gate\CurrentVersion`. Original literals include leading/trailing backslashes; the API exposes relative Windows key names.

`FeedbackLogSize` and four preferences excluded from save use machine-first reads. Other values use user-first reads. Registry read failures cause the original second-hive attempt. A user-first load can copy a machine value to HKCU, or write a default when neither hive supplies a nonempty string. A machine-first load retains the supplied current value if both reads fail. Save exclusion does **not** suppress load-time default writes.

The original manager's initial “create key” calls invoke legacy `RegSetValue` with an empty unnamed string. This changes a key's default value and can create the key. The module records these writes and their return codes. The original manager ignores nonzero codes; the outcome separately reports `algorithm_completed=true` and `complete=false` when such failures occurred. [Microsoft's RegSetValue documentation](https://learn.microsoft.com/en-us/windows/win32/api/winreg/nf-winreg-regsetvaluew) describes this default-value behavior.

Saving writes the five display DWORDs first, at HKCU `Software\Clipsal Integrated Systems\Global\Preferences`. It then issues the two unnamed HKCU writes and saves 35 preferences in original order. The five excluded values remain untouched by save. A failed HKLM preference write receives one HKCU fallback attempt. Completed prefixes are retained; there is no transaction, retry of the same operation, or rollback.

The original initialization table orders Kipper preferences first (four), global preferences next (28), and default languages last (eight). Earlier research schemas v1/v2 are historical: v1 omitted the eight language preferences, and v2 contained all definitions but used an incorrect fixture registration order. The v3 fixture derives the order from the original PE initialization table.

## Defaults and supported encodings

The caller must provide all current values. Constructor values are evidence for an isolated initialization stage, not installer or whole-application defaults. For example, an empty-store first load writes `ShowProjectManager=True` but keeps its supplied current `False` value until the next load. This original asymmetry is preserved.

Typed save supports booleans, signed 32-bit integers and valid Unicode strings up to 4096 characters. NUL-containing strings and unpaired surrogates are rejected before storage calls. Stored strings must have an exact UTF-16LE terminator, valid Unicode and no embedded NUL. Strings retain whitespace. ASCII boolean text matches `True` without case sensitivity; other ASCII text is false.

Integer reads default to **canonical signed decimal only**. This preserves the original bounded store API. Unsupported syntax, types or encodings stop with `UnsupportedPreferenceEncoding`, without copying the unsupported value into the other hive. Initial unnamed writes may already have occurred. This rejection is a deliberate boundary, not claimed original coercion parity.

An explicit `numeric_locale=('.', ',')` or `numeric_locale=(',', '.')` enables the independently verified [Toolkit numeric converter](toolkit-numeric.md) for integer reads. The tuple gives decimal and thousands separators in that order. Other values, including lists, are rejected by the constructor before I/O. The option is recorded in explicit-mode outcomes; the default outcome export is unchanged. Successful fallback copies retain the exact raw registry bytes, including whitespace and punctuation, even when the parsed integer differs from the stored text. Typed save and all noninteger decoding remain unchanged.

```python
store = ToolkitPreferencesStore(registry, numeric_locale=('.', ','))
outcome = store.load(full_current_values)
```

This option accepts at most 64 ASCII characters without NUL. Non-ASCII text, longer input and signed 64 truncation overflow remain unsupported and stop before copying. A **known parser error** has a different original boundary: if HKCU is absent and HKLM supplies malformed filtered numeric text such as `.2.3`, the original manager copies that raw text to HKCU **before** conversion fails. Explicit numeric mode preserves this completed copy, leaves the current typed value unchanged, stops before the next preference and records `ToolkitNumericConversionError`. A failure of the copy itself takes precedence. Primary-value conversion errors do not trigger another-hive read.

The original call sequence is copy at `0x851da4` / `0x851dcb`, then load at `0x851e5d`. At the actual conversion-error entry, observed active handlers belong to numeric cleanup (`0x782c0d`), integer-loader cleanup (`0x8526be`) and manager cleanup (`0x851e91`), all targeting `0x606c24`. Registry-read catches have already ended. The probe stops at this exception boundary; it does not claim Windows exception delivery or cleanup execution.

## Outcomes and verification

`complete` indicates that the bounded operation reached its end without unresolved failures. `algorithm_completed` also distinguishes ignored native return codes from a stopped sequence. `fully_observed` becomes false when values were missing or a fallback was necessary. Every attempted storage call is recorded in order, including its type and raw bytes. An exception after a backend write can leave that write committed; an incomplete operation is not proof that no change occurred.

KeyboardInterrupt and SystemExit retain their original exception object. Evidence attachment is best effort; `last_evidence` and `last_error` remain available when an exception rejects attributes or its message cannot be rendered. Reusing the store clears prior evidence before validating a new operation.

The original executable's manager, preference constructors, serialization, numeric routines and display DWORD encoding were executed in Unicorn against isolated fixtures. Allocation, string memory, resource/collection services, registry calls and exception dispatch remain explicit fixture boundaries. No user registry was changed. The production tests use an independent byte store and frozen original vectors; **a real Windows adapter and its scratch-key acceptance remain a separate stage**.

Evidence: [storage vectors](../research/fixtures/toolkit-preferences-store-vectors.json), [acceptance summary](../research/fixtures/toolkit-preferences-store-acceptance.json), and [tests](../tests/test_toolkit_preferences_store.py).

The original storage fixture remains historical and unchanged. Optional numeric decoding has separate [40-case manager vectors](../research/fixtures/toolkit-preferences-numeric-vectors.json), [integration tests](../tests/test_toolkit_preferences_numeric.py) and [acceptance](../research/fixtures/toolkit-preferences-numeric-acceptance.json). Standalone test packages containing `toolkit_preferences_store.py` must now also include `toolkit_numeric.py`; the latter uses only the Python standard library.

The separately implemented Windows adapter also passed its 13 existing native cases under [AMD64 Python on Windows ARM64 emulation](windows-preferences-compatibility.md). That compatibility run changed no store/adapter source or default gateway and does not expand this historical original-emulation fixture's scope.
