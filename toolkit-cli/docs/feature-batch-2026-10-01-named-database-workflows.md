# Named database construction and selected CLI sessions

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
Unsafe Address writes retain literal nonbyte values and duplicates. SAFE
collision checks are separate from these unsafe semantics. Complete external
DBSETXML admission stays strict; an internal incomplete graph does not relax it.

Project identity has one existing envelope owner. The global index is rebuilt
and persisted on legacy restart, retained when a Network is deleted and retired
when the Project is deleted. Unsupported Project-OID operations refuse instead
of fabricating descendant reads or writing an unrelated opaque field row.

`cgate-mock --native-project-archives` exposes its existing supported complete
XML/gzip/ZIP archive parser through process-local FILE storage. The default
mock retains internal snapshot archives. Neither option supplies host-file
access or durable storage, and mock NET SAVE DB still does not materialize
runtime definitions like cmqttd.

## Current validation

- **43 distinct focused Rust tests passed:** 14 named-graph service tests,
  26 retained NET SAVE tests (including six physical-alias controls), one mock
  archive opt-in test and two retained numeric database server/TCP regressions.
  Format, workspace Clippy with warnings denied and release build passed.
- **Source and installed-wheel checks each passed 222 parent tests and 619
  subtests, with no selected skips:** 66 command-peer tests, 35 adjacent grammar/
  transport/file tests, 118 metadata/retained-receipt guards, one original-server
  journey and two modeled backend journeys. Source metadata guards were run by
  the root; the other checks and installed guards were run by the CLI agent.
  These are overlapping environment comparisons, not feature counts.
- Each environment ran **123 public CLI processes**: 47 against owned original
  C-Gate 3.4.0.2001 and 38 each against the Rust mock and daemon. Every process
  used one connection and an exact successful project selection before its
  dependent database commands. The source modeled journey preceded metadata
  regeneration; its exact production/helper/test/binary pins remain unchanged.
  Fresh source original and all installed journeys use the regenerated package.
- Original journeys each recorded 102 CLI commands, 127 total tagged commands
  and 48 connections. Two CLI invocations deliberately received deleted-OID
  `401` refusals. Modeled journeys each recorded 168 CLI commands, 217 total
  tagged commands and 78 connections; six deliberate refusals are included.
  An owner connection performs explicit save/close/load.
- Both fresh original journeys used `--noconftest` and exactly one directly
  owned oracle process, with a per-instance PID/listener/proxy/terminal-log
  roster. They preserve the source Group across copy and unrelated Neighbor
  Network/OTHER project XML; persisted child checks cover OID, Address, TagName
  and Value rather than whole-graph XML byte equivalence.
- All owned processes, proxies, command/event listeners, PCI peers, inert
  brokers and CNI traps cleaned up. Trap contact counts are zero. Each daemon
  journey sent exactly eight PCI initialization frames and no later PCI traffic.
- Six maintained session/tagged/Unit differentials were freshly rerun against
  the final binaries. Their 1,111 current source bindings were checked before
  and after declared privacy sanitation. These replays compare retained
  original captures; they are separate from newly executed original CLI journeys.
- Unconfigured controls explicitly skipped one original test and two modeled
  nodes. They receive no configured pass credit. Native release selection now
  includes the new original test; both interop selections require the new
  backend journey in their CI execution audits. Complete native/Windows and
  hardware gates remain unexecuted for this batch.

The final wheel has SHA-256
`26a64e495bf038ea706da880a0983312a58b8c4f25a1a3dc11ea84ea4e3603b8`.
All 326 Python/JSON package files are byte-identical between source, wheel and
isolated installed package. No editable package path is used for installed tests.
The [scoped acceptance receipt](acceptance/2026-10-01-named-database-workflows/acceptance.json)
binds 564 current input files, binaries, tests and 69 normalized wire/output derivatives.
Its SHA-256 is `44c3d342b160d715bf8b175cf9dc8b39924eb5f5027e995694211085c09636b1`.
Aggregate CI and publication status are tracked separately on GitHub.

The one required Rust workspace run passed **8,614 tests, with zero failures
and one ignored private-project fixture**. It is recorded separately from the
43 focused tests; their overlapping counts are not added together. No full local
Python, native release, Windows or hardware suite ran.

## Review and retained history

Read-only production review identified and repaired root-key collision data
loss, an OID-less collection panic and missing Project identity census/restore
ownership. Local safety regressions are not newly captured native selector
semantics. Review distinguishes the agent's authored files from separately
owned implementation/tests.

A 46-command scalar vector derives from digest-bound original observations,
with only request-tag removal and equality-preserving OID substitution. It
checks exact responses, not full XML equivalence. Original private preparations
contain 5,318 commands across completed and deliberately bounded partial phases;
they are research history, never candidate-wide pass or feature-percentage counts.

Earlier failures remain separately preserved: a wrong Service document test
entry point, an empty-record normalization regression, two justified legacy
assertion corrections, owner selection and listener-census fixture failures,
the mock's formerly unexposed archive route, and metadata bootstrap/filename
corrections. The first wheel predates regenerated metadata and receives no
final package credit. Fresh original captures also replace the earlier singleton
process report that could be overwritten by conftest's extra owned host.
No uncertain mutation was replayed.

## Remaining work

- Full Project-OID hierarchy/scalar operations and source-qualified aliases.
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
