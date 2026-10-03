# Neo and NeoPro report class profiles

`cbus-toolkit cgate database-document` reconstructs the Neo and NeoPro device
report families from explicit native project snapshots. The profile annex covers
all 43 registered report unit types and their 59 exact unit-factory partitions.
This establishes a source-backed software projection of freshly loaded models;
it does not establish every stored state, original generated HTML, host GUI,
print output, firmware behavior or physical acceptance.

The existing Classic → Neo → NeoPro body and usage chain remains shared. Each
profile has eight input-key objects, eight blocks and eight scene slots. Physical
key counts come from the exact registered class's virtual method, including the
four-position KEYEx variants.

| Types | Physical positions | Factory firmware partitions | Additional key labels |
| --- | --- | --- | --- |
| KEYA1, KEYAV2, KEYA3, KEYAV4, KEYA6, KEYA8 | 1, 2, 3, 4, 6, 8 | Neo 1.3.01–1.5.02; NeoPro 1.5.03–2.9.99 | Virtual Key |
| KEYB2, KEYB4, KEYB6 | 2, 4, 6 | Same two partitions | Virtual Key |
| KEYH1, KEYH2, KEYH3, KEYH4 | 1, 2, 3, 4 | Same two partitions | Virtual Key |
| KEYM2, KEYM4, KEYM8 | 2, 4, 8 | Same two partitions | IR Key |
| KEYE1, KEYE2, KEYE3, KEYE4 | 4 each | NeoPro 0–9 | Virtual Key |
| KEYEIR1, KEYEIR2, KEYEIR3, KEYEIR4 | 4 each | NeoPro 0–9 | IR Key |
| KEYBIR2, KEYBIR4, KEYBIR6 | 2, 4, 6 | NeoPro 0–9 | IR Key |
| KEYDV1, KEYDV2, KEYDV3, KEYDV4 | 1, 2, 3, 4 | NeoPro 1.8.00–2.9.99 | IR Key |
| KEYP2, KEYP4, KEYP6 | 2, 4, 6 | NeoPro 0–9 | Virtual Key |
| KEYV1, KEYV2, KEYV3 | 1, 2, 3 | NeoPro 1.7.00–2.9.99 | Virtual Key |
| BCI4A, BCN2B, BCN4B, KEYV1SP, KEYV2SP, KEYV3SP | 4, 2, 4, 1, 2, 3 | NeoPro 0–9 | Virtual Key; Bistable column |

Firmware identity retains the established `major.minor.two-digit-release`
grammar. The factory's `0` and `9` bounds mean `0.0.00` through `9.0.00` in this
profile. Missing, decorated and out-of-range firmware identities remain partial.
The new class table expands the former five-type direct admission; historical
fixtures and source receipts remain unchanged.

For all eight KEYEx types, the source chooses IR capability by the seven-character
type-string length. Their default masks are 1, 3, 7 and 15 for suffixes 1–4.
The loader replaces a raw mask without bit zero with that exact type default,
then takes the low four bits. Disconnected physical positions print
`Unconnected Key`; later positions retain the IR or virtual-key label.

The six coupler classes expose the original Bistable interface. The report reads
`BistableSwitchBlock` by physical-key ordinal, prints `Yes` or `No` for those
positions and `&nbsp;` for later keys. The loader creates the physical coupler
collection and attaches each member to the input key with the same ordinal.
`GroupAssertOnPowerup` does not contribute a report cell. Couplers inherit Neo's
Other dependency method even though their block model is NeoPro: Area Group and
Indicator Brightness Group are reported, without invented Key Disable,
Corridor Link or Control App dependencies.

Core NeoPro join capability requires firmware at least 1.6.0 and at most four
physical keys. KEYEx and coupler classes override it with false. Active joins
remain refused by this reconstruction; capability does not imply a recovered
join-state loader or report path.

The shared body preserves source lookups for mixed applications, timer template
changes, presets, canonical scenes and action selectors. A Timer template sets
only its zero primary-block timer to 300 seconds. The scene appendix keeps the
original ramp-index quirk: the trigger selector comes from the matching key, but
the displayed appendix ramp comes from the key indexed by the scene ordinal.
Action-selector Address and Value remain separate inputs to dependency queries.

The annex also pins each exact class constructor and its inherited constructor
call, including KEYEx KeyMask creation and the coupler collection refresh.

Every consumed PP field and displayed reference must be explicit. Scene storage
must have exactly 80 table bytes and eight pointers in the existing canonical
fixed or compact layout. Enabled Scene keys require an unshared linear primary
unused-group block. Scene Modify, active joins, relocation/swap histories,
noncanonical scenes and previously retained in-memory key state remain partial.
Derived documentors supplying their own separately proven `NeoProfile` retain
that path; this catalogue does not change their factory admission.

`research/project_documentor_neo_profiles_static.py` reads the pinned EXE/MAP
without executing original instructions. Its annex pins 160 native method spans, the Bistable interface adjustor, registration spans and
731 explicit checks. The separate literal fixture contains a complete invented
61-unit Installation: one unit per factory partition and two stored-state cases.
Expected bodies and usage strings were authored from source markup and facts,
without invoking the report producer.

Focused verification from `toolkit-cli/`:

```sh
PYTHONPATH=src:research python -m pytest -q \
  tests/test_project_documentation_neo_profiles.py \
  tests/test_project_documentation_neo.py
```

Setting `CBUS_TOOLKIT_EXE` and `CBUS_TOOLKIT_MAP` to the retained pinned files
adds read-only static receipt reproduction. Unconfigured private-input checks
are explicit skips. Neither a static check nor an owned-backend report journey
supplies original process, host GUI, print or physical acceptance.
