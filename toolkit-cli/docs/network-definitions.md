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

On cmqttd, `NET LOAD DB` obtains definitions from the current tag database,
including Network rows with exact string addresses. Loading an empty project
succeeds with an empty catalogue; repeated loads add missing names and refresh matching definitions'
interface fields from those database rows. cmqttd preserves an existing
definition's immutable shared-PCI binding. Newly added database networks become
available without an earlier `NET SAVE DB`. Existing custom and renamed
definitions remain present, as do already loaded definitions whose database
row was later removed.

`NET SAVE DB` writes every current runtime definition into the loaded tag
database. A missing row gets Address equal to its exact runtime name, TagName
`n` followed by that name, and NetworkNumber `0xff`. Names such as `0254`, `254`,
`255`, `0xff`, `CustomA` and `Customa` remain distinct. A tag Network is therefore
not necessarily a physical network with an address in the range 0..255.
Existing rows retain their Network and Interface OIDs, TagName and NetworkNumber.
SAVE replaces interface metadata from the runtime definition and creates fresh
Property OIDs on each save. It does not move the shared PCI binding or open an
interface. Preserve the Network and Interface OIDs when comparing repeated saves;
do not expect Property OIDs to remain stable.

Native options are parsed as ordered key/value pairs after splitting on spaces
and `=`. Duplicate keys become separate Property rows, and a lone flag does not
create a Property. Inspect the saved XML rather than assuming that opaque runtime
option tokens map one-to-one to Properties.

```sh
cbus-toolkit cgate network definition create --project LAB \
  CustomA cni 127.0.0.1:10002 --option duplicate=one --option duplicate=two
cbus-toolkit cgate network definition save --project LAB DB
cbus-toolkit cgate database get-xml //LAB/CustomA --project LAB --output CustomA.xml
cbus-toolkit cgate project save LAB
cbus-toolkit cgate project close LAB
cbus-toolkit cgate project load LAB
```

For a named or OID scalar edit, select the loaded project on the same
connection. The command file below edits only the tag database:

```sh
cat > edit-network.cgate <<'EOF'
PROJECT USE LAB
DBSET //LAB/CustomA/TagName Workshop
PROJECT SAVE LAB
EOF
cbus-toolkit cgate run edit-network.cgate
cbus-toolkit cgate database get-xml //LAB/CustomA --project LAB --output Workshop.xml
```

Known tag mutations outside the selected project return 401 before changing
state. In particular, a separate `project use` CLI invocation cannot select a
later invocation's connection. This refusal is cmqttd's selected-project safety
boundary; the original SAVE experiment pins the selected DBSET sequence.

`NET SAVE DB` updates the loaded database. `PROJECT SAVE` commits that database
to the project baseline; CLOSE/LOAD discards unsaved materialization. cmqttd
also persists its repository state across daemon restart. These are separate
boundaries, and a successful catalogue save is not a project-save receipt.
Legacy cmqttd snapshots retain custom names for backward compatibility, while
current tag rows are authoritative. A stale numeric snapshot cannot resurrect
a deleted numeric database row.

The offline `project` commands accept these native string addresses in XML/CBZ
projects marked DBVersion 2.3, or the supported native Project/OID profile.
They retain exact case and spelling, duplicate Properties and complete subtrees.
Legacy projects retain their numeric address grammar. NetworkNumber remains an
independently validated byte; changing it does not rename Address or authorize
physical traffic to that value.
Complete cross-project copies allocate fresh OIDs. Unsafe same-project copies
of these named rows, and incomplete unsafe child additions, remain unsupported;
cmqttd refuses them before mutation. It does not report a successful copy with
the native pending-null semantics missing.

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
The FILE catalogue selector does not accept a file path. The separate
`cgate file-upload PATH SOURCE` command uploads a bounded local binary file to
the selected server's FILE service. It requires a relative server path; cmqttd
uses its virtual repository namespace. This is useful for its portable XML/SQL
conversion workflow, and does not establish native SQL-format interchange or
permission to read or write arbitrary server host files.

`NET SAVE DB`/`FILE` and catalogue mutations persist cmqttd's repository state;
`PROJECT SAVE` separately commits the project database baseline. Explicit
`PROJECT CLOSE`/`LOAD` verifies saved database state. Catalogue completion alone
does not prove a native interchange format, a successful interface open, device
readback or hardware persistence. Authentication and secure-deployment rules
come from the selected server.

## Validation and remaining scope

The acceptance batch uses disposable projects, owned loopback services and
independent no-contact interface traps. It checks native DB-versus-FILE rules,
public CLI creation, duplicate and uncertain replies, saved/reopened project
fields, runtime catalogue preservation and no post-startup PCI traffic.
See [the materialization batch report](feature-batch-2026-10-01-net-save-db-materialization.md)
for current artifacts and source/wheel acceptance, and
[the preceding catalogue report](feature-batch-2026-10-01-network-definitions.md)
for its historical evidence and GET dispatch correction.

Real adapters, opening additional interfaces, Toolkit dialog behavior,
bridge reference rewrites and physical
commissioning remain separate acceptance requirements. This does not change
the broad ledger or establish full Toolkit/C-Gate parity.
