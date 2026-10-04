# Python Toolkit CLI

## Identity and installation

`cbus-toolkit` is the Python application under `toolkit-cli/`. It is independent of the Rust MQTT bridge and supports Toolkit-style project editing, commissioning, unit configuration, scenes, and diagnostics.

From the repository root:

```sh
python3.13 -m venv toolkit-cli/.venv
toolkit-cli/.venv/bin/python -m pip install -e ./toolkit-cli
toolkit-cli/.venv/bin/cbus-toolkit --help
```

Python 3.13 or newer is required. The base package has no external dependencies. Optional extras are `serial`, `usb`, `research`, and `test`. On Windows, the virtual environment executables are under `Scripts` instead of `bin`.

## Choose the command family

| Task | Command family | Backend |
| --- | --- | --- |
| Create, inspect, validate, edit, export XML/CBZ | `project` | Local files |
| Manage native projects, networks, databases, units | `cgate project`, `network`, `database`, `unit` | C-Gate server |
| Create a closed project network or manage runtime definitions | `cgate database network-new`, `cgate network definition` | C-Gate or cmqttd; no implicit interface open |
| Inspect or edit a physical unit through cmqttd PP | `cgate physical-pp` | Shared C-Gate/PCI service; physical reads and optional writes |
| Control groups, scenes, labels, triggers, Enable | `cgate on`, `off`, `ramp`, `scene`, `label`, `trigger`, `enable` | C-Gate server; may reach hardware |
| Invoke a stored KEYGL5 scene Trigger binding | `cgate edlt-scene-trigger` | One Trigger event through C-Gate; may reach every listener for the pair |
| Inspect or change addressing and serials | `cgate address`, `serials` | C-Gate; profile and identity guards apply |
| Direct CNI queries and commissioning | `pci`, `serial-address` | Explicit PCI/CNI endpoint |
| Discover CNI2/Wiser endpoints | `interface discover-cni`, `interface scan-cni --probe BIND@DEST`, `interface scan-cni --auto-adapters [--plan-only]` | Bounded IPv4 UDP queries; auto mode needs the optional `network` extra; plan-only sends no traffic; no TCP or C-Bus connection |
| Probe or set up a serial PCI | `interface probe-serial PORT [--setup]` | Exclusive open of one explicit port; reset/identify/RECALL only; `--setup` writes cmqttd's four interface options after a `present` result and verifies readback; needs the `serial` extra |
| Inspect route bytes | `pci-route` | Offline |
| Plan supported device settings | `keys`, `sensors`, `din-settings`, `iope-settings`, `dlt`, `edlt`, `wireless`, `unit-conversion`, `unit-scenes` | Offline, with explicit inputs/specifications; `dlt profiles` explains DLT/eDLT admission; `wireless boundary` composes C-Gate learn/unit-action commands without I/O |
| Edit scenes/templates or match serial inventories | `scene`, `unit-templates`, `unit-addressing` | Local files |
| Preferences, CSV, About and update diagnostics | `preferences`, `toolkit-database-csv`, `toolkit-about`, `update-*` | Varies; some require Windows/vendor files |
| Diagnose firmware or explicitly perform USB DFU | `firmware` | Offline or explicit device, depending on subcommand |
| Inspect current completeness | `coverage --require-complete` | Packaged functional-obligation and evidence register, with the historical feature ledger included separately |

For closed network setup, read [network-definitions.md](../../../../toolkit-cli/docs/network-definitions.md). `network-new` admits legacy cmqttd creation 200 or native 301 with one UUID OID, and requires exact LOAD 200; after an incomplete load inspect the existing database row and catalogue before explicit recovery. `network definition` validates inputs before connection, requires `--project`, and exposes list/create/delete/rename/load/save/flush with no implicit OPEN or project save. DB load refreshes current database interface fields while preserving immutable physical bindings and unrelated active definitions. Use exact //PROJECT/NAME paths for cmqttd runtime Name/Type/Interface/InterfaceAddress/Options; bare server selectors and issued !OID references retain generic dispatch even when legal runtime names collide. FILE is an internal snapshot on cmqttd; a missing snapshot is empty, and existing-name collisions refuse atomically. Original FILE loads can partially add earlier rows before 408, so cmqttd atomic refusal is an explicit deviation. Original two-option FILE restoration returns408 and clean restored Options is literal null; native option-format parity remains unaccepted. NET SAVE DB materializes runtime definitions as complete tag Network rows. Keep exact string Address separate from NetworkNumber; missing rows get nNAME/0xff. Preserve Network/Interface OIDs across repeated saves, while Property OIDs change. Explicit PROJECT SAVE commits the database baseline. Offline project editing admits the captured native DBVersion2.3/Project-OID address profile and preserves exact lexical/case identities and complete XML/CBZ subtrees. cgate file-upload PATH SOURCE [--project NAME] uploads a bounded binary snapshot to the selected FILE service; cmqttd uses its virtual namespace and portable container, not native SQL-format interchange.

For offline Network addresses, an explicit older DBVersion retains numeric
aliases. An unversioned Network with NetworkNumber `255` selects native lexical
addressing, including one added to the unversioned `project new` Installation:
exact Address `254` resolves, but `0xfe` does not. Independent materialized tag
rows cannot bind the configured PCI through DALI or PP patch numeric aliases.
Read the [integration corrections](../../../../toolkit-cli/docs/feature-batch-2026-10-01-net-save-db-integration.md)
for retained OID lookup and legacy programming-field behavior.

Inspect each subcommand's `--help` and the matching feature document before constructing parameters. There is no universal `--dry-run`; use it only where the chosen workflow exposes it.

For ST7 SENLL 2.0.01..2.4.99, `sensors light-level-plan` and
`cgate unit sensor-light-level` support the dialog groups/indicator/target/margin,
`--broadcast-interval-seconds 10..65535`, `--power-up disabled|enabled|resume`,
and `--status-report-interval 3..255` seconds. They apply the complete recovered
forced save, including a loaded broadcast minimum of 10 and power-up encoding
before the maintenance polarity reset. Report the selected and reloaded power-up
states separately. Fresh Global initialization changes stored0..2 to3 before
an explicit valid selection; the raw value remains part of stale-state guards. Repeat `--on-off-control application=primary|secondary` or
`group=N|none` for an explicit ordered application/group history, including
the source-owned eight-block load and collision callbacks. The admitted SENLL
class has zero runtime InputKeys; its history never changes BlockAllocation.
Missing destination objects and mixed flat group/application edits refuse
before staging. Legacy flat plans retain their previous collision refusal.
Read `toolkit-cli/docs/senll-application-controls.md` for the exact graph and
metadata boundaries. Native PP database save/reload evidence does not establish
physical timing or power-failure behavior. Read `toolkit-cli/docs/sensors.md`
for identities, source evidence and exclusions.

For the eight admitted DIN relay/dimmer firmware-2.7.00 profiles, add
`--toolkit-save` to `din-settings plan` or `cgate unit ... din-settings` to
include one recovered agent-save projection after the requested edits. Inspect
the v2 plan's `pre_save_changes`, `save_normalization` and final `changes`.
RELDN8 marshalling differs from the ordinary agent: untouched level-store
recovery bytes can survive, short arrays retain their final stored element,
and MaxDimmingLevel can change again on a later explicit save. Never repeat
normalization to seek a fixed point. V1 targeted plans retain their previous
semantics. Database PP and project saves remain separate; this does not prove
complete original form or physical output behavior. Read
`toolkit-cli/docs/din-output-settings.md` before applying.

For ordered DIN Min/Max, Turn On and recovery-delay controls, use
`--controls FILE` with the documented JSON operation array. Both Synchronise
checkboxes start off, assignments to unchanged displayed positions preserve
their raw bytes, and coupled slider notifications retain source order.
Stagger steps use dialog channel order and the original delay conversion.
Direct edit flags cannot be mixed into a history; optional `--toolkit-save`
performs one final save projection. Inspect `control_history` and the nested
`settings_plan`; imported histories replay before staging. Recovery-level
sharing, group creation and implicit initial form notifications remain open.


`project repair SOURCE.xml --dry-run` previews the bounded local repair and
`--output NEW.xml` writes a new file exclusively. Captured XML 1.0/1.1,
ISO-8859-1/15, US-ASCII and Windows-1252 cases have literal original C-Gate
comparisons; see `toolkit-cli/docs/project-repair.md` for the exact encoding
behavior. The returned `native_load_verified=false` is intentional: a successful
portable repair does not establish native project loadability.

`project topology FILE` is a read-only map of a saved XML/CBZ project built from
statically recovered Toolkit 1.18 rules. Use `--navigate NET`, `--near-side NET/UNIT` or
`--far-side NET/UNIT` to resolve unit paths, and `--format dot|svg [--output NEW]`
for images. Report `diagnostics`, orphans and circular joins as project facts,
not live topology; layout, print and pixel parity are unassessed. See
`toolkit-cli/docs/topology.md`.

`project document FILE [--native-xml] [--output NEW] [--network N]` writes the Toolkit Document
Project HTML (UTF-8 BOM, CRLF) and never overwrites. Treat every `not documented
(unrecovered)` marker as missing evidence rather than a project fact; byte/visual
parity and printing are unassessed. `--native-xml` explicitly admits a saved
DBGETXML Installation snapshot; it does not open a live project. Recovered
DIN/classic output, bridge, DMX, classic-key usage and status projections have
per-profile bounds in the feature documentation. See `toolkit-cli/docs/project-documentation.md`.

