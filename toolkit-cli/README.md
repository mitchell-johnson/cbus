# Python C-Bus Toolkit CLI

This is an implementation in progress targeting **Toolkit 1.18.0.2754 with
C-Gate 3.4.0.2001**. It does **not yet provide 100% Toolkit parity**. The
current ledger has **42 areas: 18 implemented, 21 in progress and 3 pending**.
The simple implemented-row ratio is **18/42 = 42.86%**; it is not an estimate
of Toolkit functionality. The new [functional parity register](docs/parity-register.md)
accounts for 22,156 committed source-surface records. That inventory now
includes 412 parsed Toolkit forms, 10,102 executable controls and 1,892 event
bindings, but all remain provisional until P0 resolves them into a complete,
deduplicated functional denominator.
Run `cbus-toolkit coverage --require-complete` to inspect the evidence-derived
status. From this directory, add `--evidence-root .` to verify every recorded
input and report before attempting a release decision. Functional percentages
are `null` while `denominator_ready` is false or evidence files are unverified,
and the command deliberately exits nonzero while census or acceptance work is
unfinished.

See [completed functions and outstanding work](docs/implementation-status.md)
for the current status of all 39 feature areas, detailed eDLT functions,
accepted test checkpoints and the remaining implementation plan.

For supported physical operations without Windows, connect this CLI to the
[C-Gate service embedded in cmqttd](../docs/cmqttd-cgate.md). MQTT and CLI
requests share one CNI connection. `cgate exec` and `cgate run` can send any
command exposed by the selected C-Gate service, while the typed commands in
this CLI implement the guarded Toolkit workflows documented here. Raw command
reachability does not establish typed workflow, native C-Gate, Toolkit GUI or
hardware parity.

For KEYGL5 eDLTs, `cgate edlt-labels` reads the supported live label image and
`cgate edlt-label-audit` creates or checks serial-bound baselines that also
include the cached 44-byte `WidgetGroups` mapping. The audit distinguishes
verified static configuration from transient network-wide label observations
and unread device caches; see [the eDLT label acceptance workflow](docs/edlt-label-audit.md).

To edit a saved database object as XML, `cgate database get-xml PATH
--project NAME --output NEW.xml` writes a new native XML file and reports its
SHA-256. `cgate database set-xml PATH EDITED.xml --project NAME
--expect-current-sha256 HASH --readback` submits one complete document and
reports the server's mapped readback without implicitly saving the project.
See the [native XML file workflow and limits](docs/native-database-xml-files.md).

Run the source, installed-wheel and interoperability gates below for results
from the current revision. CI retains JUnit reports with the executed tests and
provisioning skips; those reports are separate from the evidence-derived parity
decision.

Whole-project database CSV export is available offline with
`toolkit-database-csv project.xml --native-xml-project //PROJECT --output new.csv`
and live with `cgate database-csv --project //PROJECT --output new.csv`. It
reads one project snapshot, includes every supported unit across its networks,
and rejects unsupported or ambiguous units before creating a partial report.
Rows follow snapshot network order and numeric unit-address order within each
network. The per-network sort comes from pinned original Toolkit code; full
interactive manager behavior remains unverified. See [CSV profiles and limits](docs/toolkit-database-csv.md).

## Install and run

Python 3.13 or newer, from the repository root:

```sh
python3.13 -m venv toolkit-cli/.venv
toolkit-cli/.venv/bin/python -m pip install -e ./toolkit-cli
source toolkit-cli/.venv/bin/activate
cbus-toolkit --help
```

The package has no mandatory external Python dependencies. It is maintained
alongside the separate [Rust MQTT bridge and tools](../rust/README.md).
Results are JSON on stdout, errors are JSON on stderr, and unsuccessful
operations return nonzero. Use `--compact` before the command for JSON lines.
The event monitor always emits one JSON object per line.
JSON output escapes non-ASCII characters so redirected Windows output works
with legacy code pages; decoding the JSON restores the exact Unicode text.

## Discover a CNI

Discover CNI2 and Wiser interfaces with the captured Toolkit-compatible IPv4
UDP exchange, without opening their TCP service:

```sh
cbus-toolkit interface discover-cni
```

The command sends one query, collects replies through a bounded monotonic
window, rejects malformed fixed-layout packets, suppresses exact duplicates and
returns each source address with its advertised TCP port as JSON. Product-id 2
is hidden by default to match the retained behavior; use `--include-hidden` to
inspect it. A zero-result run does not prove absence. On hosts with several
adapters, pass the numeric local address with `--bind`.

To survey active host IPv4 adapters, install the optional `network` extra and
inspect the planned routes before sending a query:

```sh
python -m pip install -e '.[network]'
cbus-toolkit interface scan-cni --auto-adapters --plan-only
cbus-toolkit interface scan-cni --auto-adapters --interface en0
```

`--interface` is optional and repeatable. The CLI derives directed broadcast
routes from operational adapters, records skipped addresses and their reasons,
and attaches the planned adapter to each probe result; actual packet egress is
not verified. To survey several
chosen adapters or subnets manually, pass one numeric local-address and
destination pair per probe:

```sh
cbus-toolkit interface scan-cni \
  --probe 192.0.2.10@192.0.2.255 \
  --probe 198.51.100.10@198.51.100.255
```

Each route gets one query and its own result. The command accepts 1–16 unique
routes with a total configured reply window of at most 300 seconds, and
distinguishes devices, no reply by deadline, filtered packets, a datagram cap,
and a transport error. It never infers absence, TCP reachability, or exclusive
ownership. Adapter discovery is a non-atomic OS snapshot; firewall, subnet
and physical-interface acceptance and native `PORT CNISCAN2` status checks
remain open.

After reviewing a result, use its `endpoint` explicitly when creating a native
network:

```sh
cbus-toolkit cgate --host your-cgate project new TEST
cbus-toolkit cgate --host your-cgate database network-new TEST 254 Local Cni 192.0.2.10:10001
cbus-toolkit cgate --host your-cgate project save TEST
```

Discovery does not choose a device, edit a project, open C-Bus, or test TCP
reachability. See [CNI interface discovery](docs/cni-discovery.md) for the
wire vectors, result fields, Rust equivalent, and acceptance boundary.

## Toolkit preferences

```sh
cbus-toolkit preferences schema
cbus-toolkit preferences initial-state > seed-preferences.json
cbus-toolkit preferences controls current-preferences.json
cbus-toolkit preferences plan current-preferences.json --edit 'cmbJavaHeapMax="512"'
cbus-toolkit preferences registry-save current-preferences.json --dry-run
```

[Preference controls and Windows storage](docs/toolkit-preferences.md) expose all
40 registered settings and five display values. Ordered control plans preserve
21 settings outside the original OK handler. Windows load/save retain the
original default-write, hive fallback, and partial-failure behavior. Load can
write missing values; a full retained input state is required. The separate
94-test checkpoint passes both supported Python versions, including twenty-one
actual Windows registry cases per run in owned test namespaces. The initial-state
command provides observed constructor values; controls include the original
address-preview text. `preferences reset-dont-ask-again` resets suppressed
prompts and supports `--dry-run`. Use
`--numeric-locale dot|comma` with `controls`, `plan`, or `registry-load` for the
bounded original numeric conversion. Separate checks cover interruption-evidence
handling and [64-bit Windows Python](docs/windows-preferences-compatibility.md).
`update-link` prints the Toolkit downloads URL;
`update-catalogue --installed-version 1.18.0` queries server-assigned candidates.
Its [19-test checkpoint](docs/toolkit-updates.md)
passes both Python versions and does not claim update availability.
`update-metadata-stages node.json --certificate signer.der --at-utc 2026-09-15T00:00:00Z`
evaluates six separate offline stages, including canonical payload, signature
against the supplied key and JWT lifetime. The certificate remains untrusted;
publisher trust, revocation and machine applicability are not evaluated.
Its [combined 56-test checkpoint](docs/toolkit-update-metadata.md) passes both
Python versions and includes the new routing CLI and existing update,
percentage and JSON output regressions. GUI runtime effects remain incomplete.

`update-package-file --catalogue-response raw-catalogue.json --node-id ID
--file-id ID --package-path local-package.exe` checks the bytes of one already
local file against the selected untrusted catalogue size and SHA-1 descriptor.
The [receipt](docs/toolkit-update-package-file.md) records exact source and
package digests. A match does not establish publisher trust, applicability or
permission to install; the command neither downloads nor executes the file.

`update-applicability-preflight --catalogue-response raw-catalogue.json
--node-id ID --platform windows_x86_64 --at-utc 2026-09-15T00:00:00Z`
inspects one untrusted catalogue candidate under an explicit evaluation
context. The bounded [preflight contract](docs/toolkit-update-applicability-preflight.md)
checks source order, architecture-specific file selection, date/media fields
and HTTPS URI shape. Twenty original-method outcomes matched on the disposable
Windows profile. The supplied UTC instant is not the original updater's local
wall clock; publisher trust, rollout policy, download and installation remain
unassessed.

`update-rollout-cohort --catalogue-response raw-catalogue.json --node-id ID
--stored-cohort 41` evaluates the original strict `visibilityInPercent > cohort`
gate for one source-pinned node with a **caller-supplied** stored 0–99 cohort.
The [bounded rollout contract](docs/toolkit-update-rollout-cohort.md) makes no
registry read or write. It does not generate a cohort, establish that the
supplied number belongs to this machine, or make an update available.

On Windows, `update-rollout-owned-registry --catalogue-response
raw-catalogue.json --node-id ID --owned-namespace my-rollout-study
--ensure-owned-key` exercises the captured missing-entry/sentinel sampling and
persistence branch under an explicitly owned HKCU Registry32 scratch key.
It also reports existing and absent-key outcomes with typed reads. The
[owned-key contract](docs/toolkit-update-rollout-owned-registry.md) explains
the key scope, exact receipts and remaining boundary: this command is tied
to its scratch key, so it does not attest to the current user's actual updater
cohort or enable an
installation.

On Windows, `update-rollout-current-user --source-assembly SesuBrick.DAD.dll
--expected-source-sha256 21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c
--expected-user-sid SID` separately reads the pinned original SESU cohort
entry in this CLI process user's HKCU Registry32 view. The
[read-only contract](docs/toolkit-update-rollout-current-user.md) explains the
source/SID guards, supported values and missing/sentinel branches. One
interactive Windows acceptance seeded a cohort with the pinned original
helper, read the same value with this CLI, then restored the absent entry.
The CLI makes no catalogue, trust, availability or installation decision.

`update-applicability-cohort-preflight --catalogue-response raw-catalogue.json
--node-id ID --platform windows_x86_64 --at-utc ...Z --stored-cohort 41`
composes the captured empty-condition date/file/media/URI gates with that
strict rollout comparison on the **same selected source node**. Its
[bounded combined contract](docs/toolkit-update-applicability-cohort-preflight.md)
reports whether the rollout gate was reached after earlier gates passed.
It still uses a caller-supplied cohort and clock/platform context, without
publisher trust, host-registry attestation, update availability or installation.

`update-revocation-stages revocation.json --signer-certificate signer.der --at-utc 2026-09-15T00:00:00Z`
evaluates seven offline stages for signed revocation metadata, including the
original embedded signer identity. The separate
[53-test checkpoint](docs/toolkit-update-revocation.md) passes on both Python
versions and preserves the existing metadata reports. It does not establish
certificate-chain trust, current publisher trust or update availability.

`update-condition-stages conditions.json --context facts.json` evaluates bounded
Boolean conditions using explicitly supplied file-existence and version facts,
or [context v2 with HKCU registry results](docs/toolkit-update-registry-conditions.md).
Supported registry leaves cover key/entry existence and bounded string/Int32
content comparisons. It preserves lazy evaluation, repeated-condition caching
and partial results. Both a computed `true` and a computed `false` exit
successfully; unknown facts and unsupported conditions remain explicit. The
combined 78-test checkpoint passes on both Python versions, including the
earlier 61 regressions, 11 supported original registry results, 107 Int32
comparisons and 248 byte-identical v1 reports. Supplied facts remain unverified;
the command does not read the live registry or determine package applicability
or update availability.

On Windows, `update-condition-live conditions.json --file-context file-facts.json
--registry-scope registry-scope.json` evaluates the same bounded expression while
lazily reading only the one to eight exact HKCU queries admitted by the scope.
It uses the checked x86 .NET Framework worker, hashes all three input files and
retains partial observation and cleanup evidence on failure or interruption.
Both computed Boolean results exit successfully. The accepted worker has seven
typed observations in LocalSystem HKCU; an 11-case original checker matrix,
one bounded two-call Python API comparison and one active-desktop-user
installed-wheel `--repeat-once` run cover selected lazy behavior. Broader
interactive contexts and preferences/settings-wrapper comparison remain open.
See [live registry observation](docs/toolkit-live-registry-observation.md).

`update-diagnostic-bundle --catalogue catalogue-report.json --metadata
metadata-report.json --revocation revocation-report.json --conditions
condition-report.json --catalogue-response raw-catalogue.json --revocation-input
raw-revocation.json --conditions-input condition-data.json --context-input
context.json --metadata-certificate metadata-signer.der
--revocation-signer-certificate revocation-signer.der --node-id ID` parses the
exact report and source files. It links the
selected metadata node to the catalogue response, its condition model, and the
revocation subject after matching both producer certificate digests and
thumbprints to supplied DER. Report-only input, missing receipts, substituted bytes,
ambiguous IDs, or unrelated reports keep linked completion false. The [provenance contract](docs/toolkit-update-diagnostic-bundle.md)
does not turn those diagnostics into publisher trust, package applicability,
update availability, a download, or an installation decision.

`update-package-bundle` joins that diagnostic bundle to one
`update-package-file` receipt. Supply both existing reports, their exact
diagnostic inputs, the raw catalogue response, the selected node/file IDs, and
the already-present package path. It reproduces both reports, re-reads the file,
and links the selected catalogue descriptor to its observed bytes. A failed
diagnostic stage can leave the independent package link intact; the joined
completion remains false. See the [exact-source join contract](docs/toolkit-update-package-bundle.md).
This receipt is not publisher trust or permission to install.

