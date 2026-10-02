# Static text, languages and saved-project report families

This batch extends the Python Toolkit CLI and Rust cmqttd service together.
It targets Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001. All execution uses owned
software peers and invented project data. Static inspection of the pinned
Toolkit EXE/MAP supplies source facts; no original instruction, Windows VM,
house service or physical C-Bus endpoint is executed.

## Delivered behavior

The ordered eDLT parent transaction accepts committed `static-text-dialog`
grid edits and `add-language-dialog` selections alongside existing widget,
Application/Activation Add and SceneManager operations. Both static-grid close
paths save; the 64 UTF-16-unit cell limit remains distinct from the PP setter's
63 UTF-8 bytes and terminator. Initial native language rows and explicit
preferences populate a fresh cache. Repeated dialogs consume that cache,
preserve matching real-row identities/custom names/lexical IDs, and preserve
the last ID0 marker before repairing the selected default. Cancellation,
English locking and all 68 nonzero factory choices have explicit contracts.
Equivalent preference representations compare by their eight semantic values;
the pinned integer grammar handles long zero prefixes without a Python digit
limit. Read [the operation guide](edlt-static-language-add.md).

Caller JSON cannot supply internal language bindings. The CLI rejects that
input before opening a connection or reading project/parameter metadata; the
native planner validates operations before database reads. Selecting a text
language can enable a later newly introduced dynamic Lighting widget. Reverse
order still refuses unknown image data, and an existing dynamic widget cannot
borrow facts from a future language selection.

cmqttd and the mock retain Network `Languages/Language` objects with issued
OIDs, signed-i32 IDs, scalar read/write/delete, complete Network XML and
durable database roundtrip. Invalid XML text, conflicting identities and
malformed collections refuse before mutation. Legacy numeric startup import
validates its language collection without re-admitting unrelated incomplete
Units or requiring previously absent Interface/NetworkNumber fields. Reads do
not persist an overlay. The first successful language mutation installs its
owned tree. [Service contracts](../../docs/cgate-network-languages.md) separate
these local operations from physical labels and native repository formats.

The shared saved-project renderer gains these bounded families:

| Family | Recovered scope |
| --- | --- |
| Multisensor / thermostat | Seven multisensor and four thermostat profiles, eleven literal bodies, fresh macro/occupancy references, resolved plant/master references and independent group/action usage |
| Wireless / gateway / remote | 50 input types through 173 class/agent partitions, two gateways through eight partitions and seven remotes; ten literal bodies, decorator/nibble maps, compacted scenes and receiver dependencies |
| Bytecraft L1 | DIMPR12 at 1.9.03–9, one logic group, twelve enable/Min-Max attributes, inherited 33 packed scenes and one complete literal body |
| Architectural dimmer | DIMAR3/6/12 and C12DIMAR, four literal bodies, channel/logic/DMX tables, fixed RMS voltage conversion, all 128 sparse ordinary scenes and fresh special-scene behavior |

`project document` reads a saved file; `cgate database-document` makes one
complete DBGETXML request and exclusively writes BOM/CRLF HTML. The public
journeys verify literal bodies, reference identity, hashes, whole-project
preservation and closed fake-CNI traps against both owned Rust servers. No
network OPEN, scan, physical programming LOAD, project mutation or SAVE is
part of those report commands. Missing consumed fields and unresolved loader
history remain visible refusals. See [report profiles](project-documentation.md).

Independent NetworkNumber resolution belongs to the pure/legacy helpers.
The native report adapter still requires canonical numeric Address and matching
NetworkNumber, and refuses distinct values. This admission boundary remains
part of #57.

## Validation and publication evidence

Required Rust checks pass: `cargo fmt --check`, workspace Clippy with warnings
denied, `cargo test --workspace` and release workspace build. The test gate
actually passes **8,702 tests**, fails zero and ignores one private-input test;
459 Rust inputs remain unchanged during that gate. Frozen server copies bind
the subsequent public CLI tests.

