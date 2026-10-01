# Named database workflows and ownership review

This batch adds closed database workflows to the Python Toolkit CLI and cmqttd.
It does not establish full Toolkit, GUI, vendor-repository or hardware parity.
The broad ledger remains **18/42 implemented rows (42.86%)**; that ratio is not
an estimate of functionality. The functional denominator is incomplete and
there are still zero fully accepted obligations.

## Resulting behavior

Typed database `get`, `set`, `add`, `copy`, `delete` and `validate` accept
`--project`, alongside the existing XML commands. They validate the project
before connection and require one exact `200 PROJECT USE` on the operation's
own connection. Copy's source read and Level initialization use that same
session. Selection failure stops dependent work; uncertain mutations are never
replayed. No project load/save or network open is implicit.

Independent named Networks can contain Applications, Groups, NetVars and Levels.
SAFE construction/copy returns a fresh `301 OID` and enforces admitted address
and parent constraints. A Level starts with absent Value; typed creation/copy
initializes it to the requested byte. Raw SAFE copy retains source Value.

Unsafe DBADD and same-project DBCOPY retain incomplete objects in one
ordered TagNode graph, including children completed before their parent.
Identity survives field completion, rename, explicit save/reload and internal
JSON restart. Unsafe Network copy targets `Installation/Project`, its qualified
form or the selected Project OID. It refreshes modeled descendant OIDs, clears
tagged Address/TagName and retains NetworkNumber, Interface/Property metadata
and Level Values. The captured nondefault NetworkNumber `17` copy retains `17`;
an earlier unsupported `0xff` inference remains in corrected private history.

NULL TagName makes direct/ancestor XML export return `444` and project save
return `408`. Named objects without Address can save; a Level also needs Value.
Raw DBSET and DBSETSAFE preserve literal NetworkNumber and Level Value strings,
including `0xff`, `999`, `oops` and `-1`; SAFE is not a general byte parser.
Unsafe Address writes retain literals and duplicates. Typed byte admission and
SAFE collision checks are separate from these raw scalar semantics. Complete external
DBSETXML admission stays strict; an internal incomplete graph does not relax it.

Deleting an independent Interface by path or OID returns `200`. The graph can
validate, save/reload and restart with the Interface absent. Root InterfaceType
and InterfaceAddress aliases then return `401`; lifecycle operations do not
panic or silently recreate it. Closed `NET LOAD DB` retains the state;
`NET SAVE DB` returns controlled `408` without model, saved-data or PCI changes.
SAFE Network rename to another owned address also refuses atomically. Original
C-Gate returned `500` for the captured deficient SAVE and SAFE collision cases;
local `408` is a deliberate liveness repair, not exact error-code parity.

Configured physical binding is protected by explicit `database_network`
ownership. An independent row keyed `254` does not become the configured owner
because its key matches the transport NetworkNumber. A complete configured-owner
DBSETXML can replace the database tree, but moving its Address/NetworkNumber or
rebinding InterfaceType/Address returns atomic `408`. Positive replacement can
canonicalize Unit XML; refusal preservation uses that accepted baseline.

Project identity has one existing envelope owner. The global index is rebuilt
and persisted on legacy restart, retained when a Network is deleted and retired
when the Project is deleted. Unsupported scalar DBGET and guarded add/copy/set/delete
forms on the selected Project OID refuse. Project-OID DBGETXML forms remain
unaccepted and can reach the legacy opaque fallback; success does not establish
descendant resolution.

`cgate-mock --native-project-archives` exposes its existing supported complete
XML/gzip/ZIP archive parser through process-local FILE storage. The default
mock retains internal snapshot archives. Neither option supplies host-file
access or durable storage, and mock NET SAVE DB still does not materialize
runtime definitions like cmqttd.

## Current corrected-candidate checks

- **50 distinct focused Rust tests passed:** 21 named-graph service tests,
  26 retained NET SAVE tests, one mock archive opt-in test and two retained
  numeric database server/TCP regressions. Format, workspace Clippy with
  warnings denied and release build passed.
- The required final Rust workspace run passed **8,621 tests, zero failures
  and one ignored private-project fixture**. It overlaps the focused tests;
  their counts are not added together.
- Source and noneditable installed-wheel checks each passed **287 parent tests
  and 680 subtests**, with zero eligible failures, errors or skips: 66 peer,
  35 adjacent grammar/transport/file, 118 metadata/receipt guards, 32 selected
  serial, 34 sanitizer and two modeled backend journeys. These are overlapping
  environment comparisons, not functionality counts.
- Each environment executed **76 public CLI processes**, 38 against the mock
  and 38 against cmqttd. Every process selected its project successfully on its
  own connection before dependent commands, including copy reads and Level
  initialization. Each environment recorded 168 CLI commands, 217 total tagged
  commands and 78 connections across both backends, including expected refusals and an explicit
  owner SAVE/CLOSE/LOAD sequence.
