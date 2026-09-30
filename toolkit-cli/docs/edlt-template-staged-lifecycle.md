> Integration update: root CLI registration and the separate parent local stager are now implemented. Apply remains refused; see [integration boundaries](edlt-template-integration-boundaries.md).

# eDLT template assignment and second-model staging

This follow-on to the [format/preview layer](edlt-template-workflow.md) computes
actual raw setter effects and reconstructs the unbound model after those
assignments. It replaces an ordered list of candidate values with an immutable,
source-bound local stage. No source editor, programming session, database or
physical unit is modified. Apply remains unavailable because real parent
callbacks and their failure reporting have not been accepted together.

The first format commit `7a23fb5d42d6f74a443df251622ca9f5f6e46565` is unchanged.
This work adds separate modules, tests and bounded original evidence. It does
not alter the shared parent editor or register a new applying operation.

## Exact PP assignment stage

[edlt_template_staging.py](../src/cbus_toolkit/edlt_template_staging.py) consumes
the exact ordered `PPAttribute.Values` token arrays, dirty flags and initialize
state. A joined `PPAttribute.Value` string is insufficient: leading empty/null
slots disappear in the getter, and a short setter preserves the old tail.
Null tokens, duplicate attribute names, and an already-initializing source are
explicitly outside this safe input profile.

```python
from cbus_toolkit.edlt_templates import EdltTemplate
from cbus_toolkit.edlt_template_staging import (
    TemplatePpSnapshot, EdltTemplateAssignmentTransaction,
)

template = EdltTemplate.from_xml(xml_bytes)
source = TemplatePpSnapshot(tuple(
    (row["name"], tuple(row["tokens"]), row["dirty"])
    for row in observed_pp_attributes
))
transaction = EdltTemplateAssignmentTransaction(source)
stage = transaction.stage(template)
transaction.validate(stage, current_source=source)
report = stage.as_dict()
# transaction.cancel() discards the local candidate and invalidates the handle.
# Both transaction.apply(target) and stage.apply(target) refuse before access.
```

The source boundary is **after BeforeChangePpAttributes and before the XML
assignment loop**. This API does not infer or attest how a caller reached it.
An issued Reset result alone does not attest the additional panel-population
and BeforeChange callbacks. The report makes caller-boundary observation false.

For every XML child, including pre-CRC headers, the stage performs Application
decimal conversion before attribute lookup, enters local initialize mode,
compares the original joined raw value, overwrites supplied slots without clearing
the tail, and explicitly marks changed assignments dirty. Unknown names are
skipped, and duplicate XML fields run in order. Exact lowercase `0xffffffff`
becomes `0xff`; `$x` preserves suffix case; `$` uses the bounded ASCII uppercase
conversion. Ambiguous culture-sensitive dollar prefixes, control characters,
non-ASCII casing and lowercase `i` in the uppercasing branch are refused. Original `$i` becomes
`0xI` under en-US but `0xİ` under tr-TR. The `$x` branch does no uppercasing.
These restrictions are stricter than original input handling.
The [two-culture observation](../research/edlt_template_assignment_culture_evidence.json)
and its pinned reproducer retain that specific casing distinction.

Raw equality and normalized equality are different. Assigning `$ab` to
`['0xAB', 'tail']` leaves those tokens unchanged but still marks the attribute
dirty because the original raw comparison differed. Assigning `X` to
`['A', 'B', 'C']` produces `['X', 'B', 'C']`; it is not replacement with a
one-element array.

The stage deliberately does not invoke BindingList or PropertyChanged
subscribers. Original listeners can throw after an earlier token has changed.
All local changes remain private until the complete assignment sequence
succeeds. A conversion/setter error or interruption publishes no candidate,
preserves the source and records the failed child plus completed steps.
Failures end the transaction; retry requires a new one. A local cancel discards
the candidate and invalidates its issued handle. This is a safety policy, not
an assertion that original Cancel rolls back its model.

## Second model reconstruction

[edlt_template_model_stage.py](../src/cbus_toolkit/edlt_template_model_stage.py)
uses the existing exact-profile `EdltLifecycle.load` plus its bounded raw
AfterLoad projection. It accepts every raw field of the supplied KEYGL5 /
5055EDL / 5.5.00 specification, explicit `LifecycleCache` facts and the inherited
dirty-name set. It creates a fresh widget/scene/static-label model from the
post-assignment data without using Reset's save path.

```python
from cbus_toolkit.edlt_template_model_stage import EdltTemplateModelStage

loader = EdltTemplateModelStage(specification)
model = loader.stage(
    stage.after.raw,
    metadata=lifecycle_cache,
    dirty_parameters=[name for name, tokens, dirty in stage.after.parameters if dirty],
)
```

The adapter copies the specification/cache and binds the result to their hashes,
the raw source spelling and dirty flags. Validation rejects foreign, cloned,
altered or stale receipts. Complete original token topology cannot be recovered
from joined strings; this adapter reports that limit instead of claiming an
exact token-array capture. Numeric arrays with ambiguous token spacing are
refused before model load. A failed load returns no partial model receipt.

The [aggregate stage](../src/cbus_toolkit/edlt_template_lifecycle_stage.py)
combines assignment and second load as one local publication boundary. If the
second load fails, it discards the assignment candidate too. The
[parent integration patch](edlt-template-parent-stage.patch) is provided for
the shared-module owner to review and apply; it is not applied in this branch.

