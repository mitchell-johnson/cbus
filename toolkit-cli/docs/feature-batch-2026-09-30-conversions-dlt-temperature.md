# Conversion, classic DLT and thermostat batch — 2026-09-30

This report describes the frozen twelve-import feature batch and its subsequent
CBZ input and firmware cleanup review fixes. It extends the earlier
[DALI/SENLL batch report](feature-batch-2026-09-30.md); the earlier report's
acceptance totals remain historical and do not attest to these later source
files. Full Toolkit and full C-Gate behavioral parity remain incomplete.

The delivered scope is bounded by the actual source, committed evidence and
profile-specific workflow contracts. A registered conversion, recovered method
or accepted native database operation does not establish complete GUI,
physical-device or frontend lifecycle equivalence.

## Delivered behavior

| Area | Delivered scope | Contract |
| --- | --- | --- |
| Toolkit conversion tweakers | 108 of 292 registered source/target pairs: eight existing dimmer pairs, seven relay directions and 93 classic-key-to-fresh-Neo directions | [Toolkit tweakers](toolkit-conversion-tweakers.md) |
| Classic DLT indicators | Seven ordered fallback, pressed-mode, duration/level and nightlight controls with initialization and save/reopen normalization | [Indicators](classic-dlt-indicators.md) |
| Classic DLT TEXT dialog | Selected existing-language initialization/finalization, legacy flavour fallback, default handling, UTF-16 prefix and confirmed Unicode input | [TEXT dialog](classic-dlt-language-dialog.md) |
| Classic DLT broadcast | Offline command compilation and outcome assessment for one explicitly supplied label flavour and prepared bitmap | [Broadcast](classic-dlt-broadcast.md) |
| Thermostat settings/templates | Fifteen preference-dependent temperature fields, corrected ControlledZones projection, explicit template allocation context and recovered callback barriers | [Settings](thermostat-settings.md), [templates](thermostat-templates.md) |
| Document Project | KEY1/2/4 bodies, seven additional output bodies, explicit NCC base-only routing and additional source-pinned action/trigger projections | [Project documentation](project-documentation.md), [usage](project-documentation-usage.md) |
| CBZ input | Bounded archive/XML reads and expansion, supported-codec refusal and structured corruption errors in Python; bounded decoded XML in Rust | [Python source](../src/cbus_toolkit/project.py), [Rust source](../../rust/cbus-mqtt/src/cbz.rs) |
| Firmware lifecycle | Separate acquisition, transfer and cleanup receipts, terminal release failures and explicit resume preserving verified image evidence | [Firmware recovery](firmware-update-recovery.md) |
| Executable census | Class-specific original proof that LED OnColor is a scalar property, correcting event-candidate classification | [Property proof](../research/fixtures/toolkit-oncolor-property-proof.json), [RTTI proof](../research/fixtures/toolkit-oncolor-rtti-proof.json) |

## Conversion rules and refusal boundaries

The client-side Toolkit registry contains 292 registrations across thirteen
tweaker classes. The 108 admitted pairs are separate from C-Gate's native
CONVERTUNIT mapping and the typed C-Gate conversion command.

The seven relay directions are RELDN8 to RELDN12, RELDN4, RELDN8B and RELSM8,
and RELDN12, RELDN8B and RELSM8 to RELDN8. Each logic array is repacked from
its own source field. Alignment and PP writes follow the target agent's
constructor order; RELSM8 preserves defaults for attributes absent from its
basic agent, including interlocking/restrike fields. Constructor mutability
also prevents treating Burden as writable merely because an ordinary
before-save hook can change it in a different workflow.

RELDN4 to RELDN8 remains deliberately refused before I/O. The original reverse
tweaker indexes more logic entries than that source actually contains. Neither
target PP truncation nor invented zero padding would reproduce those reads.
The [relay source proof](../research/fixtures/toolkit-reldn-conversion-source-proof.json),
[literal vectors](../research/fixtures/toolkit-reldn-conversion-literal-vectors.json)
and [native receipt](../research/fixtures/reldn-tweaker-native.json) retain the
algorithm, exact strings, refusal and save/reload evidence.

