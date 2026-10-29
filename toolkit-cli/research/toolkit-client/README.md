# Toolkit client inventory

This directory records how C-Bus Toolkit 1.18.0.2754 talks to a C-Gate server so
that this repository's tests (and `cgate-mock`) can assert against the same
shapes. `inventory.json` documents

- the shared reply parser of every native client class,
- the reply checks per class (what each class counts as success, as an error,
  what finishes a command early, and which fragments it matches), and
- the managed-client transport facts (ports, per-call timeouts).

## Provenance and bounds

The record comes from static analysis of C-Bus Toolkit 1.18.0.2754:

- REA over the managed DLLs (SharpCGateCommunicator 7.15), and
- a Ghidra 12.1.4 decompile of the Delphi `CBusToolkit.exe` with
  `CBusToolkit.map` symbols (680 methods, every `CIS_Tcgc*` class, the socket
  layer and the reply parser).

Nothing was executed. Only command text, reply codes and reply fragments are
recorded; vendor binaries, decompiled source and any key material stay out of
the repository. The transcription source is repository issue #161; do not edit
`inventory.json` by hand with new claims unless the same kind of recovered
evidence backs them and the provenance above is updated.

Low-confidence rows recovered together with the checks: argument layouts (from
string joins), DBGet 401, ProjectSave 408, and the Event 412-421 range.

## How handlers and tests use it

The typed CLI workflows in `src/cbus_toolkit/` that send these commands are
fail-closed: a reply that does not match a fragment this inventory records for
the owning class is reported as an unmodeled reply and exits nonzero. Tests
assert the exact request text and the recorded reply classification. Replies
that the inventory marks `partial` are handled only as far as the recorded
fragments go.

## Command workflows decision record (#162)

Of the 66 native commands Toolkit 1.18 builds, the typed workflows below are
the disposition of every command family that was previously reachable only
through `cgate exec`, research probes or the obligation JSON
(`recorded_from_issue: mitchell-johnson/cbus#162`).

| Toolkit command family | Disposition | This repository |
| --- | --- | --- |
| `apiver` | implemented | `cgate apiver` |
| `net flush <n>` | implemented | `cgate network flush` |
| `net delete <n>` | implemented | `cgate network delete` |
| `net unravel <net> [MATCHDB]`, `net unravelunit <unit> [MATCHDB]` | covered | `cgate network unravel --unit ... --match-database` (already sends `NET UNRAVEL`/`NET UNRAVELUNIT`) |
| `TreeXML <net>` | covered | `cgate network tree --xml` (already sends `TREEXML`; `TREEXMLDETAIL` via `--details`) |
| `project start <p>` | implemented | `cgate project start` |
| `config obget <object> <key>` | implemented | `cgate config obget` |
| `config obset <object> <key> [<value>]` | implemented | `cgate config obset` |
| `label kfiget <net>/<app> <group>` | implemented | `cgate label kfiget` |
| `port probe <port>` | implemented | `cgate port probe` |
| `port cniscan <range> [fast]` | implemented | `cgate port cniscan [--fast]` |
| `port refresh` | deferred | No reply class was recovered for `port refresh`; adding a typed command without its reply classification would invent behaviour. Revisit with the next decompile receipt. |
| `ID <addr> type|version` | implemented | `cgate id <address> type|version` |
| `get <unit> X` family (NetVoltage, DCPVersion, DSIChannelStatus, DSIUnitStatus, Current, OpStats, ChannelMode, ControlMode, ErrorState, DCPPanic1..3InputActive, DCPBackupGenActive, DCPHalogenCleanupActive, RawValue) | implemented (as typed workflow) | `cgate unit-get <unit> <parameter>`; `GET <unit> NetVoltage` remains covered by `cgate network diagnose` too. The raw `cgate get` forwarding keeps its previous unrestricted form. |
| `do <unit> readrawvalues` | implemented | `cgate unit-do <unit> readrawvalues` |
| `do <unit> ResetHardware` | implemented (gated) | `cgate unit-reset-hardware <unit> --request` sends it; without `--request` the command only plans the exact action. Destructive physical action follows the hardware-acceptance issue; no replay after an uncertain outcome. |
| `AIRCON set_ward_off ...`, `AIRCON set_zone_hvac_mode ...` | deferred | Hardware-touching SAL to AIRCON units; follows the hardware-acceptance issue (#176). Revisit after the fixture programme admits AIRCON endpoints. |
| `START_BACKGROUND_JOB <job>` | deferred | The successful reply class is recovered, but the valid job identities are not; a typed command would accept unmodelled job names. Revisit together with cgate-mock's background-job surface (#160). |
| `TRANSFORM MIGRATE_SQL <project>` | deferred | No per-class reply checks were recovered for the MIGRATE_SQL leaf, and the maintained native migration is already forwarded by `cgate project transform` (`TRANSFORM PROJECT`). Revisit with a dedicated receipt. |

Receipts printed by implemented commands mark exactly what is verified: a
C-Gate-side acceptance, a delivered physical action and an asynchronous result
are separate claims and stay false until their own evidence exists.
