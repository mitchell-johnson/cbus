# Toolkit client-side conversion tweakers

Toolkit 1.18 does not use C-Gate `CONVERTUNIT` when it converts a unit. It
creates the replacement unit and copies every same-named agent attribute from
the source. It then applies the tweaker registered for the (source type,
target type) pair and calls the target agent's own conversion hook. Finally,
it issues PP SET only for attributes that are still writable. A failed PP SET
is caught and ignored. This is separate from the native engine described in
[conversion.md](conversion.md).

## Public preview and guarded apply

`cgate conversion tweak` exposes all **288 currently admitted pairs** through
one operator workflow: eight DIMDN/DIMDU4, seven RELDN, 93 classic key to fresh
Neo, five coupler/auxiliary to fresh Neo, ten classic InputUnit pairs and 120
source-bound conversions into fresh DLT targets. The registry and
firmware/schema boundaries below remain the admission authority.
Unsupported pairs fail before connecting; the frontend does not widen them.

Preview an existing source and a fresh replacement at an unused address:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 conversion tweak //TEST/254/p/20 \
  --source-type DIMDN8 --target-type DIMDU4 \
  --source-spec DIMDN8.xml --target-spec DIMDU4.xml --spec-dir /private/specifications \
  --target-address 40 --firmware 2.7.00 --catalog-number L5504D2U \
  --tag-name Replacement
```

The source path must use canonical decimal Network and Unit addresses in
`0..255`. The target address must differ from the source. The operator supplies
the exact source/target specification files, target firmware and catalogue
number. `CBUS_UNITSPEC_DIR` may supply the directory. Includes are captured as
immutable, bounded private snapshots; their actual XML hashes enter the plan.
Firmware and catalogue must be single command tokens. TagName may contain
spaces and Unicode; metadata must be trimmed nonempty XML text without controls
or the SAFE `#` delimiter. The default TagName is `Tweaked<address>`.

Preview reads the complete selected project and requires **every Network to be
closed and idle**, including unrelated Networks. It loads the source through
an offline `/db//...` PP session and uses a temporary `PP NEW` session to read
the target's defaults. These sessions lock, start, end and unlock; they do not
create or save a database Unit. Preview verifies that the stored project XML
has stayed unchanged. It returns `plan` and `plan_sha256`, binding the endpoint,
whole project, specification snapshots, source PP, target defaults, original
ordered assignments and their expected native schema effects.

Review that JSON, then repeat the same command with these additional flags:

```sh
  --apply --exclusive-project --expect-plan-sha256 <reviewed-plan-sha256>
```

Apply recomputes the plan and requires the exact reviewed digest. It rechecks
the specification bytes, every Network's closed/idle state and the project
snapshot immediately before ADD. `--exclusive-project` is an assertion that
the operator controls the whole project; it is not a server transaction lock.
The frontend refuses occupied destination addresses, including decimal aliases
such as `040` and `+40`, before ADD. Do not let another client edit the project
during this workflow.

One `DBADDSAFE` creates the replacement. Its canonical UUID must be absent from
every identity present in the baseline XML, including Project OID when emitted,
and resolve through the exact addressed Unit XML before initialization. Legacy
numeric project export can omit Project OID; this is not a separate proof of
freshness against the service's opaque internal identity index. Narrow metadata writes set
UnitType, UnitName, firmware, catalogue and the requested TagName without
re-admitting unrelated raw or opaque XML. PP is reset to native defaults,
checked against the reviewed baseline, then receives the ordered assignments.
The frontend submits the declared schema effect of each original assignment:
overlong numeric arrays are truncated, partial arrays retain their target tail,
and sixbit text is normalized. Both the original hook string and submitted value
are reported. This gives the same intended native result on modeled backends
whose sparse PP store otherwise retains the literal overlong string.

