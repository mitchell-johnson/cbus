# Unicode CLI output

CLI success results, errors and event records use ASCII-safe JSON escapes.
Decoding the JSON restores the original Unicode strings, including supplementary
characters. Output file encodings are controlled by their respective commands.

A native Windows probe exposed a completed repair returning exit status 1:
the output file had been written correctly, but printing its Unicode filename
failed on redirected cp1252 stdout. Both ordinary success output and event
stream output now escape Unicode before writing to stdout. The command is
never repeated to recover from an output encoding error.

The [focused acceptance](../research/fixtures/cli-json-output-acceptance.json)
records 17 passing tests on Python 3.13.14 and 3.10.20. New regressions use actual
strict cp1252 and ASCII text streams and cover repair preview, successful file
creation, existing-target rejection, events, compact output and custom JSON
types. They verify decoded Unicode paths, the actual repaired bytes, source
preservation and a single successful write. The other 14 tests cover the
existing repair file boundary and interruptions. Captured source bytes and
loaded module hashes are preserved separately from full-suite checkpoints.

The failed native pilot remains under
`research/runtime/project-repair-windows/pilot-x86-v1`; its successful file
creation and failed result emission are both retained as evidence. Broken pipes
and other stream I/O failures remain possible and do not imply that a requested
operation was rolled back.