Author runs remain distinct from final integrated source/wheel acceptance.
The sensor lane passes 83 focused cases; its static receipt verifies 71 checks
and 64 method spans. The wireless/L1 core passes 142 focused cases with pinned
private static inputs, then separately passes two public L1 backend journeys.
The original parent checkpoint passes 22 public histories; later narrow runs
cover semantic-preference, large-zero-prefix and lexical-ID corrections with
separate immutable input manifests. None of these overlapping runs is summed
as a unique total or called full Toolkit acceptance.

The architectural lane passes 86 focused cases without skips and binds 72
static checks across 208 method spans. Static publication omits five compiler
path literals with full method hashes retained; original instructions remain
unexecuted.

The first integrated 69-module source and installed-wheel runs each retain
**20 failed, 1,723 passed, 38 skipped and 806 passing subtests**. Twelve failures
expose an undefined operation-history variable in the automatic parent-cache
path. The other eight expose stale recovered-report/static-model expectations,
trigger test doubles missing the new network context and historical operation
rosters. These failed runs remain retained with their original input bindings.

The second 69-module source and installed-wheel runs each retain **2 failed,
1,752 passed, 38 skipped and 812 passing subtests**. Both failures are the public
invalid-history connection assertions: the first CLI preflight incorrectly
moved every semantic validation ahead of connection creation. Narrowing it to
the internal-binding rejection preserves established timing. The public wire
oracle, test roster and vectors are unchanged by that correction.

The final nine-module source and fresh installed-wheel selections each pass
**221 parent tests and 617 separate subtests, with no skips**. They include all
22 new eDLT public journeys, CLI input guards and resource/execution auditors.
Exactly two of the 349 runtime files differ from the second 69-module wheel:
the CLI and its parent-input helper. The other 347 are unchanged. All 349 final
files match source, wheel and installation, and 66 observed wheel processes
have zero import-provenance violations. All 3,796 selected source inputs and
both server binaries remain fixed during the final selection. The 69-module
runs remain red; this scoped resolution is not a new green 69-module gate, and
overlapping counts are not added. Their 38 provisioning skips remain 32
original/static-input checks and six disposable native-parent checks.

CI now requires the new public parent and report journeys in both backend
jobs, and the execution auditor requires their modules. The source/wheel
publication receipt records final selected modules, execution counts,
provisioning skips, raw artifact digests, import provenance and source/binary
quiet checks. [The bounded publication receipt](../research/fixtures/static-languages-documentors-owned-release-20261003.json)
preserves the failed executions and the final scoped resolution separately.
Six fresh modeled C-Gate comparisons replay retained original cases against
the new owned binaries: **64 primary cases and four combined checks**, with
1,141 declared bindings across 213 source paths. Python `cli.py` is absent
from those maintained maps; its supplemental source snapshot is separate.
The comparisons do not execute an original server or establish frontend
acceptance.

The previous published commit's [CI run 37003083029](https://github.com/mitchell-johnson/cbus/actions/runs/37003083029), attempt 1, remains red:
the installed wheel reports **3 failed, 7,479 passed, 906 skipped and 41,303
passing subtests**; source reports **3 failed, 7,492 passed, 735 skipped and
41,303 passing subtests**. Its three NeoPro `other-family` guards incorrectly expected
the newly admitted KEYSCEN4 loader to fail. The correction adds three positive
literal own-loader cases and keeps an actual unregistered-type refusal; the
whole source module separately passes 105 tests. Earlier red author oracles
and environment/setup failures are retained; no historical run is relabeled.
The full Python suite is not repeated locally. That earlier run's separate
mock interop gate passed 148 parents/158 subtests with one vendor-spec skip;
daemon interop passed 287 parents/69 subtests with one vendor-spec skip. Those
historical backend passes do not change the failed source/wheel conclusions.

## Remaining acceptance

The broad ledger remains **18/42 = 42.86%**. It does not measure functionality;
the functional denominator is incomplete and zero obligations are fully
accepted. C-Gate primary routing remains 429/429 non-obsolete paths, with full
semantic compatibility false. Original full parent/control binding, native
serializer/save-count behavior, complete generated-page bytes/visuals,
printing/image/progress/cancel, wider loader history and applicable physical
acceptance remain open. Original/manual acceptance #72, selectors #73 and
cyber-deferred corrections #74 are not resumed; Description XML fidelity
remains #75. The new software scope advances #45 and
#57 without closing their broader acceptance obligations.