One `PP SAVE_TO_SOURCE` persists the target PP, followed by a fresh PP session
and full project readback. Acceptance requires the planned values and destination
identity to match, with source and unrelated data preserved within the structural
comparison bound. Attributes, comments, processing instructions, namespaces and
non-whitespace text are checked. The shared comparison omits whitespace-only text
around element children, including significant spaces in opaque mixed markup or
under `xml:space="preserve"`; full XML text fidelity remains open. Output records
this boundary in `xml_comparison`. Like the original tweaker API, copied `UnitAddress` PP retains
the source address while the new database Unit stays at the requested address.

Complete parameter assignment refusals remain recorded, following the original
setter's declared-failure behavior. The frontend saves and checks the retained
default for a refused parameter but exits **1**, with `accepted=false` and
`planned_assignments_complete=false`. `verified_expected_parameters` describes
that observed fallback separately; it does not alter the reviewed plan or digest.
A server failure or lost reply stops the workflow. Evidence retains attempted
and confirmed writes, phase, issued OID when bound and possible-send uncertainty.
Temporary PP SET, reset and new-session sends have separate `staging_writes`
and `staging_uncertain` evidence; a lost staging reply also stops before save.
Uncertain staging from a completed assignment refusal clears only after the
fresh target PP readback verifies its precise retained fallback.
The command never reconnects, replays, rolls back or deletes a scaffold after a
possible ADD or save. Inspect the database before planning another attempt.

For an authenticated service, add `--auth-token-file <private-file>`. The token
is used for LOGIN before selection and excluded from plan/operator evidence.
Each successful CLI connection selects the requested project once; a refused
LOGIN stops before selection.

This workflow creates a database replacement at another address. It does not
copy source tag/description/serial metadata, delete or readdress the source,
save/reopen the project, or program a physical unit. Original Toolkit GUI
replacement, retained/editor model history, other profiles and final controller
handoff remain separate acceptance. The existing native receipts below apply to
the earlier API checks; they do not establish new native acceptance of this
public frontend. Issues #73 and #74 remain outside this work.

Focused public verification uses generated synthetic profiles and owned
`cgate-mock`/`cmqttd`, with literal wire capture, controlled lost receipts and
startup-only fake PCI. It is runnable from source or an installed wheel:

```sh
CBUS_CGATE_MOCK_BIN=/path/to/cgate-mock CBUS_CMQTTD_BIN=/path/to/cmqttd \
  PYTHONPATH=src:tests .venv/bin/python -m pytest -q \
  tests/test_toolkit_tweaker_workflow.py tests/test_cgate_toolkit_tweaker_interop.py
```

For wheel acceptance, stage the tests and their committed helper modules while
importing `cbus_toolkit` from the installed package. Do not add the checkout's
`src` directory to that run. These owned checks add no original/vendor/VM or
physical-house execution credit.

## Registry receipt

`research/fixtures/toolkit-conversion-tweaker-registry.json` is the
denominator for Toolkit-side conversions. It lists all 292 `RegisterTweaker`
registrations: source type, target type, tweaker class and call site. It
also records each of the 13 classes' recovered rules and the decision for
every pair. The facts come from static inspection of the pinned Toolkit EXE
and MAP, whose hashes are in the receipt. No original code was executed, and
the receipt contains no instruction bytes or specification data.
`research/toolkit_conversion_tweaker_registry.py --validate` checks the
receipt's counts, uniqueness, class coverage and decisions.

