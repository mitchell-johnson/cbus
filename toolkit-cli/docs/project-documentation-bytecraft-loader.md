# Old Bytecraft packed scene projection

`decode_bytecraft_scenes(unit)` projects the exact old `DIMPR12` registration:
`TDIMPR12` / `TDIMPR12CGateAgent`, firmware `0` through `1.9.02`. It returns
33 immutable `BytecraftScene` records in index order, each containing twelve
on/off inclusions and levels. The shared decoder also admits the exact `TDIMPR12L1` /
`TDIMPR12L1CGateAgent` partition at firmware `1.9.03` through `9`; see
[the separate L1 report profile](project-documentation-wireless-l1.md).
The historical evidence in this note describes the old partition. DIMPR12A
selects the existing DIN ErrorReportOutput implementation and does not use
this scene decoder.

Every `PresetRec00` through `PresetRec32` must contain at least 32 explicit
byte values. Missing, malformed, partial or out-of-range arrays fail closed.
Valid trailing values are ignored; malformed trailing values are refused,
following the existing saved-project array adapter. This decoder does not
substitute schema defaults or create project application/group/level objects.

The consumed record layout is:

| Record bytes | Projection |
| --- | --- |
| 0 | Advanced mode exactly when value is 1 |
| 1, 2, 3 | Trigger group, selector Address, link group |
| 4, 5 | On mask `(byte4 << 8) + byte5` |
| 6 through 17 | Twelve on levels |
| 18, 19 | Off mask `(byte18 << 8) + byte19` |
| 20 through 31 | Twelve off levels |
| High nibble of 4, 18 | On/off ramp indices |

Scene use depends only on any included on or off channel, independently of
levels, mode, output group use and ramp bits. The high mask nibble holds the
ramp and does not overlap the twelve channel bits. Scene zero remains a
record; its distinct restore/report role belongs to the consumer.

The initial assessment's Boolean hazard omitted two instructions. The loader
normalizes mask tests with `SETG DL` at `0x1246eb1` and `0x1246f56` before
calling the low-byte setters; channels 8 through 11 remain usable. Mode uses
`DEC EAX; SETE AL` at `0x1246bca` and `0x1246bcb`, so a general nonzero test
would be incorrect. All three setters construct a Variant through
`Variants.@VarFromBool`; its byte comparison and carry sequence stores zero
or minus one. The caller has already normalized the input byte to zero or one.

The native packed getters pass zero as their missing-element default. The
pinned DIMPR12 specification declares all 33 records with 32 zero defaults,
and the constructor and `GetMaxScenes` both pin a count of 33. These source
facts do not establish how a full native PP session supplies omitted attributes;
the adapter therefore continues to require explicit records.

Recall groups resolve in Trigger application 202. Group 255 is an unused
group object, not a nil sentinel. Selector 255 is likewise an Address lookup;
the loader calls `FindLevelByAddress`, never `FindLevelByValue`. Missing levels
can be created with `Address=Value`, while an existing level keeps its own
Value. Missing group creation is subject to the manager's 256-object capacity;
a nil group yields a nil level. Consumers must resolve existing metadata when
they need original object links or names. Both summary disable and DMX switch
groups resolve through Enable application 203.

The [static receipt](../research/fixtures/project-documentor-bytecraft-loader-static.json)
reproduces all thirteen earlier assessment spans and checks the bounded count,
record layout, zero defaults, Boolean conversion, nibble order and binding
methods against the pinned EXE/MAP/spec hashes. Reproduce it with
`research/project_documentor_bytecraft_loader_static.py` and explicitly supplied
`--executable`, `--map-file`, `--specification` and `--output` paths. No vendor
code executes. Original full PP-loader runtime acceptance and generated-page
comparison remain pending. Previous GUI scene history is not modeled.
