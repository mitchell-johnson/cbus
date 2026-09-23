# Portable Windows acceptance provenance

Lifecycle and Restore native acceptance use `CBUS_WINDOWS_PROVENANCE_ROOT` to locate an explicitly owned runtime directory outside an immutable source snapshot. It must be an absolute directory containing:

```text
windows-bridge/v2/NativeWindowsBridgeV2.exe
windows-bridge/v2/bridge-ready.json
edlt-lifecycle/windows-runtime.json
```

With no override, the research harness uses its existing `research/runtime` directory. Vendor binaries and specifications still use their separate explicit settings.

`research.windows_provenance.resolve_windows_provenance` compares the local ready record and executable with read-only pulls from the owned v2 bridge. One fixed read-only Windows job then checks the runner PID/path and actual OS, .NET release, compiler and mscorlib hashes/versions. Those results must match the supplied runtime JSON. It rechecks the ready record and executable afterward, and rejects a stopped, changed or mismatched generation. The runtime JSON is not accepted merely because the file exists. The helper performs no Toolkit session, compilation, network-listener setup, physical operation or automatic retry.

Each original suite includes these external paths and hashes in its copied proof. Subsequent original executions recheck local files and the bridge generation. A renewed runner needs a new ready record and an explicit matching provenance root; historical accepted files remain unchanged.

Nine independent provenance tests and 23 existing Lifecycle/Restore tests passed on Python 3.13 and 3.10 with zero skips. A live query also passed against the old owned runner generation, with exact source hashes retained. That proves this resolver against that generation; later full acceptance must validate its own current runner. See [windows-provenance-acceptance.json](../research/fixtures/windows-provenance-acceptance.json). The complete original suites were not repeated for this harness-only correction; the next immutable full run covers their integration.
