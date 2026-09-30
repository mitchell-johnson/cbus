# IOPE JSON input admission

The standalone IOPE workflow reader applies the same regular-file pattern as
`edlt_templates_cli._read_bytes` to snapshots, edit options and saved plans.
Paths may name ordinary regular files or symlinks whose opened targets are
regular files. Directories, FIFOs, devices and sockets are refused.

The reader checks file type and the 1 MiB size limit before opening. It then
opens with the platform's nonblocking read flag and checks the actual opened
descriptor for regular-file type and size before reading. A path or symlink
substituted with a FIFO between the first check and open cannot wait for a
writer. The final read requests at most 1 MiB plus one byte; empty or oversized
actual input is refused even when size metadata was stale. Descriptors close
on admission failures and before JSON parsing. Existing UTF-8, duplicate-key
and non-finite-number validation is preserved.

These checks establish file admission and a bounded read. They do not establish
an immutable file snapshot: another writer may change a regular file during the
read, and regular-file substitutions remain permitted. Database plan input is
read before the C-Gate client is constructed.

Focused offline validation:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests:. python -B -m pytest -q \
  -p no:cacheprovider tests/test_iope_json_reader.py tests/test_iope_workflow_cli.py
```

The run passed 20 tests and 73 subtests with no skips. Independent review ran
all ten new reader tests with no skips. Fixtures use tiny synthetic JSON,
controlled descriptor metadata and guarded FIFO substitutions. Every real FIFO
snapshot, edits and saved-plan case (including FIFO symlinks) runs in a child
with a three-second timeout and a sentinel that fails if a C-Gate client is
constructed. The substitution test verifies the nonblocking flag before touching
the FIFO. No old blocking reader probe, native service, hardware operation or
full suite ran.

`research/fixtures/iope-json-reader-acceptance.json` binds the published base,
reader/test/document hashes and these executed cases. Prior native persistence
receipts were not refreshed; this change establishes the offline file boundary.