Scanner text is keyboard-wedge input: Toolkit 1.18 recognizes a 28-plus-character
software configuration code (catalogue in characters 1–16, serial from 17) and
12/28-character unit-dialog serials. It has no `CBUS:` prefix. Use
`barcode parse [TEXT]`, which reads stdin lines when TEXT is omitted, to classify
scans. Use `project add-unit FILE --network N --catalog cbusunits.xml --barcode TEXT`
to add a unit to a legacy XML/CBZ project. A duplicate serial selects the existing
unit and writes nothing. For a loaded database, use
`cgate database barcode-add //PROJECT/NETWORK --project PROJECT --catalog cbusunits.xml --barcode TEXT`.
It previews by default; `--apply --exclusive-project` sends one SAFE Unit ADD
and one native Unit XML initializer, then verifies the fresh OID, planned fields
and unrelated whole-project XML. The pure plan uses the first project-wide
duplicate serial in XML order, retains the independent second serial branch,
and omits the offline `State=New` marker from native fields. An existing match
selects its path/OID without writing. The exact Network Address may be named;
do not substitute its physical NetworkNumber. Optional
`--expect-project-sha256`/`--expect-catalog-sha256` bind the initial snapshot and
catalogue bytes; a fresh pre-write check refuses drift but is not a server-side
compare-and-swap. `--auth-token-file` supplies one private cmqttd LOGIN token
with redacted evidence. The workflow sends no PP initializer, project SAVE or
physical programming. After an uncertain ADD/initializer error, retain the
receipt and inspect through a fresh read; it does not retry, roll back or delete
automatically. Preserve exclusive project ownership. Owned backend tests and
the recovered component vectors do not establish broad Schneider native-server,
original GUI or physical-scanner acceptance. See `toolkit-cli/docs/barcode.md`.
Toolkit has no PICED launcher or handoff.

When a repaired XML `Installation` still has DBVersion 2, 2.1 or 2.2, use
`project transform-legacy REPAIRED.xml --dry-run` to validate the bounded
conversion, then `--output NEW.xml` to write a new file exclusively. The 2
and 2.1 portable cases admit unitless projects and the documented KEYGL5 5.5.00
and KEYB2/KEYB4 1.6 Unit/PP profiles. Twenty-two generated conversions across
the three source versions match original C-Gate transform bytes and the staged
cases load/read back; other projects still require native observation. See
`toolkit-cli/docs/project-legacy-transform.md`. For an explicitly selected
original XML repository, `cgate project transform NAME [--test]` forwards the
default native migration. `--xslt-file SERVER_PATH --output-file SERVER_PATH`
selects the captured explicit native form; its output must be a pre-existing
writable file on the server and is overwritten. The native default `--test`
can create a `.xml.0` backup on the server, unlike the offline dry-run.

For `serial-address apply`, the Toolkit CLI uses a nonblocking host-local advisory
lease for the canonical numeric-IP endpoint during fresh preconditions, the
single selected-serial request and journal finalization. Contending cooperating
Toolkit processes fail before PCI I/O. This is not a bus-wide lock: maintain
exclusive commissioning ownership against cmqttd, C-Gate, other hosts and other
controllers. After an uncertain attempt, use `serial-address verify --recovery`
for read-only recovery; never replay from the lease or journal alone. See
`toolkit-cli/docs/pci-selected-serial.md` for the exact fixture and limits.
For a far network through one to six bridges, pass `--project FILE
--source-network N --target-network N` to `plan`, `apply` and `verify`: the
plan observes the far network by routed MMI/IDENTIFY4, and apply/verify
re-derive the route from that exact project before any I/O, refusing
`route_binding`/`wrong_route`. Rust `serial-verify`/`serial-apply` also execute
bound routed plans; legacy unbound library entry points remain direct-only.
Routed evidence remains synthetic scripted-peer evidence, without native routed
UNRAVEL or hardware acceptance. Python reconciliation accepts completed Python
routed journals only for the exact bound offline XML/CBZ project and recorded
target network (`--network`, if supplied, must match). It reparses raw routed
inventories and receipts, checks direct local PCI identity/options and the shared
attempt marker, and binds route/project/source/target freshness. A missing or
mismatched receipt does not prevent an exact independent after-inventory from
proving the observed change. Type/firmware pins constrain database identity,
not physical compatibility. First run requires the original raw project hash;
restart requires the retained hash-bound backup, exact recomputed candidate and
validated record/current digest. Keep exclusive project file ownership; freshness
checks are not a cross-process filesystem lock. Pending source repeats require
explicit apply; exact pending destination completes only the record, changed
pending content conflicts, and completed records only report current matching.
Completed Rust routed `cbus-selected-serial-apply-v2` journals also reconcile
offline through the independent Python `rust_serial_reconcile` validator. Their
versioned proof retains reader-original and separate parser frames for the
before/after inventories, direct PCI identity/options and one-shot exchange.
Parser changes are limited to trailing CR/LF normalization and outer-checksum
addition for validated checksum-off frames. This is commissioning-frame proof,
with `raw_connection_capture: false`, not authenticated connection history.
Require a durable completed single send, exact raw inventories and request/
receipt agreement, no ignored traffic, and the existing canonical-plan marker
bound to the same plan, fingerprint, absolute journal path and scope. Missing,
partial, inconsistent or uncertain proof refuses before database writes.
Direct Rust v1 behavior is unchanged; legacy Rust v1, verify output and
marker-only recovery cannot reconcile offline. Loaded routed C-Gate projects
require `--route-project ORIGINAL_EXPORT --exclusive-project`, including planning;
the immutable raw export must match the physical plan and the whole loaded
project must equal its original or the record's exact candidate. Route, file
freshness and every network's closed/idle state are rechecked through backup,
SAVE/CLOSE/LOAD and no-op validation. Direct journals still refuse bridge
projects. Python uncertain applies can export a separate fresh direct/routed
handoff with `verify --recovery J --output V`; preserve the original journal
and marker. C-Gate reconciliation records saved whole-project evidence and
never replays a physical command or automatically restores/saves uncertainty.
A saved original requires explicit `--retry-database --apply` after readback.
See `toolkit-cli/docs/known-serial-commissioning-journey.md` and the reconciliation
contract in `toolkit-cli/docs/physical-addressing.md` and the versioned evidence
details in `docs/rust-selected-serial-routed.md`.
After an `observed_expected_change` journal, `serial-address reconcile --journal J
(--project FILE | --cgate HOST:PORT --project-name P)` plans the matching database
unit move (dry run by default; `--apply` backs up, moves, saves and verifies a
reload). It never touches the bus; see `toolkit-cli/docs/physical-addressing.md`.

`update-diagnostic-bundle` needs the four generated report files plus the exact
raw catalogue response, revocation input, condition input, context input,
metadata signer DER and revocation signer DER to
establish linked completion. Candidate, condition and context models must match
their decoded sources with JSON types preserved, including Boolean fields.
The catalogue report's fixed endpoint and request digest must also agree with
its declared installed version; this is report consistency, not network attestation.
Metadata and revocation canonicalization rows must include hexadecimal and base64
SHA-256 receipts matching their canonical UTF-8 bytes; missing or mismatched
receipts keep the corresponding link and completion false.
The condition report must retain its producer's exact-file source representation;
a substituted observed-host claim cannot establish the link. The revocation
report must retain `request_subject_association_verified=false`: matching the
source-bound subject does not prove which subject an API request used.
Each DER is bounded to 64 KiB and must match both its producer report's SHA-256
and SHA-1 thumbprint; matching the revocation subject to a report-only
thumbprint is insufficient. This binds exact certificate bytes, not publisher
trust, full X.509 parsing or signature-stage replay.
With report files alone it retains independent
hashes but exits nonzero and marks the links unverified. Its successful result
is a source-linkage diagnostic, not publisher trust or update availability.
Pass the same two DER files alongside the four JSON sources to
`update-package-bundle`; a previously complete v3 diagnostic receipt must be
reproduced as v4 before its joined completion can succeed.

`update-rollout-cohort --catalogue-response RAW.json --node-id ID
--stored-cohort 41` evaluates one original strict-greater-than visibility gate
using an explicitly supplied stored 0–99 cohort. It binds the decision to the
exact raw response and selected node digests, but does not read HKCU, generate
or persist a cohort, or determine whether this machine should receive an
update. Consult `toolkit-cli/docs/toolkit-update-rollout-cohort.md` before
composing it with applicability or metadata diagnostics; independent reports
do not by themselves establish one trusted update workflow.

`update-rollout-current-user --source-assembly SesuBrick.DAD.dll
--expected-source-sha256 PINNED_SHA256 --expected-user-sid SID` is a separate
read-only Windows HKCU Registry32 observation. It requires the exact pinned
SESU 3.0.7 DLL and current process user SID before reading the original key;
missing/sentinel/unsupported values cannot become a usable cohort and it
never samples or writes. Read
`toolkit-cli/docs/toolkit-update-rollout-current-user.md` for the exact path,
source evidence, accepted interactive missing-entry read and remaining
one guarded original-seeded numeric read. Neither is a complete rollout decision.

`update-applicability-cohort-preflight --catalogue-response RAW.json --node-id
ID --platform windows_x86_64 --at-utc ...Z --stored-cohort 41` evaluates the
captured empty-condition date/file/media/URI path and 0–99 rollout gate on the
same selected node. Read `checks.rollout_gate_reached_under_supplied_context`:
false means an earlier gate failed and the comparison was not reached; then
`checks.rollout_gate_under_supplied_cohort` is null. This remains a calculation
under supplied UTC/platform/cohort facts, not a host registry observation,
publisher trust, update availability, or install approval. See
`toolkit-cli/docs/toolkit-update-applicability-cohort-preflight.md` for the
native 15-case evidence and exact profile.

