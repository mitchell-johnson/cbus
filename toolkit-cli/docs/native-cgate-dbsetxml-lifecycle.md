# Original C-Gate DBSETXML unsaved-change lifecycle

The [owned lifecycle capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_lifecycle.json)
has SHA-256 `2efb79d46563dfb636bab3cfc60df35895e5b85e0fe25522c39764d53cf1eeca`.
It records 49 tagged requests across four owned processes of Schneider C-Gate
3.4.0 build 2001 (`cgate.jar` SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`) under the
pinned Java 11 runtime. The [capture script](../research/cgate_dbsetxml_lifecycle.py)
and [owned-service harness](../research/local_cgate.py) are bound by SHA-256
and checked by
[`test_native_cgate_dbsetxml_lifecycle.py`](../tests/test_native_cgate_dbsetxml_lifecycle.py).

Each process ran in a new `LocalCGate` work directory with six verified
loopback listeners, confirmed exit and removed work directory. The synthetic
`XLIFE` project's Network 254 used the unopened CNI address `127.0.0.1:1`.
No `NET OPEN`, PCI, CNI, broker, physical network or site project was used.
A "restart" sent SIGTERM to the owned process, copied only its `Projects`
directory into the next owned work directory and started a new process there.
The fixture records each project file as a SHA-256, size and the synthetic
TagName markers it contains; no file contents are committed.

## Observations

- `PROJECT NEW` and `DBCREATENET` write no project file. The first
  `PROJECT SAVE` writes `Projects/XLIFE/XLIFE.db`; a later save rotates the
  previous file to `XLIFE.db.old`.
- A complete Network `DBSETXML` returns `301` and reads back immediately, but
  leaves the project file byte-identical (tags 106–108).
- `PROJECT CLOSE` then `PROJECT LOAD` without `SAVE` restores the saved tree:
  the added Unit 21 returns `401` and Unit 20 has its saved TagName
  (tags 108–112). With `SAVE` first, the replacement survives (113–118).
- `PROJECT LOAD` of an already loaded project returns `200` and keeps its
  unsaved edits (119–121). A later scalar `DBSET` behaves like `DBSETXML`:
  both are gone after CLOSE/LOAD (122–126).
- After SIGTERM and restart, `PROJECT LIST` is empty until `PROJECT LOAD`,
  which reads the last saved tree; the final unsaved replacement is lost
  (tags 127–128 and 300–304).
- `tag-autosave=yes` changes none of this (tags 500–511 and 700–702). The
  C-Gate manual documents it only for projects modified by a learn update.

## Rust disposition

Both Rust servers now keep a saved image per project, written by
`PROJECT SAVE`. `PROJECT CLOSE` restores that image; runtime network state
(open/closed, retry count, physical inventory and live levels) is kept for
every Network in the saved tree. `PROJECT LOAD` of a loaded project stays a
no-op. `dbsetxml_lifecycle.rs` replays the 29 no-autosave requests and
compares every status and each readback's Unit TagNames and addresses.

These boundaries are modeled without a native capture:

- Copy, rename, `PROJECT RESTORE` and a server-file `PROJECT LOAD` treat the
  resulting project as saved.
- The configured project is treated as saved at first import. Projects in a
  repository written before saved images existed are treated as saved at
  upgrade.
- Native CLOSE of a never-saved project unloads it, and its LOAD then fails
  with `408`. The Rust model keeps such a project unchanged rather than
  delete it.
- Scene snapshots are not part of the modeled saved tree.

cmqttd's durability guarantee differs from native on purpose. Every
accepted database change is committed atomically to its JSON repository,
along with the saved images. An unsaved edit therefore survives a daemon
restart or crash, while the persisted image still governs the next
`PROJECT CLOSE`. A bridge restart is not a client-requested unload, so it
must not silently discard edits a client has already seen acknowledged. For
the configured hardware project, a CLOSE whose saved tree would change the
configured Network's address or interface binding returns `408` and rolls
back. The service test
`unsaved_dbsetxml_reverts_on_close_but_survives_daemon_restart_without_pci_io`
covers revert, restart durability, the persisted image and that guard, with
no PCI traffic.