`toolkit-about path/to/CBusToolkit.exe` reads an explicit executable and emits
the original About text, using the current local year. `--year 2026` supplies
a reproducible year; `--context captured-context.json` adds explicitly supplied
C-Gate details. The executable is read without being run. The separate
[16-test checkpoint](docs/toolkit-about.md) passes on Python 3.13 (historical runs also covered 3.10; current policy is 3.13-only),
including 51 fresh original-instruction cases per run. Display-name and context
provenance are reported; supplied context is not checked against a live service.

`toolkit-database-csv capture.json --output report.csv` exports explicit captured
report values as UTF-8 by default, preserving the original column order, serial formatting,
quoting and unavailable-group placement. `--columns address tag_name serial`
selects fields. `--cached-projection` instead consumes the strict retained
unit/group-cache schema and reproduces the 12 captured original class, Area,
reference and missing-group outcomes before export. `--native-xml-unit
//PROJECT/254/p/4` projects the admitted RELAY4, generic, KEYE1–4/KEYEIR1–4, DIMDN8, DIMDN8F,
RELDN12, SENPIROA and SENPIRIA read-only C-Gate XML shapes without manual cache transcription. KEYE
firmware 2.5.00 retains all nine ordered group associations, including repeated
unused slots and legacy records without OIDs. DIN firmware 2.7.00 retains all
16 stored associations while applying the original 8-channel DIMDN8/DIMDN8F and
12-channel RELDN12 interaction limits. DIMDN8F has pinned original factory,
class and agent evidence plus a synthetic native XML fixture; its cold native
load and original GUI report remain unverified. SENPIROA and SENPIRIA firmware 2.4.00
retain eight ordered sensor associations and select their registered ST7
classes. SENPIRIA also resolves each masked block in its configured secondary
application while Area remains in the primary application. KEYE
secondary-application masks now resolve each first-eight block through its
selected application, including distinct same-address groups; the ninth stored
slot remains primary and unavailable in the report. `cgate --host HOST database-csv
//PROJECT/254/p/4 --output report.csv` acquires the same bounded project snapshot
with one read-only `DBGETXML` command and projects it in memory. Offline
`--native-xml-units` and live `--units` export an explicit ordered selection;
`--native-xml-network` and live `--network` export every unit in one network's
numeric unit-address order; `--native-xml-project` and live `--project` export
all networks in snapshot order with numeric unit-address order within each.
An explicit selection may span networks within one project. Each export uses
one parsed snapshot capped at 8 MiB of UTF-8 and one live request, and rejects
the entire export
before exclusive output creation if any selected unit is missing, ambiguous or
unsupported. The address sort is supported by the pinned original manager
constructor/comparator and report call chain; full interactive enumeration
remains unverified. For the exact
captured missing-Area13 shape, `--apply-missing-area --backup-project BACKUP`
backs up, creates, saves, reloads and verifies the group before export. The
original 26-column form preference can be loaded with
`--toolkit-column-selection` or persisted with
`--save-toolkit-column-selection`; both use Toolkit's Windows 32-bit HKCU value
before file or C-Gate access. On Windows, `--toolkit-native-encoding` reproduces
Toolkit's CP_ACP `WideCharToMultiByte` conversion, replacement behavior and
BOM-free output. The current core/CLI set passes 82 tests, both host Windows
guards and five owned Windows tests pass, and one owned C-Gate
acceptance passes. The earlier 23-test checkpoint includes 88 fresh original
comparisons per run. Secondary associations for other families and remaining
unit profiles remain separate.

## Legacy projects

```sh
cbus-toolkit project new test.cbz --name TEST
cbus-toolkit project add test.cbz --kind network --address 254 --name Local
cbus-toolkit project add test.cbz --kind application --parent /254 --address 56 --name Lighting
cbus-toolkit project add test.cbz --kind group --parent /254/56 --address 1 --name Lounge
cbus-toolkit project inspect test.cbz
cbus-toolkit project field-set test.cbz /254/56/1 TagName 'Living room'
cbus-toolkit project export test.cbz test.xml --format xml
cbus-toolkit project validate test.xml
```

The editor retains unknown XML, comments, namespaces, archive attachments,
and opaque programming fields. Unchanged files roundtrip byte-for-byte.
Mutations use validation and atomic replacement. `--output` writes edits to
a separate file. Explicit OID references protect against dangling references;
device-specific implicit references are not yet modeled. Native C-Gate 3
SQLite projects must be managed through C-Gate rather than the legacy editor.

`project topology` builds the Toolkit topology map of a saved XML/CBZ project:
networks, interfaces, bridges and wireless gateways, orphaned networks and
circular joins. It also resolves navigation targets and exports deterministic
DOT or SVG images; original layout, print and pixel parity are unassessed.
See [topology](docs/topology.md).

```sh
cbus-toolkit project topology house.cbz --navigate 3
cbus-toolkit project topology house.cbz --far-side 254/3
cbus-toolkit project topology house.cbz --format svg --output topology.svg
```

## C-Gate and PCI

Outgoing CAL routes can also be encoded and inspected offline:

```sh
cbus-toolkit pci-route encode --unit 4 --cal 2104 \
  --bridge 30 --bridge 20 --confirmation g --checksum
cbus-toolkit pci-route inspect 5C34363145313231343034323130343444670D --checksum
cbus-toolkit pci-route receive 3836313431303032313530343831303442360D
```

The codec preserves explicit routing bytes, checks the six-entry limit and
retains unit-zero/programming ambiguity during inspection. It performs no
network I/O. See [pci-routing.md](docs/pci-routing.md) for original-code evidence
and the separate codec and CLI test checkpoints.
`receive` checks one addressed `06`/`86` frame, its mandatory checksum and
exactly one supported CAL. It retains all routing bytes without inferring a
source device or network. Its separate 45-test checkpoint passes on both
Python versions, including 1,142 fresh original constructor and checksum
cases per run.

For one raw routed read, supply both the outgoing bridges and the independent
expected reply path:

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 routed-recall 4 30 1 \
  --bridge 20 --bridge 21 --expected-source 20 --expected-destination 16 \
  --expected-route 21 --expected-route 4
```

The command requires a numeric endpoint, one positive confirmation and an exact
checksum-valid reply. It sends once and reports partial outcomes without retry.
Its [73-test checkpoint](docs/pci-routed-recall.md) passes on both Python versions,
including 428 fresh original matcher cases per run and independent loopback
peers. Declared wire-path matching does not establish physical device identity.

For raw IDENTIFY data, use the same explicit reply-path arguments:

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 routed-identify 4 1 \
  --bridge 20 --bridge 21 --expected-source 20 --expected-destination 16 \
  --expected-route 21 --expected-route 4 --expected-count 1
```

Omit `--expected-count` to accept any supported wire count from 0 through 30;
zero bytes produce an empty payload. The separate
[104-test checkpoint](docs/pci-routed-identify.md) passes on both Python versions,
including fresh comparisons with 902 original IDENTIFY cases and 428 RECALL
cases per run. Results retain raw bytes and explicit matching evidence.

When an authoritative legacy XML/CBZ project contains the selected unit, both
read commands derive the route and complete reply path without asking you to
calculate Reply Network bytes:

```sh
cbus-toolkit pci --host 127.0.0.1 --local-unit 16 routed-recall \
  4 30 1 --project-file house.cbz --project-name GRENACHE \
  --source-network 254 --target-network 252
cbus-toolkit pci --host 127.0.0.1 --local-unit 16 routed-identify \
  4 1 --expected-count 1 --project-file house.cbz --project-name GRENACHE \
  --source-network 254 --target-network 252
```

The raw forms remain available for independently known routes. Typed reads
require the target in an unambiguous zero-to-six-bridge project path, bind the
entire saved-file digest, and recheck it before I/O. They report saved-topology
resolution without authenticating live bridge connections or device origin.

For one raw routed mutation, require the exact independent ACK path and tag:

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 routed-write 4 7 AABB \
  --bridge 20 --bridge 21 --expected-source 20 --expected-destination 16 \
  --expected-route 21 --expected-route 4 --expected-ack-tag 0x55
```

The client sends once and never retries an uncertain write. A matching ACK is
wire-correlation evidence; it does not prove physical delivery, parameter
readback or persistence. See [routed WRITE](docs/pci-routed-write.md).

When a legacy XML/CBZ project is the topology source, WRITE derives the outgoing
bridge route and independent ACK path using the same planner:

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 --local-unit 16 routed-write \
  4 7 AABB --expected-ack-tag 0x55 --project-file house.cbz \
  --project-name GRENACHE --source-network 254 --target-network 252
```

This typed form binds the complete project file by SHA-256 and checks it again
immediately before the one-shot handoff. Ambiguous, cyclic, disconnected,
unsupported, stale, or deeper-than-six-bridge topology fails before a write.
Its receipt still does not establish live bridge acceptance, parameter
readback, device commit, reboot behavior or nonvolatile persistence.

```sh
cbus-toolkit cgate exec 'GET cgate version'
cbus-toolkit cgate exec 'PROJECT LIST'
cbus-toolkit cgate exec 'DBGET //TEST/254/56'
cbus-toolkit cgate run commissioning.txt
cbus-toolkit cgate --host your-cgate --tls --ca ca.pem --cert client.pem --key client-key.pem exec NOOP
cbus-toolkit pci --host your-cni identify 5 1
cbus-toolkit pci --host your-cni recall 5 48 4
```

`cgate run` keeps one session and stops on the first failed command. Commands
are never automatically retried after an ambiguous disconnect or timeout.
Interrupting a connection, command or event read invalidates the stream; a
later command requires an explicit new connection.
TLS verifies certificates and accepts an explicit client certificate.
Verified mutual TLS has been tested against the exact native server with
operator-managed certificates; see [TLS setup and acceptance](docs/native-tls.md).
`cgate exec` and `cgate run` expose the selected server's raw command surface;
they are escape hatches for commands without a typed wrapper. They do not add
Toolkit workflow guards, prove the server's native semantics, or make an
unimplemented Toolkit feature complete. Raw PCI commands have the same
boundary: they perform the requested transport operation without establishing
device or end-to-end workflow equivalence.

Native C-Gate 3 project and unit editing:

```sh
cbus-toolkit cgate project new TEST
cbus-toolkit cgate database network-new TEST 254 Local Cni 127.0.0.1:10001
cbus-toolkit cgate database unit-new //TEST/254 20 'Lounge switch' KEY4 1.2.67
cbus-toolkit cgate database unit-new //TEST/254 21 'Hall eDLT' KEYGL5 5.5.00 --catalog-number 5055EDL
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 show
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 --dry-run set UnitName LOUNGE
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 set UnitName LOUNGE
cbus-toolkit cgate project save TEST
```

Network and unit creation edit the database with the network closed. Database
edits stay in C-Gate's project model until `project save`. The `/db//...` prefix
selects the database explicitly. Live unit sources use C-Gate's network address
syntax and can communicate with hardware. Programming sessions release their
locks on success and failure. Parameter exports use the CLI's JSON format and
include database unit identity for compatibility checks.

For guarded physical programming through cmqttd, use the typed `physical-pp`
family instead of assembling a raw PP batch:

```sh
cbus-toolkit cgate --host 127.0.0.1 physical-pp inspect \
  //TEST/253/p/4 --method paged
cbus-toolkit cgate --host 127.0.0.1 physical-pp apply \
  //TEST/253/p/4 --method paged --set ParameterName '0x01 0x02'
cbus-toolkit cgate --host 127.0.0.1 physical-pp apply \
  //TEST/253/p/4 --method goc2 --set ParameterName '0x12 0x34' \
  --destination //TEST/253/p/5
```

The CLI queries `CMQTT CAPABILITIES`, derives the exact source-network lock,
and checks the loaded native schema before editing. It supports cmqttd's
`direct`, `paged`, `ncc`, `edlt`, `giu`, `sgiu`, `dali`, `goc`, `gocbyt`, and
`goc2` physical methods. Omission of `--destination` uses one
`PP SAVE_TO_SOURCE`; an explicit same-network destination uses one `PP SAVE`.
After a confirmed save, a new locked PP session physically reloads the target
and compares every edited value using its declared schema type. No mutation is
retried. `--dry-run` stops after temporary staging and same-session readback.
The JSON leaves power-cycle persistence, the broad hardware matrix, and the
original Toolkit workflow unverified. Applying any decoded unit specification
that contains an NCC parameter additionally requires cmqttd's separate routed
Save-to-NVM capability, even when the selected edit uses another method. See
[guarded physical programming](docs/physical-programming.md) for failure
evidence, exact scope, and tests.

`database unit-new` initializes a unit through the native database-loading path.
This supports large-memory devices that fail C-Gate's `PP NEW` operation. Native
project archives, restore and rename have acceptance evidence for `.zip`, `.gz`
and `.db`. [Portable XML repair](docs/project-repair.md) is available as
`project repair damaged.xml --output repaired.xml`, with `--dry-run` for a preview.
The source remains unchanged. The original XML repository supports
`cgate project repair NAME`; the SQLite repository rejects that native command.
`cgate repositories` lists observed repositories without changing the server's
selection. Repaired legacy DBVersion 2, 2.1 or 2.2 XML can use the bounded offline
`project transform-legacy repaired.xml --output converted/PROJECT.xml` step;
the 2 and 2.1 path accepts unitless projects and native-verified KEYGL5 5.5.00
and KEYB2/KEYB4 1.6 Unit/PP profiles, including conditional obsolete-parameter
removal. The default native `cgate project transform NAME` runs the original
multi-step stylesheet chain
for more complex projects in an explicitly selected XML repository;
`--xslt-file` and `--output-file` expose the native explicit path for a
pre-existing writable server-side output file, which is overwritten;
see its [native conversion and readback evidence](docs/project-legacy-transform.md).
The combined repair checkpoint passes 31 tests on both supported Python versions,
including fresh original-code comparisons, native loading and CLI file handling.
A separate Windows checkpoint passes 16 file and CLI cases on x86 and AMD64
Python, repeated from each host Python version. It includes Unicode filenames,
partial writes, cancellation and exclusive file creation; see the
[Windows repair evidence](research/fixtures/windows-project-repair-acceptance.json).

Database unit readdressing keeps its stored programming address consistent:

```sh
cbus-toolkit cgate address inventory //TEST/254
cbus-toolkit cgate address readdress //TEST/254/p/20 31 --dry-run
cbus-toolkit cgate address readdress //TEST/254/p/20 31
cbus-toolkit cgate address network-readdress //TEST/254 253 --dry-run
cbus-toolkit unit-addressing match database-units.json scanned-units.json
```

Readdressing retains the OID and metadata, creates a project backup, validates
the change and saves it. Serial matching is a report: it identifies duplicate
serials, differing types and occupied destinations before any requested moves.
It accepts arrays of `{address, unit_type, serial}` records or the inventory
command's JSON output. Bridge topology remains outside these workflows.
`network-readdress` pairs the database and runtime changes on a closed wired
network, preserves unit programming, verifies both layers and saves a backup.
The lower-level `database rename-network` changes only the database layer.

Move a supported physical KEYE1 unit to an empty address, with its serial as
an identity check:

```sh
cbus-toolkit cgate --timeout 60 address physical-readdress //TEST/254/p/4 6 \
  --serial 101136.1558 --dry-run --plan-output address-preview.json
cbus-toolkit cgate --timeout 60 address physical-readdress //TEST/254/p/4 6 \
  --serial 101136.1558 --plan-output address-recovery.json
cbus-toolkit cgate --timeout 60 address physical-verify address-recovery.json
```

This workflow supports firmware 2.5.00 on a direct wired CNI or Serial network,
with automatic unraveling/updating disabled and native `Retries=0`. It refreshes
and checks the complete physical inventory, writes the address once, then
independently verifies the outcome. `--plan-output` creates a new recovery file
before the write. A lost response reports an uncertain outcome; the separate
verification command observes the unit without repeating the write. Native
C-Gate, literal simulator exchanges, persistence and CLI recovery are tested.
See [physical-addressing.md](docs/physical-addressing.md) for the exact scope.

Commission a single unaddressed KEYE1 at address 255 to an existing database
unit with the same serial, type and firmware:

```sh
cbus-toolkit cgate --timeout 60 address serial-commission //TEST/254/p/255 6 \
  --serial 101136.1558 --plan-output commission-recovery.json
cbus-toolkit cgate --timeout 60 address serial-verify commission-recovery.json
```

The same network guards apply. The target must be physically empty and be the
only database match. The CLI matches the database serial, issues a scalar
address operation with the explicit target, and verifies the move. Native
`MATCHDB` can choose another free address after an internal serial-read fault;
this typed workflow uses the explicit address operation. See
[serial-commissioning.md](docs/serial-commissioning.md).

Read serial numbers from C-Gate's existing physical-unit cache, or explicitly
refresh an already running network:

```sh
cbus-toolkit cgate serials cached //TEST/254 > cached-units.json
cbus-toolkit cgate serials refresh //TEST/254 --unit 4 --unit 5 > scanned-units.json
cbus-toolkit cgate address inventory //TEST/254 > database-units.json
cbus-toolkit unit-addressing match database-units.json scanned-units.json
```

Refresh scans the entire network; `--unit` limits the reported addresses and
duplicate-address checks. It requires automatic unraveling and updating to
be disabled. `serials refresh` defaults to a 300-second timeout per C-Gate
command; explicit `cgate --timeout` overrides it. Missing, invalid, duplicate
or unreadable identities remain in
the JSON report and produce exit status 1. Comparing a native serial inventory
automatically normalizes decimal-dot components and preserves incomplete
source evidence. Add `--native-serials` for this comparison on plain arrays.
See [serials.md](docs/serials.md) for cache and refresh semantics.
The independent [duplicate-address fixture](docs/duplicate-discovery.md)
verifies two serials at address 255: refresh reports `duplicate_address` and
no usable identity. A native network state of `ok` alone does not establish
that every address is unique.
Generic serial inventories report `mmi_coverage_verified: false`: native
`SYNC`/`CHECKUNIT` can miss an address range. Typed address changes require an
additional `PINGU` coverage check before writing and during verification.

An exclusively owned PCI/CNI connection can collect all serial replies at one
address, including duplicates:

```sh
cbus-toolkit pci --host 192.0.2.10 --local-unit 16 serials 255
```

This collector requires a numeric IP address and the known local PCI address.
It sends one identification request and waits for the original two-second
quiet interval. It reports each reply, incomplete evidence and duplicate
identities; only a complete single identity returns exit status 0. It does
not establish the inventory of other addresses or resolve a collision.
See [pci-serials.md](docs/pci-serials.md) for correlation rules and native evidence.

A direct MMI scan reports presence across all 256 addresses:

```sh
cbus-toolkit pci --host 192.0.2.10 --local-unit 16 mmi
```

The scanner requires contiguous response blocks and the known local interface
to appear. Missing ranges remain unknown in the JSON output. Complete coverage
with a reported unit error returns a nonzero exit status. This scan observes
presence; use serial collection to identify the units at an address.
See [pci-mmi.md](docs/pci-mmi.md) for framing and native comparison evidence.

A complete direct serial inventory combines both observations:

```sh
cbus-toolkit pci --host 192.0.2.10 --local-unit 16 inventory
```

It reads full MMI coverage, collects serials at every present address, then
reads full MMI coverage again. The result retains duplicate identities,
missing serials, changed address states and partial observations. Only a
complete, consistent inventory with unique addresses and healthy MMI states
returns exit status 0. Identical scans before and after do not establish an
atomic snapshot or authorize an address change.

The default total budget is 600 seconds, with 10 seconds per observation and
the native two-second serial quiet window. The total budget can stop a scan
before every address has been read; the output identifies unattempted work.
See [pci-full-inventory.md](docs/pci-full-inventory.md) for limits and evidence.

Selected-serial command encoding and captured-reply inspection are available
offline:

```sh
cbus-toolkit serial-address encode 101136.1558 6 --checksum
cbus-toolkit serial-address receipt capture.bin --serial 101136.1558 --destination 6 --local-unit 16
```

The encoder returns wire bytes as JSON without sending them. Receipt inspection
checks the whole capture and returns zero only for one correctly correlated
exchange. A matching packet does not verify movement or persistence; those
fields remain false. See [the codec contract](docs/pci-serial-address-codec.md).

For an exclusively owned duplicate-address fixture, commissioning now provides
separate observation, apply and recovery commands:

```sh
cbus-toolkit serial-address plan 101136.1558 6 --host 127.0.0.1 \
  --local-unit 16 --expected-local-serial 100966.1187 --output new-plan.json
cbus-toolkit serial-address apply new-plan.json --recovery new-recovery.json
cbus-toolkit serial-address verify --recovery new-recovery.json
cbus-toolkit serial-address reconcile --journal new-recovery.json --project site.xml --apply
```

The accepted fixture contains exactly two known identities at address 255.
Apply repeats the full inventory and local PCI checks, durably records the
attempt, sends at most one selected-serial command, and independently observes
the resulting inventory. A matching receipt alone cannot establish movement.
Verify performs fresh observations and never replays the command. Exit status
0 means the expected identity change was observed; other outcomes return 1.
Hardware compatibility and firmware persistence remain unverified. See
[the workflow and recovery contract](docs/pci-selected-serial.md).

To populate database serial metadata from a complete identity inventory:

```sh
cbus-toolkit cgate serials populate //TEST/254 --dry-run
cbus-toolkit cgate serials populate //TEST/254
```

The supported types are KEYE1, KEYGL5 and PC_CNIED, with matching address,
type and firmware. The operation rechecks the cache before each write, creates
a project backup, verifies that only serial metadata changed, and saves the
project. `--unit` selects database targets; `--refresh` explicitly refreshes
the whole physical inventory first and uses the same 300-second timeout
default, including with `--dry-run`. Without `--refresh`, the ordinary
10-second C-Gate default applies. See [serial-population.md](docs/serial-population.md).

Network operations are explicit:

```sh
cbus-toolkit cgate network list --project TEST
cbus-toolkit cgate network state //TEST/254
cbus-toolkit cgate network open //TEST/254
cbus-toolkit cgate --timeout 60 network sync //TEST/254 --fast
cbus-toolkit cgate --timeout 120 network sync-new //TEST/254
cbus-toolkit cgate --timeout 120 network sync-new //TEST/254 --unit 6
cbus-toolkit cgate network set-project //TEST/254 TEST
cbus-toolkit cgate network learn //TEST/254 56 init-relay 1
cbus-toolkit cgate network learn //TEST/254 56 cancel 1
cbus-toolkit cgate network locate //TEST/254/208 unit 1 ON
cbus-toolkit cgate network locate //TEST/254/208 app 56 2
cbus-toolkit cgate network locate //TEST/254/208 group 56 1 OFF
cbus-toolkit cgate network locate //TEST/254/208 serial 1 12345.67 255
cbus-toolkit cgate --timeout 120 network unravel //TEST/254 --unit 255 --match-database
cbus-toolkit cgate network tree //TEST/254 --details
cbus-toolkit cgate network close //TEST/254
```

`wait-ready` observes native state without restarting operations. Against
the selected C-Gate service, the typed `learn` command admits the six retained
grades (`init-relay`, `init-dim`, `cancel`, `exit-relay`, `exit-dim` and
`exit-area`). Typed `locate` covers UNIT, APP, GROUP and SERIAL on an explicit
Network Management application 208. Both require fully qualified direct paths,
send one correlated command through `CgateClient` and never replay an uncertain
write. Their JSON receipt reports interface delivery after an exact terminal
200 while leaving device action, physical readback and persistence false. See
[network learning and locate](docs/network-learning-locate.md) for the exact
limits, retained vectors and server-side evidence. This checkpoint did not run
the Toolkit GUI or a physical unit.

Against cmqttd, the shown unravel command has a bounded physical backend for
exactly two known serials colliding at address 255 with two unique empty database
destinations on a direct network. It sends each selected-serial move once and
accepts success only after complete before/after inventories and independent
destination checks. Other unravel forms return 502. Native C-Gate retains its
broader and potentially unsafe fallback semantics described below. Discovery,
duplicate checks and clock management have their own explicit commands; broader
physical-network acceptance is still in progress.
Against cmqttd, both `sync-new` forms use five complete MMI passes. The targeted
form rejects an address already in the model, runs the native three duplicate
challenges, and reads the new unit identity. The general form reports every new
or MMI-duplicate address. Results populate cmqttd's volatile physical cache;
add or update project database units separately.
Against cmqttd, `network set-project` performs the native physical
`NET SET_PROJECT_IDENTIFY` operation. The identity is uppercased, packed into
the six-byte native value, written to parameter 35 on the first unit in
non-error present MMI state one or two with valid type data and exactly one
valid known serial reply, and read
back before success. It updates cmqttd's volatile physical
snapshot only; it does not select, rename, create, or save a project. The name
must contain 1–8 UTF-16 code units whose uppercase form fits the native
six-bit repertoire and eight-unit field. Spaces, quotes, and backslashes are
mK-quoted automatically.
Reopening an existing model can defer its next scan. Use `network sync --fast`
with the network address to request a fresh scan; waiting alone does not start it.

```sh
cbus-toolkit cgate network clocks //TEST/254
cbus-toolkit cgate network clocks //TEST/254 --target 2
cbus-toolkit cgate network clocks //TEST/254 --recover
```

Clock targets range from 1 to 10. Configuration is followed by a fresh status
query; per-unit failures or a mismatched count produce `complete: false` and
a nonzero exit status even if C-Gate's last line says OK. Recovery enables the
gateway clock and verifies that gateway separately. See the
[native clock and burden evidence](docs/native-clocks.md).

## Sensor occupancy settings

The tested ST7 profile is SENPILL 2.0.01..2.3.9 / 5753PEIRL or SLC5753PEIRL.
Layout-identical PIR and light-level sensors stay refused because the Toolkit
handles them with other classes. Preview and apply its movement event, group,
timer, light threshold and occupancy enable settings:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run sensor-occupancy --key 3 --event night --group 31 \
  --timer-seconds 513 --target-lux 550 --margin-percent 10 \
  --disable-potentiometer-override
```

Remove `--dry-run` to save the verified programming to the selected source.
Use `CBUS_UNITSPEC_DIR` to locate the decoded vendor schema. An exported PP
snapshot can be planned offline with `sensors plan snapshot.json` and the same
settings. Shared blocks and conflicting potentiometers require explicit
options. See [sensors.md](docs/sensors.md) for the supported dependencies and
the remaining sensor functions.

## eDLT widgets

The tested profile is KEYGL5 5.5.00 / 5055EDL. Configure Off/On or Dimmer
widgets in an existing database unit:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-lighting --page 1 --position 1 --group 42 --mode off-on \
  --label-text Lamp --status-type percent
```

Remove `--dry-run` to save the verified database programming. `edlt lighting-plan
snapshot.json` accepts the same widget options for offline planning. Page
placement, shared static text allocation, label references, status display,
restore levels and dimmer ramp rates are supported. Text allocation checks
references from all widget classes, navigation and scenes. Configuration CRCs
are compared with the original Toolkit DLL. Other widget types and physical
transfer remain separate work; see [edlt.md](docs/edlt.md).

Enable widgets use the fixed Enable application (203) and Off/Preset mode:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-enable --page 1 --position 2 --variable 42 --level 173 \
  --label-text "Operating mode" --status-type percent
cbus-toolkit edlt enable-plan snapshot.json --page 1 --position 2 \
  --variable 42 --level 173 --label-text "Operating mode" --status-type percent
```

Variables are 0..254 and preset levels are 0..255. Shared static text, display
variants, configuration CRCs and the original restore-level copying behavior
are supported. When changing a variable that uses a dynamic label or status,
specify the corresponding display type explicitly because its text/icon kind
depends on network metadata outside the parameter snapshot.
See [edlt-enable.md](docs/edlt-enable.md) for exact defaults, byte layouts and
the original DLL comparisons.

Shutter widgets support two-key control and two-key presets:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-shutter --page 1 --position 3 --group 42 \
  --mode two-key-presets --preset-left 86 --preset-right 170 --label-text Blind
cbus-toolkit edlt shutter-plan snapshot.json --page 1 --position 3 --group 42
```