For `update-condition-live`, use `--expected-user-sid` with the complete known
Windows SID to require the intended HKCU user before any registry request. A
mismatch fails before observation and does not switch users. Check
`observer_evidence.user_context`: explicit SID admission requires agreement with
the independently queried primary process token as well as the worker-ready SID.
Token query uncertainty fails closed; thread impersonation is not attested.
SID agreement is not proof of an interactive
desktop session or original Toolkit wrapper parity. The native condition-wrapper matrix
confirms per-name true/false caches and shows that even ASCII `I`/`i` differs
under `tr-TR`; keep the production `invariant-ascii` restriction. Do not infer
interactive preferences/settings behavior from this condition-checker evidence.
For effectful `preferences registry-load`, `registry-save`, and
`reset-dont-ask-again`, `--expected-user-sid` optionally checks this CLI
process's primary-token SID before the registry backend is constructed.
`registry-load` can itself write defaults. The guard has portable tests and
the two-load command passed a bounded interactive Windows wheel run under
the active console user's primary token. Save/reset and original GUI
user-context parity remain open; the guard alone does not attest thread
impersonation or a desktop session.
`preferences registry-load STATE.json --repeat-once` makes the original
manager's bounded first-write/second-read case explicit: the first completed
load supplies the second load's current values, both receipts are returned,
and an incomplete first pass stops. This can write defaults twice and is not
an atomic snapshot or proof of the original GUI's preference wrapper.
Owned Windows wheel checks passed both 40-value comparisons under guest-agent
LocalSystem session 0 and then the logged-in user on `WinSta0\Default`
session 1, each with scratch-key cleanup. See the
[interactive receipt](../../../../toolkit-cli/research/experiments/2026-09-28/preference-interactive-repeat.json).
The pinned original GUI was then run twice in that account after snapshotting
the fixed Toolkit keys. A missing `ShowProjectManager` value became `True`
after the first startup and stayed `True` after the second; both bounded
process trees were stopped and the fixed Registry32 value trees restored or
verified unchanged, with private exports removed. The hashes cover values,
types and subkey hierarchy, not ACLs or last-write metadata. See the
[original GUI receipt](../../../../toolkit-cli/research/experiments/2026-09-28/preference-original-gui-same-user.json).
This does not directly prove same-instance manager reads, lazy wrapper/culture
behavior or logging/C-Gate effects.
For the bounded same-instance public `Evaluate` cache-reset case, the Python
API can call `ToolkitLiveUpdateConditions.evaluate_next(..., observer=fresh)`
once after a clean Boolean result. The CLI exposes the same bounded path with
`update-condition-live ... --repeat-once`; it reports two ordered evaluation
receipts and final result, constructing and closing a fresh Windows observer
for each pass. An incomplete first pass stops before the second observer.
Keep the previous report and do not treat the two reads as an atomic snapshot.
This matches the pinned original true-then-false outcomes with separate Python
observers; it does not establish identical original worker lifetime or a
repeat-after-failure contract. The CLI two-worker path has focused portable
tests but no native Windows acceptance yet. See
`toolkit-cli/docs/toolkit-live-registry-observation.md`.

`update-package-file --catalogue-response raw-catalogue.json --node-id ID
--file-id ID --package-path local-package.exe` compares one already-local
regular file with the selected untrusted SESU size and SHA-1 descriptor. A
matching receipt exits zero; a mismatch emits a negative receipt and exits one.
It does not fetch, authenticate, approve or execute an update. Inspect
`toolkit-cli/docs/toolkit-update-package-file.md` before using its bounded
file-input profile. The equivalent Python API is
`cbus_toolkit.toolkit_update_package_file.inspect_update_package_file`.
To link that receipt with the exact-source diagnostic bundle, run
`update-package-bundle` with both generated reports, all four diagnostic
reports and their four source files, the selected node/file IDs, and the
already-present package path. It reproduces both reports and the safe-open
file hash; a network-mounted path may involve filesystem network transport. See
`toolkit-cli/docs/toolkit-update-package-bundle.md`. A source-to-package link
can be true while a diagnostic stage is failed or unsupported. The joined
completion then remains false.
`update-download` fetches one file whose URL is bound to a complete catalogue
report and its exact raw response. It uses verified TLS and same-origin
redirects, and checks size and SHA-1 before a no-overwrite publish. Failed bytes
are kept as `*.failed.partial` with a `*.failed.json` record. It never
installs; see `toolkit-cli/docs/toolkit-update-download.md`.
`update-trust` evaluates a supplied signing chain, `rv1` lists and signers under
embedded original pins or runtime-supplied anchors at an explicit instant.
`update-composite-report` joins catalogue, metadata, revocation, conditions,
applicability, trust and download eligibility for one input set; a mismatch
is `refused`. Neither establishes current publisher trust or downloads; see
`toolkit-cli/docs/toolkit-update-trust.md` and `toolkit-update-composite.md`.
Windows uses a checked Win32 disk-file handle; POSIX uses
no-follow/nonblocking/close-on-exec flags. An isolated SESU 3.0.7 oracle
accepted a wrong digest when its security-dictionary folder key did not match
the destination folder, so never substitute that isolated vendor method for
this CLI's explicit catalogue file binding. Even a matching CLI receipt is
not source, publisher, revocation or installer trust.

`update-applicability-preflight --catalogue-response raw-catalogue.json
--node-id ID --platform windows_x86_64 --at-utc ...Z` evaluates only the
captured SESU empty-condition, 100%-visibility date/file/media branch under
caller-supplied facts. It selects the first architecture-matching file whose
ID has a URL-map key, even if that URL is empty; there is no later-file
fallback. Inspect `status` and `applicability_under_supplied_context`, and
read `toolkit-cli/docs/toolkit-update-applicability-preflight.md` before use.
Its `passed` result is not current publisher, machine, rollout, version or
installer approval. Nonempty conditions, sub-100 rollout and unproved URI
or media forms are unsupported without a host or registry read.

`pci routed-recall`, `pci routed-identify` and `pci routed-write` each support
literal bridge/reply bytes or a typed legacy XML/CBZ route. The typed form
takes `--project-file`, `--source-network`, `--target-network`, and the global
`--local-unit`; it binds the file digest and derives the exact return path
before one send. WRITE additionally requires an ACK tag and never replays an
uncertain mutation. Use these only for bounded CAL transport. Saved-project
resolution does not authenticate live bridge topology; device programming
methods, readback, commit and persistence remain separate.

## Offline project example

```sh
cbus-toolkit project new demo.cbz --name DEMO
cbus-toolkit project add demo.cbz --kind network --address 254 --name Local
cbus-toolkit project inspect demo.cbz
cbus-toolkit project export demo.cbz demo.xml --format xml
```

Use a scratch directory for examples. Edits preserve unknown XML and programming fields; `--output` directs an edit to a separate copy. Native C-Gate 3 SQLite projects use C-Gate operations instead of this legacy-file editor.

For a damaged legacy XML file, `cbus-toolkit project repair SOURCE --dry-run`
previews the bounded lexical/XSLT-equivalent result, and `--output NEWFILE`
creates a separate file exclusively. The first stage always reads source bytes
as Java UTF-8. Later XML stages admit UTF-8 and a captured XML1.0
ISO-8859-1 declaration case; an ISO declaration can therefore yield mojibake
after the first read. Check the output and its `native_load_verified: false`
receipt before any separate native load. See
`toolkit-cli/docs/project-repair.md` for admitted cases and failure bounds.
Use `project transform-legacy SOURCE --output NEWFILE` only for the documented
DBVersion 2/2.1/2.2 repair envelope; it preserves SOURCE and rejects existing
output. Earlier-version projects containing other units or PP shapes require
the native XSLT path.

## C-Gate client

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20033 project list
cbus-toolkit cgate --host 127.0.0.1 --port 20033 exec 'PROJECT LIST'
cbus-toolkit cgate --host 127.0.0.1 --port 20033 run commands.txt
```

These examples target the Rust mock after it is started on port 20033. The native plain TCP default is 20023. Each CLI invocation creates a new connection; `run` keeps all commands in one session and stops at the first error. Project selection is session-local, so use explicit addresses/project arguments or one batch when later commands depend on a selection.

Native connections support TLS and client certificates. A live address such as `//PROJECT/254/p/20` can reach a physical unit; `/db//PROJECT/254/p/20` explicitly selects the database for programming workflows. Confirm which source the task requires and use the documented identity, backup, and verification behavior for writes.

For physical PP work through cmqttd, prefer the typed command:

```sh
cbus-toolkit cgate physical-pp inspect //PROJECT/NETWORK/p/UNIT --method direct
cbus-toolkit cgate physical-pp apply //PROJECT/NETWORK/p/UNIT \
  --method direct --set UnitName GARAGE --journal journals/unit-4-attempt-1.json
cbus-toolkit cgate physical-pp recover --journal journals/unit-4-attempt-1.json
```

It preflights `CMQTT CAPABILITIES`, validates every selected parameter against
`PP INFO *`, issues one SAVE or SAVE_TO_SOURCE, and uses a distinct physical PP
LOAD for readback. Current methods are `direct`, `paged`, `ncc`, `edlt`, `giu`,
`sgiu`, `dali`, `goc`, `gocbyt`, and `goc2`. Never replay an uncertain save.
Treat fresh readback as in-run device verification, not power-cycle persistence
or broad hardware acceptance. Saving any decoded unit specification that
contains an NCC parameter requires the separate NVM capability, even when the
selected edit uses another method. See `toolkit-cli/docs/physical-programming.md`.

Successful operations emit JSON on stdout, operation errors emit JSON on stderr, and failures return nonzero. Argument usage errors can be plain argparse text. `--compact` is a global option before the command; event monitoring emits JSON lines. Preserve partial-operation evidence and do not replay uncertain writes automatically.

The typed network learn/locate forms cover the six retained learn grades and
all four retained locate selectors. They require fully qualified direct paths
and return an interface-delivery receipt without claiming device action,
readback or persistence. Use the exact range and no-replay boundary in
[`network-learning-locate.md`](../../../../toolkit-cli/docs/network-learning-locate.md).
Run them only against a C-Gate service with the intended direct physical
network bound:

```sh
cbus-toolkit cgate network learn //PROJECT/254 56 init-relay 1
cbus-toolkit cgate network locate //PROJECT/254/208 unit 1 ON
```

For supported classic UnitTemplate work, use `template-export` and
`template-import` for XML files. Use database-unit `template-copy` to transfer
the original 26-field template set directly between distinct matching
KEY1/KEY2/KEY4 1.2.67 units under one exact network lock. Use
`template-reset-defaults` to restore only that field set from the selected
decoded specification. Preview either transaction with unit-level `--dry-run`.
An apply sends one PP SAVE and opens a fresh destination session; inspect
`staged_verified`, `save_confirmed`, `reload_verified` and
`preserved_parameters`. `project_file_saved=false` means a separate project
save is still required for file durability. Never retry when
`save_outcome_uncertain=true`. These commands require `/db` units, reject
cross-profile conversion and do not perform a physical or factory reset. See
`toolkit-cli/docs/unit-templates.md`.

