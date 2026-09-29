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

## Source and live-service recheck (28 September 2026)

The verifier above was rerun against the retained, hash-matched Toolkit
executable and assemblies, C-Gate JAR, owned native command captures, and
offline GUI/project evidence. All four verifier stages passed. The exact
vendor hashes and normalized command replies are in the linked fixture; the
vendor files, raw captures, and private project remain outside Git. This
reconfirms the exposed 1.18/3.4 command boundary, not physical cache absence.

A separate read-only query of the running cmqttd endpoint used
`CMQTT CAPABILITIES`, `CMQTT LABELS` for its configured network, and one
`DBGETXML` network snapshot. The service advertised saved-project `TagsDLT`
preservation, while explicitly reporting
`dynamic_label_device_readback: false`. Its label reply identified its source
as `observed-sal-traffic` and marked both `complete` and `device_readback`
false. The project query and observed-traffic query address different stores;
site-specific addresses, labels and counts are deliberately omitted here.
These replies made no physical device-cache request.

There is a direct information gap even if every saved-project label and every
static unit string is known. Consider two devices with identical project and
static memory, and no label traffic since cmqttd connected. One could have
received a dynamic label before the connection and retained it; the other
could have no such cached label. The exposed reads would be identical, while
the rendered or cached label could differ. This is an inference from the
documented observation scope and reset-on-reconnect behavior, not a claim
that either physical state was observed in the house. Therefore neither the
CLI nor cmqttd can truthfully mark an inventory of **all currently rendered
dynamic labels** complete from these inputs.

The next useful experiment is an isolated, controlled eDLT plus a captured
original Toolkit/C-Gate session. Give one group distinguishable variant
values, record the send and visible display, restart the observer without
resending, then trace every request the original Dynamic Label Editor issues
when reopened. A candidate cache-read request must return the pre-existing
value, identify the intended recipient, and survive an observer restart
before it can become a new readback API. If no such request appears, keep the
bounded limitation and investigate official device diagnostics or a new
firmware-specific protocol separately. This experiment must not use the
saved project or an observed SAL frame as a substitute for device readback.

## Generic GET and audio-label command check

The pinned C-Gate manual (PDF SHA-256
`812f84b0206b8714e6780b80ea5dfe6347357530aa899f6aecc0f7da8f44c97b`)
describes `GET object-identifier [parameter | ? | * | ??]` on printed page
140. This generic property interface deserves a separate check from the
`LABEL` subcommand registry. The same manual's page 97 describes
`AUDIO ZONE_FEED_LABEL_REQUEST` on application 205: it instructs a matrix
switcher to **send** feed description and Dynamic 1/2 labels to DLT devices.
That is a label-source rebroadcast, not an inventory of a receiving eDLT.

The [bounded GET receipt](../research/fixtures/edlt-dynamic-cache-get-scope.json)
records one fresh original C-Gate 3.4.0.2001 child in the disposable Windows
VM. Its six listeners were loopback-only. The child created `XDLT` and one
synthetic KEYGL5 5.5.00 **database** unit with only `127.0.0.1:1` configured as
its CNI. The probe sent no `NET OPEN` or `PROJECT START` command. `DBGETXML`
confirmed the synthetic unit.
`GET /db//XDLT/254/p/5 ?`, `??`, `*`, and named candidate properties all
returned `401 Network not found`; `GET //XDLT/254/p/5 ?` returned `401 Unit
not found`. These replies did **not** reach an open unit's property inventory.
They therefore cannot strengthen the native-cache absence claim. The owned
Java child exited, its temporary home was removed, and the original C-Gate
home was restored. The receipt binds the retained raw captures and scripts by
SHA-256 without including the vendor binary or site project.