Presets accept levels 6..248. The helper preserves shared labels and restore
levels, checks all configuration CRCs, and applies database programming with
save/reload verification. See [edlt-shutter.md](docs/edlt-shutter.md) for defaults,
dynamic display dependencies and the original DLL comparisons.

Timer widgets provide Toggle/Retrigger behavior:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-timer --page 1 --position 4 --group 42 \
  --duration-seconds 300 --target-level 255 --expiry-level 0 --ramp-seconds 20
cbus-toolkit edlt timer-plan snapshot.json --page 1 --position 4 --group 42
```

Duration accepts 0..64800 seconds, target 1..255 and expiry 0..255. Omitted
settings retain existing values or use the original fresh-widget defaults:
60 seconds, target 255, expiry 0 and a 1020-second ramp. The timer status
display, shared text and dynamic display dependencies are supported.
See [edlt-timer.md](docs/edlt-timer.md) for the supported ramp times and native evidence.

Fan widgets support one, two or three speeds with static status text:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-fan --page 1 --position 1 --group 42 --speeds 3 \
  --low-threshold 84 --high-threshold 170 --label-text Ceiling \
  --off-text Stopped --low-text Slow --medium-text Normal --high-text Fast
cbus-toolkit edlt fan-plan snapshot.json --page 1 --position 1 --group 42
```

Explicit speed selection restores that mode's original threshold defaults.
Text options reuse or allocate shared slots; the corresponding `--off-index`,
`--low-index`, `--medium-index` and `--high-index` options select exact slots.
Inactive speed labels retain their references. See [edlt-fan.md](docs/edlt-fan.md)
for threshold rules, dynamic label dependencies and native save behavior.

Multi Level widgets provide the same threshold and status-slot controls with
their own original defaults:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-multilevel --page 1 --position 1 --group 42 --levels 3 \
  --low-threshold 84 --high-threshold 170 --label-text Ventilation
cbus-toolkit edlt multilevel-plan snapshot.json --page 1 --position 1 --group 42
```

The initial label is blank; four default status strings are reused or allocated.
This widget supports assigned applications 48..127 and 136, with original-DLL
and native save/reload comparisons. See [edlt-multilevel.md](docs/edlt-multilevel.md).

Room Courtesy widgets expose Bell Press/Unused modes, off/on colours and
static or dynamic display labels:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-room-courtesy --page 1 --position 1 --group 42 \
  --mode bell-press --off-colour red --on-colour green \
  --label-text Courtesy --status-text Available
cbus-toolkit edlt room-courtesy-plan snapshot.json --page 1 --position 1 --group 42
```

Both colours accept none, white, red, green, blue, cyan, magenta, yellow or orange.
Omitted mode/colour settings retain existing values; a fresh widget uses Bell
Press with no colours and blank displays. Applications 48..127 and 136 are
supported. See [edlt-room-courtesy.md](docs/edlt-room-courtesy.md) for the original
byte comparisons, shared text and dynamic display requirements.

Measurement widgets expose device/channel selection, decimal precision,
signed scaling pairs, the original decimal editor conversion, and shared
prefix, suffix and label text:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-measurement --page 1 --position 1 --device-id 42 --channel 3 \
  --decimal-places 1 --gain-mantissa 125 --gain-exponent -2 \
  --offset-mantissa -25 --offset-exponent -1 --prefix-text Temperature --suffix-text C
cbus-toolkit edlt measurement-plan snapshot.json --page 1 --position 1 --device-id 42 --channel 3
cbus-toolkit edlt measurement-plan snapshot.json --page 1 --position 1 \
  --device-id 42 --channel 3 --gain-value '1,5' --measurement-culture de-DE
```

The example uses exact gain 1.25 and offset -2.5. Empty text detaches a
reference; the original label-only empty sentinel 64 is retained when present.
Page 0 supports all five standby positions. `--icon-index` selects an original
built-in icon on functional pages when icon display is enabled; omitted icon
bytes are preserved on existing Measurement widgets.
`--gain-value` and `--offset-value` use the original lossy conversion as an
alternative to explicit pairs. The default `canonical` grammar is dot-only and
fail-closed. Explicit `invariant`, `en-NZ`, `de-DE`, and `fr-FR` profiles
reproduce source-pinned Toolkit current-culture parsing, blank/zero validation,
fixed-50-place underflow, and exponent-byte wrapping. Plans report both the
editor and stored exponent when wrapping changes the value. Non-finite input is
rejected because the original Toolkit number-break loop does not terminate for
`NaN`. See [edlt-measurement.md](docs/edlt-measurement.md).

For a single retained parent-form transaction, compose a Measurement edit with
the proximity percentage control and the original load/save lifecycle:

```sh
cbus-toolkit edlt parent-form-plan snapshot.json \
  --metadata lifecycle-cache.json \
  --page 1 --position 1 --device-id 42 --channel 3 \
  --gain-value '1.5' --measurement-culture en-NZ \
  --wake-mode primary-event --group 42 --level-percent 50
cbus-toolkit cgate unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/20 --dry-run edlt-parent-form \
  --metadata lifecycle-cache.json \
  --page 1 --position 1 --device-id 42 --channel 3 \
  --wake-mode primary-event --group 42 --level-percent 50
```

The plan separates load, control, save and CRC phases. It reports the original
form-construction and worker-load branches, binding update modes, percentage
byte/meaning changes, save order and every field changed relative to an
unedited lifecycle save. Both controls are validated before the first PP write.
This is a bounded source-pinned parent composition; the complete original
WinForms dialog, focus/caret/message-box behavior and physical display/wake
behavior remain unverified. See
[edlt-parent-form.md](docs/edlt-parent-form.md).

For several distinct controls in one retained database transaction, put the
ordered operations in JSON and use the parent transaction workflow:

```json
[
  {"op":"measurement","page":1,"position":1,"device_id":42,"channel":3,
   "gain_value":"1.5","measurement_culture":"en-NZ"},
  {"op":"lighting","page":1,"position":2,"group":12,"mode":"dimmer",
   "ramp_seconds":20,"restore_level":99},
  {"op":"source-control","page":1,"position":3,
   "variant":"dynamic-1-and-2","label_text":"Audio"},
  {"op":"mra-globals","multiplexer":2,"zone":4},
  {"op":"activation","wake_mode":"primary-event","group":42,
   "level_percent":"50"}
]
```

```sh
cbus-toolkit edlt parent-transaction-plan snapshot.json \
  --metadata lifecycle-cache.json --operations operations.json
cbus-toolkit cgate unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/20 --dry-run edlt-parent-transaction \
  --metadata lifecycle-cache.json --operations operations.json
```

The JSON array contains two through 22 operations and must include a widget,
one retained SceneManager sequence or Reset.
It accepts Measurement, Lighting, Enable, Fan, HVAC, Multi Level, Room
Courtesy, Scene, Shutter, Time/Date, Timer, MRA Zone Control, Source Select and
Source Control and Blank widgets, plus activation, General, Display, Standby, Colours,
Navigation, Quick Status, Page Control, distributed MRA globals, Applications
and Corridor, one `scene-manager` nested operation array, plus an optional
operation-1 Reset baseline. Applications,
Corridor and Reset require a complete ordered
`cbus-edlt-application-cache-v1`. Supply it with `--metadata`, or let the
automatic resolver derive existing DBGETXML objects in XML child order. That
branch never creates a missing list object and uses exact TagName as its
database-view display because registry display/sort preferences are absent.
SceneManager requires
the superset `cbus-edlt-scene-manager-cache-v1` on the caller-cache path. The
automatic parent path derives that cache through the exact native SceneManager
resolver and can create missing Trigger application/group/action objects in
deterministic dependency order. Reset also requires exact raw PP strings; the
automatic branch reads all 874 selected Unit PP `Value` attributes. Its fresh
21-widget/eight-scene graph becomes the baseline
for later operations. Reset after operation 1 and duplicate Reset are rejected
before PP I/O. Blank may follow Reset only as a contiguous prefix: each Blank
receipt binds the issued fresh graph and any later or interleaved Blank fails
before PP I/O.
The planner rejects overlapping complete records, a duplicate settings owner,
conflicting page modes, missing application/group evidence, mismatched dynamic
text/icon metadata, duplicate JSON keys and unknown fields. Operation order is
meaningful: Display can enable a later HVAC icon edit, Standby can enable later
idle colour controls, a newly created MRA widget can precede `mra-globals`, and
a parent Applications edit must precede SceneManager while SceneManager must
precede every Scene widget. Only one operation owns the complete scene graph,
and incomplete capacity prefixes fail before PP mutation. A
two-slice Time/Date edit reserves both adjacent
slots. It composes shared static allocation in order, preserves every unowned
control byte, runs one terminal retained-or-fresh normalization and five-CRC projection,
then uses one parameter-write/readback/rollback sequence and one database save
on successful non-dry-run execution. The original component models have
retained independent evidence. MRA shared settings preserve the first existing
pre-conversion record, stored standby placements, raw multiplexer 3, low
status bits and unrelated bytes. The complete original multi-panel WinForms
sequence and physical behavior remain unverified. See
[edlt-parent-transaction.md](docs/edlt-parent-transaction.md).

`lifecycle.crc_fields_calculated` names all five fields. A field already holding
the calculated value is correctly absent from the changed-only `phases.crc`.

If the final database save raises or is interrupted, the CLI makes no retry
and reports `edlt_parent_transaction_evidence`. `saved=false` means the save
was not confirmed; `save_outcome_uncertain=true` and the separate PP/database
state fields prevent that result from being mistaken for a known rollback.

When one native project snapshot is authoritative, the parent transaction can
derive its metadata instead of accepting a hand-authored lifecycle cache:

```sh
cbus-toolkit edlt parent-transaction-plan snapshot.json \
  --project-xml project.xml --unit //TEST/254/p/20 \
  --operations operations.json
cbus-toolkit cgate unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/20 --dry-run edlt-parent-transaction \
  --auto-metadata --exclusive-project --operations operations.json
```

The offline PP snapshot must exactly match the selected unit in the project
XML. The plan inventories all 64 static-label slots and lists each missing
application/group creation, including HVAC application 172 and Enable
application 203 dependencies introduced by operations. Applying requires a closed, exclusively owned
project and creates a separate backup first. C-Gate exposes database object
creation, PP SAVE and PROJECT SAVE as separate operations, so this path reports
`batch_atomic=false`. It rolls back only before PP SAVE starts and never
retries an uncertain save. DYNAMIC/FONT/ICON image facts that depend on project
files or Toolkit's DLTP index fail closed. See
[edlt-parent-metadata.md](docs/edlt-parent-metadata.md).
This automatic path accepts existing Applications/Corridor lists and
operation-1 Reset raw state. It refuses missing/projected list objects. In one
combined plan it projects ordered list, Reset and contiguous fresh-graph Blank
state before the SceneManager resolver creates only its required Trigger
application/group/action objects.

Time/Date widgets support standby and functional positions, with unit-wide
date formats, time formats and leading zeroes:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-time-date --page 0 --position 1 --slices 2 --display time-date \
  --date-format 1 --time-format 24-hour --leading-zero
cbus-toolkit edlt time-date-plan snapshot.json --page 1 --position 1 --display time
```

Page 0 selects standby. A new two-slice widget at standby positions 1..4
clears the following widget's type; the plan reports that change and retains
its opaque bytes. Single-slice widgets support every displayed position.
Formatting applies to the whole unit. These commands configure display
settings; they do not set the clock. See [edlt-time-date.md](docs/edlt-time-date.md).

HVAC Temperature Display widgets select an application 172 communication group,
zone, precision and temperature units:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-hvac --page 1 --position 1 --group 42 --zone 4 \
  --decimal-places 2 --units fahrenheit --icon-index 38 --label-text Room
cbus-toolkit edlt hvac-plan snapshot.json --page 0 --position 1 --group 42
```

Page 0 supports all five standby positions. Explicit icon selection requires
a functional page with icon display enabled. Group references do not create
database groups or transmit HVAC controls. See [edlt-hvac.md](docs/edlt-hvac.md).

Global display settings choose the larger text line, icon display, timer
flashing and Fan/Multi Level wrapping:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-display --large-text status --big-icons --no-timer-flash --fan-level-wrap
cbus-toolkit edlt display-plan snapshot.json --large-text label
```

Omitted settings retain their stored values. These settings affect the whole
unit; the plan also reports Toolkit's save-time widget normalization and MRA
global propagation. See [edlt-display.md](docs/edlt-display.md) for the original
setter, full-parameter and native save/reload comparisons.

MRA widgets support Zone Control, Source Select and Source Control. Their
multiplexer and zone are shared across all MRA widgets in the unit:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-mra --page 1 --position 1 --kind zone-control --variant volume \
  --multiplexer 2 --zone 4 --key-mode decrease-increase --ramp-seconds 20
cbus-toolkit edlt mra-plan snapshot.json --page 1 --position 2 --kind source-select \
  --variant two-absolute --source1 1 --source2 7 --status-text Audio
cbus-toolkit edlt mra-globals-plan snapshot.json --multiplexer 3 --zone 8
```

`cgate unit ... edlt-mra-globals` saves only the shared MRA settings and their
required normalization. Source and zone numbers use the original UI's
one-based numbering. The plans report text allocations, changes to sibling
widgets and hidden-field restrictions. These commands configure eDLT widgets;
audio hardware control is separate. See [edlt-mra.md](docs/edlt-mra.md).

General settings configure key timing, the status-report interval, tools-page
access and power-restore mode:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-general --long-press-ms 400 --debounce-ms 75 \
  --status-report-seconds 3 --tools-page-locked --power-restore previous
cbus-toolkit edlt general-plan snapshot.json --power-restore preset
```

Key timings use exact 25 ms steps. Long press accepts 25..6375 ms; debounce
accepts 0..6375 ms. Status reports accept 3..255 seconds. Selecting `preset`
retains the configured widget restore levels. Omitted values stay unchanged,
including stored values outside the UI's selectable ranges. These commands
save database configuration; physical power-cycle behavior remains unverified.
See [edlt-general.md](docs/edlt-general.md).

Standby settings configure the timeout, destination page and nightlight keys:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-standby --enabled --after-seconds 60 --timeout-page standby \
  --nightlight-page-key --nightlight-colour page-key-colour