## eDLT Measurement decimal values

For a KEYGL5 / 5055EDL 5.5.00 database unit, configure exact scaling with
`--gain-mantissa/--gain-exponent` and
`--offset-mantissa/--offset-exponent`. To reproduce the Toolkit Measurement
text editor, use `--gain-value` or `--offset-value` plus an explicit
`--measurement-culture`:

```sh
cbus-toolkit edlt measurement-plan snapshot.json \
  --page 1 --position 1 --device-id 42 --channel 3 \
  --gain-value '1,5' --measurement-culture de-DE
```

The default culture is `canonical`: dot decimal, no grouping, blank rejected,
and stored exponent limited to -128..127. Source-pinned Toolkit profiles are
`invariant`, `en-NZ`, `de-DE`, and `fr-FR`. They reproduce each observed
decimal/group separator, final blank→1 and Gain zero→1 behavior, invariant
fixed-50-place formatting, and signed-byte exponent wrapping. Read
`composite_conversions`: `editor_exponent` is the pre-write value, `exponent`
is the stored signed byte, and `display_value` is the original getter's
post-storage rendering. Never substitute the process locale or normalize
commas on your own. The CLI rejects non-finite text because Toolkit accepts
`NaN` and then hangs in its number-break loop. See
`toolkit-cli/docs/edlt-measurement.md` for exact grouping and preservation
rules.

To combine one Measurement edit with the parent proximity percentage control,
use `edlt parent-form-plan` offline or database-unit `edlt-parent-form`. Both
require `--metadata` with a complete lifecycle cache. Use `--level-percent`
only when the resulting `--wake-mode` is `primary-event`; mode changes can
reinterpret the shared byte as a Trigger action. Inspect `phases`,
`cross_control`, `preservation`, `initialization_concurrency` and
`original_save_order` before applying. This bounded composition validates all
supplied controls before mutation and preserves the retained scene/MRA models.
Its original order is source-pinned and its individual controls have retained
native probes, but `native_parent_form_executed=false`: do not describe it as
an end-to-end execution of the original WinForms dialog. See
`toolkit-cli/docs/edlt-parent-form.md`.

For two or more supported KEYGL5 5.5.00 panel edits, use `edlt
parent-transaction-plan` offline or database-unit `edlt-parent-transaction`.
The ordered operations cover Measurement, Lighting, Enable, Fan, HVAC, Multi
Level, Room Courtesy, Scene, Shutter, Time/Date, Timer, MRA Zone Control,
Source Select, Source Control, Blank, activation, General, Display, Standby, Colours,
Navigation, Quick Status, Page Control, MRA globals, Applications and
Corridor, one retained SceneManager sequence, plus an optional operation-1
Reset baseline. Applications, Corridor and Reset require the complete
application cache; SceneManager requires the complete SceneManager cache. The
automatic parent metadata resolver derives existing ordered DBGETXML lists and
exact Unit PP strings for operation-1 Reset without projecting missing list
objects. It can project the validated ordered-list/Reset/contiguous-Blank
state into the SceneManager branch, which creates only exact required Trigger
application/group/action objects. The
transaction reconciles one page mode, rejects overlapping complete records or
settings fields, reserves both Time/Date slices, validates application/group
and effective dynamic-variant dependencies, composes shared text allocation in
order and enters every validated control before one terminal lifecycle/CRC projection.
Place Display before a dependent HVAC/MRA icon edit, Standby before dependent
idle Colours controls and a retained/new MRA widget before `mra-globals`.
Shared multiplexer and zone components each have one explicit owner; omitted
values use the first existing pre-conversion MRA record. Review `operation_results`,
`operation_metadata_dependencies`, `ownership`, `preservation` and
`execution_counts`. Blank uses whole-slot ownership. Reset creates a fresh
widget/scene graph before later operations and reports layered baseline
overrides; Reset after operation 1 and duplicate Reset fail closed. Blank may
form only the contiguous prefix after Reset, where it binds an exact issued
fresh-graph receipt; a later Blank fails closed. Applications must precede
SceneManager, and SceneManager must precede
every Scene widget so final graph dependencies are validated. The original
component evidence does not establish an executed original multi-panel form; see
`toolkit-cli/docs/edlt-parent-transaction.md`.

When a current native project snapshot is the source of truth, replace the
manual cache with the bounded automatic resolver. Offline, pass
`--project-xml` and the selected `--unit`; for the database command pass
`--auto-metadata --exclusive-project`. It derives required applications and
groups for every admitted operation, complete consumed scene-level addresses,
safe dynamic-variant facts and all 64 static-label slots, then deterministically
plans missing application/group records. With `scene-manager`, it reuses the
exact retained resolver and adds missing Trigger application, group and action
levels after container creation and before the one parent PP save. Review the
`automatic_ordered_application_cache` database-view provenance for
Applications/Corridor/Reset: XML child order and TagName are exact, while
Toolkit registry display/sort preferences are unobserved. Review the
plan before applying and use the selected source network as the exact PP lock
address. The apply creates a project backup but DBADDSAFE, PP SAVE
and PROJECT SAVE are separate C-Gate operations. Automatic rollback stops once
PP SAVE is attempted, and an uncertain reply must not be retried. Project/DLTP
image-dependent dynamic facts fail closed. See
`toolkit-cli/docs/edlt-parent-metadata.md`.

Retained SceneManager edits have a separate automatic resolver with the same
offline/native option shapes. It derives complete existing application/group
lists, consumed trigger level sets and safe default-language action text. An
exact retained getter chain can plan missing application202 as `Trigger
Control`, exact non-255 groups as `Group N`, and exact actions as `Action
Selector N`, Address=Value=N, with four blank variants. Review every creation.
Native apply requires the
exact source-network lock, closed/idle project networks and exclusive caller
ownership. Use `--backup-project` when applying: it saves/copies the source,
rechecks it, creates and reads back the objects, then crosses separate PP SAVE and
PROJECT SAVE boundaries. Rollback stops once either applicable save is
attempted; treat a lost save reply as uncertain and never retry it. The
typed accepted/cancelled `add-trigger-dialog` and `add-action-dialog` operations
are available; they model first-free 0..254 and editable `Trigger Group N` /
`Level N` seeds. Keep their ordered getter effects and transport name limits.
Original interactive Add control binding remains open. See
`toolkit-cli/docs/edlt-scene-add-dialog.md`. Image-dependent label facts
remain unsupported; use manual `--metadata` for independently established
DYNAMIC/FONT/ICON labels. See
`toolkit-cli/docs/edlt-scene-metadata.md`.

The lifecycle receipt names all five calculated CRC fields. Do not infer a
missing calculation from `phases.crc`, because that changed-only view omits an
already-correct stored CRC.

The database save follows verified PP staging. If its reply fails or is
interrupted, do not replay the command: `saved=false` means unconfirmed, while
the transaction evidence marks both save outcome and current PP/database state
uncertain.

## New conversion and NeoPro report commands

`cgate conversion tweak` previews all 288 currently admitted Toolkit client-side
pairs from a canonical source path, exact private source/target specs, unused
target address, firmware and catalogue. Review `plan_sha256`; apply requires
`--apply --exclusive-project --expect-plan-sha256 HASH`. It binds all project
Networks closed/idle, source and defaults, and original plus schema-staged
assignments. One fresh Unit and one PP save are verified against the entire
source/unrelated graph. A declined assignment exits 1 with a separately
verified fallback; a lost receipt retains the scaffold and uncertainty without
reconnect/replay/deletion. For admitted metadata/delete/readdress and
save/reopen, use the separate `cgate conversion tweak-replace` lifecycle with
a distinct backup, fresh journal and reviewed digest. It stages the first free
address, replaces once, and verifies fresh project/PP after reopen. Keep the
journal; `tweak-recover` only observes on the same bound endpoint, never replays
or restores. Original cleanup/catalogue selection, retained GUI history and
physical acceptance remain open. Read `toolkit-cli/docs/toolkit-tweaker-lifecycle.md` and
`toolkit-cli/docs/toolkit-conversion-tweakers.md` before using this command.

The earlier native XML/live NeoPro CSV checkpoint admitted KEYB2/KEYB4/KEYB6 at exactly 2.5.00. All eight blocks
select their own primary/secondary Application through SecondApplicationBlocks;
Area 255 stays in primary. Complete consumed groups and ordinary report fields
are required. Whole selections refuse atomically before output creation, using
one live DBGETXML. Public NeoPro cached v2 binds primary/secondary Application
identities, complete Group membership and mask, validating each block before
projection. This caller-supplied cache is not a fresh live read. The
then-admitted older families retained v1; NeoPro v1 remains refused; read
`toolkit-cli/docs/toolkit-database-csv-neopro-cached.md`. That checkpoint registry admitted 35 types; the later historical family registry admitted 126/262 with v2/v3 inputs described in `toolkit-cli/docs/database-csv-source-families.md`.
The historical completion registry admitted 214/262 types; its additional source
profiles use cached v4 and require both authoritative Application objects.
Base formatting defaults a missing secondary address to255, which requires a
real existing Application255 in a read-only native snapshot. Read
`toolkit-cli/docs/database-csv-completion.md`; historical v1-v3 contracts,
32/35/126-type receipts and native captures are unchanged. Static EXE/MAP reading is
not original-instruction acceptance. See
`toolkit-cli/docs/toolkit-database-csv-neopro.md` and the October 2
conversion/CSV/liveness batch for current proof and remaining gates.

## Compatibility and tests

