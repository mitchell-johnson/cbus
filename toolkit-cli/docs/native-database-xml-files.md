# Native C-Gate database XML files

The Python CLI can export one `DBGETXML` object to a new UTF-8 file and submit
one complete file through native `DBSETXML`. This is useful for reviewing and
editing a saved project Group or eDLT label tree. It operates on the selected
C-Gate server's **database**, not on a physical unit's label cache.

```sh
cbus-toolkit cgate --host HOST database get-xml \
  //PROJECT/254/56/1 --project PROJECT --output group.xml
# Review and edit a separate copy of group.xml; retain its XML root and OIDs.
cbus-toolkit cgate --host HOST database set-xml \
  //PROJECT/254/56/1 edited-group.xml --project PROJECT \
  --expect-current-sha256 SHA256_FROM_EXPORT --readback
cbus-toolkit cgate --host HOST project save PROJECT
```

Each invocation opens a new C-Gate session. `--project` selects the loaded
project on that session before the database command. `get-xml --output` writes
the native `347` XML snippet to a **new** file and emits its byte count and
SHA-256; it refuses to overwrite an existing destination. Without `--output`,
`get-xml` keeps the existing JSON response behavior. The export is a single
object snapshot, not a whole-project backup.

For an export that exceeds the existing 4 MiB line or 16 MiB response bound,
declare an explicit document budget in bytes:

```sh
cbus-toolkit cgate --host HOST database get-xml //PROJECT \
  --project PROJECT --output project.xml --max-xml-bytes 25165824
```

`--max-xml-bytes` requires `--output` and accepts 1..134217728 (128 MiB).
It bounds the exported UTF-8 snippet; transport admits at most that budget
plus 64 KiB for command/status framing. The independent 100,000-response-line
limit still applies. This export connection retains at most one unsolicited
event; a second event interrupts the read without publication or retry. This
keeps the widened line bound from multiplying across the ordinary event queue.
The option affects only this read-only
export connection, and ordinary reads retain their existing limits. A failed
or oversized read publishes no file and is never retried. A destination that
already exists is rejected before connecting; a competing writer is also
protected by the existing no-overwrite publication step.

The configured client ceiling is not a server capacity guarantee. Both owned
Rust servers retain a separate 32 MiB queued-wire batch limit; larger replies
can be refused or disconnected by the server. This path materializes the reply
and XML in memory, so the document budget is not a total process-memory cap.
The independent owned loopback wire tests retain a 17 MiB single-line XML
export, exact byte/hash comparison, unchanged default rejection and failure
without publication or replay. They establish no original C-Gate capacity,
maximum-size throughput, filesystem power-loss durability, physical behavior
or full Toolkit parity. `set-xml` and its limits are unchanged.

`set-xml` reads a nonempty UTF-8 file of at most 16 MiB and sends one C-Gate
here-document. It reports the source file's SHA-256 and the native `200` or
`301` receipt. The transport normalizes CRLF before transmission, so the
source-file digest identifies the supplied file, not necessarily the exact
wire bytes. `--expect-current-sha256` compares a fresh `DBGETXML` snippet to
the **export** digest before submission and refuses a mismatch. This is a
read-before-write guard; C-Gate does not offer an atomic compare-and-swap and
another client could change the object between the read and the write.

`--readback` fetches the target after an accepted write and reports the
native-mapped XML's hash and byte count. Native C-Gate can normalize fields,
issue OIDs, or discard unsupported markup; compare the readback with the
intended fields instead of expecting source-file byte equality. If readback
fails after acceptance, the CLI returns a nonzero status with `accepted: true`
and the error, and does **not** replay the write. The command does not issue
`PROJECT SAVE`; perform a reviewed save separately for original C-Gate
persistence. cmqttd has its own durable database transaction, but a file
receipt alone does not establish a physical unit write.

The target path must be a single C-Gate token. XML and command framing are
validated before any document bytes are sent. The public CLI workflow is
covered by a `cgate-mock` TCP interop test and an optional owned original
C-Gate 3.4.0.2001 loopback test. The latter pins its Java 11 and C-Gate JAR,
uses an unreachable synthetic CNI, verifies Group `TagsDLT` OID issuance,
stale-guard refusal, save/close/load persistence, listener ownership, and
cleanup. Run it with `CBUS_CGATE_JAVA` and `CBUS_LOCAL_CGATE_VENDOR` pointing
to the pinned disposable service; otherwise the test explicitly skips. This
does not prove every XML class or variant, physical eDLT label-cache write,
concurrent update safety, or full Toolkit GUI behavior.