| Class | Registrations | Recovered rule | Decision |
| --- | --- | --- | --- |
| TTweakerDIMDN_TO_DIMDU4 | 4 | InterLockingChannel=4; PowerUpDelay takes the aligned MaxDimmingLevel; MaxDimmingLevel=`0 0 0 0` | admitted |
| TTweakerDIMDU4_TO_DIMDN | 4 | InterLockingChannel=0; MaxDimmingLevel takes the aligned PowerUpDelay; PowerUpDelay=`0 0 0 0` | admitted |
| TTweakerInputUnit | 11 | 13 Neo/IR attributes stay at target defaults; inherited Learn and target brightness flags | ten non-sensor pairs at 1.2.67 and older SENPILL self-conversion at 1.6.00 admitted |
| TTweakerNeoToKey | 13 | 13 Neo/IR attributes stay at target defaults | 13 admitted at 2.5.00→1.2.67 with source-backed secondary-application identity rewrite |
| TTweakerKeyToNeo | 98 | as above, plus five attributes, IndicatorFunction 1→2/3→1 and the inherited Learn/CoreKey/NeoPro hooks; CouplerPro finally suppresses brightness | 93 classic-source pairs admitted for fresh 1.2.67→2.5.00; five coupler/auxiliary pairs admitted for fresh 1.2.67→2.2.00 |
| TTweakerDLT, TTweakerKeyToDLT | 117, 15 | eight (or 13) attributes stay at defaults; one-element LabelFlavourLSB/MSB=0; KeyToDLT remaps IndicatorFunction; DLT own hook uses the loaded Neo source model without inherited conversion hooks | 129 pairs admitted into fresh DLT 2.1.00, including verified KEYBIR catalogue aliases; three factory-less KEYM6 directions remain refused |
| TTweakerSENPIR, TTweakerSENLL | 16, 2 | renames between EnableGroupAddress/Logic and PIR/PEC enabler groups | 18 older-profile directions admitted; later sensor profiles require separate admission |
| TTweakerPC_DAL2, TTweakerPC_DAL2B | 2, 2 | swaps the two Application values | all four source-backed directions admitted at 4.5.00; native GUI/cold acceptance remains open |
| TTweakerRELDN8_TO_X, TTweakerRELDNX_TO_8 | 4, 4 | source-pinned GroupAddress and LogicGA13–16 repacking | seven pairs admitted; RELDN4 → RELDN8 refused because its four-element source logic cannot satisfy the original eight-element reads |

The current registry admits 288/292 directions. Read [remaining conversions](toolkit-remaining-conversions.md) for the 45 additions after the historical 243 checkpoint:13 Neo-to-classic, 4 DALI, 19 older sensors and 9 KEYBIR-to-DLT aliases. Constructor and agent hooks, lexical writes and storage effects are separate contracts. Static/source and owned-service checks do not extend earlier native API receipts into original GUI, cold native or physical acceptance. Three KEYM6 targets lack factories and RELDN4→RELDN8 has undefined short-array reads; these four remain refused.

The classic-to-Neo exception below has an independently recovered fresh-target
model lifecycle. It does not generalize to retained/editor targets or to
Neo-to-classic conversion with secondary-application group identity.

## Admitted DIMDN/DIMDU4 conversion

`cbus_toolkit.toolkit_conversion_tweakers` supports the eight pairs of DIMDN8,
DIMDN8F, DIMDN4 or DIMDN4F with DIMDU4, in both directions:

```python
from cbus_toolkit.toolkit_conversion_tweakers import ToolkitTweakerConversion

converter = ToolkitTweakerConversion(client, "DIMDN8", source_spec, "DIMDU4", target_spec)
result = converter.apply("//TEST/254/p/20", 40, target_firmware="2.7.00", target_catalog="L5504D2U")
```

The source unit is only read. The replacement is created at the given unused
database address with native defaults. The model then applies these steps:

1. Walk the target agent's constructor-order attributes. Copy each attribute
   that the source agent also has.
2. Leave `FirmwareVersion`, `SerialNo`, `State`, `UnitType` and `Burden` unwritten,
   because they start immutable. An empty source value also makes its
   attribute immutable.
3. Apply the tweaker's assignments.
4. PP SET the remaining writable attributes that exist in the target
   specification, in attribute order.

The unit is saved with PP `SAVE_TO_SOURCE` and checked in a fresh PP session
against expectations computed from the native target defaults.

