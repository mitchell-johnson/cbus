# eDLT ordered offline Save validation prerequisite

`edlt_template_save_validation.py` adds a callable source-predicate stage to the
existing template/model receipt chain. It consumes the intact **AfterLoad**
model, checks serial, Scene-widget configuration and unit validation in original
Save order, and publishes an immutable diagnostic receipt. It never calls
`prepare_save`, generates CRCs, dispatches SaveDialog or writes to a target.
Run this stage before using the separate terminal model projection.

This is source proof and a bounded software projection. It is not execution of
the original validators, controls or callbacks. Historical managed-proxy and
native durability receipts remain unchanged and prove their original narrower
scopes. No new original runtime, GUI, native service or physical operation was
performed for this step.

## Callable contract

```python
from cbus_toolkit.edlt_template_save_validation import (
    EdltTemplateSaveValidationStage, SaveValidationContext,
    ValidationGroupName, ValidationLevel, ValidationDynamicVariant,
)

context = SaveValidationContext(
    serial_text="000000004095",  # exact tbSerialVer.Text snapshot
    group_names=(ValidationGroupName(56, 42, "Synthetic group"),),
    levels=(ValidationLevel(202, 42, 2, (
        ValidationDynamicVariant("Synthetic action", False),
        ValidationDynamicVariant(None, False),
        ValidationDynamicVariant("", True),
        ValidationDynamicVariant("Synthetic icon", True),
    )),),
)
validator = EdltTemplateSaveValidationStage(model_issuer)
receipt = validator.stage(
    second_model,
    current_source=post_assignment_raw_strings,
    metadata=original_cache_facts,
    context=context,
    dirty_parameters=original_dirty_names,
)
validator.validate(
    receipt,
    current_source=post_assignment_raw_strings,
    metadata=original_cache_facts,
    context=context,
    dirty_parameters=original_dirty_names,
)
diagnostics = receipt.as_dict()
```

For an `EdltTemplateLifecycleStage` issuer, supply its combined receipt and the
original `TemplatePpSnapshot` as `current_source`. Omit `dirty_parameters`; its
assignment stage issues those facts. There is no receipt deserialization path.

The context does not attest a fresh control, cache or parent lifecycle. Missing
metadata rows mean **unknown**, not absent. Group names are required only for
the first corridor conflict. DynamicAll facts are required only for levels
actually read by dynamic Scene widgets. Names retain the distinction between
null and empty; images are represented by their null/non-null presence. The
bounded profile admits initialized collections of zero through four variants,
byte-address applications/groups/levels and stable references from the issued
KEYGL5 / 5055EDL / 5.5.00 model.

## Recovered ordering and outcomes

The original `FrmBaseUnit.Save` first checks **control text**, not model PP
serial data. Length and last-four extraction use UTF-16 code units. Text shorter
than four units succeeds before parsing. This implementation admits ASCII
digits in the final four units and the inclusive 0..4095 range. Other suffixes
return `unproven_serial_parse`, because the original uses CurrentCulture
`Convert.ToInt32` and propagates parse exceptions. Signs, whitespace and other
culture profiles are not silently reinterpreted. Out-of-range values return
`serial_rejected`; the original shows a dialog, ignores its result and returns
false. Neither case continues to later gates.

Scene widgets are selected in retained widget order using stored WidgetType 6.
Dynamic label/status options and raw variant indices follow the original byte
and nibble checks. A null label Name skips both sides, including a bad status
variant; an empty Name does not skip. A bad accessed index records
`expected_original_exception`. Inconsistencies return `scene_widget_rejected`
before unit validation. The receipt lists label errors before status errors,
deduplicates scene identity per widget and preserves local slot order; it does
not claim the original Dictionary/HashSet enumeration order or render original
dialog strings and scene names. The original dialog result is ignored.

The original Scene-widget missing-application branch returns true immediately,
discarding prior errors. An intact second-model receipt requires application
202, so this branch cannot be observed in the admitted profile. No substitute
absence boolean is accepted as proof of the add-request outcome.

Unit validation acquires every widget group **before** corridor validation,
even when link=255. It retains collection order and duplicate group references,
using the established seven-family model mapping. The first matching corridor
group supplies TagName for the exact error message. Scene checks still run
after a corridor failure; their one composed message appends after it. The
scene scan preserves the original outer skip once both populated-missing flags
are set, includes empty scenes in duplicate pairs, and excludes action 255
rather than action -1. Lazy property reads preserve the original short circuits.
`unit_rejected` carries the exact corridor/scene messages and warning order.

