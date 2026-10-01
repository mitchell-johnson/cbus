# Level editing after a database-network rename

This report records the preceding `5fec5918` software checkpoint. The
[empty TagsDLT copy extension](feature-batch-2026-10-02-empty-tags-copy.md)
supersedes its copy refusal for one strict empty label collection; other stated
compatibility limits remain.

The Rust C-Gate service and Python Toolkit CLI now route admitted Level creation
and copying through the existing numeric database owner after its tag Network
Address is renamed. A Level remains a child of the same Group or NetVar; a name
change does not create another network, move hardware or duplicate its database.

This is a database workflow repair toward Toolkit 1.18.0.2754 / C-Gate
3.4.0.2001 parity. It does not complete the functional denominator or original
Toolkit acceptance. The broader category ledger remains 18/42 implemented
categories (42.86%); this is not a verified functionality percentage. The
functional denominator is incomplete, and zero obligations are fully accepted.

## Operator workflow

These examples assume a loaded secondary project `LAB`, an existing closed
numeric database Network `11` with its associated tag Network already
materialized by explicit `NET LOAD DB`/`NET SAVE DB` or admitted complete XML
import, plus Application `56` and Group `1`. A bare `DBCREATENET` record alone
does not establish that tag overlay. Use the actual service host/port.
The service protects every network rename in its configured
hardware project while it runs; that existing restriction remains.

Save this as `rename-network.cgate` to rename the database Network in an
explicitly selected command session:

```text
PROJECT USE LAB
DBRENAMENETSAFE 11 Renamed
```

Run `cbus-toolkit cgate run rename-network.cgate`. Subsequent separate CLI
invocations select the project on their own connections:

```sh
cbus-toolkit cgate database add //LAB/Renamed/56/1 level 7 Evening --project LAB
cbus-toolkit cgate database get //LAB/Renamed/56/1/7/Value --project LAB
cbus-toolkit cgate database copy //LAB/Renamed/56/1/7 \
  //LAB/Renamed/56/1 8 Reading --project LAB
cbus-toolkit cgate project save LAB
cbus-toolkit cgate project close LAB
cbus-toolkit cgate project load LAB
```

Each typed add/copy requires a fresh `301 OID`, verifies that identity and
initializes its Value to the caller's requested byte on the same connection.
Thus the typed copy above has Address=8 and Value=8 while its source remains
Value=7. A raw `DBCOPYSAFE` retains the source Value until explicitly edited.
Qualified paths, selected bare paths and admitted bare OIDs use the same owner.
The commands do not implicitly load, save or open a project/network, and an
uncertain mutation is never replayed.

## Ownership and failure behavior

The new delegation is limited to Level ADD and Level-source COPY. It verifies
the current project, the real Group/NetVar parent, the stable numeric owner and
typed identity before invoking the legacy database operation. It does not
reinterpret a lexical/internal Network key as a physical address or broaden
global application, unit or physical resolution.

Bare Level/parent OID operands cannot contain a scalar or descendant suffix.
Unit identities and retired OIDs cannot become Level parents through a pending
claimant. Wrong parents, foreign project selection, occupied addresses,
stale Value mirrors and unsupported retained payloads refuse before mutation.
An independent named Network keeps its existing handling, including qualified
ADD from another or unselected session. LOGIN and durable commit rollback wrap
the operation as before.

Unsafe ADD can attach a Level beneath a selected incomplete Group identified by
OID. Child-first completion retains identity and completes into the same numeric
owner after the parent's fields are supplied. Copy into an incomplete destination
remains unsupported. A completed/imported Level Value edit updates only its exact
addressed pending mirror, keeping subsequent scalar/XML reads and copies coherent.

Application XML also retains a legacy typed NetVar and its Level children before
the associated tag tree is synchronized. This prevents a rename from retiring
their existing OIDs. A plain legacy NetVar with an acknowledged non-NULL Value
or retained parent/child XML extras cannot yet be represented
by that synchronization; the operation now refuses atomically with local `408`
instead of dropping the state. This is separate from the Level-copy payload
refusal and is not an original error-code claim.

## Verification and evidence

The scoped release receipt records these completed checks and their limits:

