# Ordinary numeric Level Value edits

Issue 131 addresses a database consistency gap in the owned Rust C-Gate
servers: an ordinary numeric `DBSETSAFE .../Value` could acknowledge an edit
without changing the authoritative Level XML. The adopted fix uses
the existing issued-Level-OID byte initializer and updates the selected numeric
Value mirror in the same staged commit. Fresh numeric, issued-OID and complete
XML readbacks agree after the edit and after SAVE/LOAD.

The isolated proof passed 13 library regressions, 12 source CLI cases, separate
fresh installed-wheel phases of six mock and six daemon cases, and four required
Rust gates. The adopted branch then passed its own exact 12 source CLI cases and
separate fresh wheel phases of six mock and six daemon cases using the current
installed-wheel runner. These are distinct epochs, not a repeated full suite.
A separate [resilience checkpoint](acceptance/2026-10-05-ordinary-level-resilience/report.md)
passed five source cases and fresh installed-wheel mock two/daemon three cases
for public NetVar interaction, lost receipts and disk-backed restart.
[Issue 131](https://github.com/mitchell-johnson/cbus/issues/131) remains open
pending merge and required CI at that checkpoint. The configured 1,067 explicit
identities plus seven whole modules were not fully executed in these proofs.
This guide applies to a build containing the fix. The [acceptance report](acceptance/2026-10-05-ordinary-level-value/report.md)
records the exact scopes and prior failures.

## Select and verify the owner

Use `--project` on each operation. It sends `PROJECT USE` on the same connection;
a separate CLI invocation does not select a later connection. The new adapter
accepts canonical decimal Network/Application/Group-or-NetVar/Level coordinates
for the selected loaded project, such as `//LEVELS/254/80/8/4` or `254/80/8/4`.
It does not reinterpret named or indexed selectors, leading-zero coordinates,
Unit fields, arbitrary scalar paths, or an associated tag-Network's raw owner.
These paths select a Level child beneath a Group or NetVar; the NetVar object
itself is not a Level byte owner. Nested NetVar child-Level mutation was covered
by the library proof. The historical 12 public CLI cases write Group Levels and
preserve the unrelated NetVar subtree. The separate five-case resilience proof
now writes its child Level from 66 to 42 and the Group Level from 77 to 99, while
preserving the complete ordered graph, identities, sibling byte and three
unrelated Unit PP values.

The server requires one complete typed Level with a known issued OID, a coherent
parent and matching pending/canonical mirrors. Competing, stale or incomplete
ownership refuses before mutation. A numeric getter also checks these facts
without repairing or publishing cache state.

`PROJECT COPY` can retain the same OID in multiple loaded projects. Selection
still chooses the project-scoped typed owner. A conflicting global `!OID/Value`
cache is tolerated only when another loaded, coherent, unassociated project
with that same Level OID explains its exact byte. An unexplained cache mismatch
refuses; the cache alone cannot select an owner. This checks a presently
coherent owner and byte, not which historical writer introduced the cache entry.
It does not redesign every generic issued-OID or shared Unit-OID route.

## Write one byte and read back the whole graph

`LEVELS`, `HOST`, `PORT`, addresses and `LEVEL_OID` below are placeholders. Use a
reviewed endpoint, an already loaded project and the actual unique Level OID
from a fresh authoritative XML read or `301 OID=…` receipt.

```sh
cbus-toolkit cgate --host HOST --port PORT database get-xml //LEVELS/254/80 --project LEVELS
cbus-toolkit cgate --host HOST --port PORT database get //LEVELS/254/80/8/4/Value --project LEVELS
cbus-toolkit cgate --host HOST --port PORT database set //LEVELS/254/80/8/4/Value 99 --project LEVELS
cbus-toolkit cgate --host HOST --port PORT database get //LEVELS/254/80/8/4/Value --project LEVELS
cbus-toolkit cgate --host HOST --port PORT database get '!LEVEL_OID/Value' --project LEVELS
cbus-toolkit cgate --host HOST --port PORT database get-xml //LEVELS/254/80 --project LEVELS
```

The CLI sends one `DBSETSAFE`. Use a decimal byte from 0 through 255. The
implementation reuses the existing issued-OID initializer's integer grammar and
error replies; it does not claim new native lexical parity. The public tests
require atomic `400 Invalid level value` refusals for `-1`, `256`, `oops`,
`null`, `1.5` and an overflowing signed integer, with the complete graph and
both readbacks unchanged. A same-byte write retains the graph and identities.

An ordinary Level with a genuinely absent Value can be initialized to a byte;
the prior getter reports `null`. This includes an admitted copied pending NULL
Level. The fix does not relax numeric Value requirements for complete typed
XML import or turn an opaque raw Value into an ordinary byte. Existing copied
LOAD metadata timing remains intact: an absent copied label collection can
gain its deferred empty `TagsDLT` on LOAD, without changing the original Level.

Review the response and complete Project/Application graph, including unrelated
fields and OIDs. `database set` does not save the project. If persistence is
intended, save and reload the changed project explicitly:

```sh
cbus-toolkit cgate --host HOST --port PORT project save LEVELS
cbus-toolkit cgate --host HOST --port PORT project close LEVELS
cbus-toolkit cgate --host HOST --port PORT project load LEVELS
cbus-toolkit cgate --host HOST --port PORT database get-xml //LEVELS/254/80 --project LEVELS
```

This edits the database model and performs no device programming. If a write or
save receipt is uncertain, do not replay it automatically. The historical
12-case packet did not inject lost receipts. The separate five-case proof drops
actual successful Value and project-save terminals, forwards each target once
and checks fresh effects without retry, inverse cleanup or another write/save.
Explicit CLOSE/LOAD after a lost save verifies the saved image separately.

The restart case saves the Group and NetVar child edits, reaps the first daemon
and opens a second owned context against the same explicit state file. Complete
graph and PP readbacks survive without reseeding, rewriting or another save.

## Existing raw owners remain separate

The unsafe `DBSET` body is unchanged. Its ordinary materialized byte owner still
refuses non-byte text; a valid unsafe byte control preserves its established
reply and effect. An existing associated tag-Network raw owner can retain an
opaque lexeme through its established routes and SAVE/LOAD. The new adapter
defers that owner rather than treating its text as a byte. Creating a Languages
collection to establish an association is a database mutation, not a general
raw-write workaround.

Owned model consistency and the source-backed byte/raw/NULL policy are the
accepted scope of these proofs. The five-case checkpoint supplies the remaining
local owned interactions; new native execution is not its closure precondition.
Exact native equivalence, hardware persistence, complete Toolkit parity and
full execution of the configured 1,067 explicit identities plus seven whole
modules remain separate obligations.
