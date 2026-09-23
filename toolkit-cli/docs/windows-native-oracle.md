# Isolated Windows original-model oracle

This research bridge runs probes against the unchanged Toolkit **1.18.0.2754** assemblies on Windows using the installed .NET Framework compiler and x86 processes. It leaves the guest's existing Toolkit installation, C-Gate projects, and physical network connections untouched. It is research tooling, not a public CLI transport or evidence of physical-device acceptance.

The initial v1 runner created a new test directory, unpacked the staged official vendor files, recorded Windows file versions and SHA-256 hashes, and ran the initial Page Control probe. The current `research/NativeWindowsBridge.cs` is its v2 controlled-resume replacement: it requires the owned bootstrap, verifies all 25 staged files, verifies the previous process exit, and holds an exclusive runner lock. It is not an automatic fresh-VM installer. The runner listens on no network port, creates no credentials, changes no guest security policies, polls only its owned directory, processes each named request once, and stops after four guest-clock hours or an owned `stop.bridge` marker. Each command job has a five-minute limit. A timeout terminates its immediate command process; probes must not spawn persistent descendants. No firmware or physical C-Bus operations are part of this bridge.

The guest in this session already had Toolkit 1.16.3. The exact 1.18.0 assemblies were staged side by side rather than installed over it. The 25 original DLL/EXE files were checked against host copies. The principal Windows version/hash results are:

| File | Windows file version | SHA-256 |
|---|---|---|
| CBusToolkit.exe | 1.18.0.2754 | `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab` |
| CBusLogicModel.dll | 7.14.0.0 | `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823` |
| EDLT_graphics.dll | 1.3.0.0 | `e319379709c47f97dca477c4f631880f231c060530cb2ec45a3f731b1a5d1991` |

The default AnyCPU probe compiled successfully but failed with `BadImageFormatException` when Windows selected a 64-bit process. Compiling `/platform:x86` fixed that specific compatibility issue. The initial original-model run then matched all 284 independently written Page Control expectations, with empty stderr and exit zero. Its raw CRLF transcript SHA-256 is `5daa2a94d32cbcd4f08866c15ba13846762623f14296bb3166cb49b2360150bd`.

## Host API

Use `research/windows_bridge.py` from the repository root. `WindowsBridge` accepts explicit `vm_uuid`, `guest_root`, and `utmctl` paths; its defaults describe this session's owned VM fixture. `push(relative_path, bytes)` verifies the exact round trip, `pull(relative_path)` reads within the owned root, and `run(command_script)` returns separate exit, stdout, and stderr evidence. `submit`, `result`, and `wait` expose nonblocking submission and later collection. Job identifiers cannot be reused. The UTM executable can return status zero for missing guest files, so the helper checks stderr as well as exit status.

`WindowsModelProbe(source_path, original_app_directory)` checks the host original files against the staged 25-file Windows manifest, copies a uniquely named probe source, and compiles a uniquely named x86 executable beside the original assemblies. Optional `references=("eDLT.dll", ...)` accepts only simple DLL names present in the pinned staged vendor manifest; the fixed framework references remain separate. Its `run(arguments=(), files={name: bytes})` namespaces input files and rewrites matching filename arguments. Calls on one probe instance must be sequential because its input filenames are reused; independent instances can run concurrently. It rejects nonzero exits and any stderr. `run_result(...)` returns the actual process result without treating an expected vendor exception as a transport failure; callers must assert its exact exit/output contract. These manifests establish staged-file provenance; they are not an adversarial integrity monitor for subsequent guest modifications.

Example:

```python
from research.windows_bridge import WindowsModelProbe
probe = WindowsModelProbe('research/NativeEdltPageControlProbe.cs',
                          'research/vendor/toolkit/app')
rows = probe.run().splitlines()
assert len(rows) == 284
```

The Page Control tests select this backend only when `CBUS_WINDOWS_BRIDGE=1`. Their existing Docker/Mono path remains available when that flag is absent. Closed-database acceptance may independently target the task-owned C-Gate at `127.0.0.1:20033`; setting a Windows backend never opens a C-Bus network.

## Reproduction boundary

The guest runner requires an explicit launch once using a short owned `.cmd` file. UTM `file push` and `file pull` were verified; `utmctl exec` returned empty success without executing commands in this session. The bridge therefore used the guest UI only to launch the owned compiler/runner. Rapid keyboard entry proved unreliable; a verified autocomplete selection of the short launcher path was used. Subsequent probes use file jobs only.

Original vendor binaries, complete guest transcripts, generated executables, and host/guest manifests remain under ignored research runtime/vendor paths. The tracked runner and probes contain our integration code. The initial Page Control success proves model binding/setter behavior on Windows; full PP/CRC/save/reload and physical behavior have separate evidence requirements.


## Admission correction and handover

The v1 runner could encounter a Windows sharing violation while reading a `.ready.json` file still being uploaded. One Lifecycle job failed at that pre-execution read; its process never started. Its failure transcript remains separate from later results.

The v2 runner reads ready metadata and command bytes before admission. Incomplete JSON, sharing/access failures and a hash mismatch remain queued for up to 120 admission polls. Exhaustion produces `complete=false`, `pre_execution=true`, `admitted=false`, the attempt count and the intended hash when available. This is separate from a started process's result. No failed upload is silently treated as a successful probe.

After a matching hash, the runner writes those exact already-read bytes to a new `.admitted.cmd` snapshot and flushes it to disk. It then creates and flushes `.admitted.json` before invoking the process. It never rereads the mutable upload when executing. Any existing snapshot, admission marker or result prevents replay, including an interrupted process that has no final result. The host helper requires the v2 protocol and rejects reuse of any admitted identifier. A host timeout requires inspection of durable evidence; it is not permission to resubmit.

All nine tests in `research/NativeWindowsBridgeTests.cs` passed on actual Windows. They cover partial JSON, separate ready/script sharing violations, bounded hash/JSON rejection, immutable hashed snapshots, interruption after snapshot/admission, and an actual owned command that executes before its test process exits without a result. Restart does not execute that command again. A further live-runner upload test verified partial publication remains unadmitted, later valid publication executes once, and identifier reuse is rejected.

The handover stopped v1 PID 5564, observed its exit with matching path/start-time identity, and then launched v2. A native process listing verified one v2 PID 484 and no v1 process. The previous ready/stop markers were preserved as timestamped v1 backups. The new readiness records its own four-hour expiry. The v2 guest executable SHA-256 is `7d870cd1772936ca7e3de97a56cb443390da61e8484c1638629c5fb2b5ae5440`.

The compact [v2 bridge acceptance record](../research/fixtures/windows-bridge-v2-acceptance.json) pins both runner generations, the Windows tests, live publication test, handover/expiry records and host helper. Original-model/database acceptance records retain their own historical harness hashes rather than retroactively claiming the replacement was used.