The 93 classic-to-Neo directions admit KEY1/2/4 and KEYIR1/4 source firmware
1.2.67 to fresh target firmware 2.5.00. Source-pinned conversion hooks retain
constructor defaults, learned-state mutability, indicator-function remapping,
four-entry array-prefix replacement and literal string formatting. The five
KEYBC/DINAUX registrations remain refused. Evidence is in the
[conversion source proof](../research/fixtures/toolkit-key-to-neo-conversion-source-proof.json),
[learning-hook proof](../research/fixtures/toolkit-key-conversion-learning-source-proof.json),
[literal vectors](../research/fixtures/toolkit-key-to-neo-conversion-literal-vectors.json)
and [93-direction native acceptance](toolkit-key-to-neo-native-acceptance.md).

The admitted Python API validates and creates a fresh destination. It does not
copy source tag/description/serial metadata, delete or readdress the source,
reproduce retained frontend state or program a physical unit. The other
registered conversion directions retain explicit refusal reasons.

## Classic DLT controls, text and delivery

Indicator operations retain caller order. Page fallback and pressed mode
govern whether duration is enabled; pressed mode governs the raw brightness
and nightlight controls, and a nightlight selection enables first-key
throwaway. Fresh initialization can normalize stored timer values, while a
later explicit save/reopen can normalize an otherwise reachable intermediate
state differently. Canonical plans expose these changes, rederive the source
snapshot and preserve named neighboring PP fields. Component replay uses
synthetic GUI primitives; five admitted identities have owned native PP and
project save/reload evidence. Neither is a complete original Windows form run.

The separate TEXT dialog admits one existing selected language and TEXT
variants. It preserves the legacy flavour0 fallback when exact flavour1 is
absent, uses a twenty-UTF-16-unit prefix and turns explicit empty input into
the literal `<Default>`. Finalization can create, update or delete selected
records while preserving unrelated languages, shadowed legacy records and
metadata. The Unicode warning examines the whole input, including text beyond
the retained prefix. XML-invalid split-surrogate prefixes are refused.
Consumed owner default-display text must be supplied explicitly; a tag name
cannot establish its original address/locale-dependent representation.

Broadcast planning is a different fourteen-byte delivery projection. It
compiles TEXT, ICON or DYNAMIC/FONT with explicitly prepared bitmap bytes;
it does not rasterize a font, look up a project cache or infer image facts.
Empty/default text uses the original literal byte `10`. A DYNAMIC command
precedes the original cache mark and following ICON reference.

Assessment rederives the plan and requires contiguous command indices and
matching hashes. It separates original parser completion and cache marking
from conservative acceptance of supplied responses. The original parser can
treat `bad object` as completion; that is not native acceptance. First-command
uncertainty and a later failure have different cache-mark consequences, so
the report provides a manual disposition without retry/resume commands.
Neither planning nor assessment opens a connection or sends traffic.

Retained evidence includes
[indicator initialization/native cases](../research/fixtures/classic-dlt-indicators-native.json),
[TEXT dialog original cases](../research/fixtures/classic-dlt-language-dialog-original.json),
[TEXT dialog native cases](../research/fixtures/classic-dlt-language-dialog-native.json),
[broadcast instruction replay](../research/fixtures/classic-dlt-broadcast-original.json),
[response-parser cases](../research/fixtures/classic-dlt-broadcast-results-original.json)
and [broadcast native command/receiver cases](../research/fixtures/classic-dlt-broadcast-native.json).
The last fixture covers eleven compiled commands in nine owned loopback
delivery cases plus three no-command cases. It does not establish physical
rendering, device image cache, full discovery or persistence.