Like Toolkit before it readdresses, the copied `UnitAddress` PP is the
source address. The result reports `parameter_address_matches_database`.
This module does not copy tag, description or serial metadata, delete the
source, readdress, save the project file or contact a physical unit. Unsupported
registered pairs, and every pair without a tweaker, raise
`TweakerRefused` with the receipt reason before any C-Gate I/O.

Complete native PP SET rejection replies are recorded and ignored, matching
the original parameter setter. A transport failure stops immediately without
further PP SET or save attempts; an uncertain write is never retried.

Native C-Gate 3.4.0.2001 PP SET truncates an over-long array. A short array
replaces only its leading elements, and sixbit text is upper-cased and padded.
The model relies on this behaviour, and the native test checks it directly.

## Verification

```sh
PYTHONPATH=src:tests .venv/bin/python -m pytest tests/test_toolkit_conversion_tweakers.py -q
CBUS_CGATE_JAVA=... CBUS_LOCAL_CGATE_VENDOR=... CBUS_UNITSPEC_DIR=... \
  PYTHONPATH=src:tests:. .venv/bin/python -m pytest tests/test_toolkit_conversion_tweakers.py -q
```

Owned native C-Gate acceptance ran all eight DIMDN/DIMDU4 pairs on synthetic
units with generated non-default values. Each PP list matched the model with
no PP SET failures, and spot checks confirmed the recovered rules
independently. The source stayed unchanged, and the targets were identical
after project save, close and load. This is database-level evidence only. It
does not execute the original Toolkit GUI and does not program hardware.

## RELDN relay conversion

The same API supports RELDN8 → RELDN12/RELDN4/RELDN8B/RELSM8 and
RELDN12/RELDN8B/RELSM8 → RELDN8. Both original routines have been recovered,
including the eighth registered direction RELDN4 → RELDN8, but that direction
is refused before I/O: native RELDN4 supplies four logic elements while the
original routine unconditionally reads eight. The original string load and
alignment path does not pad them. Fabricating four zeroes would conceal this
undefined original behavior.

For each field's own source array `s`, the zero-based rules are:

| Direction | GroupAddress | Each LogicGA13–16Associations |
| --- | --- | --- |
| RELDN8 → X | `s[1:5] + s[7:11] + [255]*4 + s[12:16]` | `s[1:5] + s[7:11] + [0]*4` |
| X → RELDN8 | `[255] + s[0:4] + [255]*2 + s[4:8] + [255] + s[12:16]` | `[0] + s[0:4] + [0]*2 + s[4:8] + [0]` |

The tweaker assigns GroupAddress then logic 13, 14, 15, 16, rendering decimal
elements with single spaces and no trailing space. PP SET still uses agent
constructor order, in which the logic arrays precede GroupAddress. RELDN4
targets retain the native PP SET truncation to four logic elements; the plan
records the original twelve-element string before native normalization.

RELDN8 uses the marshalling-box agent and RELDN12/4/8B use the full DIN agent.
RELSM8 uses the basic bus-powered agent and has no `InterLockingChannel`,
`RestrikeChannel` or `RestrikeDelay` attributes. Converting from RELSM8 retains
those target defaults. These agents all inherit the empty base
`BeforeUnitConversionSave` hook. The basic constructor makes `Burden`
immutable; this also corrects the inherited DIMDN/DIMDU4 flag.

Relay construction checks the supplied source and target PP shapes before any
I/O, including the explicit RELDN8B → RELDN8 specification alias. Planning
requires complete GroupAddress (16 byte values) and logic (12 Boolean values)
strings and rejects malformed, partial or oversized input. Apply validates the
source values before creating a replacement. These are deliberate safe bounds;
the original unchecked reads and malformed-token fallback are not reproduced.

Literal independent tests cover both transformations, boundaries, constructor
ordering and preserved values. The separate owned native acceptance helper
exercises seven directions, raw PP, source/default preservation, no-op plan
repetition, and project save/close/reload. It also verifies the four-element
RELDN4 source and its refusal before I/O. Static derived vectors are not native
execution evidence. Original Toolkit GUI and physical acceptance remain open.

