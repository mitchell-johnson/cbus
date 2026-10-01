# Closed network setup and runtime definitions

`cbus-toolkit cgate database network-new` creates a network in a loaded project database
and loads its closed runtime definition. It does not open an interface, discover
units, save the project or contact C-Bus. Use it through cmqttd or the explicitly
selected original C-Gate server:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 project new LAB
cbus-toolkit cgate --host 127.0.0.1 --port 20023 database network-new \
  LAB 254 Local Cni 127.0.0.1:10001
cbus-toolkit cgate --host 127.0.0.1 --port 20023 network list --project LAB
cbus-toolkit cgate --host 127.0.0.1 --port 20023 get //LAB/254 InterfaceState
cbus-toolkit cgate --host 127.0.0.1 --port 20023 project save LAB
cbus-toolkit cgate --host 127.0.0.1 --port 20023 project close LAB
cbus-toolkit cgate --host 127.0.0.1 --port 20023 project load LAB
```

The example endpoint is a placeholder for a future interface. These setup
commands leave it closed. `network-new` supports `Serial`, `Cni` and `Bridge`
database interfaces. It selects the project on its own connection, sends one
`DBCREATENET` and then one `NET LOAD DB`. Creation must return cmqttd's legacy
200 or the original server's 301 with one UUID OID receipt; loading must return
exactly 200 before the CLI reports success. The 200-versus-301 creation response
is a remaining cmqttd wire deviation. If creation succeeds and loading fails or its reply is
lost, the created database row may already exist. Inspect it and the runtime
list; the CLI never deletes it, automatically retries or opens the network.

## Runtime catalogue

`cgate network definition` manages the runtime catalogue explicitly. Every
operation requires `--project`; names are plain tokens rather than database
paths. Inputs are validated before connection and project selection. The
current connection selects that project before issuing its single operation.

```sh
cbus-toolkit cgate network definition list --project LAB
cbus-toolkit cgate network definition create --project LAB \
  GARAGE cni 127.0.0.1:10002 --option alpha=beta
cbus-toolkit cgate network definition rename --project LAB GARAGE SHED
cbus-toolkit cgate network definition save --project LAB FILE
cbus-toolkit cgate network definition delete --project LAB SHED
cbus-toolkit cgate network definition load --project LAB FILE
cbus-toolkit cgate network definition flush --project LAB 254
```

Use the same explicit `--host` and `--port` connection options as the first
example when the server is not the CLI default. CREATE supports the retained
`serial`, `cni`, `bridge`, `etherlite`, `socket`, `modem` and `wiser` type names;
repeat `--option` for additional single native option tokens. Passing a type or
option does not establish adapter support or validate that interface's settings.
RENAME accepts `--no-fix-references` for the native `nofixrefs` selector. On
cmqttd it changes the catalogue name and preserves the immutable shared-PCI
binding; it does not rename the project database network. FLUSH clears volatile
observations for the selected definition, leaving saved project data intact.

LIST accepts native 131 (entries) and 132 (empty catalogue). Every mutation
requires exactly 200. Confirmation, help, queued-only or uncertain responses
do not become a success receipt, and no operation is replayed.

## DB and FILE are different sources

On cmqttd, `NET LOAD DB` obtains numeric-address definitions from the current
tag database. Loading an empty project succeeds with an empty catalogue;
repeated loads add missing numeric names and refresh matching definitions'
interface fields from those database rows. cmqttd preserves an existing
definition's immutable shared-PCI binding. Newly added database networks become
available without an earlier `NET SAVE DB`. Existing custom and renamed
definitions remain present, as do already loaded definitions whose database
row was later removed.

Legacy cmqttd DB snapshots retain names outside canonical decimal 0..255 for
backward compatibility. Numeric definitions are taken from current database
rows, so an old snapshot cannot resurrect a removed numeric network. Native
`NET SAVE DB` can also create missing tag Network rows from runtime definitions,
including a numeric name with NetworkNumber 255. That runtime-to-tag database
projection is outside this batch and remains outstanding in cmqttd; its current
SAVE DB stores an internal snapshot.

`cgate get //PROJECT/NAME Name`, `Type`, `InterfaceAddress`, `Interface` and
`Options` inspect an existing runtime definition. Interface and InterfaceAddress
are aliases for its endpoint; Options retains space-separated tokens. A DB edit
does not change these fields until an explicit DB load. Other GET selectors
retain their existing dispatch and acceptance boundaries.
Use the explicit `//PROJECT/NAME` path for these cmqttd catalogue fields. Bare
server selectors such as `cgate` and issued `!OID` references retain their
existing meaning, even if a runtime definition has the same name.

On cmqttd, FILE selects an internal atomic repository snapshot. It is never a
host filename. A missing snapshot is an empty load. Existing snapshots merge
only if none of their names collide with active definitions; a collision
returns native 408 before changing the catalogue. The original C-Gate server
uses its configured networks file for this selector and can insert earlier
noncolliding names before a later 408. cmqttd's atomic refusal is an intentional
deviation from that observed partial-load behavior. Original testing also found FILE restoration with two opaque option tokens
returning 408; clean restored definitions return literal `null` for Options.
Native option restoration and FILE-format parity are outside this contract.
No CLI command here accepts an arbitrary file path or silently switches repositories.

`NET SAVE DB`/`FILE` and catalogue mutations persist cmqttd's internal catalogue
state; `PROJECT SAVE` separately persists the project database. Explicit
`PROJECT CLOSE`/`LOAD` verifies saved database state. Catalogue completion alone
does not prove a native interchange format, a successful interface open, device
readback or hardware persistence. Authentication and secure-deployment rules
come from the selected server.

## Validation and remaining scope

The acceptance batch uses disposable projects, owned loopback services and
independent no-contact interface traps. It checks native DB-versus-FILE rules,
public CLI creation, duplicate and uncertain replies, saved/reopened project
fields, runtime catalogue preservation and no post-startup PCI traffic.
See [the batch report](feature-batch-2026-10-01-network-definitions.md) for exact
artifacts, cases, prior failures and source/wheel acceptance.

Real adapters, opening additional interfaces, arbitrary named native tag
networks, Toolkit dialog behavior, bridge reference rewrites and physical
commissioning remain separate acceptance requirements. This does not change
the broad ledger or establish full Toolkit/C-Gate parity.