| Check | Recorded result | Boundary |
| --- | --- | --- |
| Required Rust checks: format, Clippy with warnings denied, workspace tests and release workspace build | All commands passed; workspace tests: 8,636 passed, zero failed, one ignored private-project test | Offline software checks; the ignored test supplies no private-project acceptance. |
| Focused `named_database_workflows` tests | 36 passed, zero failed/ignored: 21 existing plus 15 new | The author ran these before an equivalent Clippy refactor; the final workspace run passed the same 36 IDs at current source. Counts overlap and are not added together. |
| Independent frozen mock review | 61 tagged commands and 12 preservation/routing checks passed | One owned mock process; peers closed. This is not daemon restart, PCI, original-server or hardware acceptance. |
| Final source and isolated-wheel public CLI journeys | Five passed in each environment; zero failures/errors/skips; all 326 package files matched byte-for-byte | Each environment executed 125 CLI subprocess calls. These are owned modeled journeys, with local wire expectations, not original acceptance. |
| Complete Python source check | 6,753 parent tests passed, 14 failed, 449 skipped; 30,545 separately reported passing subtests | All 14 failures concerned the evidence publication format. The failed run is retained; no final full-suite pass is claimed. |
| Publication correction and affected consumers | 261 parent tests passed, one original-input skip; 934 separately reported passing subtests | All 12 affected modules passed, including all 34 sanitizer cases and the 14 previously failing IDs. Product source and tests were unchanged. |
| Maintained interop selection | Passed: two framing tests, 21 mock and 154 daemon parent tests, plus 227 separately reported passing subtests; two vendor-specification skips | Executed before the publication-envelope correction with identical product/test/vector/binary inputs. Counts overlap the other checks. |
| Original Toolkit/C-Gate, Windows and hardware comparison | Deferred under issue #72; not executed for this candidate | Historical captures inform contracts but supply no current original acceptance credit. |

The focused tests cover path/OID routing, source Value, NULL retention, pending
completion, invalid parent/suffix/selection, LOGIN, retained payload, stale mirror,
NetVar source-loss refusals and failed durable commit. The two additional NetVar
tests protect acknowledged parent Value and retained parent/child XML; their
loop cases are not separate functionality counts.

Public CLI tests executed against both Rust servers with owned loopback
listeners and fake PCI/broker resources, plus daemon restart and authentication.
Their local expectations are in
`rust/testdata/vectors/cgate_associated_level_cli_wire.json`. Per environment,
76 calls have argument/exit/JSON capture; 49 additional calls have full proxy
wire capture covering 133 tagged commands on 49 connections. All seven owned
processes were cleaned up. Five daemon processes sent 40 startup PCI frames in
total and zero post-initialization frames; closed-network traps had zero contacts.

The [release receipt](../research/fixtures/associated-level-owned-release-20261002.json)
binds actual results, current input and wheel hashes, cleanup, retained failed
attempts and the manual deferral. The complete Python run exposed a missing
canonical publication marker in six refreshed evidence receipts. Their
publication envelopes and generated accounting were corrected, then all affected
consumers and the final source/wheel journeys were rerun. The earlier full-suite
failure remains visible; these selected passes do not replace it. Exact-head CI
is separate and is not claimed here.

Literal comparison output remains private. A reviewed coordinate-normalized
intermediate is passed through the maintained publication sanitizer; its
canonical marker binds that intermediate, while a separate proof binds the
original literal bytes. No comparison was rerun during this correction and no
new original Toolkit/C-Gate execution is credited.

## Remaining compatibility work

- Associated typed NULL getters retain local `342 ...=null` and NULL Level
  project-save retains `200`; the retained independent/native graph reports
  different `401`/`408` behavior. These are open semantic differences.
- Completed typed Level values use canonical decimal bytes: `77`, `077` and
  `+77` read back and copy as `77`. Raw non-byte associated values and NetVar
  absent-field/value behavior need a separate owner/schema reconciliation.
  Unsupported legacy NetVar state can currently prevent a tag-tree resync;
  preserving it through the full owner/schema conversion remains unfinished.
- Copies with retained XML fields, child content or nonempty XML extras refuse
  with controlled `408`. This includes saved Levels with retained TagsDLT.
  Preservation through decorated copy remains unfinished.
- Application/Group/Unit/NetVar construction outside the admitted Level route,
  arbitrary duplicate selectors, owner migration, Project/Installation OID
  hierarchy/XML and incomplete vendor archive admission remain open.
- The original renamed-associated journey, complete original Toolkit form,
  Windows/native, hardware and power-cycle acceptance are deferred under
  [issue #72](https://github.com/mitchell-johnson/cbus/issues/72).

See [named database workflows](feature-batch-2026-10-01-named-database-workflows.md),
[network definitions](network-definitions.md) and the
[implementation ledger](implementation-status.md) for the surrounding scope.

## Later review: deferred corrections

Known associated-owner bugs are deferred in [issue #74](https://github.com/mitchell-johnson/cbus/issues/74):
canonical numeric Group COPY destinations return `401`, while renamed lexical
paths and Group OIDs succeed for admitted byte copies. The newer LOAD sweep
can also alter unsupported retained XML on a plain Level with a deferred empty
label marker. Those payloads are outside the accepted LOAD profile. A separate
missing-descendant Value-getter fallback is an unverified source-review
hypothesis. The attempted fixture failed before that edge executed. These
corrections were stopped by cyber protection; no private untested edits are
integrated or credited.