`make refresh-parity-receipts` produces actual modeled comparison captures.
Before publishing them, use the maintained
`research/sanitize_evidence_receipts.py` for the six session/tagged/unit
receipts, keeping its raw archives in a private directory. Then regenerate
physical applicability and the parity register and run their consumers.
Sanitation changes publication coordinates and artifact labels, preserving
captured observations and source fingerprints. Preserve earlier gate pins;
if packaged evidence changes after a wheel gate, verify a fresh final wheel
and the changed resource consumers instead of rebinding earlier executions.

Target: Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001. Full Toolkit parity is unfinished. `coverage --require-complete` derives its result from the packaged functional-obligation and evidence register and deliberately exits 1 until the census, implementation and acceptance requirements are complete. The provisional register currently accounts for 22,103 source records, including the sanitized 412-form, 10,102-control and 1,839-event executable census in `toolkit-cli/docs/toolkit-executable-surface.json`. Reproduce that census with `research/extract_toolkit_executable_surface.py` and explicit vendor EXE/MAP paths; never commit those vendor inputs. Functional percentages are unavailable while `denominator_ready` is false. The separately reported 42-row category percentage is not a functionality estimate. Command forwarding, the Rust mock's 431 paths, and simulator results do not establish physical-device or full Toolkit equivalence.

Read the repository's `toolkit-cli/docs/implementation-status.md` for supported functions/profiles and outstanding work, and `toolkit-cli/README.md` for detailed examples. Source is in `toolkit-cli/src/cbus_toolkit/`; tests and retained acceptance evidence are part of this application.

`update-rollout-owned-registry` is a Windows-only SESU diagnostic against an
explicit CLI-owned HKCU Registry32 scratch namespace. It can sample and write
one cohort in that namespace. The original updater's static key and entry are
separately source-pinned, but this command still addresses only its owned
scratch key; it does not read the user's updater cohort or establish update
applicability. See
`toolkit-cli/docs/toolkit-update-rollout-owned-registry.md` before using it.

For development, install `./toolkit-cli[test,research,serial,usb]`, then run `make check` and `make check-interop` from `toolkit-cli/`. Native/vendor/hardware tests require explicit environment gates; report skips separately from passes.

For database CSV, `toolkit-database-csv --native-xml-unit` and `cgate database-csv` also accept complete KEYE4 and KEYEIR1–4 firmware 2.5.00 snapshots with nine stored groups and existing application/group metadata. `--native-xml-network` and `--network` include them in whole-network exports. The shared TKEYEx class registration is source-pinned, while original GUI and cold native load acceptance for these five variants remains open; consult [the CSV profile document](../../../../toolkit-cli/docs/toolkit-database-csv.md) before exporting a whole network with other profiles.

The bounded DIN CSV projector also admits `DIMDN4`, `DIMDN4F`, `RELDN4` and `RELDN8` firmware 2.7.00 with a complete 16-slot `GroupAddress`, existing Area255 and selected primary groups, and an unused secondary application. The first three types expose four interaction groups; RELDN8 exposes eight. A pinned Toolkit EXE/MAP review supports the class, shared agent and report method routing, and a no-site fixture tests exact offline and one-request live whole-project export. Original GUI and cold native load acceptance remain open. See [the CSV profile document](../../../../toolkit-cli/docs/toolkit-database-csv.md).

`RELDN8B` firmware 2.7.00 is separately admitted with the same complete 16-slot primary `GroupAddress` and existing Area255 shape. Its original class and DIN agent are source-pinned; its own predicate exposes the first eight groups while retaining all 16 associations. The no-site fixture covers cached, offline and one-request live CSV output. Original GUI and cold native acceptance remain open; see [the variant source review](../../../../toolkit-cli/research/experiments/2026-09-28/csv-reldn8-variants-profile-review.json).

`RELDN8SP` firmware 2.7.00 has a bounded source-backed CSV profile with a resolved primary application, unused secondary application, existing Area255 and all 16 stored primary groups present. Its marshalling-box agent first loads those 16 groups, then clears the unit group manager and reloads stored indices 1–4 and 7–11. The cached receipt retains `loader_associations` for all 25 load operations and `group_identities` for the final nine; CSV exposes those nine labels. Do not describe the 25 operations as 25 final groups. The [source review](../../../../toolkit-cli/research/experiments/2026-09-28/csv-reldn8sp-profile-review.json) pins the clear and report enumeration; its no-site fixture covers cached, offline and one-request live output. The original GUI report and cold native database load remain untested for this profile.

The [static CSV factory registry](../../../../toolkit-cli/research/experiments/2026-09-30/csv-factory-registry-static.json) is the profile denominator. It lists 425 static Toolkit unit registrations (262 types), each with its exact-class agent, report methods and an admitted flag or refusal reason. The CLI appends that reason when rejecting a unit. It admits ANODN4, DIMDS8, DIMPR1/2/4, RELDC4, RELDB1, ANOMB8 and DSIMB8 (DIN per-channel reload), RELMB8 (marshalling-box remap, like RELDN8SP) and SENPIRIB 2.2.00 (`TST7SENPIRSS`, like SENPIRIA). `RELDN8` is registered to the marshalling-box agent, so its CSV shows stored indices 1–4 and 7–10, not slots 0–7. Owned C-Gate 3.4 cold-load/readback of every committed synthetic fixture reproduces the fixture CSV (`tests/test_toolkit_database_csv_native_batch.py`); this is not original GUI acceptance.

For a complete snapshot CSV selection, use `toolkit-database-csv project.xml
--native-xml-project //PROJECT --output new.csv`, or `cgate database-csv
--project //PROJECT --output new.csv` for one live DBGETXML snapshot. These
include networks in XML document order and units in numeric address order
within each network, rejecting the entire
export before output creation if any selected unit is unsupported or
ambiguous. The admitted unit profiles and read-only missing-Area restriction
remain; the per-network sort is source-backed but full interactive original
Toolkit manager enumeration is not yet verified. Use
`--units`/`--native-xml-units` for an explicitly selected supported subset.


Classic DLT project text uses `dlt text show --project-xml FILE --target PATH`,
`dlt text plan --project-xml FILE --target PATH --edit 'LANGUAGE:VARIANT=TEXT'`,
and `dlt text apply --project-xml FILE --plan PLAN --output NEW`.
Unit `dlt labels` variants and `--block-dynamic-updates yes|no` are separate
PP settings. Database blocking uses the inverse of EnableDynamicLabels;
the original two-phase physical save sequence is not implemented. Network
Language records use ID, and ID0's TagValue selects the default language.
Automatic eDLT parent/scene metadata requires a nonempty explicit Languages
collection to have unique canonical IDs, exactly one default marker and its
selected nonzero definition. Ambiguous collections are refused before label
facts or commands; do not infer native normalization or prior session state.
Absent/empty collections retain the existing English1 fallback, independently
of original degenerate-language acceptance. See `toolkit-cli/docs/edlt-parent-metadata.md`.
Read `toolkit-cli/docs/classic-dlt-label-controls.md` before composing these flows.
Classic `dlt display show|plan` and database `dlt-labels` also admit indicator
mode, inversion and clock visibility. Plans bind identity and all named fields
sharing byte 0x35, preserve unselected bits while staged and refuse stale values.
The original C-Gate drops unnamed bit7 during database save/reload; staged raw
verification is not unnamed-bit persistence. Display edits and label edits
require separate invocations. Read `toolkit-cli/docs/classic-dlt-display.md` for
source/native evidence and the remaining physical delivery/rendering limits.

Classic `dlt icon-dialog show|plan|apply` is a language-202 predefined-icon transaction with IDs 1..91 and whole selected-language finalization. `dlt unit-delivery plan|assess` takes explicit resolved key/language state and caller outcomes; it performs no device operation or recovery. Thermostat settings compose scalar/fan/temperature form-save rules with enabled remote references and their ordered application/group creation. The whole-project snapshot binds one owning transaction; graph-only changes use no PP save and one final project save. Saved-project documentors add bounded Neo/DLT/NeoClassic, PIR, temperature, scene-controller and specialized-output profiles; consumed dependency completeness and firmware admission remain explicit. Read `toolkit-cli/docs/feature-batch-2026-09-30-dlt-thermostat-documentors.md` for retained evidence, native opt-ins and the original-replay exclusion.

Thermostat settings apply one recovered form save, including dependent scalar,
fan, slave-plant and relay-drive normalization. The result can differ on a later
explicit save; do not add hidden saves to reach a fixed point. Raw PP values
and network addressing are preserved where no admitted form rule applies.
Quick-zone and dialog helpers remain bounded pure-model functions, separate
from complete GUI lifecycle and physical acceptance. The explicit process
`--temperature-preference celsius|fahrenheit` adds 15 recovered field-specific
load/save pairs; it is independent of the device TemperatureUnits setting.
The remote path admits source 1 through the existing scalar ApplicationNumber
(Lighting 48–95 or 203) and source 2 through Enable Control 203. Schedule enable
is derived from program flags. Inspect planned creations and resolved identities:
one unused setback role is allowed, every enabled schedule role must be non-unused,
and all selected non-unused objects must be distinct. Optional level additions default to decline; `--setback-levels accept` and
`--schedule-levels accept` create missing addresses 1–31 for enabled non-unused
roles. Existing Level Value metadata stays opaque and is preserved; new Values
require exact canonical bytes. Ordered `--output-group` selections and typed
`--output-operation` Select/Add/Edit records, including direct cancellation,
compose the 23 output roles with the same owning transaction. Edit binds the
currently selected identity: pass `op: "edit-output-group"`, `parameter`,
`outcome: "accept"` and optional `name`; cancellation admits no name/address.
Address/OID are immutable, shared renames remain causal, existing Level Values
stay opaque and uncertain writes are never replayed. Read
`toolkit-cli/docs/thermostat-output-add.md` and
`toolkit-cli/docs/thermostat-output-edit.md`. Missing actual ASCII output/damper defaults also admit unrelated Unicode group inventory; comparison folds ASCII letters only and duplicate generated-name matches still refuse. Read `toolkit-cli/docs/thermostat-default-names.md` and its current focused acceptance report. Do not infer application migration, arbitrary Unicode defaults or original/hardware acceptance. The fresh quick-zone owner composes `quick-zone-view`, `quick-zone-refresh`, `quick-zone-click`, `select-plant-type` and explicit `dispatch-plant-type-change` records in the same `--output-operation` history. Require explicit `--temperature-preference celsius` and the guide's settled source profile; schema and preference refuse before connection, while changed ControlledZones refusal compares the authoritative readonly snapshot. The owner retains the loaded master role, Basic save tail, final Programmable schedule state and live reference identities. Pending owner-issued messages refuse save; diagnostic JSON is not a continuation. Read `toolkit-cli/docs/thermostat-quick-zone-controls.md`. The bounded source/installed-wheel/backend acceptance is recorded in `toolkit-cli/docs/feature-batch-2026-10-04-thermostat-quick-zone-controls.md`; native/Windows control timing and complete issue 42 remain open. Omit --set for a bounded load/save of the current snapshot. Keep
all project networks closed, own project editing exclusively and review uncertain
creation/save outcomes without automatic replay. Original GUI callbacks remain open.
Template 9 group allocation requires the documented initially empty application
and explicit `--group-sort address-ascending`; other manager orders remain refused. Read `toolkit-cli/docs/thermostat-settings.md` and
`toolkit-cli/docs/thermostat-templates.md`.