## Getter effects, publication and failure

The original getters are not all reads. SceneCycle clears/rebuilds a BindingList
with events suppressed and scans bytes 13..21. Values 0..8 are retained until
the first invalid byte; that byte stays unchanged, while later bytes become
255. Those setters render exact `0xFF` and compare raw strings, so decimal
`255` or lowercase `0xff` in a trailing byte still requires a write. The
projection admits only that raw fixed point and otherwise returns
`requires_validation_mutation` without writing any bytes. Even for a fixed
point, original list/event effects are unexecuted and named in the receipt.

Trigger, action and widget-group getters can request application/group/level
creation and normalize state. The projection requires already existing facts.
An editable scene with stored action -1 is refused when actually read: the
original invokes setter(-1), refreshes dynamic labels and notifies subscribers,
even when the stored action remains unchanged. Unknown facts return
`required_fact_missing`; known states requiring writes/add requests return
`requires_validation_mutation`. A skipped original getter is not preflighted
eagerly. These are explicit offline admission decisions, not invented native
failure outcomes. A stopped gate stays incomplete rather than publishing an
invented complete unit result.

The issuer verifies the source, specification, cache, dirty facts, retained
graph, context and upstream cancellation before/after staging and again on
`validate`. Clones, tampered receipts, foreign issuers and stale inputs fail.
One issuer performs one projection. Reentrancy/cancellation during staging are
refused; unexpected failure or interruption publishes no candidate and retains
detached failure evidence. Local cancellation invalidates this receipt without
claiming original Cancel or changing the upstream model.

`source_predicates_passed` means only that these admitted source predicates
passed. Every outcome keeps `original_save_validation_verified`,
`complete_parent_lifecycle_verified`, `cache_freshness_verified`,
`apply_allowed`, `save_dispatched` and `saved` false. Both `apply` methods refuse
before inspecting a target.

## Remaining closure

An actual parent binding/control snapshot, proven Reset/Before/After callback
outcomes, any required add-request/getter notification effects, validation
dialogs, and the native host SaveDialog subscriber remain unobserved. A void
dispatch or Boolean return cannot replace native save and fresh-reload receipts.
The owned synthetic native durability proof covers only its retained image.
Original UI state is unavailable locally under this task's no-GUI/no-CPU-probe
constraint. Freshness and runtime acceptance cannot be closed from static IL.

A disjoint recoverable next workflow can export this validation receipt with
the terminal complete-image/diff receipt for review, retaining source/cache
fingerprints and an explicit untouched source. A later persistence adapter must
consume those intact prerequisites, require a concrete native save receipt and
fresh reload, and preserve failure/uncertainty evidence without automatic retry.
That workflow must continue to refuse full template Apply until parent lifecycle
and callback prerequisites are actually supplied.

Sanitized source contracts and vectors:

- [Serial](../research/edlt_template_serial_validation_source.json)
- [Scene widget](../research/edlt_template_scene_widget_validation_source.md)
- [Unit](../research/edlt_template_unit_validation_source.md)
- [Unit vectors](../research/edlt_template_unit_validation_source.json)
- [Combined source fingerprints](../research/edlt_template_save_validation_source.json)
- [Nine synthetic receipts](../research/edlt_template_save_validation_offline_attempt1.json)

The retained software run passed all nine expected source-contract outcomes and
verified that its input fingerprints, upstream models and seven historical
receipts stayed unchanged. These are synthetic receipts, not new original
runtime or native acceptance. Reproduce to a new exclusive output path:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests:. /path/to/python3.13 \
  -m research.edlt_template_save_validation_evidence \
  --output /tmp/edlt-template-save-validation-new-receipt.json
```

Focused verification uses the existing Python 3.13 toolchain, with no new
dependencies or builds:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests:. /path/to/python3.13 -m pytest \
  -q -p no:cacheprovider tests/test_edlt_template_save_predicates.py \
  tests/test_edlt_template_save_validation.py
```

The focused run for this change passed 57 tests, including UTF-16 extraction,
the source vectors, exact scene/corridor messages, lazy getter skips, raw token
fixed points, immutable issuance, stale input rejection, cancellation and
interruption. No broad suite or Rust build was run, as instructed for this task.
