# Reviewed relay conversion through save and recovery

The public Python CLI now completes one supported database move from review
through backup, conversion, project save, close/reopen and fresh verification.
`conversion plan-move`, `apply-move` and `recover` compose the RELDN4 → RELDN4A
existing-unit path against cmqttd. The low-level `conversion move` still reports
`project_saved: false`; the integrated apply performs and verifies that save.

The accepted fixture uses closed `WFCONV/254`, RELDN4 source 20
(`L5504RVF16`, firmware 2.7.00), RELDN4A destination 21 (`5504RVF`, 1.0.0),
backup `WFCONVB1`, unrelated unit 22, and indexed Application 58/Group 114.
Unit 22 retains a real programming reference to that group. All objects are
synthetic and provisioned through complete indexed Network XML.

## Delivered operator behavior

- Review binds the endpoint, private specification/catalogue/mapping hashes,
  complete indexed project snapshot, both PP images and independently
  predicted ordered target PP, identity, channels and project tree.
- Apply refuses stale input, malformed mapped PP, unsupported metadata,
  an existing backup or a reused/unresolved attempt. It requires exclusive
  ownership and every project network closed and idle.
- One verified backup precedes one CONVERT. Independent verification precedes
  one PROJECT SAVE. Close/reopen and fresh PP checks then verify the saved
  tree, destination identity, source removal, allocated OIDs and unrelated data.
- Private, fsynced journals record possible-send phases before COPY, CONVERT
  and SAVE. Interruption retains the phase and backup; recovery reads current
  project, PP and backup without repeating or restoring an operation.
- A converted loaded tree after a lost save reply remains
  `project_saved: null`, `persistence_verified: false`, `replay_authorized: false`.
  Changed or missing backup data and unavailable/conflicting recovery reads
  remain visible and produce nonzero CLI status.

The result preserves the native distinction between database address 21 and
inherited PP `UnitAddress=0x14`. It reports the mismatch explicitly and always
keeps `hardware_programmed: false`. See the [operator commands](conversion.md#reviewed-move-with-save-reopen-and-recovery).

## Current acceptance

Source and a fresh installed wheel each passed **180 focused tests**, with zero
failures, errors or skips. Fifteen native opt-in methods were excluded before
collection and are listed in the [acceptance receipt](acceptance/2026-10-01-conversion-workflow/acceptance.json).
Those methods did not execute. Subtest reports are not added to parent counts.
All 323 package Python/JSON files matched installed wheel bytes and remained
unchanged through the checks; actual import origins were checked.

Each installation also executed four public workflow cases: complete success,
lost CONVERT reply, lost PROJECT SAVE reply and stale indexed-group refusal.
All **eight cases / 74 public subprocess commands** passed. The independent
checker verified 179 ordered PP fields, all 179 fresh GET values, exact backup
and unrelated-tree preservation, destination identity, regenerated channels,
source removal and the retained group reference. The fault proxy consumed a
successful server reply before dropping it; both uncertain phases and repeated
apply refusal were checked. Stale group changes refused before backup,
conversion, save or journal creation. All cases had zero conversion-CNI
connections and verified process, listener and proxy cleanup. Daemon startup
traffic used a separately owned PCI simulator.

The original raw conversion capture matches the independent model, and 165
dependency-defined unchanged fields match that capture. The clean fixture
completes declared source defaults and explicitly sets interlock 2, zero
restrike channels, UnitAddress 20 and the eight-character PP Project string
`WFCONV00`. It has **no new native execution**; original Toolkit GUI and
physical acceptance are separate outstanding gates.

The two reported Rust CI regressions were corrected without weakening product
validation: synthetic string specifications now declare their intended length,
and PP lifecycle assertions preserve scalar `UnitName` independently from PP
`UnitName`. Four affected tests, formatting, workspace Clippy and the release
workspace build passed. Genuine current-binary replays passed 40 retained
SESSION exchanges and 28 direct/combined Unit XML comparisons; their maintained
receipts and packaged register were regenerated. No full local suite ran.
Published-revision CI is a separate check.

Earlier failed producer runs remain private, including a stale binary, import
path errors and fixture/finalization failures. They are not counted as passing
acceptance. Vendor specifications, wire snapshots and runtime copies remain
private; every owned temporary specification copy was removed.

## Remaining boundaries

Current cmqttd shallow Application/Group records created only by DBADDSAFE are
omitted from project/network XML, and fully qualified application XML selector
behavior remains incomplete. This acceptance uses complete indexed documents;
it does not resolve those backend gaps or establish lossless vendor archives.
Other conversion profiles, Toolkit client-side tweakers and frontend lifecycle,
native memory normalization, physical transfer and power-cycle behavior remain
open under the broader work item.

This delivers a major bounded workflow in issue #43, not closure of that
umbrella. The broad ledger remains **18/42 (42.86%)**; the functional denominator
is incomplete and zero obligations are fully accepted. Full Toolkit/C-Gate
parity is still unfinished.