## Conversion, classic DLT and firmware boundaries

The separate Toolkit conversion Python API admits 288 of 292 registered
source/target pairs. The earlier 123 comprise eight dimmer, seven RELDN, 93 classic-to-Neo, five
coupler-to-Neo (1.2.67→2.2.00) and ten non-sensor InputUnit directions
(1.2.67→1.2.67). Older SENPILL1.6.00 self-conversion is admitted with fresh
learning/join resets. This is separate from typed C-Gate conversion. A RELDN4 short
four-token baseline is refused before I/O; require the admitted complete source
profile. For admitted metadata/delete/readdress and save/reopen, use the separate
`conversion tweak-replace` lifecycle and read-only `tweak-recover`; read
`toolkit-cli/docs/toolkit-tweaker-lifecycle.md` first. Original catalogue lookup,
exception cleanup, editor history and physical conversion remain open.
Read `toolkit-cli/docs/toolkit-conversion-tweakers.md` and
`toolkit-cli/docs/toolkit-remaining-conversions.md`. Three KEYM6 directions
without a selected original factory and the undefined RELDN4 short-array
direction remain refused; no new original GUI or physical acceptance is implied.

Wireless Connection admits WGATE5N/F 2.2.90..2.4.99; Scenes and Remotes
require WGATE5F. Database Connection/Scenes plans require the exact database
source/lock, exclusive project ownership, closed networks and fresh stale checks.
WTXU project-remote creation is metadata-only and crosses three explicit saves;
it does not pair or initialize PP. Typed `wireless action plan` and
`cgate unit ... wireless-action` separate cached GETs from explicit DOs.
Use `--allow-physical-action` for effectful execution and at least eight seconds
for Recall/Reset. Cached identity and a 202 acknowledgement do not prove
physical identity, one bus frame, radio effects or backend retry behavior.
The closed native action case proves 401 refusal, not positive action acceptance.
See `toolkit-cli/docs/wireless.md`.

For `dlt indicators plan`, repeat `--indicator-control NAME=VALUE` in the
intended order. Inspect initialization changes, enabled controls and save/reopen
normalization. `dlt text-dialog` operates on a selected existing TEXT language
and preserves the source-backed legacy flavour0/default representation. Its
20-UTF-16-unit prefix and whole-input Unicode confirmation are separate rules;
read `toolkit-cli/docs/classic-dlt-language-dialog.md` before applying.

`dlt broadcast plan` and `assess` are offline: supply explicit label facts,
prepared bitmap bytes and immutable command outcomes. An original cache mark
is not an accepted response or verified device state. There is no transport
executor or retry; see `toolkit-cli/docs/classic-dlt-broadcast.md`.

Firmware completion requires `cleanup_complete` independently of
`images_verified`. Inspect the stopped journal before explicit read-only resume;
never silently reflash after a failed release or acquisition. See
`toolkit-cli/docs/firmware-update-recovery.md`.

Firmware package metadata and selected images must consume the same bounded
immutable snapshot. `update-resume` admits the interrupted journal package
SHA-256 before archive parsing, decryption or USB construction. Refuse missing
or malformed digest bindings and differing bytes; after admission, consume the
captured bytes even if the mutable filename changes. ZIP/AES integrity and
SHA-256 do not authenticate vendor firmware. NCC and container payload helpers
are offline models; no physical NCC or recognized-container execution is
admitted. Read `toolkit-cli/docs/firmware-package-snapshot.md`.

Rust project-label extraction bounds both raw and expanded/decoded input,
including lossy UTF-8 replacement expansion, before output. CBZ archive
CRC/decompression/unsupported-codec failures are structured refusals. The
class-specific OnColor proof changes the executable inventory only; it does
not establish GUI or physical acceptance.

## IOPE component workflows

Use `cbus-toolkit iope-workflow` or `python -m cbus_toolkit.iope_workflow_cli`
for the eight bounded IOPE1R1/IOPE2R2/IOPE2C4 components at 1.0.00..1.2.99.
Database plans require the exact /db source and source-network lock, exclusive
project ownership and every project network closed/idle. Existing group/action
metadata is checked before staging and save. Inspect separate PP and project
save attempts and fresh reload; an uncertain save is never replayed. Scene
selectors use existing Level Address, not Value. Retained scene levels require
the documented positive canonical graph; whole scene saving, template/input
transactions, live groups and physical programming remain excluded. Read
`toolkit-cli/docs/iope-workflows.md` and each component document.

For eDLT template format/export/preview and issued assignment/second-model/Reset/terminal stages, read `toolkit-cli/docs/edlt-template-integration-boundaries.md`. Apply remains an unconditional refusal before target access. Do not equate source CRC, local normalization or a synthetic database durability receipt with original template Apply/OK.

Old DIMPR12 firmware 0–1.9.02 has bounded project-documentation bodies and
independent group/action usage, with an explicit 33-record packed scene
projection. NeoClassic KEYC/KEYCIR bodies and usage consume canonical
SceneModify commands. Require complete consumed PP/model facts; unknown
dependencies retain unresolved markers. DIMPR12A selects the existing DIN
ErrorReportOutput implementation. Exact L1 firmware1.9.03 through9 has its own
report/usage profile; wider loader history, unregistered firmware, original
complete loaders, initialized GUI history and full-page byte/visual parity
remain open. See [Bytecraft](../../../../toolkit-cli/docs/project-documentation-bytecraft.md)
and [integration boundaries](../../../../toolkit-cli/docs/feature-batch-2026-10-01-routed-commissioning-documentors.md).


The earlier source-backed extensions admitted 120 additional DLT-target conversion
pairs (243/292 total) and 91 additional CSV unit types (126/262 total). Read
`toolkit-cli/docs/toolkit-dlt-conversions.md` and
`toolkit-cli/docs/database-csv-source-families.md` before using these profiles.
DLT conversion deliberately omits inherited conversion hooks and preserves
literal constructor order. Wireless CSV v3 requires sixteen input blocks and
complete installed-output tails, even beyond visible report columns. The
remaining conversion/CSV profiles, original GUI/cold native family acceptance
and physical behavior remain open.

An earlier batch added 45 conversion directions (288/292 total) and 88 CSV
types (214/262 total), with exact firmware, loader and consumed-state boundaries
in `toolkit-cli/docs/toolkit-remaining-conversions.md` and
`toolkit-cli/docs/database-csv-completion.md`. These are static/synthetic and
owned-service software scopes. They do not promote historical receipts to the
current source or establish new original GUI, cold native family, VM or hardware
acceptance. Remaining refused registrations and full Toolkit parity stay open.


## Final CSV admission and database documentation

The maintained CSV registry admits all 262 statically registered types and
424/425 registration rows under explicit firmware, exact-class and consumed-PP
profiles. The duplicate KEYGL5/TKEYGL5 row has no exact agent; its separate
5.5.00/5055EDL profile remains supported. Read
`toolkit-cli/docs/database-csv-last-profiles.md` for temperature, IOPE, fan,
wireless and infrastructure Application255 dependencies. Complete authoritative
Application/Group identities remain required; cached v4 is resolved manager
state, not physical programming. Type admission is not full functional parity.

Use `cbus-toolkit cgate database-document --project //PROJECT --output NEW.html`
for a loaded cmqttd/C-Gate database. It sends one complete343/347/344 DBGETXML,
binds Project.Address independently of TagName and exclusively writes HTML.
`--network N`, `--generated-at ISO` and `--catalog FILE` are optional. It reads
saved programming only: no OPEN, scan, physical programming LOAD or project
SAVE. Interrupted reads never retry or create output. Saved legacy/native
commands share the renderer, including bounded light-level, WHAA and DALI
bodies. Inspect unresolved markers and the false original-page/physical flags.
Read `toolkit-cli/docs/native-project-documentation.md` and
`toolkit-cli/docs/project-documentation-remaining.md`.

For ordered eDLT `add-application-dialog`, require explicit
`creation_preferences` with Boolean `allow_user_defined` and `allow_legacy`.
The original owner/eDLT overload supplies the catalogue, not caller pointer
bounds. Inspect the offered addresses, locked standard names, native validation
order and reserved confirmation before apply. Description is a separate
DBSETSAFE after issued creation. Nonempty values require exact issued-OID scalar
342 before PP save and after project reload; blanks make no assignment or
null-readback claim. Description XML parity remains open in issue75. The parent
checks issued OIDs against the observed complete Project snapshots before any
initializer or inverse deletion. Operation-1 Reset plus Add binds fresh
defaults; initial scene/proximity getters retain their earlier allocations.
One parent PP save still crosses a separate target project save. Never replay
an uncertain save. See `toolkit-cli/docs/edlt-application-reset-add.md`.


## Static grid, Language Add and saved reports