cbus-toolkit edlt standby-plan snapshot.json --no-enabled
```

Enabling applies the original timeout setter before an explicit duration;
without `--after-seconds`, it preserves a stored one-second timeout and sets
other durations to three seconds. Disabling preserves hidden nightlight and
destination values. See [edlt-standby.md](docs/edlt-standby.md).

Colour settings support fixed screen/key palettes, four brightness levels and
six numeric control-group references:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-colours --text-colour white --background-colour blue \
  --active-screen-group 255 --active-screen-brightness 200
cbus-toolkit edlt colours-plan snapshot.json --indicator-on-group 42
```

Group 255 selects fixed mode. A controlled value becomes editable after its
group is set to 255, including in the same command. Idle brightness controls
require standby to be enabled. Group references do not create database groups.
See [edlt-colours.md](docs/edlt-colours.md).

Quick Status supports four modes, a numeric group reference, three colours and
the original linked threshold controls:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-quick-status --mode page-key --group 42 \
  --low-threshold 85 --high-threshold 170 \
  --low-colour red --middle-colour yellow --high-colour green
cbus-toolkit edlt quick-status-plan snapshot.json --mode off
```

When both thresholds are supplied, the low threshold is applied before the
high threshold regardless of argument order. Changing one can adjust the
other; the plan reports effective values. Off/page-key modes use key colours,
and background/text modes use screen colours. Omitted raw colours are preserved
according to the original model. A separate finite Windows control matrix
checks 1,248 colour-property transitions; complete form initialization remains open. See [edlt-quick-status.md](docs/edlt-quick-status.md).

Activation controls select how the unit wakes and which proximity event it
configures:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-activation --wake-mode trigger-event --group 7 --action-selector 42
cbus-toolkit edlt activation-plan snapshot.json --wake-mode primary-event \
  --group 42 --level 255
cbus-toolkit edlt activation-plan snapshot.json --wake-mode primary-event \
  --group 42 --level-percent 50
```

Use `--level` for a protocol byte or `--level-percent` for an explicit decimal
percentage. The percentage option reproduces the original control arithmetic:
`50` becomes byte 127. Input syntax and the original rounding behavior are
documented in [edlt-percentage.md](docs/edlt-percentage.md). Its ten arithmetic
tests and nine CLI/regression tests pass on both supported Python versions;
these are separate from the published full-wheel checkpoint.

Standby must already be enabled. `--activation-page` requires the standby
timeout page; `--ignore-first-key-press` requires key-press wake mode and a
current/page-1 timeout destination. Switching between primary and Trigger
Control events can retain the same numeric group under a different application;
the plan reports that change. These commands save configuration without
creating group/action metadata or verifying physical wake events. See
[edlt-activation.md](docs/edlt-activation.md).

Page Control passes ten helper/CLI tests on both Python versions, including
284 original Windows vectors and 13 full native C-Gate cases. The explicit model
lifecycle passes 19 tests on both versions, including 76 original cases, 2,048
Enable constructor combinations and 34 native save/reload cases. The commands are:

```sh
cbus-toolkit edlt page-control-plan snapshot.json --group 42
cbus-toolkit edlt lifecycle-requirements snapshot.json
cbus-toolkit edlt lifecycle-plan snapshot.json --metadata lifecycle-cache.json
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-lifecycle --metadata lifecycle-cache.json
```

Page Control uses application 203; group 255 disables it. The lifecycle command
shows the model's load, before-save and CRC phases using explicit caller-supplied
cache facts. It checks metadata syntax before entering the programming session
and reports missing facts before parameter edits. These workflows support
database destinations. See [Page Control](docs/edlt-page-control.md) and
[model lifecycle](docs/edlt-lifecycle.md) for their current validation and limits.

The preset-level editor passes 16 tests on both Python versions, including 64
captured Windows cases and 15 fresh original/native comparisons with save/reload
for every case. Use `edlt restore-levels-plan snapshot.json --metadata
restore-cache.json --widget 6 --level 128`, or the database
`cgate unit ... edlt-restore-levels` command. `--synchronise` follows the original
16-control event, including hidden controls; an unchanged value does not
propagate. See [preset restore controls](docs/edlt-restore-levels.md) for cache
format, mode options and supported scope.

Primary/Secondary Application selections and Corridor controls accept ordered
edits with an explicit complete metadata cache:

```sh
cbus-toolkit edlt applications-plan snapshot.json --metadata application-cache.json \
  --select secondary=255 --select primary=57 --select secondary=56
cbus-toolkit edlt corridor-plan snapshot.json --metadata corridor-cache.json \
  --edit link_group=42 --edit office_group=1 --edit seconds=256
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-applications --metadata application-cache.json --select secondary=255
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-corridor --metadata corridor-cache.json --edit seconds=300
```

Both workflows retain the original loaded model through control edits and save,
including scene references and original save-time normalization. Application
selections reproduce intermediate secondary-disable effects. Corridor plans
report displayed and stored timer values separately: changing to 256 seconds
reproduces the original stored value of 255. The Application workflow passes
13 tests per Python version with 14 fresh original/native save/reload cases;
Corridor passes ten tests with 74 original vectors and twelve native cases.
Twelve ordered CLI/helper tests cover persistence, input guards and failure
evidence through the final save and both cleanup stages. See [Applications](docs/edlt-applications.md)
and [Corridor](docs/edlt-corridor.md) for cache formats and exact limits. These
standalone paths still require caller-supplied metadata. The composed parent
transaction accepts both dialog operations with the same complete application
cache and gives them field ownership inside one terminal save. Its automatic
project resolver can derive and create bounded metadata for the other admitted
operations, but it cannot replace the ordered list contract for these two.
The complete form, project/DLTP image-dependent metadata and physical operation
remain separate work.

Select Blank for one visible widget while retaining the loaded scenes, static
text and original MRA globals:

```sh
cbus-toolkit edlt blank-plan snapshot.json --metadata lifecycle-cache.json --page 1 --position 2
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-blank --metadata lifecycle-cache.json --page 1 --position 2
```

The [Blank workflow](docs/edlt-blank.md) passes 54 tests per Python version,
including 31 original control cases, thirteen native save/reload cases and
the prior lifecycle/restore regressions. Plans distinguish the selected Blank
from a stored end marker, and reject covered standby or navigation positions.
The ordered parent transaction accepts `blank` with the same page/position
placement and retained receipt, reserves its whole slot and performs one
shared terminal save/CRC projection with later distinct operations.
The database Blank workflow remains separate from the guarded physical
FactoryDefault command below; physical post-reset readback and persistence are
still separate acceptance work.

Reset eDLT controls using an exact raw export and explicit form context:

```sh
cbus-toolkit edlt reset-plan raw-export.json --metadata lifecycle-cache.json \
  --active-tab widgets --binding-variant audited-local-wiring
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-reset-controls --metadata lifecycle-cache.json \
  --active-tab widgets --binding-variant audited-local-wiring
```

The [Reset controls workflow](docs/edlt-reset.md) preserves identity fields,
applies the original ordered defaults and retained-model transitions, and
reproduces the selected tab's effects. Its raw input preserves numeric spelling
and dirty state. Fifty-five tests pass on both Python versions, including four
fresh original/native cases per version, all 874 parameters, five CRCs and
save/reload checks. The ordered parent transaction accepts Reset only as
operation 1 with the same exact raw/application-cache contract, then binds
later operations to its fresh graph before one terminal save. Contiguous Blank
operations immediately after Reset use fresh-graph receipts. The original
interactive Reset-plus-Blank form, full form initialization and physical reset
remain unverified.

Copy selected eDLT global categories to existing database units:

```sh
cbus-toolkit edlt global-plan source.json --metadata lifecycle-cache.json --category colour
cbus-toolkit cgate edlt-global source.json --metadata lifecycle-cache.json \
  --category colour --destination //TEST/254/p/21 --destination //TEST/254/p/22 \
  --exclusive-project --dry-run
```

Remove `--dry-run` to create a backup and save each target. Every project network
must be closed, and the caller must have exclusive use of the project. The
[Global Programming workflow](docs/edlt-global-programming.md) passes 28 tests
on both Python versions, including 38 saved/reloaded targets per version.
It reproduces the original category selection and CRC policy; complete form
initialization, missing-target creation and physical programming remain open.

The [factory preparation option](docs/edlt-global-factory-cli.md),
`--factory-context context.json`, adds the original default-template Reset and
Project preparation for six captured source families. Its 77-test checkpoint
passes both Python versions, with exact raw source checks, mandatory backups,
full target reloads and partial-failure preservation. The native command also
requires `--source-database` matching the context source. Post-Reset user edits
and complete form initialization remain outside this factory option.

The retained Scene Manager accepts an ordered operation array, for example
`[{"op":"copy","scene":1},{"op":"paste","scene":2},{"op":"set-name-text","scene":2,"text":"Evening"}]`
in `scene-operations.json`:

```sh
cbus-toolkit edlt scene-manager-state snapshot.json --metadata scene-cache.json \
  --operations scene-operations.json --list-groups 2
cbus-toolkit edlt scene-manager-plan snapshot.json --metadata scene-cache.json \
  --operations scene-operations.json --validate
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-scene-manager --metadata scene-cache.json --operations scene-operations.json
```

When the project snapshot contains all consumed label facts, derive the cache
automatically instead:

```sh
cbus-toolkit edlt scene-manager-plan snapshot.json \
  --project-xml project.xml --unit //TEST/254/p/20 \
  --operations scene-operations.json --validate
cbus-toolkit cgate unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/20 --dry-run edlt-scene-manager \
  --auto-metadata --exclusive-project --operations scene-operations.json
```

[Scene Manager](docs/edlt-scene-manager.md) retains scene and group identities
through copy/paste, level/ramp edits, validation and serialization. `set-name-text`
uses exact text reuse or the highest free whole-unit static slot in operation
order; `set-name-index` with index 255 clears a scene's reference. Plans report
the string overlay, allocation history, evidence fingerprint and final pointers.
An incomplete scene-capacity edit remains inspectable and cannot be saved. The
frozen acceptance records eight native save/reload cases per Python version;
the additive name-allocation suite also has an environment-gated full-capacity
preview/save/reload case.
At 64 items, it reproduces Toolkit's extra temporary CRC byte while C-Gate
stores 232 tokens. The declarative [scene-table editor](docs/edlt-scenes.md)
uses the normalized stored representation. Full form binding and physical-device
behavior remain separate work.

[Automatic SceneManager metadata](docs/edlt-scene-metadata.md) derives
complete existing application/group lists, consumed trigger-level addresses
and safe default-language text rows from one exact `DBGETXML` snapshot. The
retained getter chain projects a missing application 202 as `Trigger Control`,
an exact non-255 trigger group as `Group N`, and an exact missing action as
`Action Selector N` with `Value=N` and four blank label variants. Native apply
requires a closed, idle, exclusively owned project, saves and copies a backup
before creation, rechecks the source, then records the separate PP SAVE and
PROJECT SAVE outcomes and verifies after reload. Use `--backup-project NAME`
to select the retained backup name. Interactive blank Add dialogs,
image-dependent labels, complete control binding, and physical display
behavior remain open.

Capture current lighting levels into a database scene, broadcast stored levels,
or invoke the scene's retained Trigger binding:

```sh
cbus-toolkit cgate unit --lock-address //TEST/253 --source /db//TEST/253/p/20 \
  --dry-run edlt-scene-capture --metadata scene-cache.json --network //TEST/254 --scene 1
cbus-toolkit cgate edlt-scene-broadcast snapshot.json --metadata scene-cache.json \
  --network //TEST/254 --scene 1 --scope current --item 1
cbus-toolkit cgate edlt-scene-trigger snapshot.json --metadata scene-cache.json \
  --network //TEST/254 --scene 1 --force
```

[Scene capture and broadcast](docs/edlt-scene-live.md) sends one command at a time.
Capture requires a complete verified reading before it can save; a partial result
retains the observed prefix for review. Capture dry runs perform live reads and
discard temporary database changes. Broadcast sends immediate stored levels and
records each acceptance or failure. Seventeen tests pass on both Python versions,
including fourteen fresh original-DLL cases per version, native save/reload and
independent simulator persistence. Toolkit's background UI timer and physical
device behavior remain unverified.

The [retained scene trigger](docs/edlt-scene-trigger.md) resolves the stored
application-202 group/action pair before connecting, then submits one native
Trigger event without retry. It requires the exact identity-bearing
`cbus-cli-parameters-v1` envelope; raw PP mappings and wrong profiles fail
before client construction. A terminal `200` proves C-Gate acceptance only;
`408`, 5xx and transport failures remain outcome-uncertain, and all submitted
requests report that device side effects are possible. The event is group-scoped
and can reach every configured listener. It performs no PP write or save and
does not claim that a physical eDLT executed the scene.

The reusable load/save lifecycle also passes a separate 45-test checkpoint on
both versions, retaining the earlier 76-case original matrix, 2,048 Enable
combinations, 34 native lifecycle cases and 15 native restore cases. Shared
error reporting preserves the original programming cause even if formatting
that exception itself fails; [39 focused tests](docs/edlt-error-evidence.md)
pass on both Python versions.

Clear a selected eDLT's dynamic labels through a guarded native request:

```sh
cbus-toolkit cgate edlt-label-clear plan //TEST/254/p/5 --serial 101183.1666
cbus-toolkit cgate edlt-label-clear request //TEST/254/p/5 \
  --serial 101183.1666 --plan-output clear-labels-plan.json
```

The request requires an already running, direct wired network, a freshly
verified identity and complete inventory, with native retries and automatic
unraveling/updating disabled. It records an optional new plan file durably before
sending one request. A native acknowledgement is reported separately from
verified erasure; uncertain outcomes are never automatically retried. The
27-test suite passes on both Python versions using native C-Gate and an
independent persistent per-unit label fixture. Physical erasure remains
unverified. See [the clear-label contract](docs/edlt-label-clear.md).

Request a physical KEYGL5 FactoryDefault only after reviewing a fresh guarded
plan and recording the expected native serial:

```sh
cbus-toolkit cgate edlt-factory-default plan //TEST/254/p/5 \
  --serial 101183.1666 --plan-output factory-default-plan.json
cbus-toolkit cgate edlt-factory-default request //TEST/254/p/5 \
  --serial 101183.1666 --plan-output factory-default-intent.json
```

