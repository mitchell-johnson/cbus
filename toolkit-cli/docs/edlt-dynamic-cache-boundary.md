# eDLT dynamic-label cache readback: native 1.18 / 3.4 boundary

For Toolkit **1.18.0.2754** and C-Gate **3.4.0.2001**, the exposed native
command surface provides no evidenced operation that enumerates labels already
stored in a physical eDLT's dynamic-label cache. This is a bounded conclusion
about these installed releases. It does not prove that every eDLT firmware
has no undocumented diagnostic or programming protocol.

An additional offline observation in the original Toolkit 1.18 GUI confirms
that its network **Dynamic Label Editor** exposes Applications, Groups,
Dynamic Labels, four displayed variants, Edit Languages, Set Network Language
and Send Labels. The selected network was closed, its house CNI host was
blocked, and Send Labels was disabled. The local project XML contains one
nonempty `TagDLT` under a network/application/group, with a text flavour and
language; the KEYGL5 unit has no `TagDLT` descendants and instead carries 64
separate `StaticTextString` programmable parameters. Project dynamic-label
definitions and physical unit static strings are different stores. The
site-specific text and project XML remain private. The particular group's
value was confirmed in XML but **was not displayed in the GUI**. This did not
read the device, validate rendering, or prove that Toolkit/C-Gate can retrieve
its pre-existing dynamic-label cache. The GUI's Variant 1–4 captions are
recorded as displayed, without inferring protocol index equivalence.

The [source-bound P6.05 fixture](../research/fixtures/edlt-dynamic-cache-native-scope.json)
records the exact Toolkit executable, C-Gate JAR, eDLT/LabelEditor assemblies,
Java runtime and relevant class/IL hashes. The pinned native C-Gate
`LabelPrimaryCommand` constructor registers exactly four children: `CLEAR`,
`CLEAREDLT`, `KFIGET` and `KFISET`. `KFIGET` retrieves eight key-function
indicator values for one unit after three volatile selector writes and an
IDENTIFY request; it is neither a label-content getter nor a passive bus read.
The original eDLT dialog opens the label editor to send project labels, or
invokes `ClearEdltLabel` and checks its receipt. Neither path yields a cache
inventory.

A fresh owned C-Gate child with six verified loopback listeners and no project,
CNI or device returned those same four children for both `HELP LABEL` and
`LABEL ?`. `HELP LABEL GET`, `READ`, `CACHE` and `INVENTORY` returned native
`400 Syntax Error.`; the corresponding `LABEL` commands against a nonexistent
unit also returned 400 before object resolution. The child and its temporary
state were removed. The normalized responses, raw-capture digests, exact
source hashes, and a hash-linked reference to the retained 431-path full native
HELP census are in the fixture. This combination of bytecode registration
and independent native dispatch is the evidence for the release-specific
absence conclusion; a help-text search alone would not suffice.

`cbus-toolkit cgate edlt-labels` still reads KEYGL5 5.5.00 physical static
strings, widget references and scenes through cmqttd. Separately,
`CMQTT LABELS` reports a bounded network-wide ring of incoming and confirmed
outgoing dynamic-label SAL observed **since the current cmqttd connection**.
Even when assembled into text, Unicode or bitmap records, the ring is
recipient-unverified, incomplete and reset on reconnect. A unit-shaped query
is a compatibility alias for the same network ring. It cannot establish the
labels a particular eDLT held before the connection, whether a label rendered,
or whether it persisted through a power cycle. The service capability remains
`dynamic_label_device_readback: false`; the CLI reports
`device_dynamic_label_cache_readback: false` and refuses a forged `complete` or
`device_readback` observation document.

The read-only `DBGETXML` saved-project `Group/TagsDLT/TagDLT` enumeration is a
third, independent source. Its text, language, flavour and type describe the
configured group label; they do not prove that a particular eDLT received it,
currently displays it, or retained it after a restart. The CLI reports these
rows in `project_group_labels`, separate from physical static strings and the
observed SAL ring.

The decision is invalidated by a different Toolkit/C-Gate artifact hash, a
new registered native command or independently captured device-cache query,
or a change that upgrades observed traffic to a readback claim. Reproduce the
source check with:

```sh
cd toolkit-cli
python3.13 research/verify_edlt_dynamic_cache_scope.py \
  --cgate-app /path/to/ignored/pinned/cgate/app \
  --toolkit-app /path/to/ignored/pinned/toolkit/app \
  --raw-help /path/to/private/owned-help-capture.json \
  --raw-commands /path/to/private/owned-command-capture.json
```

To recheck the retained GUI screenshots and private project XML hashes and
their structural separation, add `--private-gui-staging` with the ignored VM
evidence directory. This check verifies the original XML fields without
printing the private label text. The sanitized fixture binds the retained
GUI evidence report (`a00bfa095d64938824d54928c69bd5dd5be496390f1d423a21814202c581a5e8`),
project contract (`9a85f210e996f5e0772ef3d0c77310af41cc5412c7440cef205b95c3e615d204`),
project XML and three screenshots by SHA-256. Their absence from a public
checkout does not turn the observation into an accepted P0/P6 parity receipt.

The vendor and raw-capture flag pairs can be omitted independently. Without
those private files, the same script validates the committed fixture and its
conservative conclusion. `tests/test_edlt_dynamic_cache_scope.py`
guards the registry/help agreement and native rejection cases. Existing
`tests/test_cmqtt_observed_bounds.py` and Rust service tests guard the separate
observation provenance boundary. A future release or firmware inquiry needs a
new native capture and source analysis; this fixture must not be stretched to
that target.

## Underlying command and decoder evidence

The [underlying-contract receipt](../research/experiments/2026-09-28/underlying-label-cache-contract.json)
extends the command/help and retained offline Windows GUI evidence with five
hash-bound classes from the same original C-Gate jar. Fresh disassembly checks
confirm that the clear request builders (`ku` and `kt`) construct clear
operations, while `kv` requests `213D`, recognizes response prefix `8D3D80`,
and decodes four bytes into eight 4-bit key-function indicators. The SAL
application paths send labels or decode received broadcasts; a broadcaster's
address does not identify the receiving unit's cache contents.

A separate host-Java probe invoked only the original `kv.m(String)` static
decoder, without creating a C-Gate server or device transport. Null and empty
inputs returned null; synthetic byte suffixes `01234567`, `10325476` and
`FFFFFFFF` returned the exact eight-nibble arrays in the receipt. The probe
uses a deliberately synthetic prefix: this helper alone does not establish
frame validity, successful wire exchange, or a read-only operation. In
particular, it does not remove KFIGET's selector writes described above.
The [small authored probe](../research/experiments/2026-09-28/CbusKfiDecoderProbe.java)
can be compiled with `javac -d <empty-owned-directory>` and run with that
directory plus the pinned jar and its `lib/*` on the classpath. Keep the output
directory isolated: unrelated extracted obfuscated classes can shadow jar
classes on case-insensitive filesystems. The jar and raw disassembly remain
private; no vendor code is included in the receipt.

Retained firmware package directory inspection found encrypted main images
in eDLT 1.3.0, 1.4.0, 1.5.0 and 1.7.0 archives. Their hashes bind that bounded
observation; it is not firmware dispatch analysis or proof that a diagnostic
read is impossible. No cache address layout, enumeration/pagination rule,
request/response correlation, terminator, or completeness contract has been
established. **P6.05 / issue #49 remains open.** A future implementation needs
those details plus independent native and physical acceptance. No guessed
CLI or cmqttd readback route is introduced by this evidence update.
