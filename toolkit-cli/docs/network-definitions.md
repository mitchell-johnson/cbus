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

For a named or OID database operation, pass `--project` to select the loaded
project on that invocation's connection. Get, set, add, copy, delete, validate,
get-xml and set-xml share this option. For example:

```sh
cbus-toolkit cgate database get //LAB/CustomA/TagName --project LAB
cbus-toolkit cgate database set //LAB/CustomA/TagName Workshop --project LAB
cbus-toolkit cgate database add //LAB/CustomA application 56 Lighting --project LAB
cbus-toolkit cgate database add //LAB/CustomA/56 group 1 Lamp --project LAB
cbus-toolkit cgate database add //LAB/CustomA/56/1 level 7 Evening --project LAB
cbus-toolkit cgate database validate //LAB/CustomA --project LAB
cbus-toolkit cgate project save LAB
```

These examples require an existing loaded `LAB/CustomA` and unused child
addresses. Typed add/copy use DBADDSAFE/DBCOPYSAFE; a Level creation also reads
the issued OID and initializes its Value to the requested byte on that same
connection. Raw DBCOPYSAFE retains the source Level Value until explicitly
edited. A selection refusal or lost reply stops the dependent operation;
the CLI does not reconnect or replay. Selection does not implicitly load,
save or open a project/network, or rewrite a qualified path to another project.

For an explicitly selected multi-command session, a command file remains
useful. The following edits only the tag database:

```sh
cat > edit-network.cgate <<'EOF'
PROJECT USE LAB
DBSET //LAB/CustomA/TagName Workshop
PROJECT SAVE LAB
EOF
cbus-toolkit cgate run edit-network.cgate
cbus-toolkit cgate database get-xml //LAB/CustomA --project LAB --output Workshop.xml
```

An existing numeric database Network in a secondary project may also have a
renamed tag Address. Admitted Level add/copy through its renamed qualified or
bare path, or its Group/NetVar OID, follows the original numeric database owner.
It does not create another physical Network. See the
[associated Level workflow](feature-batch-2026-10-02-associated-levels.md) for
selection, Value initialization and save/reload. The
[raw Value extension](feature-batch-2026-10-02-associated-raw-level-values.md)
retains nonempty scalar Value strings on existing associated Levels under a
Group or NetVar. The [empty TagsDLT extension](feature-batch-2026-10-02-empty-tags-copy.md)
admits one strict empty Level collection after reload, preserving the source and
the destination's owner. Other decorations remain unsupported.
The service's existing restriction on renaming any Network inside
its configured hardware project remains.

OID mutations are selected-project scoped. Absolute named DBADD/DBADDSAFE
parents can target their qualified project without changing the current
selection, as observed in original C-Gate; this does not authorize an OID
mutation in that other project. A separate `project use` CLI invocation cannot
select a later invocation's connection. Explicit `--project` keeps standalone
typed operations predictable. LOGIN requirements still precede mutation.

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
Projects with an explicit older DBVersion retain numeric address aliases.
An unversioned Network with NetworkNumber `255` also selects the native lexical
address profile. This includes a Network added to the unversioned Installation
created by `project new`: Address `254` with NetworkNumber `255` resolves as
exact `254`, and its numeric alias `0xfe` does not resolve. Offline project
validation and complete external DBSETXML require an independent byte
NetworkNumber (including the supported `0xff` spelling). Changing it does not
rename Address or authorize physical traffic to that value.
Independent named database Networks support SAFE Application, Group, NetVar
and Level construction/copy. Group and NetVar can contain Levels; NetVar is an
Application child and has no Value field of its own. The admitted copies issue
fresh OIDs for modeled descendants and preserve the source graph.

Raw DBADD and same-project DBCOPY also retain incomplete named graphs by OID.
The unsafe Network-copy parent is `Installation/Project`, its qualified form,
or the selected Project OID. A bare project name is not that unsafe parent.
Copy clears the tagged objects' Address/TagName while retaining NetworkNumber,
Interface/Property metadata and Level Values. Missing TagName causes XML export
444 and project save 408; a named object without Address can be saved, while a
Level additionally needs Value. Child completion preserves creation order and
the issued OIDs. Unsafe Address writes retain literal values and duplicates;
SAFE byte/collision checks are a separate admission boundary.

Raw DBSET and DBSETSAFE on an independently owned named Network retain scalar
lexemes for NetworkNumber and Level Value. Original C-Gate accepts `255`,
`0xff`, `999`, `oops` and `-1`; a separate captured SAFE NetworkNumber=`999` and
Level Value=`oops` case also validates, saves and reloads. cmqttd preserves this
raw metadata behavior. Typed child
creation still validates the requested address and initializes Level Value to
a byte, and complete external XML admission remains strict. This does not
establish original acceptance on numeric-associated or configured physical rows.

