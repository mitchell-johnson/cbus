# Repair a project XML file

```sh
cbus-toolkit project repair broken.xml --dry-run
cbus-toolkit project repair broken.xml --output repaired.xml
cbus-toolkit project repair broken.xml --output repaired-crlf.xml --line-ending crlf
```

The command reads a regular file, computes the portable lexical repair and both repair transforms, and writes a new output file when requested. It does not change the source, connect to C-Gate, open a project repository, or contact hardware. Repair completion and well-formed output do not establish that C-Gate will load the project.

`--dry-run` needs no output path and performs no output writes. It returns the computed repair evidence, including the expected output size and SHA-256. A normal run requires `--output`; the file is created exclusively. An existing file, symlink or the source path is never overwritten. The command neither creates missing parent directories nor automatically removes a failed partial output.

`--max-bytes` defaults to 8 MiB and accepts 1 through 64 MiB. It bounds source reads and transformed output through the portable repair API. The source must be a regular file: directories, symlinks and special files are rejected before opening; a descriptor check also verifies the opened object. Nonblocking open is requested where available to avoid a FIFO wait if the path changes. The size is checked before reading and each read is capped so growth beyond the limit stops before output creation. A concurrent source writer is not locked out; the reported source hash describes the bytes actually read.

## Writes and failure evidence

The new output is written using checked byte counts, followed by file `fsync` and one close attempt. No write or close is retried after an uncertain exception. Successful short writes continue at the confirmed byte offset; a zero or invalid count stops. The source closes before transformation/output creation, so a failed source close does not start an output write.

Results distinguish output creation, confirmed written bytes, completed writes, file-sync success and close success. `output_bytes_confirmed` is a lower bound when a write raises after modifying the file. `output_may_exist` and `output_may_be_partial` retain uncertainty; failed repair never implies that no output bytes were written. No rollback, replay or automatic deletion is performed. File sync is not a directory-sync or crash-recovery guarantee.

The nested `repair.output_sha256` is the hash of the **computed payload**. It is not an independent readback of the output file. The write operation checks counts, sync and close; only the acceptance tests separately read their owned outputs to verify them.

`stage` identifies file/transform progress. If the portable repair API fails, `repair_failure_stage` retains its more specific `manual`, `repair`, `tidy`, `verify` or bounds stage. `ProjectRepairFileError.details` contains the attempted-operation evidence and `original_error` preserves the underlying ordinary exception. `KeyboardInterrupt` and `SystemExit` preserve the original object; attachment is best effort and the CLI can recover evidence from the current operation by exact error identity. Secondary cleanup or evidence-export failures do not replace the first error. A reused operation clears previous evidence.

The Python boundary is `ProjectRepairFileOperation().run(source, output=..., dry_run=False, line_ending='lf', max_bytes=...)` in `project_repair_cli.py`. `options`, `run(args)` and `error_payload` implement the shared CLI integration.

## Acceptance scope

The [focused file/CLI fixture](../research/fixtures/project-repair-file-acceptance.json) records 14 tests on macOS Python 3.13.14 and 3.10.20. They include actual new-file output, exclusive-create rejection, FIFO/symlink guards, read growth, partial write mutation, zero writes, fsync/close failures, precise transform stages, and primary-interruption evidence through the integrated CLI. No Windows file-boundary acceptance is claimed by these runs.

The separate [Windows acceptance](windows-project-repair.md) passed six host tests on each Python version, including 16 native file/CLI cases on each of the existing Windows Python 3.13.14 x86 and AMD64 runtimes. All four native jobs passed and removed their owned scratch trees. These runtimes execute on an ARM64 Windows 11 guest; executable PE architecture and raw Windows architecture-query results are recorded separately. Unix FIFO behavior and privilege-dependent symlink creation are excluded from this Windows scope.

The first Windows pilot found that default cp1252 stdout could reject a Unicode success response after the output file had already been written. The CLI now emits ASCII-escaped JSON, preserving exact Unicode paths after JSON decoding. Final native subprocess cases retain cp1252 with UTF-8 mode disabled and verify preview, new output, existing-target rejection, source bounds and malformed input. The XML output remains UTF-8, and the JSON change does not replay the repair or alter LF/CRLF file bytes. Exact inputs, the initial failure and final results are pinned in [windows-project-repair-acceptance.json](../research/fixtures/windows-project-repair-acceptance.json).

The [portable repair acceptance](../research/fixtures/project-repair-portable-acceptance.json) separately covers the original lexical and transform semantics. Independent review exposed CR text changing group identity between stages, Python 3.10 attribute-whitespace serialization, namespace undeclaration handling and UTF-16 acceptance differences. The corrected implementation matched all 72 captured original edge outcomes on both Python versions before file-boundary integration. Historical failed review outputs remain separate from the accepted results. Neither fixture changes a frozen full-suite checkpoint's claims.