For KEYGL5 5.5.00, include `static-text-dialog` and `add-language-dialog` in the
existing ordered `edlt parent-transaction-plan` or database-unit
`edlt-parent-transaction` operation array. The static operation supplies ordered
committed `{index,text}` edits and `close:button|window`; both closes save.
Its 64 UTF-16-unit cell limit differs from the PP setter's first 63 UTF-8 bytes
plus terminator. An edit does not select or allocate a widget label. Inspect
split UTF-8/NUL projection and existing label references before apply.

Language Add supplies the complete ordered `selected_ids`, explicit initial
`preferences` (`registered-defaults` or eight signed factory preference values),
and optional cancellation. Initial native XML then preferences populate a fresh
cache; later dialogs consume the retained cache rather than reimporting it.
Accepted lists contain 1–8 distinct nonzero factory IDs; existing English1 is
locked. Preserve matching rows/custom names/OIDs and the last ID0 default
marker. Chinese is factory ID202. Factory selection admission is separate from
signed-i32 unknown database row IDs. Read
`toolkit-cli/docs/edlt-static-language-add.md` for the operation schemas.

Prefer automatic metadata with a known existing closed database unit and exact
source-network lock. Inspect language creations/deletions and issued-OID
readbacks before PP staging. The parent composes one owning PP save and a
separate project save; it does not reproduce the original callback's per-row
save count or create cross-command atomicity. Before PP save, failure uses the
saved-source reload boundary; after a possibly issued save, preserve uncertainty
and do not replay. Use a reviewed backup and exclusive project ownership.

The shared saved-project renderer now has bounded multisensor, thermostat,
wireless input/gateway/remote, Bytecraft L1 and architectural dimmer report bodies
and independent usage/action consumers. Architectural reports admit four factories
and 128 sparse ordinary scenes. Thermostat masters require explicit unambiguous
NetworkNumber; generated/missing plant groups remain refused. Native report selection preserves exact database Address identity separately
from the source signed-integer heading/anchor projection and physical
NetworkNumber. Numeric spellings can normalize to the same HTML anchor and
named addresses project to255; inspect exact identities in JSON metadata.
Consumed Number lookups refuse ambiguity and unresolved unknowns. Original
manager ordering and full-page acceptance remain open. Wireless
receivers and consumed scene objects must exist. Use `project document` for
files or `cgate database-document` for one fresh DBGETXML. Inspect unresolved
markers and original-page/physical flags. Read
`toolkit-cli/docs/project-documentation-sensors.md`,
`toolkit-cli/docs/project-documentation-wireless-l1.md` and
`toolkit-cli/docs/project-documentation-architectural.md`.

For ST7 SENLL reports read `toolkit-cli/docs/project-documentation-st7-light-level.md`: the selected class has zero fresh keys, block4 TimerMin10 and direct ordered Level/On-Off/Broadcast/Enable dependencies. Stored key/scene values do not create report dependencies. DIMPR12A selects the existing DIN ErrorReportOutput profile, not Bytecraft. Exact native report identity/projection rules are in `toolkit-cli/docs/native-project-documentation.md`.

Retained static-grid histories admit begin/input/commit/cancel/focus events. Explicitly commit, cancel or change cell focus before modal close; pending-close timing remains unproved and refuses. One private parent name cache survives dialog opens and later widget/SceneManager allocation, including names longer than the truncated PP image. Initial .NET Framework replacement decoding preserves unchanged/equal-name malformed rows. New parent loads and Reset rebuild it; operations JSON cannot inject cache state. Standalone allocators remain strict. Read `toolkit-cli/docs/edlt-static-language-add.md` and `toolkit-cli/docs/feature-batch-2026-10-03-grid-native-report-corrections.md`.


## Explicit SceneName callbacks

For KEYGL5 / 5055EDL firmware 5.5.00, `get-name` and `scene-name-control` are retained SceneManager operations. Use explicit input/Enter/Leave/arrow-preview/selected-name/list-refresh histories; inspect all 64 `static_names`, eight `scene_names_view` rows, allocations and pending/suppression receipts. Source-faithful property allocation keeps the old reference until replacement succeeds, checks exact cached reuse before capacity and preserves the full name while PP stores only its first 63 UTF-8 bytes plus NUL. This differs from the unchanged additive `set-name-text` release-before-allocation policy. Input allows 64 UTF-16 units; embedded NUL and unpaired surrogates refuse. Stable Framework whitespace clears a reference; whitespace-only U+180E requires the original host and refuses. Pending input can be inspected and continued within issued state but never saved or injected from JSON. Ordered parent operations adopt checked names; later widgets reuse them and later indexed grid edits update shared scene getters. Direct model edits do not infer automatic host control refresh; later Enter writes the retained display unless an explicit read refreshed it. Culture ordering, equal-name survivors, automatic notification/scene switching, pending modal close, async dispatch, complete original form and physical rendering remain open. Read `toolkit-cli/docs/edlt-scene-name-control.md` and `toolkit-cli/docs/feature-batch-2026-10-03-scene-name-control.md`. Preserve separate PP/project save uncertainty and never replay.


## Explicit SceneManager selector callbacks

For KEYGL5 /5055EDL firmware 5.5.00, `get-selector-view` reads the source TriggerGroup then ActionSelector and returns complete ordered application, actual trigger, named action and dynamic-label rows. Choose the exact current ordinal, identity and value before preparing `scene-selector-control` callbacks. Primary/secondary values are 0/1. Actual trigger lists do not inherit the legacy synthetic unused255. The global retained form keeps direct action/label bindings when Current is null; a later levels callback can still write the old bound scene while disabled. Trigger setter and explicit resolve/bind/getter/refresh remain separate. A fresh owner or Reset starts unbound; pending SceneName text is never committed/discarded by these callbacks and still prevents saving.

Manual cache v2 supplies exact trigger_list and action_lists in addition to unchanged v1 facts. Native automatic metadata now issues a private causal timeline for create-enabled getters and accepted/cancelled SceneManager Add histories. Each initial scene retains its loaded label epoch. Creation refreshes all modeled network collections; old bound lists survive until an explicit callback rebinds them. Read the current complete choice rows and use their exact ordinal, identity and value; a newly created action cannot be selected from an old binding. Earlier parent edits/Add are visible at the SceneManager position, while later widget objects stay out of earlier lists and validation/save contexts. Reset reissues a fresh initializer. Earlier text-only Language mutation now uses a sealed initializer that independently replays the public parent prefix and exact XML projection while preserving original scene-label ownership. Initial valid getters and scene-current callbacks keep old DynamicAll; an ActionSelector setter or explicit trigger-current refresh uses current text labels. Image/FONT/opaque DLTP or ambiguous Language histories refuse. Read toolkit-cli/docs/edlt-scene-buttons-language.md before combining these operations. Exported cache/state/timeline JSON is review material, never an issuer. Native apply materializes reviewed objects before PP staging and does not run original COM/WinForms scheduling. Keep legacy direct-operation creation paths separate. Do not infer host currency selection, null parsing, notification cascades, async/modal behavior or original/physical acceptance. Read toolkit-cli/docs/edlt-scene-selector-control.md, toolkit-cli/docs/edlt-scene-selector-metadata.md, toolkit-cli/docs/edlt-scene-inventory-timeline.md and the causal inventory batch report. Preserve one owning PP save, separate project save and no replay after uncertainty.


## SceneManager Add buttons and reconciliation

Use `scene-button-control` with `button` equal to `add-trigger-group`,
`add-action-selector` or `new-lighting-group`, an explicit `dialog` outcome and
`scene` 1..8. Lighting additionally requires `selected_scenes`; zero/multiple
rows return without creating. Read selector views first and bind actual returned
identities/ordinals/values. Action Add consumes the retained selected Trigger,
not a later raw Trigger edit, and cannot select a new action absent from old
Items. Lighting compares returned Group address with application-choice values;
it does not insert a scene item. Inspect `scene_button_control` callbacks and
`planned_creations`. Cancellation skips accepted OnOK checks but setup still
needs a free provisional address. Accepted naming requires explicit native
Project.TagName. JSON cannot issue owner/control/initializer authority.

`coverage --reconciliation-bundle FILE --reconciliation-artifact-root DIR`
diagnoses declared source profiles, obligation variants, mappings and pinned
evidence. Report its nested `complete_for_declared_surface` separately from
global completion. Supplied JSON cannot issue original/physical gate authority
or make `--require-complete` pass. Read
`toolkit-cli/docs/toolkit-obligation-reconciliation.md`; do not infer functional
profiles from control names, forwarded commands or test filenames. Treat
OnColor as a scalar only for `TLEDStatusIndicator` and
`TFlashLEDStatusIndicator`; other OnColor bindings remain events requiring
handler evidence.


## Image-backed label and Language successor

The native image profile now admits SHA-bound ordered project FILE exports and
optional decoded DLTP files. FONT matches the prefix before its first comma;
every non-ICON type can match the exact whole key, with first directory-order
match. ICON uses exact DLTP integer-key text. All consumed project images are
decoded within the documented bounded BMP profile; full GDI/codecs, opacity,
filename culture and rendering remain open. The exporter retains bytes in its
private output and emits hashes/counts rather than duplicate pixels in stdout.

Lighting `label_controls` executes the exact source type/index recursion and
explicit ComboImageTagDLT callbacks after its ordinary widget projection, with
the shared whole-unit static cache. Current Lighting getters consume current
causal group rows after earlier Language changes; Scene initial labels retain
their separate old-object references until an explicit setter/refresh. Owner,
source snapshot, operation position/history and rows seal the in-process binding.
Static suggestion ordinals require an observed culture/order profile and refuse
on the current automatic path. Read `toolkit-cli/docs/edlt-label-controls-images.md`.


## Explicit MRA callbacks

