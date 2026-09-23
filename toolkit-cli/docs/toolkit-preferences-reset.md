# Reset DontAskAgain

`ToolkitDontAskAgainReset` implements the Preferences dialog's registry deletion order for the exact Toolkit 1.18.0 executable. It deletes only this logical HKCU subtree:

```text
Software\Clipsal Integrated Systems\C-Bus Installation Software\3.0\DontAskAgain
```

This action is separate from saving the 40 registered preferences. It does not load preferences, change their values, display a notice, or reload a running Toolkit process.

## API

```python
from cbus_toolkit.toolkit_preferences_reset import ToolkitDontAskAgainReset
from cbus_toolkit.windows_preferences_reset import WindowsDontAskAgainRegistry

registry = WindowsDontAskAgainRegistry()
reset = ToolkitDontAskAgainReset(
    registry, max_keys=256, max_depth=32, max_name_units=1024,
)
outcome = reset.run()
evidence = outcome.as_dict()
```

Constructing either object performs no registry operation. `run()` performs one traversal. Call an instance sequentially; a new run clears its previous evidence. The three limits are caller-selected resource bounds, not Toolkit product limits. Each accepts an integer from 1 through 1,000,000; booleans are rejected. The key bound includes the root and attempted child opens. Name lengths count UTF-16 code units. Raising a bound requires an explicit separate invocation.

Portable backends implement `DontAskAgainRegistry`: `open_key`, `query_info`, `enum_key`, `close_key`, and `delete_key`. The first three return the immutable `OpenKeyResult`, `KeyInfoResult`, and `EnumKeyResult`; close and delete return unsigned Windows status codes. Successful open results supply an owned handle. Child names must be single nonempty registry components. The Windows adapter owns every handle it opens and rejects other handles, hives, root paths and access masks.

`WindowsDontAskAgainRegistry` uses the original access mask `0xf003f` with an explicit 32-bit registry view. It calls the Unicode Win32 open/query/enumerate/close functions and `RegDeleteKeyExW` with that view, corresponding to the original x86 `RegDeleteKeyW` operation. Its optional `test_namespace` maps the logical target beneath a fresh HKCU `Software\CBusToolkitCli\Tests` subtree; this is the only redirection accepted. Acceptance uses this redirection exclusively.

## Results and failures

`complete` requires that traversal finishes, the root delete returns zero, every recorded registry status is zero, and no exception occurs. The result also preserves the less strict original behavior:

- `original_boolean` is the root delete's Boolean result, or `None` if traversal stopped early.
- `original_notice_requested` means the original click handler would reach its notice request after the deletion wrapper returns. The handler ignores the deletion Boolean. This can be true even when deletion failed or the key was missing.
- `target_delete_succeeded` means only that the root delete call returned zero. Windows can defer deletion while another process holds a key open. `absence_verified` is always false: the coordinator does not perform a subsequent absence check.
- `already_absent` means the final root delete returned the missing-key status 2 or 3. It is not a claim that no concurrent process can recreate the key.
- `operations` preserves the ordered attempted/completed calls, returned statuses and error details. `issues` includes every nonzero status, even those ignored by the original algorithm.

The notice's original message identifier is `0x2bfc` (11260), with caption argument `WHITE`. The emulator records that request; it does not implement the GUI or infer the notice text. `notice_displayed` is false.

The operation is not transactional. Before deleting a parent, it queries its initial child count and visits enumeration indexes in descending order. Definite open/query/enumeration/child-delete/close status failures are retained and handled in the original order. A configured bound, malformed backend result or raised exception stops dependent operations; still-owned ancestor handles receive one close attempt. There is no rollback, retry, or replay after uncertain deletion.

Ordinary exceptions return an incomplete outcome and remain available as the exact `last_error` object. `KeyboardInterrupt` and `SystemExit` are re-raised by identity, even if formatting or attaching evidence fails or cleanup raises a second interruption. `last_outcome` and `last_evidence` provide fallback evidence; an exception also receives `toolkit_preferences_reset_evidence` when it permits attachment. Cleanup failures remain separate from the first error. Exported mappings are detached from the immutable outcome.

## Original and native evidence

The oracle executes hash-pinned instructions from `CBusToolkit.exe`, SHA-256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`:

| Original entry point | Address | Proven behavior |
|---|---:|---|
| `btnResetDontAskAgainClick` | `0xddf2d4` | Exact HKCU target, wrapper call, unconditional notice after return |
| `CIS_Registry.RegistryDeleteKey` | `0x8455ec` | Default registry object, root selection, ignored deletion Boolean, release |
| `TRegistry.Create` | `0x660b54` | Access mask `0xf003f`, HKCU, lazy-write field |
| `TRegistry.DeleteKey` | `0x6610a0` | Descending recursive enumeration and ignored child/status results |
| `TRegistry.GetKeyInfo` | `0x661250` | Initial child count and name-length allocation |
| `TRegistry.GetKey` | `0x661c68` | Open access and zero handle on failure |

Thirteen literal traces cover empty/missing/nested/Unicode trees and injected open, query, enumeration, child/root delete and close status failures. Original instructions use explicit fixtures for allocation, Delphi strings, Win32 operations, object release and the notice sink. The captured vectors use `SysLocale.FarEast=false`; the original alternate allocation-size branch is identified but not claimed by these vectors. OS exception dispatch, real GUI binding and concurrent registry modification are outside the original probe's acceptance scope.

Eight separate tests use actual Windows registry APIs through the owned Windows Python 3.13.14 x86 runtime. They check Unicode traversal, preservation of parent/sibling values, missing-key behavior, configurable limits, exact 32-bit view, scope/handle guards, and an interruption after an actual child deletion. All scratch namespaces are removed. Running this gateway from macOS Python 3.10 validates the host harness with that interpreter; it does not claim a Windows Python 3.10 run.

The portable output does not infer that an arbitrary injected backend is a verified Windows implementation; `actual_registry_backend_verified` remains false. Separate acceptance records contain the actual backend and runtime evidence.

For focused acceptance, set `CBUS_TOOLKIT_EXE` to the exact executable and `CBUS_WINDOWS_PROVENANCE_ROOT` to the current owned runner's verified provenance root, then run `tests.test_toolkit_preferences_reset` and `tests.test_windows_preferences_reset`. Original emulation requires `pefile` and `unicorn`; no vendor executable is packaged. The native gateway uses the frozen [`windows-python-runtime.json`](../research/fixtures/windows-python-runtime.json) manifest and never accesses the real Toolkit preference subtree.

The [compact acceptance record](../research/fixtures/toolkit-preferences-reset-acceptance.json) pins the final source, original vectors and raw report hashes. Both macOS host runs passed 11 tests without skips, including 13 freshly executed original traces and a gateway running the 8 Windows cases. This is focused acceptance of the new helper; it is separate from the previously frozen full-suite checkpoint.

An additional [64-bit Windows compatibility run](windows-preferences-compatibility.md) passed the same eight native reset cases under an isolated AMD64 Python process on Windows ARM64 emulation. It changed no adapter code or default public gateway.