Whole-unit key/group selection, network/global language changes, warmed GUI
cache, FONT/ICON project editing, complete enable-transfer-restore save
ordering and full original/physical acceptance remain open.

## Thermostat temperature and allocation context

`--temperature-preference celsius|fahrenheit` is an explicit Toolkit process
preference, independent of the unit's TemperatureUnits PP field. It enables
the fifteen recovered temperature load/save projections. Omitting it keeps
raw values and declares temperature normalization unreproduced.

These projections preserve field-specific signed loads, low-byte casts,
rounding and the two upper guard clamps. They refuse results outside the
selected specification/byte range instead of silently wrapping every field.
Untouched dependent changes and requested values share one recovered form
save; no extra hidden save is added to force a fixed point. ControlledZones
is reconstructed from InstalledZones rather than accepted as an arbitrary
raw subset. Source evidence and independently composed original byte vectors
are retained in the [temperature source receipt](../research/experiments/2026-09-30/thermostat-settings-temperature-static.json)
and [round-trip vectors](../research/fixtures/thermostat-settings-temperature-roundtrip-vectors.json).
[Native acceptance](../research/experiments/2026-09-30/thermostat-settings-temperature-native.json)
covers all four aliases and both preferences with opposite device units,
dependent save effects and unrelated PP/XML preservation.

Template output groups use scalar ApplicationNumber; the generic Application
array is preserved independently. `--group-sort address-ascending` admits
template9 allocation only in an initially empty output application outside
172/203. It declares a bounded original sort context rather than inferring a
saved preference or manager order from XML. Original comparator/insertion/
search replay and native four-alias/group-only-save cases are linked from
[the template contract](thermostat-templates.md). Existing-prefix reuse,
preloaded/unsorted managers, locale-sensitive sorting and ordinary-load side
effects remain separate gaps.

The [quick-zone callback receipt](../research/experiments/2026-09-30/thermostat-quick-zone-callback-static.md)
narrows those gaps with exact notification locks, checkbox feedback
suppression and deferred ComboBox list behavior. It introduces no public
quick-zone action and does not prove complete message-loop, parent-enable,
initialization or PP-save behavior. Full dialog lifecycle and physical
thermostat acceptance remain false.

## Project documentation scope

Document Project now emits recovered KEY1/2/4 timing, macro/micro, group,
preset and expiry bodies. The first matching group block supplies retained
level/timer values; fresh PP construction order does not establish warmed
GUI history. Fifteen DIN output profiles now have channel/logic bodies,
including ANODN4, DIMDS8, DIMPR1/2/4, RELDB1 and RELDC4. Explicit firmware/class
selection is required. The admitted NCC outputs produce base-only bodies;
channel/logic or usage behavior is not invented from their type names.

RELDF1 and SENTEMPB/4 action projections retain distinct selector Address,
unused trigger sentinel, fan-master/digital-temperature and overwritten-error
reference rules. Bounded action, macro and trigger-wrapper comparisons use
synthetic dependency providers. They are not original whole-page, PP-loader
or native missing-application execution. The [outputs receipt](../research/experiments/2026-09-30/project-documentor-outputs-static.json),
[classic-key source receipt](../research/experiments/2026-09-30/project-documentor-classic-key-static.json),
[direct-action comparison](../research/fixtures/project-documentor-direct-actions-original.json)
and [trigger-wrapper research](../research/experiments/2026-09-30/project-documentor-trigger-original.md)
state their exact scopes.

HTML still writes a new local file from one digest-bound snapshot. Unknown
consumed data remains explicitly unrecovered. Full original page bytes/visuals,
registry/locale ordering, live load/scan state, printing, progress/cancel and
physical acceptance remain open.

## Input and cleanup review fixes

