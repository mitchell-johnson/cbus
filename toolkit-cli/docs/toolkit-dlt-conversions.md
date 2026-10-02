# Source-bound DLT conversions

`cgate conversion tweak` and `tweak-replace` admit 129 source-backed Toolkit
tweaker registrations into KEYDL4, KEYML5 or KEYBL5 at firmware `2.1.00`.
The original DLT checkpoint added 120 directions; verified KEYBIR aliases now add 9 more. With the other recovered families the client admits 288 of 292 registered pairs; see [remaining conversions](toolkit-remaining-conversions.md). Admission remains specific to the source type, firmware
and decoded specification shape; it is not unrestricted DLT conversion.

| Source profile | Firmware | Pairs into the three DLT targets |
| --- | --- | --- |
| KEY1/KEY2/KEY4/KEYIR1/KEYIR4 | 1.2.67 | 15 |
| 32 recovered Neo, Saturn, Reflection, Neo Classic and KEYE models | 2.5.00 | 96 |
| KEYDL4/KEYML5/KEYBL5 | 2.1.00 | 9 |
| KEYBIR2/KEYBIR4/KEYBIR6 with exact KEYB2/4/6 catalogue aliases | 2.5.00 | 9 |

The exact modern types and constructor order are recorded in the sanitized
[source proof](../research/fixtures/toolkit-dlt-conversion-source-proof.json).
KEYM6's three registrations remain refused because no static Toolkit factory
model is established. KEYBIR2/4/6 use independently verified literal catalogue
aliases to KEYB2/4/6 specifications; an inferred IR-looking name is insufficient.
The current proof binds those aliases and the actual specification shapes.

Preview a new DLT alongside the source:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 conversion tweak \
  //PROJECT/11/p/20 --source-type KEYM2 --target-type KEYDL4 \
  --source-spec KEYM2.xml --target-spec KEYL4.xml --spec-dir ./specs \
  --target-address 21 --firmware 2.1.00 --catalog-number TARGET \
  --tag-name Replacement
```

Review the complete returned plan and repeat it with `--apply
--exclusive-project --expect-plan-sha256 REVIEWED_DIGEST`. This creates one
fresh destination and leaves the source in place. Every project Network must
be closed and idle. Occupied or ambiguous destination addresses, stale plans,
changed specifications and mismatched source firmware refuse before ADD.
The operator supplies private decoded specifications and target catalogue
defaults; no vendor specification is bundled or original catalogue lookup
claimed. KEYML5/KEYBL5 use the retained KEYL5 specification identity, KEYDL4
uses KEYL4, and the KEYE models use the shared KEYE identity. Unsupported
shapes and extra DLT PCx/PA6 PP fields refuse locally.

For replacement, use `conversion tweak-replace` with the same source/profile
arguments, omit `--target-address` and `--tag-name`, and supply
`--backup-project PRETWEAK`. Apply additionally requires a new `--journal`
and the reviewed digest. The existing [replacement lifecycle](toolkit-tweaker-lifecycle.md)
creates one checked backup, uses the first free staging address from 1 through
255, copies the established scalar metadata, saves the transformed PP,
deletes the source once, readdresses the fresh destination, then saves,
closes and reloads the project. A lost reply stops without replay or automatic
rollback. `conversion tweak-recover --journal ATTEMPT` observes that bound
attempt without writing or authorizing replay.

The DLT hook does **not** call the inherited Learn/CoreKey/NeoPro conversion
hooks. It preserves the aligned Learn flags and group positions instead of
performing the classic-to-Neo reshaping. Classic indicator functions map `1`
to `2` and `3` to `1`; shorter arrays retain the fresh target's tail.
The DLT constructor appends KeyDisableGroup and KeyDisableGroupInvert twice;
the reviewed ordered assignments retain both occurrences. NightlightColour
is absent from this constructor.

Each LabelFlavour assignment is the one-element string `0`, rather than eight
invented zeros. Native schema staging retains the target's remaining elements.
An empty aligned source value suppresses its write even when the hook later
assigns a value, preserving the constructor/default effect. Non-DLT sources
leave EnablePageFallback and IndicatorMode at target defaults. Neo Standard
nightlight comes from PA6, other admitted Neo models use PCx, and Neo Classic
forces nightlight and first-key throw-away off. A DLT source has no PCx PP
field in this profile, so its loaded inherited nightlight model remains off.
Neo Classic brightness `2` becomes `5`; other Neo brightness `2` or `3`
becomes `1`. These are loaded-model rules, not copied GUI settings.

Dedicated pure tests cover all 120 admission profiles, literal hook effects,
empty fields, duplicate order and refusal bounds. Owned mock/daemon public
subprocess journeys cover creation and the complete replacement/recovery
composition across classic, standard, Saturn, Reflection, Neo Classic, KEYE
and DLT sources, including successful replies lost after mutation, stale plans
and daemon authentication. This establishes modeled software behavior without
original instruction execution, GUI/history, physical programming or controller
handoff acceptance. Original exception cleanup and catalogue lookup remain
open parity requirements. The structural XML comparison preserves substantive
text, attributes, namespaces, comments and processing instructions; it ignores
all whitespace-only text, including opaque and `xml:space="preserve"` content.
Arbitrary source Unit extensions remain in the backup rather than being copied
into the replacement. Issues #73 and #74 are separate and were not retried.
