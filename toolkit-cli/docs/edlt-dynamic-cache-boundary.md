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
