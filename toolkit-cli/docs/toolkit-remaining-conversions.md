# Neo Classic, PCI/DALI and older sensor conversions

The public `cgate conversion tweak` and guarded replacement workflow now admit
45 additional registered Toolkit directions. This brings the conversion
registry to **288 of 292 directions** (98.63%) within its declared fresh-model
profiles. This denominator measures registered conversion directions; it does
not measure total Toolkit parity, every firmware revision, native GUI behavior
or physical programming acceptance.

## Profiles

| Family | Added directions | Exact source and fresh target profiles |
| --- | ---: | --- |
| Neo Classic to classic key | 13 | KEYC1/C2/C4/CIR1/CIR4 at 2.5.00 to registered KEY1/2/4/IR1/IR4 targets at 1.2.67 |
| PCI/DALI application swaps | 4 | PC_DAL2, PC_DAL2B and PC_DAL2C at 4.5.00; only registered pairs |
| Older PIR | 16 | Every cross/self pair among SENPIRSS at 1.2.67 and SENPIROA/IA/IB at 1.2.68 |
| Older light level and multisensor | 3 | SENLL 1.2.67 to SENLL 1.2.67 or SENPILL 1.6.00; SENPILL 1.6.00 self-conversion |
| KEYBIR to DLT | 9 | KEYBIR2/4/6 at 2.5.00 to the three registered fresh DLT 2.1.00 targets |

Literal vendor catalogue mappings establish PC_DAL2C as `PC_DAL2B.xml`, all
four older PIR identities as `SENPIRSS.xml`, and KEYBIR2/4/6 as
`KEYB2/4/6.xml`. The older SENPILL profile explicitly requires
`SENPILL_1.xml`, declared type SENPILL. A separate OEM catalogue alternative
does not widen this admission. Filename, declared type, selected firmware and
the relevant parameter shapes are checked before connecting.

## Operator workflow

Supply the private specifications and a catalogue number that matches the
installed catalogue. For example, preview a Neo Classic conversion on a closed
test project:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 conversion tweak //TEST/254/p/20 \
  --source-type KEYC2 --target-type KEY2 \
  --source-spec KEYC2.xml --target-spec KEY2.xml --spec-dir /private/specifications \
  --target-address 40 --firmware 1.2.67 --catalog-number <matching-catalogue-number> \
  --tag-name Replacement
```

Review the returned ordered assignments, preserved defaults and
`plan_sha256`, then repeat the same command with
`--apply --exclusive-project --expect-plan-sha256 <reviewed-digest>`.
The [conversion workflow guide](toolkit-conversion-tweakers.md) describes the
closed/idle whole-project checks, temporary PP sessions, fresh OID validation,
save/readback, failure handling and replacement lifecycle. These profiles use
that workflow without weakening its guards. Database conversion does not
program the physical unit.

## Recovered behavior

Neo Classic to classic key first applies the inherited InputUnit immutable
fields and fresh Learn flags. CoreKey removes each of the first eight source
groups whose application object equals the concrete secondary application.
Equal primary and secondary identities therefore remove all eight block
groups, even when the secondary mask is zero. Area slot 8 is outside this pass.
The result uses source slots 0–3, Area slot 8 and three 255 values, rendered as
uppercase two-digit hexadecimal tokens. The primary application remains and
the secondary becomes 255 when concrete. IndicatorFunction is copied without
an inverse remapping; target brightness is writable. The profile requires a
concrete primary application and complete two-application, nine-group and
one-mask inputs.

Both PCI/DALI tweaker classes swap the two Application elements, rendering
decimal `second first` without a trailing space. Both agent classes inherit
the empty conversion hook. Burden remains immutable; fields present only on
the newer DALI agent retain fresh target defaults.

Older PIR uses the CoreKey constructor's 34 attributes plus
EnableGroupAddress and EnableGroupLogic. Its IndicatorFunction is one two-bit
element. Brightness is disabled; EEPROMLevelStore, InfraRedBank, LightIndex,
LightLevel, LightLevelStore1 and LightLevelStore2 retain target defaults.
LRCommand, BlockAllocation and indicator assignment fields remain copied.
These older source models do not enter the ST7 polarity or disable-PIR branch.

Older SENLL runs the Learn conversion hook. SENLL to SENPILL uses the
EnableGroupAddress → PECEnablerGroup rename only when the destination's
same-named source field is absent. A same-named empty source field clears
mutability; an empty renamed field does not. Its absent GroupAddress leaves
the fresh agent string empty, and the original default-element accessor
produces nine 255 values; the target schema stores eight. The 87-attribute
multisensor constructor re-enables DisableIR and disables brightness. At the
pinned 1.6.00 firmware its four join groups become 255 because join mode
requires at least 2.0.0. ST7 lux translation is not reached; fresh target lux
defaults remain for SENLL sources and existing values survive self-conversion.

The nine KEYBIR directions use the existing
[source-bound DLT hooks](toolkit-dlt-conversions.md) with literal catalogue
aliases. DLT admission is now 129 directions from 35 modern source types plus
its classic/DLT sources.

## Evidence and remaining directions

The sanitized [source proof](../research/fixtures/toolkit-remaining-conversions-source-proof.json)
contains the pinned EXE/MAP/catalogue hashes, 22 literal aliases, 22 selected
factory profiles, original method interval hashes and constructor facts.
Inspection reads original bytes and private XML statically; it does not load
or execute original instructions. Vendor specifications, original instruction
bytes and site project data are excluded from Git.

Thirteen independent [literal vector cases](../../rust/testdata/vectors/toolkit_conversion_remaining.json)
exercise application identity, secondary removal, Area preservation, both DALI
swaps, sensor immutable/default fields, rename behavior and multisensor join
resets. The pure tests generate complete synthetic constructor/specification
profiles, validate all 36 non-DLT additions in creation and replacement plans,
and reject firmware, schema and malformed source mismatches. The existing DLT
tests cover the nine alias admissions. Run the focused suite:

```sh
cd toolkit-cli
PYTHONPATH=src:tests .venv/bin/python -m pytest -q \
  tests/test_toolkit_conversion_remaining.py tests/test_toolkit_conversion_dlt.py \
  tests/test_toolkit_conversion_tweakers.py tests/test_toolkit_tweaker_workflow.py \
  tests/test_toolkit_tweaker_lifecycle.py
```

The batch passed 107 parent tests and four subtests with one native acceptance
test skipped because vendor acceptance was not configured. Owned backend
integration evidence is recorded separately. These tests do not establish
original Toolkit GUI, retained editor history or hardware acceptance.

Four registered directions remain explicitly refused:

* KEYM6 → KEYDL4, KEYML5 and KEYBL5: no original unit-factory registration or
  concrete factory model exists for KEYM6. A renamed or invented factory would
  not establish compatibility.
* RELDN4 → RELDN8: its literal specification supplies four Boolean elements
  for each LogicGA13–16 array, while the original reverse tweaker reads eight
  directly without padding. The existing source proof and fresh byte/spec
  recheck retain this undefined-read refusal. Supplying fabricated zeros would
  replace original behavior with an unproved conversion rule.

Other sensor firmware, ST7 conversions, retained model histories and native
acceptance remain separate work even where a registered direction has this
fresh-model profile.
