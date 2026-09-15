# Windows project repair file boundary

The optional test gateway stages unchanged package sources in a new, hash-pinned
ZIP and runs the repair file API and complete CLI dispatch with the existing
owned Python 3.13.14 x86 and AMD64 runtimes. It does not install software or alter
PATH, registry settings, C-Gate, Toolkit projects, or hardware. Every extracted
runtime file is checked against its official-release manifest before testing.

Six host tests comprise four gateway/interruption checks and two native jobs.
Each native job contains 16 cases: Unicode and space/equals paths, exact binary
LF/CRLF output, Windows O_BINARY and exclusive creation, read-only preview,
existing-output/source preservation, directory/missing-file rejection, source
size/growth limits, invalid options and malformed transform stages, confirmed
short-write offsets, unknown partial writes, zero writes, fsync and source/output
close failures, primary KeyboardInterrupt/SystemExit preservation, separate-process
CLI dispatch, and CLI cancellation after actual partial output.

The fault fixtures wrap real Windows file descriptors. They distinguish confirmed
byte counts from bytes that may have reached a file before an exception. No
power-loss durability claim follows from these injected failures. Unix FIFO
behavior is not applicable on Windows; privilege-dependent symlink creation is
not exercised, and no privilege or host policy is changed.

The gateway records IsWow64Process2 process/native machine values, pointer width,
Python version, stdout encoding, every loaded package-source hash and raw job
artifacts. x86/AMD64 acceptance on the current ARM64 Windows 11 guest is emulated
process acceptance, not native x86/AMD64 hardware coverage. Test scratch trees
are removed and their absence is checked. Input ZIPs, harnesses and one-shot
bridge job artifacts are deliberately retained as evidence.

The first x86 pilot is preserved under
`research/runtime/project-repair-windows/pilot-x86-v1`. Fifteen cases passed; the
complete CLI case exposed a default-cp1252 output failure. Unicode-path preview
returned UnicodeEncodeError, and a repair created the correct 640-byte file but
could not print its success JSON. The following existing-target command rejected
replacement and left its bytes unchanged. The captured ZIP pins this pre-fix
behavior separately from subsequent acceptance.

The Windows checks do not establish native C-Gate loadability of arbitrary XML.
[Native loading of generated Python repair outputs](project-repair-native.md)
and the original repair-transform comparisons remain separate evidence.

Run the optional acceptance with an explicit live owned bridge generation:

```sh
CBUS_WINDOWS_PROVENANCE_ROOT=/absolute/owned/generation \
  PYTHONPATH=src:. python -m unittest tests.test_windows_project_repair -v
```

The gate requires the already staged owned runtimes and matching current bridge
provenance. It never installs a runtime, renews a runner, or replays an uncertain
job. A result-artifact sharing retry, when needed, reads the same admitted job
under the bridge's bounded policy.

The first post-fix runs (`final-313-v1` and `final-310-v1`) passed all six host
tests and all native file cases. Their harness had an overbroad derived
`emulated` boolean based only on IsWow64Process2's process-machine result. The
AMD64 process returned zero while the reported native machine was ARM64. Those
runs remain preserved; the final harness records the Python executable's actual
PE machine, both raw API values and their mismatch explicitly, without treating
zero as proof of matching architectures.

Final acceptance is pinned in
[windows-project-repair-acceptance.json](../research/fixtures/windows-project-repair-acceptance.json).
All six host tests passed on macOS Python 3.13.14 (25.544 seconds) and 3.10.20
(26.508 seconds), with no skips. Each host launched one Windows x86 job and one
AMD64 job; all four jobs passed their 16 cases and removed their scratch trees.
The 121 host input files were archived at launch and stayed unchanged. Each
Windows process loaded 35 package sources directly from its immutable ZIP; the
ZIP was identical across hosts for each architecture.

Both Windows runtimes retained their default cp1252 stdout/stderr and disabled
UTF-8 mode. The corrected CLI emitted valid ASCII-escaped JSON, preserving exact
Unicode source/output strings after decoding. The subprocess sequence returned
0 for preview, 0 for new output, and 1 for existing destination, oversized source
and malformed input. The output hash remained unchanged when replacement was
rejected. UTF-8 XML file bytes and CRLF/LF selection were unaffected by the JSON
rendering fix. All job-result reads completed without a sharing retry; no job
was resubmitted.
