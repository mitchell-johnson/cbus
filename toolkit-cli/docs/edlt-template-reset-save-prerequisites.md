# eDLT template reset and terminal model prerequisites

This follow-on adds two callable prerequisites around the existing
[assignment and second-model stages](edlt-template-staged-lifecycle.md).
They establish bounded Reset provenance and prepare a retained model's final
PP image. They do not silently bridge the still-unproved parent callbacks.
No template Apply operation is registered or enabled.

## Bounded Reset receipt

[`EdltTemplateResetPrelude`](../src/cbus_toolkit/edlt_template_reset_prelude.py)
uses the existing `prepare_unit_reset` entry point, stopping before terminal
BeforeSave and CRC work. It copies the complete ordered source tokens,
specification and application cache, then records the original supported
partial-dialog context: Widgets, General, Standby or Colour with an explicit
binding variant. Its source is the PP input to that bounded initialization,
not an arbitrary retained Toolkit editor history.

```python
from cbus_toolkit.edlt_template_reset_prelude import EdltTemplateResetPrelude

resetter = EdltTemplateResetPrelude(spec)
prelude = resetter.stage(
    source, metadata=application_cache,
    active_tab="widgets", binding_variant="audited-local-wiring",
)
resetter.validate(
    prelude, current_source=source, metadata=application_cache,
    active_tab="widgets", binding_variant="audited-local-wiring",
)
```

The receipt checks defaults, excluded raw tokens, all 21 cleared byte-one
fields, the fresh Blank graph and exact Widget10 Time/Date insertion. It does
not rely on the original reset Boolean, which can mask a failed default reset.
Source, specification, cache, tab, binding variant, graph identity or receipt
changes invalidate validation. Failure publishes no candidate; cancellation
invalidates the issued handle without replaying original Cancel.

`after_reset` comes directly from the retained phase's token arrays and dirty
flags. It is **not** an attested post-BeforeChange assignment source. The
template next reconstructs panels and invokes BeforeChange again. Those
callbacks are fixed unresolved obligations; the API accepts no caller Boolean
that can promote them to success and performs no automatic assignment chain.

Reset preparation performs two model loads: initial initialization and the
fresh reset graph. A later post-template model reconstruction would be the
third load in that combined history. The earlier stage name “second model”
describes its isolated before/after-template comparison, not a total count
for Reset plus template loading.

## Retained terminal model receipt

[`EdltTemplateTerminalStage`](../src/cbus_toolkit/edlt_template_terminal_stage.py)
accepts an intact model-stage or lifecycle-stage issuer and its issued
candidate. It validates that upstream candidate before and after one
`prepare_save` call on the same retained lifecycle. It does not reload the
model, reinterpret a JSON receipt, or invoke the original Save event.

```python
from cbus_toolkit.edlt_template_terminal_stage import EdltTemplateTerminalStage

terminal = EdltTemplateTerminalStage(lifecycle_stager)
image = terminal.stage(
    lifecycle_candidate, current_source=assignment_source, metadata=lifecycle_cache,
)
terminal.validate(image, current_source=assignment_source, metadata=lifecycle_cache)
```

The output contains the complete validated numeric/text PP image, five OEM
CRCs, and lossless canonical PP rendering. It retains the model's scene, label
and MRA state and separates the before-CRC image from final values. Canonical
rendering does not claim original terminal setter spelling or dirty flags.

Active-control flush, serial/scene/unit Save validators, parent callbacks,
native host dispatch and persistence remain unexecuted. `apply` refuses before
target access, even for an intact final image. A cancelled upstream lifecycle
candidate cannot validate its later terminal receipt. Reentrant staging,
mid-stage cancellation, foreign receipts and stale sources are rejected.

## Callback outcomes and the remaining original-state gap

The [static provenance analysis](edlt-template-reset-beforechange-provenance.md)
and [outcome classifier](../research/edlt_template_rebind_outcomes.py) distinguish
ordinary dispatch, caught binding failures and propagated failures using the
previously retained 31-case proxy fixture. No new original GUI or interpreter
probe is required. A normal return can still follow a caught binding error or
OnFormClosed; it is not proof that controls successfully rebound.

The second BeforeChange depends on actual radio grouping and checked state,
binding source identity, update mode and event/subscription history. The
recorded reset PP values alone cannot reconstruct those facts. Original
Windows form state is needed to accept this exact retained control history;
the locally available managed/model and static evidence does not supply it.

The remaining save validators can be recovered independently of that UI gap,
but their acceptance must remain separate from model normalization and native
image durability. A database-only native save/reload receipt can prove that a
synthetic closed-model image persisted; it cannot prove template GUI behavior,
validation dispatch success, label rendering or physical-device effects.

The two earlier commits remain unchanged. Shared parent modules and central
registration are untouched; the earlier parent factory patch remains an
unapplied integration proposal for its owner.

## Focused verification

The [retained Reset comparison](../research/fixtures/edlt-template-reset-prelude-original-acceptance.json)
passes all 44 original cases through `after-reset`: 432 phases, 377,568 exact
raw comparisons, 432 dirty sets and 432 initialization flags. It observes 88
model loads and zero guarded terminal save/CRC or socket connection calls.
This is a fresh local comparison against retained Windows observations, not
44 new original-runtime executions.

The focused Python slice passes **86 tests and 308 subtests, with no skips**.
It includes the new Reset/terminal guards and existing assignment, second-model
and aggregate-stage regressions. Set `CBUS_UNITSPEC_DIR` to the explicit private
original specification directory for the retained Reset comparison:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.13 -m pytest -q -p no:cacheprovider \
  tests/test_edlt_template_reset_prelude.py \
  tests/test_edlt_template_reset_prelude_original.py \
  tests/test_edlt_template_terminal_stage.py tests/test_edlt_template_staging.py \
  tests/test_edlt_template_assignment_vectors.py tests/test_edlt_template_model_stage.py \
  tests/test_edlt_template_lifecycle_stage.py
```

The callback classifier reproduces its committed report exactly and rejects
changed input. No new WinForms, managed-runtime or IL-interpreter probe, broad
build or full test suite was run for these prerequisites.

Three additional tests in `test_edlt_template_terminal_native.py` pass without
starting a service. They check primary-error preservation across multiple
cleanup failures, interrupted cleanup and hostile exception formatting. The
native helper records PP and project save attempts, confirmed replies and
uncertain outcomes separately from fresh readback and cleanup. It never retries
a save automatically. Its application/group cache is explicitly synthetic,
not derived from or created in the temporary project.

The [first owned native run](../research/edlt_template_terminal_native_attempt1.json)
passes: 43 changed parameters staged; one successful PP save reply; project
save/close/load; then all 874 values, five CRCs and eight raw regions (338
bytes) match in a fresh PP session. The network remains `state=new` before and
after save. The loopback CNI sentinel receives zero connections; listener
ownership, child exit and temporary-directory removal are verified. Script,
runtime-helper, model and private specification source fingerprints remain
unchanged. The final and reloaded image hashes match. This receipt proves only
the explicitly scoped synthetic image's database durability.

A useful disjoint continuation is an offline Save-validation workflow covering
the original serial, Scene-widget and unit scene/corridor validators. Those
model checks can be recovered separately from WinForms binding state. They
would improve the terminal receipt without inventing missing callback or
persistence guarantees.