Evidence and reproduction:

- [Original constructor and array review](toolkit-reldn-conversion-source-review.md)
- [Owned native receipt](../research/fixtures/reldn-tweaker-native.json): seven conversions,
  one refusal, 15 units reloaded, no PP SET rejection and confirmed process cleanup.
- Portable tests: `.venv/bin/python -m pytest -q tests/test_toolkit_conversion_tweakers.py tests/test_toolkit_conversion_reldn.py`
- Native tests: set `CBUS_CGATE_JAVA`, `CBUS_LOCAL_CGATE_VENDOR` and
  `CBUS_UNITSPEC_DIR`, then run `.venv/bin/python -m pytest -q tests/test_reldn_tweaker_native.py`.

The native helper's `NOOP` check sends the C-Gate `NOOP` command and confirms
the target is unchanged. Repeated planning is also unchanged. Applying a
conversion again creates a different replacement; this API does not claim
idempotent replacement or register any self-conversion pair.

## Classic key to fresh Neo conversion

The existing API now admits 93 registered `TTweakerKeyToNeo` directions from
KEY1, KEY2, KEY4, KEYIR1 and KEYIR4. The initial profile requires an actual
source firmware of `1.2.67`, target firmware `2.5.00` and a freshly created
target. The five KEYBC/DINAUX registrations use the separate coupler profile
below. Historical Neo firmware, Neo-to-classic conversion and an existing
edited target are outside this profile.

```python
plan = plan_writes("KEY4", "KEYB4", source_values, set(target_spec.parameters),
                   target_firmware="2.5.00")
converter = ToolkitTweakerConversion(client, "KEY4", source_spec, "KEYB4", target_spec)
result = converter.apply("//TEST/254/p/20", 40,
                         target_firmware="2.5.00", target_catalog="5084NL")
```

Use the target's actual catalogue number. Planning describes the exact fresh
profile in `model_context`; apply checks the database source firmware before
PP loading or target creation. Constructor checks reject mismatched types,
historical `_A` specifications and unsupported array shapes before I/O.

The 35-attribute classic source and 63-attribute NeoPro target preserve original
constructor order. The inherited `InfraRedBank` target attribute is renamed
`IRBank`; it therefore has no same-name classic source and retains its target
default. The tweaker suppresses its original 18 named fields and maps each of
the four IndicatorFunction entries `1→2`, `3→1`, retaining other values. Its
output uses decimal tokens with one trailing space.

The inherited hook chain then runs in original order:

1. **Learn:** the target firmware enables LearnAnyApp and LearnMode. The fresh
   model's current/original learned flags are both false, so LearnedFlag is
   immutable. This is a model initialization fact, distinct from the native
   PP LearnedFlag default of 1.
2. **CoreKey:** a classic source has no second application capability, so the
   dual-to-single rewrite is skipped. GroupAddress becomes source entries
   0–3, four 255 entries, then source entry 4. The output is uppercase,
   two-digit hexadecimal with `0x` prefixes, single spaces and no trailing
   space. IndicatorBrightness becomes writable even though its constructor
   flag was false.
3. **NeoPro:** the non-NeoPro source causes the original 13 IR, disable,
   corridor and application-join fields to retain target defaults.

PP SET follows constructor order. Four-entry key, command and timer arrays
replace only the corresponding target prefix; the remaining target entries
retain native defaults. Unsupported or malformed transformation arrays fail
before creating a replacement.

The [source review](toolkit-key-to-neo-conversion-source-review.md),
[fresh-model lifecycle proof](toolkit-key-conversion-learning-source-review.md)
and [native acceptance](toolkit-key-to-neo-native-acceptance.md) keep original
static evidence separate from the executed C-Gate checks. All 93 directions
passed native acceptance, including raw PP and 98 source/target units after
save/close/reload. Original GUI replacement, retained target history, source
deletion, final readdressing and hardware programming remain separate.