The owning parent admits `mra_controls` for `zone-control`, `source-select`
and `source-control`; use the schemas in `toolkit-cli/docs/edlt-mra-controls.md`.
The binding seals the exact issued instance, causal complete PP, operation,
selected32-byte record, all64 retained Names and reference inventory. Receipts
and JSON do not issue or resume controls. Static writes keep their old raw
reference during allocation; Select's hidden status is still used. Status
writes do not use AppGroup's index-reset rule. Read-only views never invoke the
Zone macro getter; `get-zone-macro` explicitly repairs an invalid pair.

Initialized multiplexer/zone values come from the first surviving loaded MRA
model before conversion; Reset starts fresh initialization. Shared distribution
occurs at terminal BeforeSave, with independent explicit owners. Existing Reset
still admits only initial navigation0/1 and widget types0,2,6,7,8,10,255; these
callbacks do not broaden its initial model profile. Binding declarations are
created in InitializeComponent. The frozen form vector's SetUpDataSource phase
means activation context only; see the sanitized
`toolkit-cli/research/fixtures/edlt-mra-control-provenance.json` qualification.
Original host dispatch, culture order, modal choices, rendering, audio hardware
and full Toolkit acceptance remain open. Component evidence does not change
ledger states or complete the provisional functionality census.

## AppGroup, Scene widget and automatic Global Programming controls

The owning automatic parent now issues explicit `label_controls` for Enable,
Timer, Shutter, MultiLevel, Fan and Room Courtesy in addition to Lighting. The
binding requires exact issued identity, owner, causal postordinary PP/history,
current dynamic rows and all64 retained Names. Fan/MultiLevel's four static
status controls use ComboBoxStaticText; other target modes use their actual
panel type choices. Scene operations accept flat ordered `scene_controls` for
observed choices, status text, cycle getters/current rows and explicit buttons.
A pure `get-view` does not imply SceneCycle normalization. Raw8 is admitted by
the explicit component getter; native parent save still requires configured
active scene references0..7. Read `toolkit-cli/docs/edlt-widget-control-adapters.md`
before constructing histories. Receipts never issue or resume an owning control.

For Global Programming, `edlt global-plan --project-xml FILE --unit PATH` and
`cgate edlt-global --auto-metadata --source-database PATH` derive the ordinary
source from exact project/XML/PP/order/current Language and SHA-bound image
providers. Live targets must be distinct same-project units other than source.
The coordinator checks whole-project freshness and each complete874-PP target,
and preserves unrelated canonical graph data. No label transfer, image upload,
Language mutation, target lifecycle or factory preparation is implied. Read
`toolkit-cli/docs/edlt-global-image-metadata.md`; uncertain successful saves stop
without replay. Original GUI/native/hardware acceptance remains separate.

## Dual-key callbacks and complete Neo report factory profiles

For Timer, Shutter and Room Courtesy parent operations, `dual_key_controls`
adds explicit property and binding histories. Use a controls-only retained
page/position operation to preserve raw macro, level, ramp and hidden bytes;
ordinary scalar edits and explicit conversions retain their existing
configuration/default profile before callbacks. Inspect the issued control
view and exact choices; getters may clamp source fields, while receipt/view
serialization never invents mutation getters. The parent owns one PP save,
static Names and uncertain-save recovery. Read
`toolkit-cli/docs/edlt-dual-key-controls.md`; original input parsing, framework
notifications, modal icon selection, rendering and hardware remain open.

Saved Neo/NeoPro reports cover 43 exact types across 59 source factory partitions.
Require the complete admitted PP/dependency graph rather than infer absent
values. KEYEx masks/defaults/IR positions and six couplers' Bistable cells have
source-specific rules; the couplers inherit Neo Other-usage behavior even while
using Pro blocks/scenes. Read
`toolkit-cli/docs/project-documentation-neo-profiles.md`. A document generated
from saved XML or one fresh database snapshot is not original GUI/print or
physical acceptance.


For explicit retained Time/Date callbacks, read
`toolkit-cli/docs/edlt-time-date-controls.md`. Add `time_date_controls` inside
the owning ordered `time-date` operation, with exact current source-issued
ordinal/identity/value for offered writes. Binding reads preserve raw display
255. Type writes admit only10/11 despite exposing the complete source choice
lists. Changed10→11 claims its actual next record and available Restore0;
same11 and11→10 preserve the neighbor. Keep full PP/global/LevelBarStyle,
static-label, causal Reset and terminal ownership guards. JSON receipts or
copied/rebound bindings cannot issue continuation authority. Assignment and
notification intents do not prove raw-token equality, initialization mode,
implicit WinForms dispatch or rendering. Use one owning PP SAVE plus a separate
project SAVE and never replay uncertainty. If cmqttd returns the exact applied
repository500, the transport closes and automatic parent/SceneManager inverse
recovery is suppressed; fresh read-only inspection remains explicit.

## Per-unit Neo indicator panel

Use `keys neo-indicator-editor-show|neo-indicator-editor-plan` with a decoded
schema and PP snapshot; the plan takes an ordered `--controls` JSON array.
The existing-database `cgate unit ... neo-indicator-editor` command accepts
`--controls` or a reviewed `--plan`, with `--dry-run` for PP staging only.
This is separate from the Unit Magic bulk options/styles. Thirty ordinary
profiles at firmware 2.5.00 support physical LED style/on-colour edits,
read-only derived off-colours, global indicator callbacks and all-eight-slot
load/save normalization. KEYE remapping and whole-parent form histories remain
outside this lane. Consult `toolkit-cli/docs/neo-indicator-editor.md` for exact
control eligibility, catalogue labels, hidden-field normalization and source
versus runtime acceptance boundaries.

## Explicit thermostat damper histories

Use `thermostat settings preview|apply --output-operation JSON` for the seven
records in `toolkit-cli/docs/thermostat-damper-controls.md`. FormShow precedes
after-show/group-change/modulation callbacks. InstalledZones assignment and
zone update are separate records; do not invent automatic notification delivery.
Cache identities belong to this fresh owner, not an imported receipt. Binding
changes the model; warning Click observes checked state. Inspect final factor
serialization, ControlledZones, graph creations and whole PP preservation.
No-op writes nothing; graph-only mutation has no PP save. Use one settings
transaction and never replay an uncertain save. Native GUI, subscriber
multiplicity outside the separate fixed fresh-owner profile and hardware acceptance stay open.
The new `toolkit-cli/docs/thermostat-quick-zone-controls.md` describes that
bounded explicit owner integration; its accepted source/wheel scope is recorded in `toolkit-cli/docs/feature-batch-2026-10-04-thermostat-quick-zone-controls.md`.
The batch report separates failed 22-module predecessors from the corrected
78-case source/installed-wheel follow-ups; do not combine their test counts.

## Application SAFE database workflow

For complete admitted Application database copy or Address/TagName edits, read
`toolkit-cli/docs/application-database-safe.md` first. `cgate database copy`
reads the source and sends one `DBCOPYSAFE`; `cgate database set` sends one
`DBSETSAFE`. Supply `--project` on that same operation connection, check fresh
issued identities and the complete graph, then explicitly save the project that
changed. Address moves retain subtree identities and recorded order; copied
descendants receive fresh OIDs. Incomplete sibling reservations and unsupported
source metadata refuse before commit. Never retry an uncertain mutation or save.
Existing Unit/shared-OID and raw owners remain unchanged.

Application scalar acceptance does not prove numeric Level Value mutation.
The separate now-adopted consistency fix is described in
`toolkit-cli/docs/ordinary-level-value.md`. Its adopted branch separately passed
exact source 12 and fresh installed mock 6/daemon 6 cases with the current
runner. The separate resilience report at
`toolkit-cli/docs/acceptance/2026-10-05-ordinary-level-resilience/report.md` records
source five and fresh installed mock two/daemon three cases for public NetVar
edits, lost successful Value/save receipts and disk-backed restart. Owned policy
is source-backed; issue 131 remains open pending merge/required CI at that
checkpoint. Prior proofs remain distinct. These focused proofs do not execute
the full configured 1,067 explicit identities plus seven whole modules. In a build with
the fix, use canonical numeric coordinates, `--project` on the same connection
and a complete coherent typed byte owner. Require fresh numeric/OID/whole-XML
readback. A coherent presently loaded foreign owner can explain an exact global
OID-cache byte; it does not prove which historical writer created that cache.
A cache alone is not owner authority. Unsafe, Unit/shared-OID and existing
associated raw owners remain separate. Target 3.4 HELP*
documents the copy/set business rules but not the missing exact mutation,
error/no-op/case/whitespace receipts of issues 124/125. Those native boundaries,
native/hardware acceptance and the general parity ledger remain open.

The original full source Make interop checkpoint passed all 1,050 required IDs
and seven whole core modules, with two optional UnitSpec skips. The fresh
installed 28/31 focused phases are separate. Later matrix/serial/metadata
composition and issue 131 adoption are outside that original acceptance.


## Conversion XML and prepared thermostat zone controls

Conversion creation, replacement and read-only recovery use a conversion-only
semantic XML comparator. Inherited `xml:space="preserve"`, mixed-content
separators, CDATA and whitespace-only leaves are significant; only default-scope
element-container formatting indentation is ignored. Detached Units retain
actual ancestor scope and namespace context. Invalid directives refuse locally.
Read `toolkit-cli/docs/conversion-xml-preservation.md`; preserve stopped journals,
never replay uncertain sends, and never promote legacy journal observations to
new semantic persistence proof. This does not widen native XML schema admission.

Use `{"op":"zone-checkbox-binding","binding":"MeasuredZones.Zone2","checked":true}`
in the existing ordered `--output-operation` history for one of the 34 prepared
thermostat Boolean bindings. Require the current fresh owner and explicit
`--temperature-preference celsius`; equality guards, synchronous callbacks,
shared damper/output references and one sealed family save apply. Read
`toolkit-cli/docs/thermostat-zone-controls.md` for the exact closed roster,
profile and Basic/Programmable consequences. JSON diagnostics are observations,
not resumable owner state. Unknown bindings, non-Booleans and caller callbacks
refuse before connection. Native GUI admission/dispatch, Application migration,
Delete, unrecovered temperature/time controls and hardware remain separate work.