On an existing numeric-associated Level, `database set PATH/Value VALUE
--project NAME` now retains a nonempty non-byte scalar tail, including `0xff`,
`999`, `oops`, `-1`, multiword text and XML-representable Unicode. For scalar
Value reads/writes, qualified and bare exact canonical numeric paths, renamed
lexical paths and the issued Level OID resolve the same
authoritative owner. An existing independent numeric-looking Network keeps its
lexical precedence on successfully resolved objects. Existing C-Gate tokenization folds tail whitespace to single
spaces. SAFE recognizes an i64 in byte range; unsafe recognizes a u8. Byte
values keep decimal canonicalization: `077` and `+77` read back as `77`, while
SAFE `-0` becomes `0` and unsafe `-0` remains text. Literal `null` is stored text and remains
distinct from a Level whose Value is absent in XML. Neither scalar writes nor
reads send PCI traffic, and project persistence still requires explicit SAVE.
Bare numeric object DBGETXML remains unsupported (`404` in owned service tests).
Uniform Level XML reads use a renamed qualified/bare path or OID; qualified
numeric object XML uses legacy owner-dependent projection; its raw/renamed profiles are outside this acceptance.

Raw Value storage survives project SAVE/CLOSE/LOAD and cmqttd's internal JSON
restart, preserving OIDs, exact completed pending mirrors and unrelated data.
DBCOPY/DBCOPYSAFE of a raw Level or a containing subtree and tag-tree resynchronization
refuse atomically with local `408` before a lossy byte/NULL projection. Numeric
aliases and OID suffixes cannot bypass that preservation guard. These refusals
are local limits, not original error-code equivalence. Complete external
DBSETXML remains strict and does not admit exported raw Value documents. Empty
SAFE values and `#` retain existing validation; XML-unrepresentable characters
refuse before mutation. See the new report for execution evidence and the
remaining raw-copy, NULL/NetVar-parent and original acceptance work.


Known associated-owner bugs are deferred in [issue #74](https://github.com/mitchell-johnson/cbus/issues/74):
canonical numeric Group COPY destinations return `401`, while renamed lexical
paths and Group OIDs succeed for admitted byte copies. The newer LOAD sweep
can also alter unsupported retained XML on a plain Level with a deferred empty
label marker. Those payloads are outside the accepted LOAD profile. A separate
missing-descendant Value-getter fallback is an unverified source-review
hypothesis. The attempted fixture failed before that edge executed. These
corrections were stopped by cyber protection; no private untested edits are
integrated or credited.

Deleting an independent Network's Interface removes that metadata and its OID.
The remaining tree can validate, save/reload internally and load as a closed
runtime definition with empty interface metadata. Missing InterfaceType and
InterfaceAddress aliases return `401` for reads and writes. NET SAVE DB refuses
atomically with `408` until the required metadata exists; the captured original
returns `500` for this case. SAFE rename to an occupied Network address also
refuses atomically with `408`, where the original returns `500` without changing
either owner. These controlled error responses are deliberate liveness repairs.
Numeric-associated/configured rows retain their complete Interface requirement.

Incomplete graphs survive cmqttd's internal JSON restart and explicit project
baseline reload. They do not widen complete external DBSETXML or native archive
admission: exporting such a graph does not prove it can be restored through a
complete-XML parser. New unsafe/deep-child copies containing Units or unmodeled
OID-bearing XML refuse before mutation. Renamed numeric-associated Level ADD and
Level-source COPY now have the bounded owner route described above; associated
raw copying, NULL/NetVar-parent reconciliation and decorated copies remain open, together with
broader duplicate-selector precedence and full Project-OID operations.
Local deletion retires descendant
OIDs immediately; original C-Gate was observed to retain stale descendant reads
until reload. No native bug-equivalence or full workflow parity is claimed.

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
See [the integration corrections](feature-batch-2026-10-01-net-save-db-integration.md)
for physical/database ownership fixes, and
[the export-order checkpoint](feature-batch-2026-10-01-net-save-db-export-order.md)
for current evidence of Network creation-order export. See
[the materialization batch report](feature-batch-2026-10-01-net-save-db-materialization.md)
for the first candidate's preserved evidence. See
[the preceding catalogue report](feature-batch-2026-10-01-network-definitions.md)
for its historical evidence and GET dispatch correction.

Real adapters, opening additional interfaces, Toolkit dialog behavior,
bridge reference rewrites and physical
commissioning remain separate acceptance requirements. This does not change
the broad ledger or establish full Toolkit/C-Gate parity.
