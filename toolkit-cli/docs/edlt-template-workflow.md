> Integration update: root CLI registration and the separate parent local stager are now implemented. Apply remains refused; see [integration boundaries](edlt-template-integration-boundaries.md).

# eDLT template interchange and staged preview

The dedicated `edlt_templates` API validates and preserves the ordered eDLT
template representation, exports a template from explicit ordered source
attributes, and previews assignment candidates. It does not reset a unit,
change a programming session, execute parent bindings, or save anything.
Every preview has `apply_allowed=false`; its `apply(target)` entrypoint refuses
before accessing the target.

This is useful file interchange and validation, not a completed TemplatesDialog
load or Apply workflow. [Issue #43](https://github.com/mitchell-johnson/cbus/issues/43#issuecomment-5906822582)
owns the format, CRC and ordered assignments.
[Issue #45](https://github.com/mitchell-johnson/cbus/issues/45#issuecomment-5906824162)
owns the required reusable parent reset/rebind transition. Existing classic and
NeoPro [unit templates](unit-templates.md) retain their separate admitted
profiles and transactions.

The isolated implementation starts at repository main
`8f1608b91d3ce155e1ce42e8b0df0dfc4ecd91d4`. Only new, narrowly scoped files are
added. The [central registration patch](edlt-template-registration.patch) is
provided for the owner and passes `git apply --check`; it has not been applied.

## Callable boundary

The API is in [edlt_templates.py](../src/cbus_toolkit/edlt_templates.py):

```python
from cbus_toolkit.edlt_templates import (
    EdltTemplate, export_edlt_template, preview_edlt_template,
)

template = EdltTemplate.from_xml(xml_bytes)
preview = preview_edlt_template(
    template,
    pp_attribute_names=ordered_known_names,
    spec=target_spec,
    target_firmware="5.5.00",
)
# Review the diagnostic result. No unit or PP session was opened or changed.
# preview.apply(target) is an unconditional refusal.
```

`spec` and `target_firmware` are optional validation context. A declared list of
known PP names determines candidate assignments; it is not a live observation
of a target or proof of its setter behavior. The preview retains duplicate
assignments and their child order, reports local validation failures and
warnings, and exposes the Application conversion separately. It does not
compute an `after_reset` image, a final PP image, control state, or expected
save CRCs. A candidate value is not an executed setter.
`raw_setter_validated=false` remains explicit even when the local schema
accepts every value: schema tokenization can normalize spaces or accept an
array shape whose original raw setter has different tail/dirty behavior.

`export_edlt_template(description=..., firmware=..., unit_name=...,
primary_application=..., secondary_application=..., pp_attributes=...)`
requires ordered `(name, raw_value)` pairs for the original PPAttributes
enumeration. The explicit unit name and application properties are part of
the original export contract. Do not claim that an arbitrary mapping or a
generic `session.values()` result supplies the same complete enumeration,
order, or computed property values without independent evidence. Preserve
raw value spelling; do not sort attributes or normalize all numeric values
before export.

`EdltTemplate.to_xml()` serializes the accepted template representation. The
parser's deliberately bounded text-only XML profile excludes nested markup,
entities and other unproved XML forms. Original XmlDocument `InnerXml`
behavior for excluded forms is not inferred. A refusal of such a form is a
documented admission boundary, not an assertion that Toolkit rejects it.

The separate [edlt_templates_cli.py](../src/cbus_toolkit/edlt_templates_cli.py)
module provides inspect, preview and export. Registration in the central CLI
is an owner integration step. No command should expose database import,
reset, `--apply`, PP SAVE or project SAVE through this staged layer.

From `toolkit-cli/`, the standalone entrypoint is usable immediately:

```sh
PYTHONPATH=src python -m cbus_toolkit.edlt_templates_cli inspect template.xml
PYTHONPATH=src python -m cbus_toolkit.edlt_templates_cli preview template.xml --pp-attribute-names names.json
PYTHONPATH=src python -m cbus_toolkit.edlt_templates_cli export source.json --output new-template.xml
```

`names.json` is an explicit JSON string array. `source.json` has exactly
`description`, `firmware`, `unit_name`, `primary_application`,
`secondary_application` and `pp_attributes`; the last is an ordered array of
`[name, raw_string]` pairs. Export creates a new file exclusively. An existing
file is preserved. A failed write reports whether the new file may be partial.
The `apply` command returns a structured refusal before reading any input.

The accepted file profile is deliberately narrower than the original:

- UTF-8, at most 1 MiB and 4,096 plain, flat fields, without attributes,
  namespaces, comments, DTDs, CDATA, entities or extra processing instructions;
- one pre-CRC UnitType and FirmwareVersion, exactly one decimal UInt16 CRC,
  and matching values in any repeated identity fields;
- empty or single-line raw text; whitespace-only and XML-sensitive values
  are refused, including literal `>` whose original `InnerXml` is `&gt;`;
- export requires a unique supplied PPAttribute collection and byte-valued
  application properties. Import inspection retains repeated ordinary fields,
  including fields before CRC, without declaring those duplicates safe to apply.

This avoids silently escaping values the original exporter interpolates raw,
normalizing its XML line endings, selecting the last of conflicting headers,
or discarding part of the assignment history. The format layer can inspect an
empty payload, but this is never native or lifecycle admissibility.

## Original order recovered from the managed binary

Toolkit 1.18.0.2754 uses `eDLT.dll` version 7.16.0.0, SHA-256
`75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3`.
The 2026-09-30 fresh managed pass pinned these methods independently of the
Python implementation:

| Original method | Token / RVA | Relevant contract |
| --- | --- | --- |
| `TemplatesDialog.BtnSaveClick` | `060001E6` / `F024` | Ordered export, duplicated identity headers, explicit UnitName/Application |
| `TemplatesDialog.BtnLoadClick` | `060001E7` / `F368` | Validation, ordered CRC, reset, ordered assignments, rebind, deferred persistence |
| `FrmBaseUnit.BeforeChangePpAttributes` | `060002DD` / `1851C` | Stop redraw and change seven bound radio selections |
| `FrmBaseUnit.AfterChangePpAttributes` | `060002DE` / `18588` | Rebuild the model and refresh parent bindings in order |

The load transition is:

1. Validate the exact `UnitTemplate` root and read identity headers. UnitType
   must be `KEYGL5`; FirmwareVersion must be nonempty. The original does not
   compare source firmware with destination firmware.
2. Collect the `InnerXml` values of children after the first CRC in child
   order, calculate the shared checksum, and compare it with the stored CRC.
3. Invoke `ResetUnit(true)`. The original discards its Boolean return value.
4. Invoke `PopulateWidgetPanels`, then `BeforeChangePpAttributes`.
5. Traverse **all root children** in XML order, not just children after CRC.
   Convert a nonempty Application from space-separated decimal integers to
   lowercase `0x` strings. For every child, enter static PP initialize mode,
   look up its name, and, if a known attribute's current raw string differs,
   assign `Value` and explicitly mark `HasBeenChanged=true`. Leave initialize
   mode after each ordinary iteration. Unknown PP names are skipped.
6. Invoke `AfterChangePpAttributes` and display success. Persistence occurs
   only through a later unit-dialog Apply or OK.

Export writes UnitType and FirmwareVersion before CRC and again in the
checksummed body. It exports UnitName explicitly and Application as the
primary/secondary decimal properties. Its subsequent PP loop excludes
UnitAddress, Application, Project, NetworkAddress, UnitName and SerialNumber.
Those are **export exclusions**: the import assignment loop has no matching
identity exclusion list. Do not infer destination identity preservation for
an arbitrary hand-authored template.

The shared CRC trims values for concatenation but tests the original
untrimmed value for its `0x` prefix. It uses the low byte of each UTF-16 code
unit and omits the final byte from the CRC input. Attribute names and sorted
maps are not substitutes for the original ordered value stream. Duplicate
matching identity fields are part of the normal export structure; collapsing
them can change the checksummed stream and assignment history.

The CRC seed is `0xFEED`, polynomial `0x1021`, no final XOR. Each input byte is
fed least-significant bit first into the CRC's high bit. Lowercase `0x` at the
start of the original string invokes literal-space tokenization and signed
Int32 hexadecimal-to-decimal conversion before concatenation. This branch
rejects repeated/trailing spaces rather than removing empty tokens. The
buffer holds at most 65,536 UTF-16 low bytes. The final byte omission means
some altered values still have a matching original CRC; the emitted
`canonical_xml_sha256` separately identifies the canonical file representation.

The original's culture-sensitive `StartsWith("0x")` can ignore a zero-width
joiner or NUL in a prefix. The helper refuses ambiguous prefixes that become
`0x` after removing control, format or combining-mark characters. This is a
deliberately narrower admission rule, including some forms the original
accepts, rather than an inference from the host's locale. The evidence uses
the owned runtime's invariant culture; arbitrary Windows locale equivalence
is not claimed.

The loop does **not** exclude UnitType or FirmwareVersion. If the caller's
PP collection contains them, export adds further matching occurrences after
the explicit body identities. Do not assert that a real unit always has that
collection shape without observing it.

`BeforeChangePpAttributes` stops `RedrawTimer` and sets the original
`radioButton5`, `radioButton3`, `rbColourIndicatorOffFixedColour`,
`rbColourIndicatorOnFixedColour`, `radioButton4`, `radioButton6` and
`rbRestorePreset` to checked. These are control writes that may fire bindings,
not merely diagnostic phase names.

`AfterChangePpAttributes` invokes, in order:

1. `EDLTUnit.AfterLoadPPData`;
2. `SetupForm`;
3. recursive `SetUpControls(Controls)`;
4. `PopulatePrimarySecondaryApplication`;
5. `bsMainUnit.ResetBindings(true)`;
6. `UpdateNavigationControl`;
7. `ShowSelectedWidget`;
8. `tpKeyFunctions_SelectedIndexChanged(this, null)`;
9. `RedrawTimer.Start()`.

The local fresh pass retains exact method IL-byte hashes and offsets in
`managed-pass/method-proofs.json` and source analysis in
`managed-pass/FINDINGS.md`. These are private research artifacts; full vendor
assemblies and disassembly must not be committed. Static source order does
not establish that a complete original form executed this history.

## Why existing parent operations do not authorize Apply

The [retained lifecycle](edlt-lifecycle.md) provides model load/save phases and
five save CRCs. The [Reset helper](edlt-reset.md) supplies a real issued fresh
graph, exact raw strings, token tails, dirty flags and initialize-mode phases.
The [parent transaction](edlt-parent-transaction.md) composes admitted typed
controls on that graph and performs one terminal save projection. These are
useful dependencies, but none is the template transition described above.

| Required gate | Existing evidence and remaining dependency |
| --- | --- |
| Source editor state | Reset covers explicit Widgets, General, Standby and Colour tabs, initial navigation 0/1 and bounded stored widget types. Its bindings are partial or audited local wiring. Arbitrary prior editor/binding history is unproved. |
| Reset outcome | Reset has checked original successes. Template code ignores failure. A safe adapter must require an explicit successful result before any imported assignment. |
| Second model rebuild | Template import resets, then populates panels, changes raw PP, and calls a further AfterLoad/rebind. Parent typed edits retain their issued graph; generic raw assignment cannot be inserted as an equivalent typed operation. |
| Raw setter semantics | The original PP `Value` setter can preserve an unsupplied array tail. Assignment order, duplicates, raw spelling, initialize mode and dirty flags therefore matter beyond independently codec-valid values. |
| Cache and binding effects | Application lists, existing groups, scene objects, language/image variants, navigation, selected widget and active page must describe the same retained parent. Supplied names or a flat PP snapshot do not prove those facts. |
| Terminal validation/save | Active-control validation, serial and scene checks, `EDLTUnit.IsValid`, BeforeSave and CRC work must run after the imported graph is rebound. A successful file CRC is unrelated to this gate. |
| Complete original comparison | Existing Reset and component captures do not execute the complete original template load/rebind/Apply history, including failure and cancel branches. |

The separate [Global-factory Reset](edlt-reset-factory.md) is narrower still:
it admits six captured whole numeric source patterns and a specific Global
tab removal transition. It is not a general escape from the template gate.
The current format layer intentionally does not mutate shared parent or
metadata implementations to bypass any of these requirements.

## Failure and future transaction contract

The original assignment loop has no restoration of prior values and no
`finally` protecting `PPAttribute.bInitialiseMode`. An exception may leave a
partial editor state and initialize mode set. Its enumerator cleanup and
outer control-visibility cleanup do not repair that state. The safer current
behavior is explicit: all work is local parsing/preview, and every attempt to
apply refuses before target access. There is no hidden partial apply or
rollback claim.

Before enabling application, the lifecycle owner must provide an issued,
snapshot-bound reset/rebind transaction with an explicit original control
context and complete cache facts. It must preflight every admitted assignment,
retain exact order and raw strings, reject stale inputs, require successful
reset, and publish no persistent change before a separate Apply/OK boundary.
Failure must preserve the cause and phase evidence; cancellation must discard
the staged editor. A future PP/database adapter must also distinguish staged
changes, confirmed PP save, project save and uncertain persistence, and must
not automatically retry an uncertain save.

Acceptance must include reset false/exception, a failure after an earlier
assignment, an interruption, duplicate/degenerate/native-inadmissible inputs,
stale bindings, page and selected-widget refresh, cancel without save, and
one successful original load/rebind/Apply followed by native save/close/load.
Until that receipt exists, keep `apply_allowed=false` even if all format and
individual codec checks pass.

## Reusable research fixtures

[edlt-template-original-vectors.json](../research/fixtures/edlt-template-original-vectors.json)
retains 73 synthetic original/runtime cases: 50 unchanged original CRC-helper
calls, four raw-helper calls, 11 framework Application conversions and eight
framework XML file-load cases. The original helper executes under the pinned
owned Mono runtime with network denied. The separate framework cases repeat
the recovered operations; they do not execute TemplatesDialog. The receipt
pins assembly and method hashes and explicitly keeps original dialog, parent
lifecycle and physical verification false.
The [acceptance receipt](../research/fixtures/edlt-template-original-acceptance.json)
binds the retained fixture to a second fresh original replay: all 73 cases
matched, and original/runtime input hashes remained unchanged.

[edlt_template_original.py](../research/edlt_template_original.py) and its
[C# probe](../research/edlt_template_original_probe.cs) reproduce those bounded
observations from explicit local original/runtime paths. Their `--verify-fixture`
option compares all fresh literal results with the retained fixture. No native
C-Gate persistence acceptance is claimed for this staged-only layer; it has no
admitted target mutation to save/reload. Portable tests compare the supported
format and conversion profile with these original literals.

| Fixture or harness | Useful scope | Limit |
| --- | --- | --- |
| [NativeEdltResetMatrixProbe.cs](../research/NativeEdltResetMatrixProbe.cs) and [captured vectors](../research/fixtures/edlt-reset-windows-vectors.json) | Original Reset/component arms; 874 raw fields, token/dirty phases and initialization state | Controlled partial WinForms context; no full LoadUnit/SetEDLTFrm, template load or renderer flush |
| [NativeEdltResetNavigationTrace.cs](../research/NativeEdltResetNavigationTrace.cs) | Distinguishes snapshot reads from binding-driven navigation normalization | Captured Reset contexts only |
| [NativeEdltLifecycleProbe.cs](../research/NativeEdltLifecycleProbe.cs) and [lifecycle acceptance](../research/fixtures/edlt-lifecycle-acceptance.json) | Original model constructors, cache facts, AfterLoad/BeforeSave and CRC behavior | No complete parent bindings or template workflow |
| [test_edlt_reset_native.py](../tests/test_edlt_reset_native.py) | Pattern for synthetic database PP stage, all-field/raw readback, save/close/load and `state=new` proof | Existing Reset tests are not template acceptance; require explicitly configured owned oracles |
| [local_cgate.py](../research/local_cgate.py) | Owned hash-pinned C-Gate 3.4.0.2001 child with ephemeral loopback ports, empty project ownership and no auto-reopen | Original persistence oracle only; no proof of Toolkit UI or physical behavior |
| [windows_bridge.py](../research/windows_bridge.py) and [windows_provenance.py](../research/windows_provenance.py) | Existing file-only Windows .NET model runner and generation-bound provenance | Availability must be checked explicitly; do not adopt an unknown process or shared live project |

Private fixture roots on the research host contain `toolkit/app`,
`unitspec-plain/KEYGL5.xml`, `cgate/app`, owned Mono and Java runtimes, and
historical `edlt-reset-controls`/`edlt-lifecycle` reports. They are optional
research inputs, not packaged production dependencies. Reuse exact pinned
files and isolated synthetic projects only. A format/CRC oracle can run
without opening any network; a native persistence comparison must keep every
synthetic C-Bus network closed and must never issue `NET OPEN` or a physical
unit command.

Central CLI registration should expose only this module's admitted file
operations. Capability/coverage owners should record format/preview support
separately from outstanding template apply and full parent equivalence; a
command being registered does not close either issue.

## Focused validation

Run from `toolkit-cli/` with Python 3.13 and the test extra:

```sh
PYTHONPATH=src:tests python -m pytest -q -ra -p no:cacheprovider \
  tests/test_edlt_templates.py tests/test_edlt_templates_cli.py \
  tests/test_edlt_template_original_vectors.py \
  tests/test_unit_templates.py tests/test_unit_templates_neo.py
```

The 2026-09-30 run passed 59 tests and 196 subtests. Six pre-existing classic/Neo
tests skipped because their original executable, native C-Gate, or specification
environment variables were not configured for that run. These skips are not
eDLT acceptance. The eDLT format, CLI and literal-vector tests had no skips.
No full suite, Rust build, network unit operation or physical-device test ran.