Disassembly of the pinned `CBusEdlt` constructor registers `WidgetGroups` as
a declared property and `FactoryDefault` as a method; it does not register a
declared dynamic-label getter. That constructor alone did not account for
inherited or runtime properties. The open-unit `?`, `*` and `??` replies this
section called for are now captured against an owned native server; see
[Open-unit generic GET inventory](#open-unit-generic-get-inventory-owned-native-30-september-2026).

### Inherited generic-GET registration audit

The [pinned class-chain receipt](../research/fixtures/edlt-dynamic-cache-get-inheritance.json)
extends the constructor check to `CBusEdlt` and all seven superclasses back
to `Bo` in the same C-Gate 3.4.0.2001 JAR. The source verifier disassembles
each hash-bound class and accounts for every insertion into its generic
property and method registries. All 59 property insertion call sites occur
in constructors; overloaded constructors repeat the same declarations. The
chain declares 31 class-scoped property names (30 distinct names because
`Address` appears twice) and six method names. Its eDLT-specific property is
`WidgetGroups`, which reads 44 group bytes; the inherited `SlotGroups` also
reports group assignments. None is a dynamic-label or cache-content getter.

The pinned `Bo` getter delegates a named read to the `Cl` property map; the
map throws `ParameterNotFoundException` for a name it does not contain and
uses the same map for its property-name enumeration. This strengthens the
exact-release finding for **constructor-registered generic `GET` properties**.
It does not turn the earlier synthetic-unit 401 responses into an open-unit
capture, exclude an external runtime registration, or prove firmware-level
impossibility. The owned-native open-unit capture below supplies the
missing runtime check; physical proof remains open.

The fixture-only check needs no proprietary files. To repeat its source
comparison against the retained vendor JAR, run:

```sh
cd toolkit-cli
python3.13 research/verify_edlt_get_inheritance.py \
  --cgate-app /path/to/ignored/pinned/cgate/app \
  --javap /path/to/java11/bin/javap
```

The verifier fails if the JAR or any of the eight class hashes, inheritance
declarations, property names, method names, or constructor-only registration
counts change. Focused `tests/test_edlt_get_inheritance.py` guards the
fixture against accidental promotion to device-readback or open-unit proof.

## Open-unit generic GET inventory (owned native, 30 September 2026)

The [open-unit receipt](../research/fixtures/edlt-open-unit-get-native.json)
resolves the earlier inconclusive 401 replies. Owned C-Gate 3.4.0.2001
(JAR SHA-256 `3ec48394…`, Java 11, six loopback listeners) loaded a project
whose CNI was the Python PCI simulator and opened network 254. Unit 5 is the
named SIMTEST KEYGL5 identity from `synthetic_units` (`IDENTIFY` type
`KEYGL5`, version `5.5.00`, serial `101183.1666`). The
[probe](../research/edlt_open_unit_native.py) adds only the blocks native
requested for these commands: learn-enable byte `3E` (chosen `00`), a writable
`FF` selector block, and `IDENTIFY 3D` carrying chosen key-function nibbles.
It also uses the existing 10 ms simulator reply delay, which avoids a
confirmation race that otherwise left unit 5 unsynchronized. No simulator
block stores label text.

With the network and unit both at `State=ok`, native reported
`ClassName=com.clipsal.cgate.cbus.dev.CBusEdlt`:

- `GET <unit> ?` listed exactly 30 parameters, and `??` described and `*`
  returned the same 30 without an error line. The set is identical to the 30
  distinct constructor-registered names in the class-chain receipt above, so
  no runtime registration adds a property to an open eDLT.
- None of those parameters names a label, cache, dynamic or text value.
  `WidgetGroups` returned the 44-byte static widget group mapping.
- `DynamicLabels`, `DynamicLabel`, `LabelCache`, `Labels`, `Label`,
  `LabelText`, `Cache` and `KFI` each returned `402 Operation not supported
  ... (Parameter <name> not found)` with no bus traffic.
- The lighting application (`//…/56`) and one widget group (`//…/56/27`)
  expose only state, naming, learning, level, ramp and membership properties.
- `GET <unit> *` issued only `RECALL 3E`; the other values came from the
  model built by `NET SYNC` identity and parameter reads.
- `LABEL KFIGET <network>/56 5` sent `A3FF0009`, `A5FF0082001C` and
  `A5FF008404FF` selector writes, then `IDENTIFY 3D`, and returned exactly
  `kfi1`–`kfi8`: the chosen nibbles `0`–`7`. It returns no text.

**Resolved answer:** native C-Gate 3.4.0.2001 does not expose a readable
dynamic-label cache for an open eDLT. Its generic property map, the `LABEL`
registry (`CLEAR`, `CLEAREDLT`, `KFIGET` and `KFISET`) and its
application/group objects provide no command that returns stored label
content. The unit is simulated, but that does not weaken this conclusion.
C-Gate builds the property list in its own classes, before and independently
of any device reply, and the list matched the bytecode audit exactly. This
leaves no native operation for cmqttd to reproduce, so cmqttd keeps
`dynamic_label_device_readback: false`. It does not add a readback route.

The remaining gap is outside the native command surface. An undocumented
firmware request or a request issued only by the original Toolkit GUI has not
been ruled out, because eDLT firmware images are encrypted. Any such path needs
a controlled physical eDLT, the original Dynamic Label Editor trace and an
observer restart, as described above. This capture makes no physical rendering
or persistence claim.

`tests/test_edlt_open_unit_get.py` checks that the receipt was captured by
the committed probe against the pinned JAR. It also checks the 30-name set
against the inheritance receipt and rejects a forged label property,
answered candidate, unopened unit or unexpected device request. Its
`NativeOpenUnitGetTests` class is in the native release gate and repeats the
capture. Regenerate the receipt with:

```sh
cd toolkit-cli
CBUS_LOCAL_CGATE_VENDOR=/path/to/ignored/pinned/cgate/app \
CBUS_CGATE_JAVA=/path/to/java11/bin/java \
PYTHONPATH=src:. python3.13 research/edlt_open_unit_native.py \
  --output research/fixtures/edlt-open-unit-get-native.json
```