## Coupler and auxiliary input to fresh Neo conversion

The five remaining `TTweakerKeyToNeo` registrations use a distinct profile:
KEYBC2/KEYBC4 → BCN2B/BCN4B, and DINAUX4 → BCI4A. Source firmware must be
`1.2.67` and target firmware must be `2.2.00`. BCI4A uses the catalogue's
explicit `BCN4B.xml` specification alias. Other aliases and firmware are
refused before replacement creation.

```python
converter = ToolkitTweakerConversion(client, "DINAUX4", source_spec, "BCI4A", target_spec)
result = converter.apply("//TEST/254/p/20", 40,
                         target_firmware="2.2.00", target_catalog="L5504AUX")
```

The original source agent still has 35 attributes, including brightness and
IR fields absent from these source PP schemas. The target CouplerPro agent
inherits 62 CoreNeoPro attributes directly, then adds BistableSwitchBlock and
GroupAssertOnPowerup. It does not construct NightlightColour. RetardationIndex
exists only in target PP and retains its native baseline.

The inherited group and indicator transformations apply in their original
order. The coupler model's learning-property predicate returns true; fresh
learned history remains false/false. Its final conversion hook then makes
IndicatorBrightness immutable, overriding the inherited CoreKey decision.
Native acceptance verifies retained brightness `0xff`, indicator tail
`3 3 3 3`, the 16-entry light-level prefix within the 28-entry target array,
source preservation and all eight source/target units after save/close/load.

The [coupler source review](toolkit-key-to-coupler-conversion-source-review.md)
and [five-pair native acceptance](toolkit-coupler-to-neo-native-acceptance.md)
record the independent source and runtime evidence. Both KeyToNeo profiles
together admit all 98 registrations within their exact firmware and fresh
model boundaries. Original GUI and physical acceptance remain open.

## Classic InputUnit conversion

Ten `TTweakerInputUnit` registrations now admit source and fresh target
firmware `1.2.67`: the six cross-pairs among KEY1, KEY2 and KEY4, KEYBC2 ↔
KEYBC4, and BCNC4A ↔ BCNC4B. The separate SENPILL self-conversion remains
refused. BCNC4B uses the explicit `BCNC4A.xml` catalogue alias in both roles.

```python
converter = ToolkitTweakerConversion(client, "KEY1", source_spec, "KEY4", target_spec)
result = converter.apply("//TEST/254/p/20", 40,
                         target_firmware="1.2.67", target_catalog="5034N")
```

All seven selected models have the same 35-attribute constructor inventory.
The InputUnit tweaker suppresses 13 named attributes; only InfraRedBank exists
in these targets. The inherited Learn hook enables LearnMode and LearnAnyApp
at this revision, and disables LearnedFlag for fresh false/false model history.
CoreKey consults the target brightness predicate: true for KEY1/2/4, false
for KEYBC2/4 and BCNC4A/B. GAVBroadcastFlag remains initially immutable.

Every selected model is non-Neo and has HasApplication2=false. No group
reshape, secondary-application scrub or indicator remap runs. Pure planning
therefore preserves aligned GroupAddress, IndicatorFunction and Application
strings verbatim, including formatting; it does not parse or pad them.
Runtime construction still requires the exact eight-group/four-indicator
specification and firmware. Empty aligned values follow the original writable
flag rules, and PP staging uses the existing native normalization contract.

BCNC's ordinary save hook applies microfunction and learning defaults, but
conversion bypasses that hook. Those defaults are not injected. PatchEnable
is present only in native PP, absent from the agent inventory, and retains
the target baseline even when the source PP contains a different value.

The [InputUnit source review](toolkit-input-unit-conversion-source-review.md)
and [native acceptance](toolkit-input-unit-native-acceptance.md) separate
original instruction evidence from ten executed database conversions and
17 units verified after save/close/reload. Original CPU/GUI execution,
physical programming, other firmware and retained target models remain
outside this acceptance.
