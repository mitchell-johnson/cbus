# Repaired legacy project conversion

The original C-Gate 3.4.0 build 2001 XML repository refuses a Python-repaired
bare `Project` while its wrapped `Installation` has DBVersion 2.2. The
source-bound [native receipt](../research/fixtures/project-legacy-transform-native-receipt.json)
records four generated examples. Each first returned `PROJECT LOAD` 408, then
`TRANSFORM PROJECT` 200, then `PROJECT LOAD` 200 and `DBGETXML` 344. The
original `v22tov23.xslt` is pinned in that receipt. In these four examples its
written bytes equal changing the sole literal `<DBVersion>2.2</DBVersion>` to
2.3 and removing the final LF.

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
`null`), and `native_load_verified: false`; conversion alone cannot verify a
different project's loadability. The command accepts the UTF-8, XML 1.0
`Installation` envelope produced by the portable repair, one literal direct
DBVersion 2.2, one direct `Project`, a final LF, and an optional project
address matching `[A-Z][A-Z0-9_]{0,7}`. It rejects DTDs, alternate version
spelling, other encodings and malformed or oversized XML. It does not implement
arbitrary XSLT or C-Gate's other version migrations.

For an explicitly selected original XML repository, the typed native client
also forwards the two captured forms:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port PORT project transform RPMAL --test
cbus-toolkit cgate --host 127.0.0.1 --port PORT project transform RPMAL
```

This changes files on the server and depends on its current repository
selection. The typed path exposes only the default version transform; custom
stylesheets and output-name arguments from native HELP remain outside this
workflow. The offline command above is independent of the server.

The native test stages one generated network project and three previously
captured bare fragments. For all four, the portable bytes exactly match the
native transformed file, and a fresh owned native service loads and reads back
that file. The network project retains groups 1 and 255; native readback
generates OIDs. The three fragments have no network and acquire their project
name from the staged filename. No network is opened. The original
`TRANSFORM PROJECT --test RPMAL` returned its 2.2-to-2.3 plan and left
`RPMAL.xml` unchanged, but created `RPMAL.xml.0` containing the source bytes.
It is therefore a native file-mutating preview, unlike the portable
`--dry-run` which creates no output.

These observations cover only the four named generated files and the original
XML repository. Arbitrary repaired databases, SQLite repository behavior,
Windows conversion and complete Toolkit workflow parity remain unverified.
