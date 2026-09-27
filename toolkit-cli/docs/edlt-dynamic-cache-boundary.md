# eDLT dynamic-label cache readback: native 1.18 / 3.4 boundary

For Toolkit **1.18.0.2754** and C-Gate **3.4.0.2001**, the exposed native
command surface provides no evidenced operation that enumerates labels already
stored in a physical eDLT's dynamic-label cache. This is a bounded conclusion
about these installed releases. It does not prove that every eDLT firmware
has no undocumented diagnostic or programming protocol.

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

The vendor and raw-capture flag pairs can be omitted independently. Without
those private files, the same script validates the committed fixture and its
conservative conclusion. `tests/test_edlt_dynamic_cache_scope.py`
guards the registry/help agreement and native rejection cases. Existing
`tests/test_cmqtt_observed_bounds.py` and Rust service tests guard the separate
observation provenance boundary. A future release or firmware inquiry needs a
new native capture and source analysis; this fixture must not be stretched to
that target.
