# Wireless Connection, gateway remotes, WRM globals and the learn boundary

The wireless modules cover database editing and explicitly selected unit actions:

- `cbus_toolkit.wireless_connection` edits the gateway Connection tab from a
  frozen project topology and PP snapshot.
- `cbus_toolkit.wireless_gateway` edits the Remote Switch mapping of the
  *C-Bus Wireless to wired gateway (2.x)* dialog (help topic 13876).
- `cbus_toolkit.wireless_unit_globals` edits the Learn Mode group of the Neo
  retrofit (WRM) wireless units. It also offers spec-level house-code and
  key-mask edits.
- `cbus_toolkit.wireless_scenes` replaces the Advanced gateway's scene tables.
- `cbus_toolkit.wireless_project_remotes` creates WTXU project metadata.
- `cbus_toolkit.wireless_actions` reads cached status and statistics, and
  dispatches explicitly authorized physical unit actions.
- `cbus_toolkit.wireless_commissioning` reproduces the commands C-Gate composes
  for `NET LEARN` and the wireless unit actions. It performs no I/O.

The database editors do not pair a device or learn a house code. Physical
actions have a separate explicit admission boundary described below. The
rules come from a sanitized static review of Toolkit 1.18.0.2754
and C-Gate 3.4.0.2001 (see [Evidence](#evidence)). Nothing was executed in the
original Toolkit.

## Gateway Connection tab

Admitted: **WGATE5N and WGATE5F firmware 2.2.90..2.4.99**, using
`WGATE5X_2.xml`. Original registration and base callbacks establish WGATE5N
Connection admission independently. Its base dialog keeps Connection visible
and hides Mode, Remotes and Scenes. The raw shared-specification fields for
those controls are preserved as opaque state, including `MapWirelessRemotes`.

WGATE5F uses the Advanced dialog: its Connection tab requires Network Gateway
mode (`MapWirelessRemotes=0`). Remote Switch mode hides the original
Connection tab. Older profiles remain outside this slice.

| Control | Parameter | Rule |
| --- | --- | --- |
| Application 1 / Application 2 | `Application` | Two application addresses. Primary 255 means All Applications and forces secondary 255, whose caption is `<Unused>`; Application 2 is then disabled. The same eligible address can be selected for both applications. |
| Send to adjacent network (wired) | `ApplicationConnectEnabled` | Copies the checkbox. Turning it off also clears `SynchroniseToWired`. |
| Synchronise to wired | `SynchroniseToWired` | Enabled while sending to the adjacent network. An explicit on request with adjacent sending off is refused. |
| Send to other remote network / destination | `ForwardingMode`, `ForwardingRoute` | Resolve the selected destination through actual directed bridge units in the frozen project. The CLI requires an explicit destination. |
| Status Monitor Application | `StatusMonitorApplication` | Independent application selection; no adjacent or synchronisation checkbox cascade. |

A changed application selection must exist in the source network, except
the special value 255. The original combo admits group-capable applications
and 255: with the pinned standard application table, it rejects addresses
192, 205, 206, 208, 223, 224 and 228. This is broader than Lighting, Trigger
Control and Enable Control. Both gateway application lists contain all
eligible source-network applications; neither excludes the other selection.
Unchanged legacy selections are preserved.

WGATE5F application edits require empty scene and remote mapping tables. Its
original application-change callbacks can rebind scene groups, clear commands, clear
remote group assignments or move secondary keys to the primary application.
Those callbacks can also create project metadata. Refusing this dependency
case prevents retaining mappings whose meaning changed. Other Connection
edits preserve the existing scene and remote tables. WGATE5N base application
callbacks have no Advanced scene or remote cascade, so its application edits
preserve those opaque tables. Its plan consumes exactly the six Connection
parameters; Advanced plans retain their additional dependency snapshot.

The gateway's **unit address identifies the initial adjacent network**.
Forwarding entries identify networks beyond it. For example, a gateway at
source network 254, unit 200, enters adjacent network 200. An actual bridge
at `200/p/123`, followed by one at `123/p/99`, resolves destination 99 to
entries `[123, 99]` and `ForwardingRoute=[27, 123, 99, 255, 255, 255, 255]`.
Reverse edges are used only when actual bridge units exist in that direction.

This slice admits `BRIDGE2N` and `BRIDGE2F`, with one to five extra networks.
It rejects missing, cyclic, ambiguous or unsupported topology before PP
mutation. Source and adjacent networks are not remote destinations. The
enabled route header is `9 * (extra_network_count + 1)`. Six extra networks
remain refused because the original save leaves its depth variable zero
when all six slots are occupied; a different header must not be invented.

Each original stored route entry is validated independently against the
project. The original save also tests each entry independently and retains
valid entries after an unused entry. This corrects the earlier receipt's
phrase “255 after the first unused one.” `connection show` reports the loaded route interpretation. A non-route
edit preserves the stored route, including malformed tails. An explicit disable writes seven 255 bytes with `ForwardingMode=0`;
that fixed-width normalization is a bounded database operation, not proof of
the original dialog's disabled-route string-buffer behavior.

Plans freeze the consumed project facts and all PP dependencies. Native
preflight rejects malformed plans and mismatched targets before connecting or
reading PP. For a valid target, apply requires `--exclusive-project`, the
exact source-network lock, fresh consumed metadata from database XML and
every project network closed with synchronisation idle. Stale PP or topology
refuses before staging. This protects a database edit; it does not prove
gateway forwarding over a radio or wired network.

The command saves PP to the database unit. Project persistence requires a
separate `PROJECT SAVE`; the native acceptance explicitly performs that save
before closing and reloading the synthetic project.

## Gateway Remote Switch mapping

Admitted: **WGATE5F firmware 2.2.90..2.4.99** with `WGATE5X_2.xml`. Toolkit
registers only this identity with `TCBusWirelessGatewayAdvancedUnit`. That
class's `TCBusWirelessGatewayAdvancedCGateAgent` loads and saves the Mode
control and the Remotes tab.

Refused before any write:

- **WGATE5N at any firmware.** Toolkit uses `TCBusWirelessGatewayUnit`, which has
  no Remote Switch mode or Remotes tab. This applies even though C-Gate
  exposes the same 68 parameters from `WGATE5X_2.xml`.
- **WGATE5F below 2.2.90.** These units use `WGATE5X.xml`, which has 30
  parameters and no remote table.
- **Any other unit type or firmware.**

### Controls and parameters

| Control | Parameter | Rule |
| --- | --- | --- |
| Mode (Network Gateway / Remote Switch) | `MapWirelessRemotes` | Item index 0/1. The Remotes tab is visible only in Remote Switch mode, so remote edits need that mode. Toolkit fills in a network default when Application 1 is 255; that switch is refused (see below). |
| Remote Control *N* (1..8) | `RemoteIdentityN` | 32-bit serial stored little-endian. `FF FF FF FF` means no remote. `--serial none` clears the remote. |
| Key Function | `KeySceneMaskN[slot]` | Group Dimmer = 0. Scene Set / Scene Toggle = 1. |
| Application switch | `ApplicationSecondayN[slot]` | Group keys only: 1 = secondary application. The switch is disabled while `Application[1]` = 255. Scene keys write 0. |
| Key Assignment (group) | `GroupAddressN[slot]` | Group 0..254, or 255 (none). |
| Key Assignment (scene) | `GroupAddressN[slot]` | `(scene − 1) << 4` plus 1 (Scene Set) or 6 (Scene Toggle). The scene must be configured and have a trigger group. |

**Keys and slots.** Each remote has 16 PP slots. The dialog shows 10 keys
(two groups of five).

- While a remote is selected, dialog key *k* uses slot
  `WTXU_KEY_MAP[k−1]` = `(5, 4, 3, 2, 1, 13, 12, 11, 10, 9)`, counting slots
  from 1. This is the WTXU remote map; the six other slots are hidden.
- Without a remote, Toolkit uses the identity map and disables every key, so
  `--remote-key` needs an assigned remote.
- `--remote-slot S=…` writes a raw slot 1..16 and is reported as
  `raw_slot_edits`.

**Scenes.** Scene *n* is configured if `SceneVectorOffset` has at least *n*
entries that are not 255 and satisfy `(v & 0x7F) < 100`. Scene keys also need
`SceneTriggerGroup[n−1]` ≠ 255. The editor does not decode scene vectors, so
Toolkit's check that a scene vector is non-empty is not reproduced.

The editor changes only the parameters named in a plan. It does not reproduce
these whole-dialog save effects, and `show` reports stored values that a
Toolkit save would rewrite:

- all 8 identities and 128 slots rewritten on every save;
- scene-key `ApplicationSeconday` forced to 0;
- scene commands other than 1 saved as 6 (Toolkit loads them as Scene
  Toggle);
- slots loaded without a remote saved through the WTXU map;
- scene tables rewritten by `SaveScenes`;
- Connection-tab parameters rewritten by the base agent;
- the Remote Switch cascade that assigns the network's default Lighting or
  Heating application to an unassigned Application 1 and gives every
  group-less key group 255;
- creation of project remote-control units, groups and scenes.

Use the separate Connection workflow above for Connection-tab parameters.
Remote mapping plans do not edit them.

Neither workflow reproduces the complete wireless parent save. The original
main PP SAVE is followed by ProjectSave and network LoadStatus, then a separate
terminal PP transaction saves `UseSecurity`. That later transaction has its
own 6000 ms SAVE timeout and error handling; it is not part of the first
SAVE. `UseSecurity` retains the loaded model Boolean; no HouseCode-derived
security policy is established. Network LoadStatus reads InterfaceState,
State and SyncState. A separate generic unit-status operation sends physical
PSYNC and is excluded from database editing. Complete WRM parent save also
serializes UnitInfo, Indicators, Channels, Blocks, Keys, KeySets, KeyMask,
Scenes and Macros, with profile-specific remaps. These complete save
dependencies and the terminal security lifecycle remain outside the subset
parameter editors.

## WRM unit globals

Admitted: WRM2D1, WRM2R1, WRM4D1, WRM4D2, WRM4R1, WRM4R2, WRM8D1, WRM8D2,
WRM8R1 and WRM8R2 at firmware 2.0.0..2.4.99, each with `<type>_2.xml`.
Toolkit uses the `TWRM<type>` (`TCBusWirelessInputUnit`) classes for these
units.

Refused before any write:

- the EZ variants (`TnmWRDX`);
- firmware below 2.0.0 (other classes and 1.x specifications);
- WRB, WRP and other wireless families.

| Control | Parameter(s) | Rule |
| --- | --- | --- |
| Allow Learn Mode + Current/Any Application Learn (`--learn-mode off/current/any`) | `LearnAllowed`, `LearnMasterMode` | off = 0/0, current = 1/0, any = 1/1. The radio buttons are disabled while learn is off. |
| Allow Network Learn | `LearnNetworkAllowed` | Copies the check box. |
| Reset (learn history) | `LearnedFlag` | Clears the flag. Enabled only while the unit has learned; otherwise refused. |
| House Code (read-only in Toolkit) | `HouseCode` | Displayed as eight hex digits `b3 b2 b1 b0`. `--house-code` parses the same order. Not a Toolkit control. |
| Key masks (no Toolkit control) | `KeyEnableMask1..4`, `KeyMaskAllowed`, `KeyMaskSave` | 16-bit masks and bytes. A Toolkit save writes 0xFFFF / 0 / 0 (`SaveKeyMask`). |

Plans list house-code and key-mask edits under `beyond_dialog`. These are
spec-level edits, not reproduced Toolkit controls. The Key Set Control tab
writes `KeyOffset*`, not the masks, and is not edited here.

The original normal WRM constructor creates **16 InputKeys** even on units
with 2, 4 or 8 visible buttons. Its whole-dialog `SaveKeyMask` therefore writes
`KeyCurrentMask=65535`; visible button count is not the mask width. This
resolved construction rule does not expand the globals editor into a full
wireless-unit dialog save.

## Stored Scenes with existing project metadata

`wireless scenes` edits the Scenes tab visible for WGATE5F firmware
2.2.90..2.4.99 in Wireless Remotes mode (`MapWirelessRemotes=1`). The
explicit full list combines the Scene Manager command list and scene-detail
application, trigger and ramp controls. It does not simulate interactive
selection, deletion callbacks or the entire gateway dialog save.

Each of at most eight scenes selects the primary or secondary application,
trigger group/action, ramp enum 0..15 and distinct command groups 0..254 with
levels 0..255. Level 255 is data; group 255 is a vector terminator. Empty scenes
are valid. The shared vector costs `2 * commands + 1` bytes per scene, up to
100 bytes; the manager's 12-command field is not a per-scene limit in this
allocation mode. Scene Toggle remote keys require a nonempty scene; Scene Set
may reference an empty scene. Both require assigned trigger/action metadata.

The serializer writes full 8-entry trigger/rate/offset arrays and the full
100-byte vector. It replaces the used vector prefix and preserves every old
byte after it. Clearing the list writes `255/255/0/255` slot tables and retains
the entire old vector. Sparse loaded offsets, unterminated vectors and active
rates outside 0..15 fail closed. Existing remote mapping bytes and ordinal
references are preserved; deleting a referenced ordinal is refused.

Plans bind the PP snapshot, selected gateway identity, project topology and
application/group/action metadata from one frozen XML snapshot. Existing
metadata is required for both loaded and requested scenes, including the
Trigger Control group255 object for unassigned scene triggers. The original
agent can create missing applications, groups and action selectors during
load and save those project changes separately; this workflow refuses those
missing dependencies. It does not perform automatic metadata creation.

```sh
cbus-toolkit wireless scenes show gateway.json --project-xml snapshot.xml \
  --source-network 254 --gateway-address 200
cbus-toolkit wireless scenes plan gateway.json --project-xml snapshot.xml \
  --source-network 254 --gateway-address 200 --scenes scenes.json > scene-plan.json
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/200 \
  wireless-gateway --plan scene-plan.json --exclusive-project
```

For example, `scenes.json` contains the complete desired list:

```json
[{"application":"primary","trigger_group":10,"trigger_level":20,"rate":5,
  "entries":[{"group":7,"level":0},{"group":9,"level":255}]}]
```

Saved plans are validated before a C-Gate client is created. Native execution
requires the exact database source, exclusive project ownership and every
project network closed with synchronization idle. It stale-checks consumed
project facts and all scene/remote dependencies, stages only the five scene
parameters and verifies PP readback plus unrelated parameter preservation.
The normal unit workflow saves the PP source unless `--dry-run` is present.
It does not claim radio scene execution or the parent dialog's later saves.

## WTXU project remote creation

`wireless project-remote plan` creates a reviewable metadata-only plan for an
existing admitted WGATE5F gateway. The local original catalogue must resolve
exactly the supported WTXU/5888TXBA row. The plan chooses the first free unit
address in 100..255 and the first unused case-sensitive `Remote 01`, `Remote 02`,
… name in the source network. Exhaustion, duplicate serials, ambiguous catalogue
rows and unsupported gateway profiles are refused.

```sh
cbus-toolkit wireless project-remote plan --project-xml snapshot.xml \
  --catalogue-xml cbusunits.xml --source-network 254 --gateway-address 200 \
  --serial 70179.836 > remote-plan.json
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/200 \
  --dry-run wireless-gateway --plan remote-plan.json --exclusive-project
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/200 \
  wireless-gateway --plan remote-plan.json --exclusive-project
```

This path validates and freezes the plan before connecting, then bypasses PP
programming entirely. Preview reads and stale-checks the complete native
project, verifies every network is closed/idle, and performs no writes. Apply
repeats those checks, creates the WTXU row with firmware0 and UnitName `REMOTE`,
and follows three distinct source-backed project save boundaries:

1. Save the constructor identity row, before serial/catalogue metadata exists.
2. Add the known serial, empty description and catalogue; perform the inherited
   database agent's project save.
3. Reassert the resolved WTXU unit type and perform the creation caller's save.

The constructor's original serial argument is an empty Delphi string, not a
numeric zero. No PP defaults are guessed or written. Existing project content,
including gateway mappings, is preserved. Native C-Gate regenerates its own
configuration OIDs on project saves; only those UUID values may differ, while
configuration names, values, order and all other project data remain checked.
Native DBSETSAFE rejects rewriting an unchanged TagName as a self-collision;
the workflow retains its already-verified name instead.

A failed or uncertain mutation stops immediately, returns a partial-result
receipt including each attempted save, and performs no automatic rollback or
replay. `saved=false` does not mean earlier stages were undone. The command
creates a project record; it does not pair a radio remote, discover serials,
assign it to a gateway page, run the original load dialog or initialize PP.

## C-Gate learn and unit-action boundary

`wireless_commissioning` rebuilds the command bodies C-Gate composes (`aW.e`,
before PCI framing):

| C-Gate command | Command body (unit 0x14) | Reply |
| --- | --- | --- |
| `NET LEARN <net> <app> <grade> <group>` | `\05 <app> 00 03 <grade> <group> <check>`, where `check` = −(grade+group) mod 256. For example, `\05380003010AF5`. | None |
| `DO <unit> MAISync` | IDENTIFY 0xFE: `\46140021FE` | 8 bytes |
| `DO <unit> ResetOpStats` | CAL 0x08: `\46140008` | None |
| `DO <unit> RecallOpStats` | four 12-byte reads, `\4614002A000C` … `\4614002A240C` | 48 bytes → 12 LE counters |
| Status GET properties | No bus command; cached strings | Text, initially `unknown` |
| Internal Psync status refresh | IDENTIFY 0x50..0x53 | Updates cached strings |

`NET LEARN` accepts only grades 1, 2 and 0x80..0x83 (init relay, init dim,
cancel, exit relay, exit dim, exit area).

Learn, explicit DO actions and the internal Psync refresh need a live network.
Status GETs and GET OpStats read existing runtime caches; they do not establish
freshness or implicitly synchronize a unit. The old boundary receipt conflated
status GET with its separate physical refresh; that classification is corrected.
The Rust cmqttd does not implement these wireless actions.

## Typed cached reads and wireless actions

The typed action workflow admits the same bounded WGATE5F/WRM profiles listed
in its source receipt, verified against a local original catalogue. A frozen
project snapshot binds the unit address, native OID, known serial and identity.
The unit's current cached runtime profile and serial must match before execution. This
binds the database and runtime records; it does not physically identify hardware.

```sh
cbus-toolkit wireless action plan --project-xml snapshot.xml \
  --catalogue-xml cbusunits.xml --source-network 254 --unit-address 20 \
  --operation cached-status > action-plan.json
cbus-toolkit cgate unit --lock-address //TEST/254 --source //TEST/254/p/20 \
  wireless-action --plan action-plan.json
```

Operations are `cached-status`, `cached-op-stats`, `mai-sync`, `recall-op-stats`
and `reset-op-stats`. Cached status exposes all four native fields, including
UnitTemperature; the original dialog shows only supply voltage and the two
radio power readings. Cached OpStats may be empty or left over from a previous
successful recall. Neither cached operation refreshes a unit.

Physical DO actions require `--allow-physical-action`; their omission is
refused before connecting. `--dry-run` validates and reads bound records without
issuing DO. The command never opens a network or creates a PP session. Recall
and Reset require a transport timeout of at least the original eight seconds;
MAISync has no recovered original Toolkit timeout and uses the explicit finite
transport timeout (CLI default ten seconds).

A successful Reset reply confirms that C-Gate completed the send, not that
counters are zero. Recall reads OpStats only after its exact successful DO
reply. Failure or an uncertain response stops without CLI command replay, reset,
rollback or a second command that could hide stale cache data. Native C-Gate
may itself retry bus requests according to the network configuration; a single
CLI DO command does not prove a single physical frame. MAISync is a
native C-Gate action; no original Toolkit status-dialog callback was found.

The original status refresh is broader: `Psync` with a 15-second timeout, then
three status GETs, RecallOpStats and GET OpStats. Psync also updates diagnostics
and application metadata, so the typed cached view does not implicitly perform
that sequence. Physical pairing, original GUI execution and radio results
remain unverified. Development DO tests use synthetic peers only. The owned
closed-project native test pins the unit-not-found refusal and confirms that
database presence alone does not establish runtime cache availability.

## Commands

Offline, from a PP export or a bare mapping with `--unit-type` and
`--firmware`:

```sh
cbus-toolkit wireless gateway show gateway.json
cbus-toolkit wireless gateway plan gateway.json --mode remote-switch
cbus-toolkit wireless gateway plan gateway.json --remote 2 --serial 0x10203 \
  --remote-key 1=group:7:secondary --remote-key 2=scene-toggle:1 --remote-slot 16=group:none > plan.json
cbus-toolkit wireless globals plan wrm.json --learn-mode current --network-learn off --house-code 00c0ffee
cbus-toolkit wireless boundary --unit 20 --learn 56 1 10
```

Connection plans also require a saved project XML snapshot. The PP identity
must match the selected gateway in that project:

```sh
cbus-toolkit wireless connection show gateway.json --project-xml snapshot.xml \
  --source-network 254 --gateway-address 200
cbus-toolkit wireless connection plan gateway.json --project-xml snapshot.xml \
  --source-network 254 --gateway-address 200 --application1 56 --application2 202 \
  --adjacent-network on --synchronise-to-wired on --destination-network 99 \
  --status-monitor-application 56 > connection.json
```

Assignments use `group:G[:primary|secondary]`, `group:none`, `scene-set:N` or
`scene-toggle:N`.

Against a native C-Gate database unit. Physical destinations are refused. The
editor plans, applies, reads back and verifies; `--dry-run` skips the save,
and `--plan` stale-checks every owned and dependency parameter first:

```sh
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/30 wireless-gateway --show
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/30 --dry-run wireless-gateway \
  --remote 1 --serial 66051 --remote-key 3=group:12:secondary
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/30 wireless-gateway --plan plan.json
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/31 wireless-globals --learn-mode off
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/200 wireless-gateway \
  --plan connection.json --exclusive-project
```

If a PP write fails or its reply is uncertain, the result reports
`attempted_parameters` and nothing is saved or retried. Use
`CBUS_UNITSPEC_DIR` for the decoded specifications.

## Evidence

| Evidence | What it pins |
| --- | --- |
| `research/fixtures/wireless-source-review.json` | Sanitized static receipt covering: profile registrations; attribute offsets; control-to-parameter rules with original addresses; the WTXU key map; scene encoding; dependencies; save order; unreproduced save effects; the ForwardingRoute rule; the WRM learn/house-code/key-mask rules; unresolved points. It records hashes of the executable, map, catalogue, form resources, help topics and specs. |
| `research/fixtures/wireless-connection-source-review.json` | Fresh static receipt for the Connection controls, application lists/filter and callbacks, directed topology builder, per-entry route save/load rules, profile limits, separate terminal `UseSecurity` save and normal 16-InputKeys WRM construction. Supersedes the earlier route-tail wording and unresolved key-count note; records exact method addresses and hashes. |
| `research/fixtures/wireless-base-connection-source-review.json` | Independent WGATE5N base unit/agent registration, Connection visibility, exact six fields, catalogue/spec selection and application callbacks without Advanced dependencies. Supersedes the earlier deliberate WGATE5N Connection exclusion. |
| `research/fixtures/wireless-base-connection-native-acceptance.json` | Positive owned closed native project workflow at both WGATE5N firmware bounds: plan, stale refusal, stage, raw readback, 62 unrelated parameters preserved, save/close/reload and four actual CLI operations. No NET OPEN, NET SYNC or DO; physical forwarding remains unverified. |
| `research/fixtures/wireless-parent-save-source-review.json` | 36 original method hashes establish the loaded security Boolean, distinct main/project/network-status/security phases, network GET versus unit PSYNC distinction and the nine remaining WRM cascades. Source evidence only; no complete parent workflow execution. |
| `research/fixtures/wireless-scenes-source-review.json` | 98 exact original method hashes pin visibility, vector tail preservation, allocation, scene detail controls, ordinal remote references and load-time metadata side effects. |
| `research/fixtures/wireless-scenes-native-acceptance.json` | Owned closed synthetic project acceptance for full arrays, stale state, unrelated PP preservation and save/close/reload; separately records native permissive array behavior. Database evidence only. |
| `research/fixtures/wireless-project-remotes-source-review.json` | Original constructor, naming/allocation, catalogue/default boundaries, inherited dispatch and three project saves. |
| `research/fixtures/wireless-project-remotes-native-acceptance.json` | Owned native metadata-only creation and CLI preview/apply/stale refusal, three saves, uncertainty stop/no replay, full gateway PP and project preservation, save/close/reload. No pairing or PP initialization. |
| `research/fixtures/wireless-actions-toolkit-source-review.json` | Original status/reset callbacks, explicit Psync/Recall/GET order and timeouts, no timer or initial I/O, no original MAISync callback. |
| `research/fixtures/wireless-actions-cgate-source-review.json` | Native class/catalogue admission, cached versus physical command semantics and exact responses. |
| `research/fixtures/wireless-cgate-boundary.json` | C-Gate class hashes, command templates, examples and why each action needs a live network. No command was executed. |
| `research/fixtures/wireless-gateway-native-acceptance.json` | Owned C-Gate 3.4.0.2001 on loopback. WGATE5F at 2.2.90 and 2.4.00: 10 verified edits and 36 raw PP byte assertions, invalid and boundary edits, preservation of unrelated parameters, save, project close and reload with identical values and raw image. Refusals for WGATE5N 2.4.00 and WGATE5F 2.2.89 leave values unchanged. |
| `research/fixtures/wireless-connection-native-acceptance.json` | Owned C-Gate 3.4.0.2001 with four closed synthetic networks. WGATE5F 2.2.90 and 2.4.00: 38 raw-byte assertions, stale PP/remote/topology refusals, configured-mapping application-change refusal, 62 unrelated parameters preserved per profile, explicit seven-byte disabled-route normalization and save/close/reload. Real CLI subprocesses verify offline planning, preview without persistent change, saved apply and stale refusal. The owned interfaces remain closed; no physical verification. |
| `research/fixtures/wireless-unit-globals-native-acceptance.json` | All ten WRM types (2.0.0, 2.4.00 and 2.4.99): 60 verified edits and 120 raw byte assertions, save/close/reload. Refusals for WRM2D1EZ, WRM2D1 1.11.0 and WRB2D1. |
| `tests/test_wireless_gateway.py`, `tests/test_wireless_unit_globals.py`, `tests/test_wireless_commissioning.py`, `tests/test_cli_wireless.py` | Offline, native and CLI tests. The native CLI test covers dry-run preview, saved-plan apply, stale refusal and the database-only guard. |
| `tests/test_wireless_connection.py`, `tests/test_wireless_connection_cli.py`, `tests/test_wireless_connection_native.py` | Connection rules, CLI behavior and literal independent topology cases; the opt-in native test uses an owned C-Gate process with synthetic closed networks for plan/stale/apply/raw-readback/save-close-reload and preservation checks. Native database success establishes database behavior only. |
| `tests/test_wireless_base_connection.py`, `tests/test_wireless_base_connection_cli.py`, `tests/test_wireless_base_connection_native.py` | WGATE5N six-field ownership, opaque Advanced state preservation, separate profile admission, forged-plan and preconnect guards, actual CLI/native persistence and cleanup. |

Open:

- Physical learn/join outcomes, radio pairing, house-code transfer and gateway
  forwarding.
- Original Toolkit GUI execution of these tabs.
- Automatic scene group/action creation, original load-time remote discovery
  and gateway mapping integration, the Remote Switch Application 1 cascade,
  and interactive Scene Manager callbacks.
- Whole-dialog remote mapping validation outside the bounded Scenes workflow.
- Remote classes other than WTXU.
- Connection profiles beyond the bounded WGATE5N/F range, other bridge families,
  six-entry routes, configured-scene/mapping application changes and the
  complete original parent save lifecycle.
- WRB/WRP/WRD, EZ and 1.x wireless units.
- Decorator wireless dialogs.
- cmqttd wireless support.
