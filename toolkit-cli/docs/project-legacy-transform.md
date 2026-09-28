# Repaired legacy project conversion

The original C-Gate 3.4.0 build 2001 XML repository refuses a Python-repaired
bare `Project` while its wrapped `Installation` has DBVersion 2, 2.1 or 2.2.
The source-bound [2.2 receipt](../research/fixtures/project-legacy-transform-native-receipt.json)
records four generated examples. Each first returned `PROJECT LOAD` 408, then
`TRANSFORM PROJECT` 200, then `PROJECT LOAD` 200 and `DBGETXML` 344. The
additional [earlier-version receipt](../research/fixtures/project-legacy-transform-versions-native-receipt.json)
records three repaired fragments at each of DBVersion 2 and 2.1, and two
native-rejected versions. The original default migration chain is 2 → 2.1 →
2.2 → 2.3. In the ten accepted examples, the written bytes equal changing the
sole literal `DBVersion` element to 2.3 and removing the final LF. Their
original migration files and `projectversions.xml` are hashed in the receipts.

The portable command performs that bounded conversion offline into a **new**
file. It does not run `PROJECT REPAIR`, open a C-Gate connection or overwrite
the source or an existing output:

```sh
cbus-toolkit project repair damaged.xml --output repaired.xml
cbus-toolkit project transform-legacy repaired.xml --dry-run
mkdir converted
cbus-toolkit project transform-legacy repaired.xml --output converted/RPMAL.xml
```

The output directory must already exist. Use the intended C-Gate project name
as the output filename when staging it in an XML repository. If the repaired
fragment has no `Project/Address`, native load of the tested files assigned
both that address and the project tag from the staged filename. The portable
result reports the source and output SHA-256, observed project address (or
`null`), source and output DBVersion, and `native_load_verified: false`;
conversion alone cannot verify a different project's loadability. The command
accepts the UTF-8, XML 1.0 `Installation` envelope produced by the portable
repair, one literal direct DBVersion 2, 2.1 or 2.2, one direct `Project`, a
final LF, and an optional project address matching `[A-Z][A-Z0-9_]{0,7}`.
For version 2 or 2.1, it also admits unnamespaced `KEYGL5` firmware `5.5.00`
and `KEYB2`/`KEYB4` firmware `1.6` units with canonical direct
`PP Name="..." Value="..."` tokens. A PP name may contain spaces, as the
native Neo snapshot's `EEPROM Checksum` does. The command preserves other
programming bytes and applies the original stylesheets' obsolete-parameter
removals: `Remote3` through `Remote8` identity/key-map fields in the 2.1→2.2
stage, plus the 2→2.1 stage's specified mask, offset, feature, key 9–16 and
remote 1–2 fields. For `KEYB2`/`KEYB4` firmware `1.6` without an `Application`
PP, the 2.1→2.2 stage also removes `KeyDisableGroupInvert`,
`CorridorLinkEnable`, `NightlightColour` and `DisableIRNEC` from that unit.
With an `Application` PP, those four fields remain. The portable result lists
removed names in source order under `removed_programming_parameters`.

The earlier original stylesheets also add parameters and change selected
firmware versions. Other Unit types and firmware versions, noncanonical PP
tokens, namespaced units and the PP expansion/rename triggers still require
original C-Gate's native transform. The portable command rejects DTDs,
alternate version spelling, other encodings and malformed or oversized XML.

For an explicitly selected original XML repository, the typed native client
forwards the default migration and its plan:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port PORT project transform RPMAL --test
cbus-toolkit cgate --host 127.0.0.1 --port PORT project transform RPMAL
```

This changes files on the server and depends on its current repository
selection. The typed client now also exposes the original explicit-stylesheet
and output-file form, which has different file semantics:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port PORT project transform OLD \
  --xslt-file transform/v22tov23.xslt \
  --output-file /path/on/cgate/server/projects/NEW.xml
```

The output path is on the **C-Gate server**, must already be a writable file,
and is overwritten. Original HELP calls it an output project name, but the
owned native run accepted an absolute existing XML file and rejected a bare
new project name with `No write permission for output file`. The stylesheet
path was resolved from the server working directory: `transform/v22tov23.xslt`
worked, while bare `v22tov23.xslt` returned `xslt file not found`. The explicit
`--test` plan left that output and the source unchanged and did **not** create
the source `.xml.0` backup in the captured case. The later transform overwrote
only the output; it loaded and returned DBVersion 2.3 XML as `NEW`. Keep a
separate backup before using this native operation. Arbitrary user-supplied
stylesheets, relative server paths and output failure recovery still need
their own acceptance. Supplying the same built-in stylesheet without
`--output-file` also succeeded in the owned run: C-Gate replaced the source,
saved its original bytes in `.xml.0` and loaded the transformed result.

The first native test stages one generated network project and three previously
captured bare fragments at version 2.2. The second stages those three bare
fragments at versions 2 and 2.1. For all ten, the portable bytes exactly match
the native transformed file; a fresh owned native service loads and reads back
the staged file. The network project retains groups 1 and 255; native readback
generates OIDs. The bare fragments have no network and acquire their project
name from the staged filename. No network is opened. The original
`TRANSFORM PROJECT --test RPMAL` returned its 2.2-to-2.3 plan and left
`RPMAL.xml` unchanged, but created `RPMAL.xml.0` containing the source bytes.
The second test confirms this backup side effect for default versions 2 and 2.1 and,
more surprisingly, for rejected versions 1 and 2.4: native `--test` returned
408 with `No suitable transforms`, left the source unchanged and still created
the `.xml.0` backup. It is therefore a native file-mutating preview, unlike
the portable `--dry-run` which creates no output.

An additional [owned KEYGL5 receipt](../research/fixtures/project-legacy-transform-units-native-receipt.json)
generates a full KEYGL5 5.5.00 PP snapshot inside original C-Gate, stages
version 2 and 2.1 copies, and compares four portable outputs byte-for-byte
with original `TRANSFORM PROJECT`. Two copies retain all PP values; one removes
an obsolete `Remote3Identity` at version 2.1, and one removes `FeatureSet` at
version 2. Each transformed file subsequently passes original `PROJECT LOAD`
and `DBGETXML`, with the removed fields absent on readback. The service uses
an owned XML repository and loopback listener and does not open a network.

The [owned Neo receipt](../research/fixtures/project-legacy-transform-neo-native-receipt.json)
generates full `KEYB2` and `KEYB4` firmware `1.6` PP snapshots inside the
original C-Gate. Each snapshot includes `EEPROM Checksum` and the four
conditional fields. Eight staged version 2/2.1 copies cover both unit types
with and without an `Application` PP, plus global `Remote3Identity` and
version-2 `FeatureSet` removals. All eight portable outputs match native
`TRANSFORM PROJECT` bytes exactly, then pass `PROJECT LOAD` and `DBGETXML`.
Readback retains the four conditional fields only when `Application` was
present. The owned service opens no physical network.

These observations cover 22 generated conversions, two rejected versions and
two explicit built-in-stylesheet variants (server output and in-place) in the
original XML repository. Arbitrary repaired databases, other unit/PP
migrations, custom stylesheets and output paths, SQLite repository behavior,
Windows conversion and complete Toolkit workflow parity remain unverified.