The request repeats the complete identity, inventory, topology, runtime and
database guards, then sends one non-replayed `DO ... FactoryDefault`. An exact
202 receipt proves the source-correlated unit ACK only. The result keeps reset,
defaults readback, retained address, reboot, rendering and power-cycle
persistence unverified. No database record is rewritten. See the
[FactoryDefault contract](docs/edlt-factory-default.md).

Navigation settings configure page mode, time/temperature formats, logos and
static or dynamic page labels:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-navigation --page-mode multiple --variant page-names \
  --page-name 1 Upstairs --page-name 2 Downstairs
cbus-toolkit edlt navigation-plan snapshot.json --page-mode multiple \
  --variant dynamic-labels --dynamic-group 42 --page-name-index 1 3 \
  --metadata navigation-groups.json
```

Repeated page arguments must name distinct pages. Dynamic page indices require
matching caller-supplied group metadata; this records cached choices without
claiming physical label verification. Single page mode preserves hidden
navigation and functional-widget values. See [edlt-navigation.md](docs/edlt-navigation.md).

Bind a Scene widget to an existing configured scene on the same profile:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-scene --page 1 --position 1 --scene 2 \
  --label-type scene --status-text Ready
```

`edlt scene-plan snapshot.json` accepts the same settings offline. Scene numbers
are 1..8; the selected scene must have output items or an assigned trigger.
Scene labels use the scene's existing name, and dynamic labels/status require
its trigger group. This widget workflow preserves the stored scenes. See
[edlt-scene.md](docs/edlt-scene.md) for the original DLL and native PP evidence.
The default mode is `off-on`. Use `--mode ramp --ramp-seconds 30` or
`--mode nudge --offset 42` with a single `--scene`. Cycle mode takes an ordered
list such as `--mode cycle --cycle-scene 1 --cycle-scene 2`, with up to eight
entries, and optional `--cycle-variant cycle|select`.

Author the stored eDLT scenes from an ordered JSON array:

```json
[{"application":"primary","trigger_group":42,"action_selector":77,
  "name_text":"Evening","items":[{"group":9,"level":127,"ramp_seconds":20}]}]
```

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-scenes --scenes scenes.json
cbus-toolkit edlt scenes-plan snapshot.json --scenes scenes.json
cbus-toolkit edlt scenes-inspect snapshot.json
```

The complete table supports eight scene slots and 64 output items. Each scene
has an assigned trigger; it may have no output items. Static names share the
unit's text storage. Existing widgets retain their scene slot and trigger
identity, so deleting or moving a referenced scene is rejected. Original DLL
packing, capacity, CRCs, native raw bytes and CLI save/reload are tested.

## Thermostat temperature conversions

Fourteen original integer temperature conversions are available offline, with an
explicit Celsius or Fahrenheit preference:

```sh
cbus-toolkit thermostat-temperature methods
cbus-toolkit thermostat-temperature convert CGateTempToUnitTemp 0 --units fahrenheit
```

The conversion above returns 68. Original intermediate rounding, signed integer
wrapping and method-specific limits are preserved. The Python API is
`convert_temperature(method, value, units=...)`; see
[thermostat temperature arithmetic](docs/thermostat-temperature.md).
The focused checkpoint passes 17 tests on each Python version, including a fresh
28,840-case original-instruction comparison per run. A separate Windows probe
matched all 28 pilot and 1,176 full cases. The retained inner scheduling-level
Python API now has its own [17-test dual-Python acceptance](docs/thermostat-schedule-levels.md),
covering all 14 captured original outcomes and ordered save phases. It creates
missing levels 1 through 31 while preserving existing records.

The [native scheduling command](docs/native-thermostat-schedule.md) now previews
and creates missing levels in one existing Enable Control group in a closed
project:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20033 thermostat-schedule-levels \
  //TEST/254/203/1 --action Enable --exclusive-project
```

Add `--apply --backup-project THBAK1` to save the whole current project, create a
backup, apply missing levels and verify them after save/reload. Existing levels
retain their values, labels and OIDs. The combined 67-test checkpoint passes on
both Python versions, including five native integration methods and eight
project/group scenarios per run. Full thermostat selection/settings, native
collection-order equivalence and physical behavior remain outstanding.

Compose the captured unit-load, outer selection and missing-level rules directly
from one closed-project programmable thermostat snapshot:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20033 thermostat-schedule-compose \
  //TEST/254/p/4 --exclusive-project
```

Add `--apply --backup-project THBAK2` to create a missing application 203, role
groups and scheduling levels, then persist them with one target project save.
The preview exposes the exact application/group/level creation plan. Apply
rejects stale or ambiguous project identities before mutation, preserves and
verifies the complete unit record plus unrelated project/network/unit/application
metadata, and never retries a lost write or save reply. Its composition layer
passes 18 focused host tests; two retained owned C-Gate 3.4.0.2001 integrations
cover the manager and public CLI transaction paths from the earlier checkpoint.
Physical thermostat verification remains outstanding.

Evaluate the [retained outer scheduling workflow](docs/thermostat-scheduling.md) offline over supplied
resolved state (Python 3.13, 9 CLI tests):

```sh
cbus-toolkit thermostat-scheduling selected state.json
cbus-toolkit thermostat-scheduling required state.json
cbus-toolkit thermostat-scheduling create-levels state.json --policy direct
cbus-toolkit thermostat-scheduling end-save-lock locked-state.json
```

`state.json` holds `{groups, roles, enabled}` with byte addresses (255 is the
shareable unused sentinel) and existing level records. The commands perform
no unit loads, native writes or device operations.

## Toolkit unit templates

Export and import Toolkit XML templates for classic KEY1, KEY2 and KEY4 units
at firmware 1.2.67 (catalogues 5031N, 5032N and 5034N respectively):

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  template-export key-template.xml
cbus-toolkit unit-templates inspect key-template.xml
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/21 \
  --dry-run template-import key-template.xml
cbus-toolkit cgate unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/20 --destination /db//TEST/254/p/21 \
  --dry-run template-copy --profile KEY4
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/21 \
  --dry-run template-reset-defaults --profile KEY4
```

Remove `--dry-run` to save the verified database programming. The template's
attribute order, checksum and XML escaping are checked against the original
Toolkit executable. Imports preserve the destination's address and other
excluded identity fields; corrupt checksums are rejected before opening a PP
session. Existing output files are preserved. `unit-templates export
snapshot.json key-template.xml` exports the same format offline. See
[unit-templates.md](docs/unit-templates.md) for the supported fields and limits.
The default profile is KEY4; add `--profile KEY1` or `--profile KEY2` to the
export/import command for those units. Imports require matching unit types.
`template-copy` transfers a matching profile directly between two closed
database units. `template-reset-defaults` resets only the original 26 template
fields from the decoded specification. Both commands stage safely with
`--dry-run`. Applying performs one PP save, opens a fresh destination session,
verifies every template field and checks the stable excluded identity and
other listed preservation values exposed by the server. A lost save reply is
reported as uncertain and is never retried. The receipt explicitly reports that the
enclosing project file and physical hardware were not saved.

## eDLT USB diagnostics

Install the optional serial dependency with `pip install '.[serial]'`, then
read an explicitly selected eDLT diagnostic port:

```sh
cbus-toolkit firmware identify --port /dev/cu.example-edlt
cbus-toolkit firmware ncc-versions --port /dev/cu.example-edlt
cbus-toolkit firmware parse-id captured-id.txt --package eDLTFirmware_1.7.0.zip
cbus-toolkit firmware inspect-package eDLTFirmware_1.7.0.zip
```

Identification, NCC version parsing and hardware variants are compared with
the original updater assembly. The serial client sends only the diagnostic
read commands. Incomplete, ambiguous or unusable identity results return exit
status 1 with their available fields. Package comparison examines archive
metadata; it does not verify firmware contents. Vendor payload compatibility,
NCC installation and physical USB-device acceptance remain incomplete.
See [firmware-diagnostics.md](docs/firmware-diagnostics.md) for the tested
serial formats, partial results and original-assembly comparisons.

Install the optional `usb` extra and a libusb1 backend to inspect standard USB
descriptors without claiming a device interface:

```sh
cbus-toolkit firmware usb-list
cbus-toolkit firmware usb-inspect --bus 1 --address 7 --expected-serial ABC123
```

Listing reads cached enumeration metadata. Inspection reads only the selected
device's descriptors, USB strings and active configuration, preserving partial
results on failure. The USB serial is separate from the diagnostic serial.
Bus/address identifies the current connection, so select it from a fresh list.
This does not establish DFU readiness or exclusive ownership. Timeouts apply
per control transfer; enumeration, opening and closing have no timeout.
See [usb-inspection.md](docs/usb-inspection.md) for the exact request restrictions
and tests through the actual PyUSB library with an independent fake backend.

DFU records and supplied image containers can also be inspected offline:

```sh
cbus-toolkit firmware dfu-status '00 05 00 00 02 00'
cbus-toolkit firmware dfu-command 0100080000050000
cbus-toolkit firmware dfu-descriptors device-descriptor.bin configuration-descriptor.bin
cbus-toolkit firmware dfu-inspect supplied-image.dfu --vendor-id 0x166a --product-id 0x0501
cbus-toolkit firmware dfu-plan --length 1280 --address 0x2000 \
  --flash-size 0x40000 --application-start 0x2000
```

These commands decode captured status/command records, check DFU suffixes and
container CRCs, or plan transfer records within explicit memory bounds. They
perform no USB access or firmware installation. A valid container does not
establish payload compatibility with a device. Device error statuses and
unsupported or malformed records return exit status 1. External flash plans
currently accept only address zero because the original wrappers disagree on
address units for nonzero external checks.
The [DFU evidence](docs/dfu-protocol.md) includes original DLL transfers against
an independent memory simulator and deliberately corrupted readback.
The [injected DFU client](docs/dfu-transport.md) validates active descriptors and
memory geometry, programs or erases explicit ranges, and independently reads
back every byte. It retains partial results on transfer, polling and close
failures. A claimed PyUSB transport now connects this client to an explicitly
selected eDLT already in DFU mode:

```sh
cbus-toolkit firmware usb-dfu-inspect --bus 1 --address 7 --expected-serial ABC123 \
  --device-descriptor device-descriptor.bin \
  --configuration-descriptor configuration-descriptor.bin \
  --flash-size 0x40000 --application-start 0x2000 \
  --release-policy reset-first-alternate
```

The descriptors, serial and geometry must match the selected device. With the
same required options, `usb-dfu-program raw.bin --offset 0x2000` programs raw
bytes and `usb-dfu-erase --offset 0x2000 --length 0x800` erases the specified
range. Programming does not erase automatically or unpack firmware containers.
Both modifying operations require complete byte-for-byte readback.

Results preserve acquisition, transfer and release outcomes separately. An
interruption returns available transfer evidence and releases the owned USB
resources. Release may reset the interface to its first alternate, which is
why its policy is explicit. The transfer deadline excludes USB acquisition
and release. Tests use the real PyUSB library with a fake backend and independent
flash memory; physical bootloader and vendor firmware acceptance remain open.
See [usb-dfu.md](docs/usb-dfu.md) and [firmware-usb.md](docs/firmware-usb.md).

## Stored unit scenes

The tested Neo profile is KEYE1 2.5.00 / 5031NMML:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run device-scene --scene 1 --entry 42=255 --entry 43=64 \
  --key 1 --ramp-seconds 12 --action-selector 7 --trigger-group 23
```

Remove `--dry-run` to save. `unit-scenes inspect snapshot.json` reads the scene
table; `unit-scenes plan snapshot.json` accepts the same settings offline.
Entries can also come from `--entries file.json`, an array of `{group, level}`
objects. The unit supports forty commands total, up to ten per scene. This
workflow preserves packed scene numbering and can clear the final populated
scene with `--clear`. See [device-scenes.md](docs/device-scenes.md) for supported
key bindings, shared settings and remaining scene functions.

## Classic keys and unit conversion

```sh
cbus-toolkit keys presets
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run key-macro --spec-dir /path/to/decoded/specs --spec KEY4.xml \
  --key 1 --preset timer --group 42 --timer-seconds 300
cbus-toolkit cgate conversion check-catalog //TEST/254/p/20 DIMDU4 L5504D2U
cbus-toolkit cgate conversion catalog //TEST/254/p/20 DIMDU4 L5504D2U
```

Remove `--dry-run` to save the key edits to the explicit source. The 18 classic
presets support KEY1/KEY2/KEY4, KEYIR1/KEYIR4, KEYAUX4, DINAUX4 and KEYBC2/KEYBC4
(no Bell Press on the auxiliary units), with group, block, timer and recall settings.
`keys plan` produces an offline plan from an exported PP snapshot.
See [preset rules and acceptance](docs/macros.md).

Native conversion creates a project backup by default. `conversion move`
transfers programming into an existing replacement unit and removes the source.
See [conversion behavior and native limitations](docs/conversion.md).

Classic settings can also be aligned between existing database units while
retaining the destination's address and identity:

```sh
cbus-toolkit cgate conversion align //TEST/254/p/20 //TEST/254/p/21 \
  --spec-dir /path/to/decoded/specs --source-spec KEY4.xml --target-spec KEY2.xml --dry-run
cbus-toolkit unit-conversion --spec-dir /path/to/decoded/specs \
  plan KEY4.xml KEY2.xml source-parameters.json target-parameters.json
```

Removing `--dry-run` creates a project backup and saves the destination settings.
Source units and destination metadata are retained. See the
[alignment rules and exclusions](docs/offline-conversion.md).

Replace a classic database unit at its original address, retaining its metadata
and aligned programming with a saved project backup:

```sh
cbus-toolkit cgate conversion replace //TEST/254/p/20 \
  --source-spec KEY4.xml --target-spec KEY1.xml --firmware 1.2.67 \
  --catalog-number 5031N --learned-policy preserve_source --dry-run