- All owned processes, proxies, listeners, PCI peers, inert brokers and CNI traps
  cleaned up. Traps received zero contacts. Each daemon journey sent exactly
  eight PCI initialization frames and no later PCI traffic; the mock used no PCI.
- Six maintained session/tagged/Unit comparisons were rerun against the final
  release binaries. Their **1,111 current source bindings** were checked before
  and after declared sanitation. They replay retained original captures and
  do not constitute newly executed original-server journeys.

The wheel SHA-256 is
`393903920c25dee9b1ae60600bf93317a5539cdbef615bdf2cb680da2976d689`.
All **326 Python/JSON package files** match between source, wheel and isolated
installation. The [corrected scoped receipt](acceptance/2026-10-02-named-database-publication-correction/acceptance.json)
binds current inputs, release binaries, package checks, test results and declared
normalized derivatives. Independent publication audit and exact-head CI remain
separate from these local results; GitHub tracks their terminal status.

No full local Python suite, complete native/Windows gate, hardware test or house
deployment ran for this correction.

## Original acceptance and review history

Current original Toolkit/C-Gate acceptance is **deferred**, with zero current
original CLI execution credit. [Issue #72](https://github.com/mitchell-johnson/cbus/issues/72)
records the work, intended outcome and manual acceptance checklist. Historical
source and wheel journeys against original C-Gate each ran 47 CLI processes;
those belong to the preceding candidate and do not validate the corrected one.

Six independently audited native preparation phases contain **262 terminal
commands**. They support the literal scalar, absent Interface and collision
contracts above. The failed initial 17-command prerequisite phase is excluded.
Only the SAFE `999`/`oops` reload case is established; native reload adds empty
TagsDLT nodes. No whole-graph XML byte equivalence, all-lexeme reload or broad
GUI/hardware conclusion follows from this preparation.

Read-only source review found the numeric-key/ownership panic and confirmed its
repair and strict configured binding controls. It records historical backend
self-authorship and the reviewer's authored selected-serial tests explicitly;
execution evidence and independent publication audit are separate records.

The selected-serial correction changes the **live test fixture only**. It copies
the unchanged golden plan and gives the OS-backed receipt the existing 200 ms
fixture headroom. A deterministic eight-byte partial receipt persists the actual
move, then requires durable uncertainty, one send, no later I/O and no replay.
The prior CI failure's exact cause remains unproven without its journal.

Both accidentally expanded guard selections are retained as excluded private
history: each had 259 parent cases, including three unconfigured skips, and
777 subtests. Only the corrected exact five-module guard attempts receive final
credit (118 parents/550 subtests each); completed other phases were not repeated.

The preceding public receipt failed publication privacy review because partial
roles retained macOS user-bucket and pytest-account suffixes. Its branch history
and private copy remain preserved. The corrected receipt uses a frozen private
role table, declared transformations and recursive decoded-coordinate/hostname
checks. The first corrected draft was also rejected before publication for an
incomplete nested-hostname scan. Accepted main receipts remain untouched.
Parent review subsequently found a plain JSON JUnit `hostname` field in the
committed `a24e66e2` evidence that the local audit missed. That receipt and audit
are revoked and preserved as failed review history. The replacement explicitly
normalizes parsed JSON hostname fields and structurally inspects encoded JSON,
including escaped keys and nested serialized strings. This correction changes
evidence and documentation only; the application source, package, metadata,
release binaries and their test results remain bound to the same verified bytes.

Other earlier preparation failures, interrupted pre-fix workspace execution and
source-drift review attempts remain preserved without current acceptance credit.
No uncertain mutation was replayed.

## Remaining work

- Full Project-OID hierarchy/scalar operations, source-qualified aliases and
  accepted XML routing beyond legacy fallback responses.
- Renamed numeric-associated Level creation and legacy owner delegation.
- Mixed Unit/decorated copy graphs and hidden identities in retained XML. New
  unsafe/deep-child forms refuse these before mutation; previously supported
  complete SAFE Network copy grammar is preserved.
- Duplicate-address selector precedence and more postcollision lifecycle cases.
  Captured unsafe writes do not establish every subsequent selector.
- Native no-selection OID `440` versus existing local configured-session `401`.
  Qualified add `301` and OTHER-selected OID mutation `401` are implemented
  operation-specifically; there is no blanket native-selection refusal claim.
- Incomplete external archive admission. Internal JSON persistence does not
  prove restoration through strict complete-XML or private vendor parsers.
- Original stale descendant-OID behavior after parent deletion: cmqttd retires
  coherently immediately; original reads remained stale until reload.
- Complete native/Windows gates, real devices, rendering, timing and power-cycle
  acceptance, private repository/FILE forms and the broad parity denominator.

See [network definitions](network-definitions.md) for operator commands and
[implementation status](implementation-status.md) for overall scope.
