# Technical findings and evidence index — 30 September 2026

This is a navigation and synthesis record for **Toolkit 1.18.0.2754 / C-Gate
3.4.0.2001**. Its publication baseline is fetched `origin/main`
[`9d399be55b90e2f6db03a08a5f452669b3392a05`](https://github.com/mitchell-johnson/cbus/commit/9d399be55b90e2f6db03a08a5f452669b3392a05).
The integrated batch below has its own source-bound validation; later owner
revisions in the queue remain unaccepted by that batch. Their presence in a
working tree is not publication or integration acceptance. This index does not replace the
[implementation status](../toolkit-cli/docs/implementation-status.md),
[functional register](../toolkit-cli/docs/parity-register.md), or
[remaining-work plan](parity-review-and-roadmap.md).

## Reading the evidence

- **Recovered original behavior:** pinned EXE/MAP/assembly bytes, inspected
  method ranges, resources and explicit control flow. Static recovery does not
  execute a form or establish a database/device effect.
- **Original component execution:** original instructions or managed methods
  with declared inputs and adapters. Prepared graphs, interpreted IL and proxy
  controls retain those qualifications; they are not complete original GUIs.
- **Synthetic software execution:** literal vectors, memory peers and scripted
  loopback services test implementation behavior and failure handling.
- **Owned native database execution:** original C-Gate against closed synthetic
  projects can establish PP/XML save/reload within the tested profiles. It does
  not establish live C-Bus behavior, a radio pairing or displayed pixels.
- **Physical acceptance:** requires its own bounded observation and provenance.
  None is added by this index. Counts from overlapping scopes must not be added.

Source hashes, expected results, exact tested revisions, skips and failed runs
remain in domain evidence. Public receipts must be **sanitized derivatives**
when the original record contains local coordinates or identifiers: identify
the normalized fields, retain technical input/source hashes and outcomes, and
keep the exact original privately. Sanitization is not a rerun. Do not silently
change an executed-source hash or claim a later wheel was tested by an older run.

## Published foundations and canonical contracts

The following commits are reachable from the publication baseline. Their
acceptance is bounded by the linked contracts, not by the breadth of a title.

| Area | Published revision(s) | Canonical findings and remaining boundary |
| --- | --- | --- |
| DALI and SENLL | `9a792616`, correction `9d399be5` | [Batch evidence](../toolkit-cli/docs/feature-batch-2026-09-30.md), [DALI](../toolkit-cli/docs/dali-commissioning.md), [sensors](../toolkit-cli/docs/sensors.md). The 21 global/15 line proxy families and 133 physical global leaves do not admit all physical line intentions or whole-proxy replacement. SENLL forced-save order is recovered; colliding shared-key reassignment, optical/timing and power-failure acceptance remain open. Explicit scene level 255 is the DALI removal sentinel and is refused. |
| Thermostat | `43ca4b5f` | [Settings](../toolkit-cli/docs/thermostat-settings.md), [templates](../toolkit-cli/docs/thermostat-templates.md), [temperature](../toolkit-cli/docs/thermostat-temperature.md). One recovered form save includes dependent writes. Repeating saves can change the result; never add hidden saves to reach a fixed point. Complete initialized GUI callbacks and physical behavior remain open. |
| Document Project | `63bdd691` | [Documentors](../toolkit-cli/docs/project-documentation.md), [group usage](../toolkit-cli/docs/project-documentation-usage.md). Recovered profiles and explicit saved-native-XML input are bounded projections. Missing bodies remain marked unrecovered; manager history, locale ordering, full-page bytes/visuals, printing and cancellation are separate gaps. |
| Classic DLT | `e2fbe7bd`, `abef8e82` | [Labels](../toolkit-cli/docs/classic-dlt-label-controls.md), [display](../toolkit-cli/docs/classic-dlt-display.md), [delivery source](../toolkit-cli/docs/classic-dlt-delivery-original.md). Saved TEXT/PP display controls are distinct from physical transfer. Native save drops unnamed bit 7; staged raw verification does not establish its persistence. |
| Conversion | Existing bounded registry | [Conversion tweakers](../toolkit-cli/docs/toolkit-conversion-tweakers.md), [offline conversion](../toolkit-cli/docs/offline-conversion.md). Source/target constructor, writable attributes, post-copy hooks and specification admission are separate requirements. A registered conversion pair is not automatically implemented. |
| Wireless | Existing bounded profiles | [Wireless](../toolkit-cli/docs/wireless.md). Project metadata, PP settings, cached status, physical actions and whole-dialog security saves have distinct effects and ownership. Radio and complete-parent acceptance remain open. |
| eDLT | Existing bounded parent workflows | [Parent transaction](../toolkit-cli/docs/edlt-parent-transaction.md), [metadata](../toolkit-cli/docs/edlt-parent-metadata.md), [remaining controls](../toolkit-cli/docs/edlt-remaining-controls.md). Supplied caches and staged component order do not prove the original parent executed. Template loading has an additional lifecycle, described below. |
| IOPE | Existing settings subset | [IOPE settings](../toolkit-cli/docs/iope-settings.md). Recoveries, timer fields and dependent writes are profile-specific. Separate component editors must not be promoted to a complete form save. |
| Firmware | Existing bounded DFU workflow | [Update plan](../toolkit-cli/docs/firmware-update-plan.md), [faults and recovery](../toolkit-cli/docs/firmware-update-recovery.md), [original oracle](../toolkit-cli/docs/firmware-original-oracle.md). A simulator or source-linked package is not authenticity, bootability or physical-update acceptance. |
| Routed selected serial / PP | Python `c8b801b7`; native PP transcript `a687fb3f`, GOC2 correction `e496733a` | [Selected serial](../toolkit-cli/docs/pci-selected-serial.md), [routed writes](../toolkit-cli/docs/pci-routed-write.md), [cmqttd boundaries](cmqttd-cgate.md). Exact route/unit/tag/count correlation and no replay after uncertainty remain required. Component construction and scripted inventories do not establish a native routed mutation or bridge/device persistence. |

The published [batch record](../toolkit-cli/docs/feature-batch-2026-09-30.md)
retains the installed-wheel 150-test/861-subtest result, original database
comparisons, platform skip and opt-in deselections. Its initial two harness
failures and earlier admission/fixture failures remain historical failures;
later focused passes do not rewrite them. No full-functionality percentage is
available while the census/denominator remains incomplete.

## Integrated conversion, DLT and temperature batch

This revision integrates the twelve feature/evidence imports described in the
[batch report](../toolkit-cli/docs/feature-batch-2026-09-30-conversions-dlt-temperature.md).
It adds 108/292 admitted conversion pairs, ordered classic DLT indicators and
TEXT-dialog transactions, offline label-broadcast compilation/assessment,
thermostat temperature preferences and bounded allocation, additional
documentors, CBZ bounds and firmware cleanup handling. The
[root validation](../toolkit-cli/docs/imported-toolkit-root-validation.json)
records source commits, actual binary/source hashes and focused checks;
[installed-wheel acceptance](../toolkit-cli/docs/imported-toolkit-features-acceptance-summary.json)
preserves the source replay-selection error and exact wheel exclusions.
No full GUI or physical acceptance is implied. Publication replaces private
runtime coordinates with explicitly labeled sanitized derivatives and retains
raw originals privately.

## Integrated firmware package safety

The [package identity contract](../toolkit-cli/docs/firmware-package-snapshot.md)
records immutable regular-file capture, bounded ZIP/AES reading and exact
plan/image admission. Resume now checks the interrupted journal's package
digest before its first archive parser, decryption reader or USB opener.
Real-journal regressions reproduce the old defect and verify the correction.
The [focused source/wheel receipt](../toolkit-cli/docs/firmware-package-snapshot-acceptance.json)
passes 167 tests and 234 subtests in each environment with one original assembly
replay excluded before execution; the [root validation](../toolkit-cli/docs/firmware-package-snapshot-root-validation.json)
independently matches 277 package files. Offline NCC and payload interpretation
are now implemented; physical commands, authenticity, bootloader behavior and
Windows acceptance remain open. No full-suite or hardware run is implied.

## Integrated Toolkit controls and workflows

The [latest batch report](../toolkit-cli/docs/feature-batch-2026-09-30-toolkit-controls.md)
integrates the previously queued coupler/InputUnit conversion, wireless,
classic DLT ICON/delivery, disabled thermostat defaults and additional
documentor chains. It also adds early stored/Deflate-only firmware codec
admission. The conversion registry now admits 123/292 pairs and refuses 169.
The [domain reports](../toolkit-cli/docs/feature-batch-2026-09-30-conversions-wireless.md)
and [DLT/thermostat/documentor boundaries](../toolkit-cli/docs/feature-batch-2026-09-30-dlt-thermostat-documentors.md)
retain exact owner provenance and outstanding acceptance work.

The [composed receipt](../toolkit-cli/docs/toolkit-controls-acceptance-2026-09-30.json)
preserves initial feature source/wheel results (1,291 pass, one historical
binding failure, two static-input skips and 1,658 subtests), the final affected
source result (188 pass/309 subtests), and the final wheel result (187 pass,
one omitted-reference failure, followed by its exact-case pass). All seven
new required native database gates executed successfully. All 297 final
package files match source, wheel and installed bytes; 294 are unchanged from
the initial feature wheel. This is qualified carry-forward plus focused
follow-up, not a repeated full feature run on the final wheel.

The [legacy route follow-up](../toolkit-cli/docs/toolkit-controls-legacy-route-acceptance-2026-09-30.json)
passes 17 tests/50 subtests in source and the same wheel, without skips. It
corrects two historical whole-CLI bindings exposed by the earlier firmware
publication's failed CI. Exact historical archives and nine unchanged project
AST subtrees preserve old proof; fresh native API storage is kept separate
from portable CLI execution and forwarding evidence. Original receipt hashes
and failed CI outcomes are unchanged. The
[root validation](../toolkit-cli/docs/toolkit-controls-root-validation-2026-09-30.json)
records package identity, source imports and sanitized derivative provenance.
Full GUI, radio, physical update/transfer and power-cycle acceptance remain open.

## IOPE, template and failure-evidence integration — 1 October

The [follow-up batch](../toolkit-cli/docs/feature-batch-2026-10-01-iope-templates-recovery.md)
integrates the complete committed IOPE chain through `18d78566`, the four
eDLT template revisions through `d951e882` and firmware CLI error reporting
from `3e658045`, with separate integration fixes. Uncommitted owner validator
investigations are excluded. Eight IOPE components now have public CLI
registration; eDLT format/export/preview and the parent local stager are
registered, with a separate guarded offline Save-validation stage; Apply remains refused. Firmware failure/cancellation adds
bounded scalar lifecycle evidence and a read-only journal snapshot; backend
error strings in new fields use fixed labels after a reproduced privacy defect.

The [combined source/wheel receipt](../toolkit-cli/docs/iope-template-firmware-acceptance-2026-10-01.json)
records 642 passed test nodes and 1,951 passed subtests in each context, with
zero failures/skips and five deliberate pre-execution exclusions. One IOPE
matrix method is collected under two module paths; both call nodes passed.
Separate terminal-image database proofs compare 874 parameters and five CRCs
per context, without executing Apply. Native/static provision is qualified
separately. Historical owner hashes remain unchanged; the eDLT
terminal native receipt is a declared sanitized derivative. Controller hardware,
whole initialized template Apply and original firmware/physical acceptance
remain open. See [IOPE integration](../toolkit-cli/docs/iope-integration-scope.md),
[templates](../toolkit-cli/docs/edlt-template-integration-boundaries.md) and
[firmware diagnostics](../toolkit-cli/docs/firmware-cli-error-evidence.md).

## Routed commissioning and documentor integration — 1 October

The [next batch](../toolkit-cli/docs/feature-batch-2026-10-01-routed-commissioning-documentors.md)
consolidates Rust routed execution through `b7c8aa9b`, Python routed project
reconciliation through `2abc4ab3`, independent Rust apply-v2 frame validation
through `756a1eb1`, and Bytecraft/SceneModify documentors through `5fdf0b4f`
and `28201602`. Source and installed-wheel acceptance must bind the combined
revision; historical owner counts and hashes remain historical. The one
private host-name field in the first routed receipt is a declared derivative,
with its raw fingerprint and unchanged technical results retained.

Rust apply/verify re-derive the exact one-to-six-bridge route from the pinned
project, preserve endpoint ownership and durable attempt intent, send once and
recover read-only. Python independently reparses the versioned raw/parser
frame proof and exact inventories before offline XML/CBZ reconciliation.
Uncertain/partial proof and routed live C-Gate reconciliation remain refused.
Documentor additions require complete explicit old DIMPR12 and canonical
SceneModify inputs; initialized loaders, original GUI/page comparison and
physical acceptance remain separate.

## Queued local work at this snapshot

These are inspected owner revisions, **not public commit links or permission
to apply a chain blindly**. Keep the order, reconcile integration copies, and
record the final sanitized accepted commit when published. Supplemental paths
are written as code because some do not exist in the baseline tree yet.
Uncommitted follow-on work is intentionally excluded from accepted results.

| Area | Owner commit sequence after its published equivalent | Retained result, supplementary path and exact gap |
| --- | --- | --- |
| Firmware packages | `de74df7e` → `b058a43d` → `1b03e1da` integrated above | Immutable package execution admission, offline NCC transcripts and normalized payload interpretation now have focused source/wheel validation. Patchset analysis remains queued; CLI error-reporting is integrated in the next batch below; vendor authenticity, nonzero external-flash behavior and physical payload acceptance remain open. |

## Fresh source recovery: facts that must survive integration

A separate fresh static pass re-read all 27 top-level binaries (22 managed,
five native), all 412 DFM resources, 10,102 components and 80,954 properties.
It disassembled 1,704 mapped native ranges and 16 managed application/support
assemblies: 1,061 types, 9,338 methods, 69 manifest resources and 52 BAML names.
These are inventories, not counts of implemented or accepted functions.

The private extraction manifest and complete disassemblies remain outside Git.
This is their sanitized behavioral synthesis; it does not make those private
artifacts public acceptance receipts. Domain owners must retain the relevant
bounded source proofs alongside each implementation.

| Original input | Version | SHA-256 |
| --- | --- | --- |
| `CBusToolkit.exe` | 1.18.0.2754 | `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab` |
| `CBusToolkit.map` | Matching MAP | `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb` |
| `CBusLogicModel.dll` | 7.14.0.0 | `34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823` |
| `eDLT.dll` | 7.16.0.0 | `75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3` |
| `FirmwareUpdater.exe` | 1.16.3.0 | `f54ea945167436b8a3e95decb1d146d01d60e4af1badcd34f4bad626df1e54d5` |

1. **Correct the event census by property type.** `OnColor` on the two LED
   classes is a scalar `TColor`, not an event. Excluding those 53 records
   yields 1,839 candidates; exact root-class/MAP lookup resolves 1,822 and
   leaves 17 unresolved. Preserve real events regardless of handler-name
   prefixes. The correction must propagate through the
   [executable surface](../toolkit-cli/docs/toolkit-executable-surface.json)
   and dependent records. This integrated revision regenerates that census
   and versions the correction; its publication baseline contains the older one.
2. **The main executable is native Delphi x86.** Machine `0x14c`, image base
   `0x600000`, no CLR directory; code VA is `0x601000 + MAP segment-1 offset`.
   PE/MAP, DFM/RTTI/VMT and native instructions supply its evidence. Managed
   assemblies use a separate recovery path. Linear disassembly stopped early
   in 369 ranges; embedded data requires control-flow-aware follow-up. Optional
   WPF `monodis` failed while `ikdasm` and Cecil succeeded. BAML names alone
   are not reconstructed XAML.
3. **Conversion hooks follow actual dispatch.** RELDN8↔X repacking is recovered
   in `0x12EDE28..0x12F0488`, including Group then logic 13/14/15/16 setter order.
   The 144 derived vectors are static expectations, not executed native output.
   DLT hook `0x121DCBC` does not call the inherited Neo/CoreKey/Learn chain;
   eDLT conversion methods `0x12B9000`/`0x12B9008` are empty. Class ancestry or
   method names cannot substitute for constructor/mutability proof.
4. **Language loading and label classification are ordered.** Flavour 1 can
   use legacy 0; ordinary direct flows remove absent alternates. The classifier
   at `0x858658` tests the previous DYNAMIC value before assignment. Nineteen
   recovered direct callers pass false through Group/Level wrappers; the true
   preserve branch and indirect callers are not disproved. A failed optional
   runtime probe supplied no accepted evidence; cleanup was unconfirmed in its
   private failure record. Static findings remain separate from that failure.
5. **Default-language inference needs context.** `CBusNetwork.ReadXmlData`
   (`0x06000292`, RVA `0x9EF8`) distinguishes metadata-only default 2 from a
   real language 2 with no default metadata; the latter can preserve old state
   or leave fresh default 0. Published metadata guards refuse ambiguous
   explicit collections. Broader original input admissibility and retained
   session normalization are still unresolved.
6. **Template loading is a lifecycle.** Original load (`0x060001E7`, RVA
   `0xF368`) resets, populates panels, calls BeforeChange, assigns in order,
   then calls AfterChange/rebind; persistence waits for Apply/OK. Reset can mask
   failure. Rebind can catch an error and continue. Save can return true with
   no subscriber, and Apply/OK can ignore its Boolean. Dispatch is not a
   successful binding or a persistence receipt.
7. **Thermostat prepared graphs differ from fresh forms.** The earlier
   synthetic core produced used zones `1→3`; the corrected AdvancedUI prepared
   core produced `0→2`, with 15,926 original instruction events and three model
   callbacks. These are different declared contexts. The remaining bridge
   `0x11221fc → 0x11221c8 → 0x112947c → 0x1129508` can process posted plant
   message `0x423` using dispatch-time state. Pointer equality/raw PP does not
   prove an empty queue. Ready-form activation, native text/selection/focus,
   notification order and joined BeforeSave/save-reload remain required.
8. **Managed UI needs its own census.** The 169 candidates include 27
   Form/Window and 68 UserControl descendants. Architectural dimmer has six
   managed dialogs plus tab/view-model transitions. Do not mechanically add
   169 to 412 or treat candidates as deduplicated workflows.
9. **Network label editing batches by group.** The sender (`0x0600000F`, RVA
   `0x2820`) keys dirty entries by application/group/variant/language, without
   action level, and processes matching labels across levels. It ignores the
   SaveDltToUnit Boolean and clears dirty entries on ordinary return. Exact-level
   transport alone does not reproduce the batching or failure contract.
10. **Wireless whole-form save has a second boundary.** Main PP SAVE,
    ProjectSave and LoadStatus precede a separate UseSecurity session/save
    (`0x1258434`, `0x1257E40`, `0x1257F10`). Normal construction creates 16 input
    keys, hence mask 65535. A route value 255 does not discard later valid
    entries. Bounded Connection/Scenes editors do not reproduce every parent
    save or radio effect.
11. **Original network scan coordinates more than NET SYNC.** Recovery at
    `0x85C6B0`, `0x85C7F8`, `0x120F4E3`, `0xF3237C` identifies `fast 2`, a rolling
    65-second inactivity budget, active-ID cancellation, suppression of
    in-flight group refresh and terminal status/project-save order. The
    sub-second completion quirk needs an independent oracle before adoption.
12. **FONT and whole-unit labels have further prerequisites.** Static DLT
    rendering uses an 82×40 monochrome intermediate and 62×16 final bitmap,
    Windows font metrics, placement/crop/inversion and runtime ANSI codepage
    conversion. A matching font name on another host does not establish
    pixels. Missing/blank unit-key clears differ from per-flavour broadcasts;
    caught versus aborting failures and repeated-key ordering need their own
    lifecycle evidence. No new physical executor is established here.

Fresh firmware/NCC/variant inspection and core eDLT CRC/load inspection also
confirmed existing findings; they did not create new closure claims.

## Keeping this record current

For each accepted batch, replace queued identifiers with the final published
commit, link newly available canonical domain paths, preserve failures/skips,
and identify exactly which source/native/physical boundary advanced. Keep
unapplied patches, uncommitted experiments and private proofs distinguishable.
Update domain-owned evidence through its owner; do not regenerate parity
ledgers merely to make this index look current.

Before publishing documentation or fixtures, check personal paths, endpoints,
hostnames, room/group mappings, identifiers and live-state records. Retain
legitimate synthetic loopback fixtures and public original input provenance.
Exact audit locations, raw runtime coordinates and household observations
belong in private records outside Git and must not be copied into issues.