```

Remove `--dry-run` to apply. `--learned-policy` is required: preserve the source,
use the target default, or reproduce the frontend branch with explicit learned
history. The target serial defaults to blank (unassigned). The replacement is
staged and checked before promotion; failed operations report recovery and
backup details. See [classic replacement](docs/classic-replacement.md).

Neo-core profiles also have verified preset helpers:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/21 \
  --dry-run neo-key-macro --spec KEYM4.xml --key 4 --preset timer \
  --group 31 --timer-seconds 300 --indicator-block 8
cbus-toolkit keys --spec-dir /path/to/decoded/specs neo-plan KEYM4.xml neo-values.json \
  --key 4 --preset timer --group 31 --timer-seconds 300
```

These support 8 blocks, primary/secondary application selection, recalls,
timer expiry and explicit indicator assignment. An ordinary preset clears the
key's scene-selector bit while retaining the scene table. The 31 tested profiles
cover the Neo, Reflection, Saturn, Saturn ZEN, Classic Neo, Decorator, Modena,
Avanti and 30M mech KEYE1 specifications at firmware 2.5.00; see
[extended keypad scope and evidence](docs/extended-macros.md).

## Events and trigger control

```sh
cbus-toolkit cgate --timeout 60 events --mode e8s1c1 --follow
cbus-toolkit cgate events --state //TEST/254 --count 10
cbus-toolkit cgate trigger event //TEST/254/202/1 '50%'
cbus-toolkit cgate trigger event //TEST/254/202/1 'Dinner scene'
cbus-toolkit cgate trigger kill //TEST/254/202/1
cbus-toolkit cgate trigger state //TEST/254/202/1
```

Event output includes the original record, category and any native timestamp
and event code. Overflow produces a failed summary; an idle timeout or a lost
connection ends the stream with an error. Increase `--timeout` for quiet
networks. `--state` requests an event snapshot without opening the network.
Trigger writes report queuing separately from device verification. Cached state
queries do not claim to read the last action selector from hardware.

Use native `database add ... netvar` for Trigger/Enable variables. Added and
copied level tags receive both their address and value so that C-Gate can save
them. A returned OID can be addressed as `!OID`, including levels below NetVars
whose numeric paths fail in the native server.

Enable Control has separate SET and cached-level operations:

```sh
cbus-toolkit cgate enable set //TEST/254/203/1 50%
cbus-toolkit cgate enable set //TEST/254/203/1 'Sensor enabled'
cbus-toolkit cgate enable level //TEST/254/203/1
cbus-toolkit cgate enable groups //TEST/254/203
```

Native `enable remove` requests deletion of the saved runtime value. In this
vendor version it leaves the in-memory value intact, so CLI acceptance does
not claim removal was verified. See [Enable Control acceptance](docs/enable.md).

## Scene files

```sh
cbus-toolkit scene new evening.scene
cbus-toolkit scene add evening.scene //TEST/254/56/12 255
cbus-toolkit scene add evening.scene //TEST/254/56/24 127 --seconds 4
cbus-toolkit cgate scene execute evening.scene
cbus-toolkit cgate scene record-file evening.scene recorded.scene
```

Playback queues the file's actions in order and stops on the first failure.
Recording samples native cached levels into a new file after every read
succeeds. Local edits support separate output files and atomic replacement.
These commands are independently tested against C-Gate and the simulator;
the vendor's separate named `scene play` and `scene record` commands return
401 in this build. Device scene tables and persistent trigger listeners remain
separate work. See [scene workflows and evidence](docs/scenes.md).

## Network calculator

Calculate the current and impedance of a native project's database network:

```sh
cbus-toolkit cgate network calculate //TEST/254
```

For an entirely offline calculation, supply your vendor `cbusunits.xml` and
a JSON array of units. For example, `calculator-units.json` can contain:

```json
[
  {"catalog_number": "5034N", "unit_type": "KEY4"},
  {"catalog_number": "5500BUR", "unit_type": "BURDEN"},
  {"catalog_number": "5500PS", "unit_type": "POWER"}
]
```

```sh
cbus-toolkit calculator --catalog /path/to/cbusunits.xml calculator-units.json
```

This example returns 350 mA supply, 18 mA consumption and 944 ohms, passing the
vendor limits. Both calculator commands return nonzero for a failed electrical
calculation. Units can also specify `"burden": "1"` and
`"switchable_supply_enabled": true`. Burden values retain native text semantics:
only the exact string `"0"` disables it. Results include unknown catalogue counts;
offline results also include failure reasons and the catalogue hash. See the
[calculator scope and native differential tests](docs/calculator.md).

## Dynamic labels

```sh
cbus-toolkit cgate label text //TEST/254/56 1 'Lounge' --variant 2
cbus-toolkit cgate label unicode //TEST/254/56 1 'Māori' --variant 1
cbus-toolkit cgate label --family trigger text //TEST/254/202 7 'Scene' --action-selector 9
cbus-toolkit cgate label dynamic //TEST/254/56 1 80 --icon 1 --width 8 --height 1
cbus-toolkit cgate label clear //TEST/254/56 1 --unicode --variant 1
cbus-toolkit cgate label cache-clear //TEST/254/56 5
cbus-toolkit cgate label cache-clear //TEST/254/56 5 --key 3
```

Label commands also support built-in icons, language selection, raw payloads
and ASCII clearing. The CLI reports `queued: true, device_verified: false` for
native acceptance. The independent simulator verifies completed Unicode and
bitmap payloads and reloads their stored state; it does not establish physical
display behavior. The separate `cache-clear` command emits native
`LABEL CLEAR APPLICATION UNIT [KEY]` after validating a label-capable
application (48–95, 202 or 203), unit 0–255 and optional key 1–8. Its native
acceptance and PCI confirmation record do not prove device delivery, cache
erasure, persistence or readback. It is distinct from the empty-label
`label clear` action and the guarded KEYGL5 `edlt-label-clear` workflow. See
[label limits and acceptance evidence](docs/labels.md).

### Live eDLT label inventory

Use the physical service embedded in `cmqttd` to inventory the exact supported
KEYGL5 5.5.00 profile on a direct network without opening a second CNI
connection:

```sh
cbus-toolkit cgate --host 127.0.0.1 \
  edlt-labels --network //PROJECT/254
```

The network form uses a 300-second per-command timeout by default so its
whole-network synchronization can finish. `cgate --timeout` explicitly
overrides that value; the selected-device form retains the 10-second default.
The serial refresh commands described above share the longer default.

This form runs one whole-network serial refresh (`NET SYNC` followed by
`NET CHECKUNIT`), classifies the fresh records and reads supported addresses in
numeric order. It uses a 300-second command timeout by default for the fresh
network scan; an explicit `--timeout` overrides that value. The JSON retains
the fresh inventory, unsupported firmware,
unknown or ambiguous identities, other unit families, successful device
snapshots, and read or observation errors. Every successful device snapshot
contains the static strings and their references, with live identity, stable
configuration-header and static-text CRC checks. Physical IDENTIFY4 reads
bracket each selected memory snapshot. The fresh inventory identity is attached
only when both physical serials match its serial; a mismatch remains a
per-device read error and cannot attach stale identity evidence. The snapshots
are read one at a time and therefore are not an atomic network image. If
selection, a device read, the observation query, or the saved project group-tag
query is incomplete, the CLI
still prints the partial report with `complete: false` and exits nonzero.
If a whole-network MMI candidate produces no IDENTIFY4 reply, its native
`No units detected` CHECKUNIT row remains an unknown identity and keeps the
selection incomplete. A silent physical unit cannot be excluded merely because
it missed that reply window; successful eDLT snapshots are still retained.

The command issues `CMQTT LABELS` once after the device reads, at network scope.
Those bounded records are traffic observed during the current `cmqttd`
connection. They are transient, network-wide and recipient-unverified, and the
CLI keeps them at the inventory's top level rather than attaching them to any
device. A unit-shaped `CMQTT LABELS //PROJECT/NETWORK/p/UNIT` request remains a
compatibility alias for the same network ring; it does not narrow the records
to that unit. No physical operation reads an eDLT's existing dynamic-label
cache, so `device_dynamic_label_cache_readback` and the observation document's
`device_readback` remain false and the observations remain incomplete.

The report also includes `project_group_labels`: saved
`Application/Group/TagsDLT/TagDLT` rows from one read-only
`DBGETXML //PROJECT/NETWORK` snapshot. Each row names its application, group,
language, flavour, type and value. This is the configured project label, not
the label stored or displayed by a particular eDLT. For cmqttd's status-200
reply, the CLI verifies its `saved_project_group_dlt_labels` capability and
configured project against the requested project so
older builds that dropped imported tags cannot return a falsely complete empty
list. Native C-Gate's status-344 XML completion is accepted directly. The
nested `project_snapshot_complete` field covers only the returned saved Group
tags; `device_label_inventory_complete` remains false. The network and
single-unit forms keep this project-wide result separate from physical static
strings and transient observed traffic. A failed project query keeps any
successful physical evidence, marks `complete: false`, and exits nonzero.

The original single-device form remains available when the caller deliberately
selects one address:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 30 \
  edlt-labels //PROJECT/254/p/5
```

Read the same service's opaque physical KEYGL5 `WidgetGroups` mapping with:

```sh
cbus-toolkit cgate --host 127.0.0.1 --timeout 120 \
  edlt-widget-groups //PROJECT/254/p/5
```

This typed command runs a successful whole-network `NET SYNC` first, then
requires one exact `GET //PROJECT/NETWORK/p/UNIT WidgetGroups` status-300
response containing 44 comma-separated decimal bytes. The JSON identifies the
result as a physical synchronized-cache read and preserves the native CSV. The
mapping stays opaque and the physical observations are sequential, so the
result does not claim an atomic network snapshot, dynamic-label cache readback,
display rendering, or persistence. `NET SYNC` leaves persistent device
configuration unchanged, but its KEYGL5 metadata sequence does write a
volatile OEM selector before reading the two application bytes; the JSON
reports both facts. It shares cmqttd's CNI and never opens a direct connection.
cmqttd only creates the property for a non-error present MMI-state-one-or-two
address with exactly one raw IDENTIFY4 reply carrying a known serial and
matching configured/fresh KEYGL5 types. Repeated identical known replies and
mixed known/unknown replies are ambiguous addresses and
fail with no metadata read or stale property, and reconnect invalidates an
in-flight snapshot.
See [the strict response contract](docs/edlt-widget-groups.md).

Create a serial-bound label baseline, or compare a later fresh read after
commissioning or programming, with the joined network audit:

```sh
cbus-toolkit cgate --host 127.0.0.1 \
  edlt-label-audit //PROJECT/254 --write-baseline edlt-labels.json
cbus-toolkit cgate --host 127.0.0.1 \
  edlt-label-audit //PROJECT/254 --baseline edlt-labels.json \
  --mode configuration
```

The audit uses the same 300-second default for each C-Gate command and accepts
an explicit `cgate --timeout` override.

The audit uses the inventory's one physical synchronization, then consumes each
unit's cached 44-byte `WidgetGroups` mapping without a second sync. Baselines
require every selected image, physical serial and mapping to be complete; files
are created exclusively and are checked for fingerprint tampering when loaded.
`exact` compares all 9,216 physical bytes, `configuration` compares decoded
label-bearing records and `labels` compares label text/references/placement.
All three include physical identity and `WidgetGroups`. Added or removed units
fail every mode. Dynamic-label traffic stays in the diagnostic receipt and is
excluded from the baseline because it is incomplete and recipient-unverified.
See [the eDLT label acceptance workflow](docs/edlt-label-audit.md).

cmqttd also exposes the native physical KFI commands through raw C-Gate
execution:

```sh
cbus-toolkit cgate exec 'LABEL KFIGET //PROJECT/254/56 5'
cbus-toolkit cgate exec 'LABEL KFISET //PROJECT/254/56 5 1 2 3 4 5 6 7 8'
```

The application token is a native `LabelSupportingApplication` scope/class
gate; it is not encoded into KFIGET's fixed selector `0x1c`. KFIGET sends three
volatile parameter-`0xFF` writes before IDENTIFY, so do not treat it as a
dynamic-label cache read or run it casually on live hardware. All KFI writes
and the GET IDENTIFY request are generation-safe exact-once sends with no
transport replay. A lost confirmation faults the programming lane until the
PCI connection is re-established.

Trigger events and cached native state are also typed commands:

```sh
cbus-toolkit cgate trigger event //TEST/254/202/1 'Evening scene'
cbus-toolkit cgate trigger kill //TEST/254/202/1
cbus-toolkit cgate trigger state //TEST/254/202/1
```

Named selectors are resolved from native database level values. Native trigger
groups have no `Level` getter; `state` reports cached object state. See
[Trigger Control behavior and native acceptance](docs/trigger-control.md).

## CGL exchange

```sh
cbus-toolkit cgate cgl export TEST test.cgl --network 254 --application 56
cbus-toolkit cgate cgl import TEST controller.cgl
cbus-toolkit cgate project save TEST
```

Import creates a native backup project by default and returns its name. Use
`--backup-project NAME` to choose it, or `--no-backup` to omit it. The native 3.4
importer adds missing applications, groups and levels, preserving existing
names. Networks must already exist and be routable. A skipped network produces
a nonzero exit status and the native import summary. Export refuses to replace
an existing file.

## Rust C-Gate model

The sibling `rust/cbus-cgate` crate and `cgate-mock` executable recognize every
command in the supplied C-Gate 3.4 manual and bytecode command registry: 224
public headings, 268 registered subcommands and 431 unique command paths after
overlap. Core Toolkit paths have dedicated native-shaped state models; the
remaining application, DALI and private families have deterministic stateful
emulation. The [command coverage record](docs/rust-cgate-command-coverage.md)
lists the sources, behavior tiers, tests and physical-hardware boundary.

## PCI simulator

```sh
cbus-toolkit simulator serve --port 10001 --state simulator.json --wire-log wire.jsonl
# In another terminal:
cbus-toolkit pci --host 127.0.0.1 --local-unit 16 identify local 1
cbus-toolkit pci --host 127.0.0.1 write 5 0 41a000
cbus-toolkit pci --host 127.0.0.1 recall 5 0 3
```

