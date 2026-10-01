# Runtime definitions saved as native tag Networks

`NET SAVE DB` now writes cmqttd's current runtime network definitions into its
loaded project database. The Python Toolkit CLI retains the resulting complete
Network trees, including exact string addresses, OIDs, Interface Properties and
later database edits. The workflow can save, reopen, copy, archive, export and
restart a project without confusing a tag address with a physical C-Bus network.

This is a bounded software milestone for
[issue 27](https://github.com/mitchell-johnson/cbus/issues/27),
[issue 29](https://github.com/mitchell-johnson/cbus/issues/29) and
[issue 32](https://github.com/mitchell-johnson/cbus/issues/32).
Their wider original Toolkit and hardware obligations remain open. No house
network, real adapter, Windows VM or physical C-Bus device was used.

## Delivered behavior

A missing tag row receives the exact runtime name as Address, `nNAME` as
TagName, NetworkNumber `0xff`, and fresh Network/Interface/Property OIDs.
`42`, `0254`, `254`, `256`, `255`, `0xff`, `CustomA` and `Customa` do not collapse
into a numeric network map. Existing rows preserve Network/Interface OIDs,
TagName and the exact NetworkNumber spelling. Interface metadata comes from
the runtime definition even when there was no intervening DB load.

Each repeated SAVE creates fresh Property OIDs. The native option rule splits
whitespace and `=` into ordered sequential pairs: duplicates remain separate
Properties, a lone flag produces no Property, and mixed flag/value tokens can
pair differently from the operator's intention. XML metacharacters are escaped
and preserved. This does not claim arbitrary escaped-token support in the typed
CLI's plain-token grammar.

The numeric network map continues to own physical addressing, topology and the
shared PCI connection. A saved tag Interface may differ from that immutable
transport metadata. Database-only edits retain later Unit/Application/PP changes,
current OID ownership, physical inventory and live state. Export uses one complete
current tree rather than a stale SAVE snapshot.

Runtime storage keeps creation order separately from NET LIST's sorted display.
Parsed tag documents retain scalar/child interleaving and the native empty PP
form. The existing numeric Unit mapper can normalize a redundant `oid` attribute
and legacy scalar order during import; imported OID, scalar and PP values remain
checked, and new string-address subtrees retain their complete structure.

The later-edit checks also repair preexisting SAFE Application/Group additions
that previously reported 200 while remaining absent from Network XML. They now
use the typed database owner and retain the same completion receipt. Associated
Level OID edits use that owner's setter rather than an opaque direct-path field.

DBGETXML and DBGET expose rows by exact name or selected-project OID. DBSET,
DBSETXML, deletion and copy operate on that authoritative tree. Select the project
on the same connection before named or OID scalar mutations. A known tag
selector outside that selected scope is refused with 401 before mutation; this
cmqttd safety boundary is recorded separately from the selected native contract. Whole-project
exports preserve creation order and complete children. A deleted tag row is
absent from the current complete project; SAVE can rematerialize it with fresh
identities while its runtime definition is still present.

Deleting an associated numeric row also removes its pending objects, Levels,
scalar fields, Unit document metadata and child OIDs, including descendants
linked through an incomplete pending parent. Retirement removes ownership in
the selected project while retaining an identity still owned by another project.
Complete copies validate their
entire new record before registration; invalid path-component addresses refuse
atomically. These fixes follow two concrete findings from the final Astra review.

NET SAVE DB changes the loaded project database. PROJECT SAVE commits a saved
baseline; CLOSE/LOAD restores that baseline and discards unsaved materialization.
cmqttd's atomic repository also retains the local database and catalogue across
daemon restart. Project copy, its local archive namespace, XML/CBZ and its portable
SQLite conversion container retain the named rows within their existing backend
limits.

Offline `project` commands recognize exact string addresses in the captured
native DBVersion 2.3 and Project/OID profiles. NetworkNumber is independently
validated as a byte. Copy allocates fresh subtree OIDs, move preserves identity,
and failed duplicate or invalid edits leave the original document unchanged.
Legacy project address aliases remain numeric.

The typed `cgate file-upload SERVER_PATH LOCAL_FILE [--project NAME]` snapshots
one bounded regular local file before connection and uploads it as a base64
FILE document. It admits only relative server paths and requires exact 200.
The selected server owns the path policy; cmqttd uses a virtual repository.
There is no implicit project save, operation replay or native SQL-format claim.

## Original contract and acceptance boundaries

The new frozen original C-Gate 3.4.0.2001 experiment contains **126 raw commands**.
Its [native fixture](../../rust/testdata/fixtures/native_cgate_net_save_db_materialization.json)
SHA-256 is `933f54f4532db59f9f6b8cec610d8e4376aceda9429018c515062f83e0359a7b`.
The [experiment record](../research/experiments/2026-10-01/net-save-db-materialization-native-contract.json)
SHA-256 is `86b7c7db964280c1a1bfe2aba54eaa11ab5a3d0bc14f209a23d95eeb67cae11a`.
The raw socket probe uses system Python 3.9, an owned Java 11 server and synthetic
closed projects; it does not import or exercise the Python Toolkit package.
The original JAR, Java executable, helper, private raw bytes and cleanup are
independently digest-bound. Earlier native captures and published receipts
remain unchanged.

A separate fresh **15-command** original raw-socket experiment checks deletion:
after removing both the tag row by OID and its runtime definition, LOAD DB
returns an empty catalogue and complete project. Native direct named XML can
still return its stale deleted snippet. The retained capture is separate from
the frozen 126-command experiment and from public Toolkit CLI execution.

A further fresh **19-command** original check pins project name reuse. DELETE
followed by NEW/USE has an empty runtime catalogue and database; LOAD DB stays
empty. An earlier SAVE FILE snapshot survives and can explicitly restore its
runtime definition without adding a database row. cmqttd retires only implicit
active/DB snapshot state when deleting the project and preserves that explicit
FILE recovery contract.

The actual public CLI acceptance described in the receipt uses Python 3.13,
current source and a fresh isolated installed wheel. It is separate from the
126-command boundary probe and from Rust replay of retained original cases.
Focused tests, CLI calls, source/wheel repetitions and subtests overlap and must
not be added as independent functionality or test counts.

## Final source and installed-wheel evidence

The [acceptance receipt](acceptance/2026-10-01-net-save-db-materialization/acceptance.json)
is SHA-256 `26d59868a7f0794af32718e3f0f6da39784f8d5977896a562ae3ae7fbdd9d869`.
Its 92 supporting derivatives retain original raw digests, explicit coordinate
roles and any FILE payload projection. The execution source is the frozen
working tree at `62edbee6`; the publication commit comes afterward.

| Check | Source | Isolated installed wheel |
| --- | --- | --- |
| Focused Python parent tests | 218 passed | 218 passed |
| Subtests, recorded separately | 742 passed | 742 passed |
| Standalone public cmqttd workflow | 114 CLI calls | 114 CLI calls |
| Fresh original C-Gate public CLI workflow | 89 CLI calls | 89 CLI calls |
| Runtime skips in the focused selection | 0 | 0 |

The 114-call journey checks all 14 guards and 1,141 unchanged source bindings.
It includes 97 exact ordinary command sequences, two exact document sequences
and 15 public offline calls. The maintained 147-call catalogue workflow remains
selected in the focused tests and passed separately before final package
acceptance. These executions overlap; their counts are not added as independent
functionality or unique tests.

The fresh wheel is SHA-256
`db1d299eba715e4e700d57eece17f5a0afe547831bbd62244917ef56250c75ae`.
All 326 Python/JSON package files match the current source and actual installed
imports. Final Rust validation covers 75 unique focused tests in 76 passing
executions, `cargo fmt --check`, workspace/all-target Clippy with warnings denied
and a release workspace build. The 15 new scalar wire cases, 30 retained LOAD
cases and 158 CGL cases are separate vector counts within that validation.
Six current retained-original differentials carry 1,087 current source bindings.

The original public CLI runs each bind 1,167 source files and independently
check their exact online wire, offline/preflight absence, actual package paths,
wheel, original Java/JAR artifacts and terminal cleanup. FILE upload/download
returned 200/346 and retained the exact owned 23-byte payload. Earlier original
CLI harness failures remain retained: case-folded filenames first collided,
then one offline command referenced the superseded export filename. The final
indexed output paths preserve exact identities and all native assertions.

Final complete PCI capture contains exactly eight startup frames for each of
two owned daemons and no later writes. All daemon, proxy, broker and CNI-trap
resources closed; the trap received no connection and the synthetic serial path
remained absent. This is not serial syscall tracing or bidirectional MQTT
lighting acceptance. Native provisioning classes were not selected, and these
fresh bounded original runs do not replace the native release gate.

The read-only Astra review found the numeric-delete cleanup and invalid-copy
admission defects and checked their narrow corrections. It also identified
publication binding checks, which now require current source/binary/package
bindings, exact test IDs, process exits, output digests and clean native proxies.
It did not execute or independently certify these tests. Final publication
also caught and retained a missing `/tmp` coordinate alias and an incorrectly
selected sibling guard log before emitting this receipt. No private raw bytes,
validation log or historical acceptance receipt was rewritten to pass.

CI is tracked separately against the exact publication commit. No local full
suite, full native gate, Windows GUI or physical hardware acceptance is claimed.

## Retained failure and compatibility limits

The preserved `62edbee6` cmqttd binary returned SAVE DB 200 but exported no tag
Networks after runtime definitions were created. The genuine seven-command
public CLI failure remains privately immutable, with binary and before/after
source/package bindings, exact replies and owned cleanup. The old project reader
also rejected the captured named rows; a separate pure reader comparison records
nine prior validation errors and the corrected exact-address results. That reader
comparison is not original runtime or GUI acceptance.

The maintained earlier catalogue test now expects native materialization instead
of its previous snapshot-only behavior. Its old producer/test bytes and old
acceptance receipts are preserved. Changing that semantic assertion is required
by the newly measured native SAVE DB contract; the owned test remains selected.

The byte-identical earlier producer rejected the new binary after 78 CLI calls
because it expected unchanged tag XML. Its exact failure is retained. A later
new-workflow run exposed a genuine 20-call CLOSE/LOAD bug: saved database rows
were restored but stale runtime definitions remained. The lifecycle fix restores
the catalogue from the saved database too. Newly materialized snapshots are
distinguished from genuine legacy snapshots, so deleting a tag row and runtime
definition cannot resurrect it through the old custom-definition fallback.

A 76-call public run then exposed an unselected SAFE scalar edit that returned
200 without changing the authoritative tag tree. The final regression requires
401 and unchanged complete project XML, then executes PROJECT USE and the
evidence-pinned DBSET on one connection. The refusal is a local safety boundary;
it is not attributed to the original selected-session experiment. A separate
57-call preparatory failure came from colliding CustomA/Customa output filenames
on the Mac filesystem. Indexed filenames preserve both exact identities and all
readback assertions.

Public evidence explicitly omits opaque FILE payloads that can hide private
coordinates in base64 XML or SQL containers. Exact private wire and output bytes,
decoded file digests, lengths and the complete raw report remain SHA-bound;
coordinate-role substitutions and payload omissions are declared projections.

Native OID deletion can leave a stale direct named XML snippet while whole-project
XML no longer contains the Network. cmqttd returns a coherent current view; the
original stale-cache result is retained as a deviation. cmqttd DBCREATENET still
returns its legacy 200 rather than native 301. FILE catalogue collision refusal
remains atomic rather than native partial insertion. Original two-option FILE
restoration can return 408 and clean restored Options is literal `null`; native
FILE format and option restoration parity remain open.

cmqttd's portable SQLite container is distinct from Schneider's private native
schema. Broker CONNECT/SUBSCRIBE and one connection per owned daemon verify
lifecycle, not bidirectional lighting control. Absence of a synthetic serial path
is not syscall tracing. Interface opening, wider GET/SHOW selectors, bridge
reference rewrites, original Toolkit dialogs, device effects, multi-interface
operation and power-cycle persistence are not established by this batch.

Complete cross-project copies use fresh OIDs. Unsafe same-project named-row
copies and incomplete unsafe child additions remain explicit pre-mutation
refusals. Their native pending-null object lifecycle remains outstanding; this
batch does not turn those unsupported forms into successful partial copies.

The broad ledger remains **18/42 (42.86%)**, with 22 areas in progress and two
pending. The functional denominator is incomplete and **zero obligations are
fully accepted**. No full suite or native release gate is credited by these
focused checks. This milestone does not establish full Toolkit or full C-Gate
behavioral parity.