Python XML/CBZ inputs and declared total archive expansion are bounded to
128 MiB. Duplicate/encrypted members and compression other than stored/deflate
are refused. Every member read has an explicit size bound; mismatched sizes,
CRC errors and decompression failures become structured project errors before
output mutation. Rust label extraction bounds file bytes, expanded XML and
the decoded UTF-8 size. Review added a preallocation count for lossy UTF-8
replacement expansion, including bare XML, so invalid bytes cannot bypass
the decoded-size bound. [Python adversarial fixtures](../tests/test_project_input_safety.py)
and [Rust file-boundary fixtures](../../rust/cbus-mqtt/tests/cbz_input_safety.rs)
test parser behavior, not full Schneider archive interoperability.

Firmware acquisition failure now retains its cleanup receipt in the aggregate
result and, when available, journal. Transfer and cleanup errors remain
separate; a cleanup failure never replaces a primary transfer/interruption
error. Failed release stops before the next operation. `complete` requires
successful cleanup independently of `images_verified`.

Final readback can verify all images while failed release leaves an
interrupted journal with verified stages. Explicit resume reinspects and
reverifies those stages; matching images need no erase/program, while a
mismatch follows the existing bounded restart rules. A later acquisition or
reverification cleanup failure stops again with evidence retained. The
[release tests](../tests/test_firmware_update_release.py) and
[recovery contract](firmware-update-recovery.md) cover memory/fake-PyUSB
behavior; physical driver, bootloader and firmware acceptance remain open.

Package inspection/loading integrity is also outstanding: the existing loader
reopens the package without enforcing the inspected plan's digest/CRC across
those reads. This cleanup batch does not fix that separate boundary; the
immutable-snapshot/pre-USB correction is the next firmware integrity work.

## Validation and completeness

The focused integrated source run completed 809 tests and 1,339 subtests.
Seven original-instruction JIT nodes executed despite the intended
deselections because absolute deselection names did not match pytest's
collected node IDs. That execution is explicitly excluded from accepted
network-denied original-replay evidence. The run provides 802 ordinary
passing cases; the 1,339-subtest figure describes the complete executed run,
not a separately recounted ordinary-only selection. No full suite ran.

The final installed wheel accepted 955 unique test cases, with zero skips and
exactly seven replay nodes excluded by a collection assertion before execution.
Its initial run passed 951 tests and 2,191 subtests, with four failures. Three
guards needed the exact tracked AI-reference and CI files in the isolated
artifact copy; their targeted rerun passed three tests and three subtests.
The fourth, an owned DLT receiver startup, passed its unchanged test in 6.52
seconds under the original 20-second deadline. The wheel, runtime source and
test code remained identical across those rechecks. The initial failed run is
retained; this is not a claim that the entire wheel run was repeated cleanly.

The consolidated [batch acceptance receipt](imported-toolkit-features-acceptance-summary.json)
records those scopes and corrections. Earlier worker source/wheel/native
receipts remain scoped to their recorded hashes and cases. No further JIT
replay is included in this batch; the source selection error remains history.

The CBZ review passed eleven Rust unit and six public file tests. Workspace
formatting, strict Clippy checks and the workspace release build passed.
The [root validation receipt](imported-toolkit-root-validation.json) also
records the 55-test firmware scope, 97 generated-register guards and fresh
SESSION_ID/tagged/XML differentials on both Rust servers. These focused checks
do not imply a full workspace test run. No physical acceptance is added.

The executable classification correction removes 53 proven scalar OnColor
records from event candidates: TLEDStatusIndicator and TFlashLEDStatusIndicator
have a TColor getter/setter, while unknown classes keep their event-candidate
classification. The corrected provisional register contains 22,103 source
records, 1,839 event bindings, 487 obligations and 28 workflow entries. The
correction improves the denominator's provenance; it does not complete a
workflow or make a functional percentage available.

Consult the [implementation ledger](implementation-status.md) and
[functional parity register](parity-register.md) for current gaps. Full
Toolkit/C-Gate compatibility and the broad original GUI/physical gates remain
false. Generated final acceptance receipts must bind the exact final source
and wheel rather than rewriting older receipt fingerprints.