The simulator persists explicitly configured parameter blocks and rejects
unsupported operations. `--fragment-size` exercises fragmented responses.
`--response-delay 0.01` adds ten milliseconds of simulated reply latency;
the native clock fixture uses this to avoid C-Gate's immediate-confirmation race.
`--profile captured` uses recorded commissioning exchanges; `--profile synthetic`
uses deliberately configured device state with verified protocol behavior.
`--checksum` on the simulator and PCI client must match. PCI reads and writes
correlate confirmations, source units, parameters and ACK tags. Local operations
use explicit addressing after BASIC interface identification when needed.
The simulator's evolving commissioning profile is tested against the real
C-Gate service; it is not yet a complete C-Bus hardware model.
`pci recall` supports direct or `--addressing programming` requests and assembles
segmented replies up to the requested 255-byte limit without truncation.

## Vendor evidence

Keep the installer and its documentation privately, outside tracked files;
`research/vendor/` is one ignored local location. Start with your legally
obtained Toolkit 1.18.0 download:

```sh
brew install innoextract sevenzip
python3 toolkit-cli/research/extract_vendor.py /path/to/C-Bus_Toolkit_V1_18_0.zip
cbus-toolkit inventory --cgate-dir toolkit-cli/research/vendor/cgate/app \
  --help-dir toolkit-cli/research/vendor/toolkit-help manifest
cbus-toolkit inventory --cgate-dir toolkit-cli/research/vendor/cgate/app commands --filter DBADDSAFE
```

The initial artifact inventory contains 3,767 help topics, 577 catalog entries,
271 unit types and 3,750 firmware revision entries. The command reference
lists 209 entries; additional internal programming commands exist and the
complete workflow census is still being expanded.

The [original-artifact provenance manifest](docs/original-artifact-provenance.md)
pins the private target installer, extracted Toolkit/C-Gate files, bundled JRE,
and decoded unit-catalogue inputs by hash and version without committing their
contents. Verify those inputs before an original comparison; the pin alone is
not a native or hardware acceptance receipt.

Decode the vendor's authenticated unit specification format for inspection:

```sh
pip install -e './toolkit-cli[research]'
python3 toolkit-cli/research/decode_unitspec.py \
  toolkit-cli/research/vendor/cgate/app/unitspec toolkit-cli/research/vendor/unitspec-plain
cbus-toolkit unit-schema --spec-dir toolkit-cli/research/vendor/unitspec-plain show RELDN12.xml
cbus-toolkit unit-schema --spec-dir toolkit-cli/research/vendor/unitspec-plain defaults RELDN12.xml
```

Schema validation exposes inconsistent vendor defaults instead of silently
truncating them. Inspecting a schema does not program a unit or validate its
memory encoder.

The separate memory codec exposes logical PP layouts, encoding, decoding,
masked patch application and explicit physical/logical array remapping:

```sh
cbus-toolkit memory --spec-dir toolkit-cli/research/vendor/unitspec-plain layout KEY1.xml IndicatorBrightness
cbus-toolkit memory --spec-dir toolkit-cli/research/vendor/unitspec-plain encode KEY1.xml IndicatorBrightness 128 > patch.json
cbus-toolkit memory apply captured-memory.json patch.json edited-memory.json
cbus-toolkit memory --spec-dir toolkit-cli/research/vendor/unitspec-plain decode KEY1.xml IndicatorBrightness edited-memory.json
```

Images use `{"format":"cbus-sparse-memory-v1","bytes":{"63":255}}` with
decimal addresses and byte values. Missing bytes remain unknown; partial-byte
edits require known original bytes. The codec does not perform physical
transfer, unit checksum calculation or protection handling. Text encoding is
explicit because native C-Gate string writes depend on its JVM charset.

## Tests and independent oracle

The current Python 3.13 source-tree gates are:

```sh
cd toolkit-cli
make check
make check-interop
make check-wheel
make require-complete
```

CI runs the nine-case original C-Gate `SESSION_ID` differential on both fresh
Rust servers, then the source-only selection, `cgate-mock` interop and real
`cmqttd` interop as separate reported steps. A second
job installs the wheel into a fresh environment and rejects any import from
`src/`. JUnit artifacts retain the executed and skipped cases. Provisioned
native and physical-hardware release jobs are manual and fail on missing
provision or any skip; see the repository [test strategy](../docs/testing.md).
`make require-complete` is the enforcing parity gate and remains nonzero until
the full census, implementation and acceptance requirements are complete.

The source and wheel suites report explicit vendor, Windows, native-service
and hardware provisioning skips when those facilities are absent. An offline
pass does not establish native or physical acceptance. See the current CI
artifacts and [test strategy](../docs/testing.md) for exact counts and gate
scope.

```sh
PYTHONPATH=toolkit-cli/src python3 -m unittest discover -s toolkit-cli/tests -v
python3 toolkit-cli/research/oracle.py start
cbus-toolkit cgate exec 'GET cgate version'
python3 toolkit-cli/research/oracle.py stop
```

Enable native acceptance against that disposable server:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
  CBUS_UNITSPEC_DIR=toolkit-cli/research/vendor/unitspec-plain \
  CBUS_TOOLKIT_HELP_DIR=toolkit-cli/research/vendor/toolkit-help \
  CBUS_TOOLKIT_EXE=toolkit-cli/research/vendor/toolkit/app/CBusToolkit.exe \
  CBUS_FIRMWARE_UPDATER=toolkit-cli/research/vendor/toolkit/app/FirmwareUpdater.exe \
  CBUS_DFU_DLL=toolkit-cli/research/vendor/toolkit/app/Firmware/eDLTFirmware/usb_drivers/i386/lmdfu_edlt.dll \
  CBUS_SCENE_NATIVE=1 CBUS_NATIVE_TLS_TEST=1 \
  python3 -m unittest discover -s toolkit-cli/tests -v
python3 toolkit-cli/research/verify_catalog.py --host 127.0.0.1
python3 toolkit-cli/research/verify_catalog.py --host 127.0.0.1 --all-revisions --boundaries \
  --output toolkit-cli/research/runtime/catalog-boundaries.json
python3 toolkit-cli/research/verify_projects.py --host 127.0.0.1 --server-archive-dir /work
```

Native database tests create their own temporary projects with closed networks.
Protocol tests connect only to their own simulator fixtures. Scene and TLS
acceptance create disposable Docker containers by default or owned local C-Gate
processes when `CBUS_NATIVE_SERVICE_BACKEND=local` is explicitly selected. Full acceptance requires the
`research`, `serial` and `usb` extras; USB diagnostic tests use owned pseudo-terminals
and descriptor inspection uses a fake backend through the actual PyUSB library.
Tests do not adopt existing projects. The historical project runner reports unsupported
operations explicitly; the dedicated [project repair](docs/project-repair.md)
commands have their own original Windows and native C-Gate acceptance.

For a durable JSON result, run `research/acceptance.py --require-no-skips`
with the required environment. It records test results and source hashes,
fails if tests are skipped or sources change during the run, and keeps Toolkit
parity separate from test success.

The audited [installed-wheel checkpoint](docs/test-acceptance.json) passed
**1,725 tests on Python 3.13.14 and 1,725 on Python 3.10.20** (historical dual-Python checkpoint; current policy is 3.13-only), with zero failures,
errors or skips and all 14 native gates enabled. The wheel SHA256 is
`5bebe9ea185da7e18171fad7434907b6dc0a398293198dd7c8aa0228253fef12`.
Both runs used the same 195 test modules and imported package hashes; the
snapshot contains 112 packaged files. The runs completed on 15 September 2026,
in approximately 71 and 75 minutes respectively. The audit checked the frozen
wheel, all snapshot inputs, complete test selection and actual imported modules.

This checkpoint integrates the eDLT widget and lifecycle work, original Windows
model comparisons, native C-Gate save/close/reload checks, project repair,
preferences, update metadata transport, repositories, serial commissioning,
addressing, simulator, USB and firmware diagnostic tests present in that wheel.
It also includes programming and transport cleanup corrections, Global factory
settings, and the Windows result-recovery correction. The previously interrupted
Shutter comparison completed through save and reload in both full runs.
See the report for the exact test list and [original oracle adapters](docs/original-oracle-adapters.md)
for backend scope. These tests cover the implemented behavior; they do not
establish complete Toolkit or physical-device parity.

The retained focused checkpoints below were recorded outside that frozen
wheel; each linked record identifies its runtime, source scope and date:

- [Configuration CRC](docs/edlt-crc.md): 21 tests, including 65,588 fresh original CRC results per run.
- [Percentage conversion](docs/edlt-percentage.md), [bounded parent composition](docs/edlt-parent-form.md), [ordered parent transaction](docs/edlt-parent-transaction.md), [automatic parent metadata](docs/edlt-parent-metadata.md) and [automatic SceneManager metadata](docs/edlt-scene-metadata.md): pure conversion and CLI acceptance, standalone original Windows 12- and 528-case captures, and portable focused coverage for all declared operations. Automatic parent metadata resolves existing Applications/Corridor lists and exact Reset raw strings, accepts contiguous fresh-graph Blank operations, and composes those results with the exact Trigger application/group/action creator before one parent PP save. Toolkit registry display/sort preferences, the original interactive Reset-plus-Blank and complete parent/SceneManager dialogs, project/DLTP images, and combined Schneider C-Gate/physical acceptance remain outstanding. Current exact test totals are reported by the repository test run rather than treated as a static capability claim.
- [About information](docs/toolkit-about.md): 16 tests, including 51 original instruction cases per run.
- [Signed update metadata](docs/toolkit-update-metadata.md), [revocation stages](docs/toolkit-update-revocation.md), [supplied-context registry conditions](docs/toolkit-update-registry-conditions.md), [applicability preflight](docs/toolkit-update-applicability-preflight.md), [supplied-cohort rollout gate](docs/toolkit-update-rollout-cohort.md), [owned-registry rollout branch](docs/toolkit-update-rollout-owned-registry.md), [combined supplied-cohort applicability preflight](docs/toolkit-update-applicability-cohort-preflight.md), [linked diagnostic provenance](docs/toolkit-update-diagnostic-bundle.md) and [local package join](docs/toolkit-update-package-bundle.md): bounded diagnostics plus exact source-file and selected package-byte receipts, with explicit trust and availability limits.
- [PCI routing](docs/pci-routing.md), [incoming routing](docs/pci-incoming-routing.md), [routed RECALL](docs/pci-routed-recall.md), [routed IDENTIFY](docs/pci-routed-identify.md) and [routed WRITE](docs/pci-routed-write.md): separate codec and transport checkpoints; all three commands accept project-resolved routes, while WRITE adds exact ACK path/tag matching and one-send mutation uncertainty evidence.
- [Database CSV export](docs/toolkit-database-csv.md): 82 earlier core/CLI tests, two host Windows-adapter guards, five owned Windows tests and one owned C-Gate acceptance for captured values, exact saved column selection, cached-object projection, RELAY4/generic/KEYE1-4/KEYEIR1-4/DIMDN8/DIMDN8F/RELDN12/SENPIROA/SENPIRIA/KEYGL5 file/live native XML, explicit ordered multi-unit, whole-network and whole-project export from one shared bounded snapshot/request with whole-selection rejection before output creation, KEYE per-block secondary-application associations, ordered repeated group associations, guarded Area13 persistence, portable UTF-8 and Toolkit-native Windows ACP output; the historical 23-test checkpoint includes 88 fresh original cases per run, while original Toolkit manager enumeration remains unverified. The five newly admitted KEYE4/KEYEIR profiles have static and synthetic evidence only; their original GUI report and cold native load remain unverified.
- [Thermostat temperature conversions](docs/thermostat-temperature.md): 17 tests with 28,840 fresh original cases per run and separate original Windows arithmetic acceptance.
- [Thermostat scheduling](docs/native-thermostat-schedule.md): 67 tests in the retained level-writer checkpoint; the composed unit/application/group/level workflow adds 18 current host tests and two retained owned-C-Gate cases with exact planning, backup, one target save/reload, opaque project-data preservation and explicit no-retry uncertainty evidence.

These overlapping focused counts must not be added to the full-suite count.
Their linked fixtures identify the exact inputs and limitations; a later full
wheel will integrate the newer changes.

To freeze a built wheel with its matching tests and harnesses, use
`research/prepare_wheel_acceptance.py path/to/package.whl`. The script checks
every packaged source file, copies the local tests and fixtures, and refuses
to overwrite an existing snapshot. Run its copied `research/acceptance.py`
in an isolated environment that installs the snapshot's wheel. The vendor
directory remains external and is not distributed in the wheel.

After the Python 3.13 run, `research/audit_wheel_acceptance.py SNAPSHOT
--report REPORT.json --output NEW-SUMMARY.json` checks that the wheel, snapshot,
complete test selection and imported module hashes agree. It requires passing
runs without skips on Python 3.13, with all native gates enabled, and
keeps test success separate from Toolkit parity. It verifies recorded results;
it does not run the tests itself. To re-audit a historical dual-version snapshot,
provide both reports and `--python 3.13 --python 3.10` explicitly.

For snapshots containing the Rust interop suite, set `CBUS_CGATE_MOCK_BIN`
to the absolute path of a freshly built `cgate-mock`. The acceptance runner
records its path, size and SHA-256 before and after the run; the wheel audit
requires this explicit gate and stable binary evidence. This verifies the test
binary bytes, not native C-Gate equivalence or Rust build provenance.

The oracle runs the **actual vendor C-Gate 3.4.0 jar** with Java 11, using
disposable project storage. Docker is the default; an explicitly selected local
backend verifies that every listener belongs to its own child process and binds
only to 127.0.0.1. Its test-only access rule enables the internal `PP` command family
used by Toolkit. It does not connect to a physical C-Bus network by itself.
The vendor Java runtime is needed for C-Gate operations, while offline project
and schema operations run in Python.

Remaining work is tracked in three acceptance layers: finish the executable
Toolkit surface census and map each workflow to the ledger; compare remaining
controls, error paths and device/firmware variations with independent Toolkit
behavior; and verify real device, network, persistence, recovery, USB and
firmware effects across the supported hardware profiles. The detailed eDLT,
unit-family, topology and diagnostic gaps are listed in the current
[implementation status](docs/implementation-status.md). The source/topic
census is in [toolkit-surface.md](docs/toolkit-surface.md), and
[capabilities.json](src/cbus_toolkit/capabilities.json) is the completion gate's
machine-readable input.