```python
from cbus_toolkit.edlt_template_lifecycle_stage import EdltTemplateLifecycleStage

editor = EdltTemplateLifecycleStage(specification)
candidate = editor.stage(template, source=source, metadata=lifecycle_cache)
editor.validate(candidate, current_source=source, metadata=lifecycle_cache)
report = candidate.as_dict()
# editor.cancel() discards the candidate; editor.apply(target) still refuses.
```

The combined stage requires firmware 5.5.00 and exact token-to-raw round trips
before invoking its model adapter. The original importer did not impose these
restrictions. They prevent cross-profile or lossy input from becoming a model
receipt with unsupported claims.

## Recovered callback and terminal limitations

The original six-method [rebind probe](edlt-template-rebind-recovery.md)
interprets pinned original IL with explicit control/model proxies. It recovers
branch, traversal, exception and callback order; it does not run real control
binding or silently substitute a proxy for accepted form behavior.

Newly recovered details affect any future applying implementation:

- `SetUpControls` traverses children first but skips BaseWidget and its
  descendants. `ResetControlBinding` has a different traversal and does descend
  into those nodes.
- Binding exceptions can be caught, logged and followed by a message box,
  after which later controls still bind. A returned AfterChange call does not
  attest successful bindings.
- `SetupForm` can catch an error, invoke OnFormClosed, then continue its later
  setup work. It also adds event subscriptions, so callback accumulation must
  be observed across repeated template loads.
- PopulateWidgetPanels disposes old panels and creates new ones. Model graph
  reconstruction alone does not prove disposed-control lifetime, selected
  widget, active page or redraw-timer correctness.

The [terminal recovery](edlt-template-terminal-recovery.md) establishes that
Save validates serials, scene widgets and the unit before dispatching a void
save event. It can return true with no subscriber. Apply/normal OK discard
that return value; global OK follows a separate close path. Neither result
is a persistence receipt. Cancel invokes form closure; model rollback is not
established.

There is a further reset hazard: `ResetUnit(true)` can mask a false result from
ResetToDefaults inside the reset handler itself and continue into after-change
and Time/Date insertion. Checking only ResetUnit's Boolean would therefore be
insufficient. A safe adapter must attest reset postconditions and callback
outcomes, not copy the original ignored/masked results.

## Remaining acceptance gates

The local assignment and second-model stages now run and are independently
compared with original model/setter execution. Completing the applying parent
transaction still needs all of the following in one retained context:

1. Original Reset/panel population/BeforeChange effects, including internal
   ResetToDefaults failure and the exact starting token/dirty state.
2. Actual control rebinding, subscription counts, swallowed-error capture,
   selected-widget/page refresh, disposed-panel lifetime and redraw state.
3. Full failure/cancel behavior and a proven isolated candidate boundary before
   publishing any real editor changes.
4. Validation plus one save request with separately confirmed PP/project
   persistence, and no retry or inferred success after an uncertain result.

No original Windows whole-form, native C-Gate save/reload, or physical-device
acceptance is claimed. Original assemblies and full disassemblies remain
private. The new probes use existing pinned runtimes, synthetic inputs and
network-denied processes; the production stage has no transport interface.

## Focused evidence and validation

| Layer | Retained evidence | Scope |
| --- | --- | --- |
| Ordered setters | [67-case acceptance](../research/edlt_template_assignment_acceptance.json) | Unchanged original PPAttribute methods; explicit loop/lookup proxies; 52 successes and 15 expected errors |
| Second model load | [25-case acceptance](../research/fixtures/edlt-template-model-original-acceptance.json) | Unchanged original model; 49 load phases, 42,826 numeric plus 42,826 raw comparisons, and 49 dirty-set comparisons |
| Parent rebinding | [31-case fixture](../research/edlt_template_rebind_vectors.json) | Six original IL bodies interpreted with explicit proxies; 6,142 instructions and 1,972 calls; no actual control binding |
| Terminal paths | [14-case evidence](../research/edlt_template_terminal_evidence.json) | Six copied branch bodies with proxy operands and 27 original method hashes; no validators or persistence executed |

The portable model tests additionally compare all 25 repeat-load fixtures with
the new adapter using a synthetic 874-field schema. Five selected fixtures
cross the combined assignment/model boundary, including malformed-second-load
discard. Original mutable list-container identity is deliberately represented
as separate immutable snapshots; element replacement and data effects are
compared without claiming retained WinForms lists.

Run only the targeted Python slice (Python 3.13 or newer):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.13 -m pytest -q -p no:cacheprovider \
  tests/test_edlt_template_staging.py tests/test_edlt_template_assignment_vectors.py \
  tests/test_edlt_template_model_stage.py tests/test_edlt_template_lifecycle_stage.py \
  tests/test_edlt_templates.py tests/test_edlt_templates_cli.py \
  tests/test_edlt_template_original_vectors.py
```

This slice passes 98 tests and 420 subtests with no skips. The supplied parent
factory patch and the earlier CLI registration patch both pass `git apply
--check`; neither is applied. No full Python suite, broad Rust build, new
toolchain installation, native persistence or physical-device test was run.
