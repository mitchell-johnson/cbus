# Retained C-Gate repositories and large backups

cmqttd supports a **256 MiB (268,435,456-byte)** serialized version-one JSON
repository. This budget covers the whole durable model: active projects, saved
project images, internal archives, FILE contents, CONFIG/ACCESS snapshots and
other durable tables. It is a bounded cmqttd storage profile; it does not
establish Schneider repository formats or an original C-Gate capacity limit.
The per-command line, here-document, imported-unit XML and unit-specification
limits remain independently enforced.

## Storage and operator behavior

Commits stream JSON through a byte-counted writer into a newly created temporary
file beside the repository. A successful serialization is flushed and synced
before atomic rename; the containing directory is synced on Unix. Temporary
files created by a failed pre-rename attempt are removed. Exceeding the budget
or failing before rename leaves the old repository image in place, and the
owning service command restores its prior model and reports the existing
`500 Database commit failed; change rolled back` response. An I/O error after
rename, particularly directory sync, remains an uncertain durability boundary;
these tests do not establish universal disk-fault rollback, and operators must
inspect state rather than replay an uncertain save.

Startup checks the file size before deserializing and then reads through a
bounded streaming reader. Growth beyond the limit, including trailing
whitespace, refuses startup. Malformed, unsupported-version and oversized
repositories are errors; startup never resets them to an empty database.
Existing version-one repositories remain readable without a schema migration.
This change does not deploy or rewrite the house's Docker repository.

`DBGET` and `DBGETXML` use the existing database dispatcher after the same
admission, authorization and project-selection gates, without constructing
whole-repository rollback snapshots or comparing durable images. Their exact
responses and connection selection are preserved. Other commands retain their
existing transaction lane. Mutations still clone model/projection state; the
serialized-byte limit is not a process-memory, per-project or throughput bound.

Inspect `CMQTT CAPABILITIES` before depending on the profile:

```json
{
  "repository_max_bytes": 268435456,
  "repository_storage": "bounded-streamed-atomic-json-v1",
  "repository_snapshot_free_reads": ["DBGET", "DBGETXML"]
}
```

## Focused acceptance and remaining work

The retained synthetic service workload keeps sixteen large `PROJECT COPY`
backups simultaneously: seventeen saved graphs occupy 53,596,904 serialized
bytes. It compares every complete network document before and after a fresh
service restart; verifies physical observations remain on the source and never
appear on copies; checks foreign PP ownership refusal and owner session/lock
preservation; and proves 64 successful/refused database reads construct zero
durable snapshots and leave the repository bytes unchanged.

A separate real-daemon test performs copy/save/use/XML reads for all sixteen
backups, starts a fresh daemon process, loads all sixteen saved graphs and
checks complete readback. Its repository occupies 53,604,472 bytes before
restart and 53,611,400 afterward. The exact owned startup sweep is complete
before measuring repository work; that work produces no PCI frames. MQTT
lighting delivery to the scripted PCI continues after each epoch. These are
owned software fixtures, with no house, bridge or physical device acceptance.

Boundary tests cover exact encoded byte limits (including escaping and UTF-8),
overflow preservation/temporary cleanup, reader growth, malformed/trailing JSON,
rename failure, Unix owner-only permissions and oversized startup refusal.
The command-level rename failure retains the loaded model and owned PP session.
The required Rust gates and current Python integration outcomes are recorded in
the batch report; historical fixture failures are retained separately.

[Issue77](https://github.com/mitchell-johnson/cbus/issues/77) remains the broader
capacity/scaling work item. The new profile resolves the observed 32 MiB backup
failure for the retained workload. Original C-Gate workload comparison, larger
capacity profiles, mutation-memory scaling and post-rename disk-fault acceptance
remain unfinished. Never infer unlimited storage or broad native compatibility
from these bounded checks.
