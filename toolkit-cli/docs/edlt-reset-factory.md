# Retained Global-factory Reset dependency

This additive, offline model transition supports the exact KEYGL5 / 5055EDL /
5.5.00 profile. It represents the original factory's initially selected Global
tab, silent Reset, and subsequent removal of that tab. It does not construct a
form, send C-Gate commands, apply Global categories, or reset physical hardware.
The existing `EdltResetControls.plan` API still accepts only its previously
tested Widgets, General, Standby and Colour contexts and initial Nav0/1 states.

## Issued state and source boundary

```python
lifecycle = EdltLifecycle(spec)
reset = EdltResetControls(spec, lifecycle=lifecycle)
preparation = EdltGlobalPreparation(spec)
receipt = preparation.factory_context(
    raw_parameters,
    reset_editor=reset,
    context=GlobalPreparationContext(source_path, form_project, cached_project),
    metadata=application_cache,
    dirty_parameters=(),
)
retained = reset.prepare_global_factory(
    raw_parameters,
    metadata=application_cache,
    preparation_context=receipt,
    dirty_parameters=(),
)
terminal = reset.prepare_global_factory_save(retained)
```

All three objects share the exact UnitSpec instance and lifecycle. The receipt
binds the full ordered 874 original raw PP strings, explicit application/cache
facts, source/form/cache project identities, dirty names and specification.
Copied, replaced, exported or foreign receipts cannot be resumed. The issued
`FactoryResetEdlt` also retains and validates its original and fresh model
objects, nested scene/group identities, exact raw phases and typed projections.
`FactoryResetSave` is a review result, not an input receipt or persistence API.

The source must match one of six **whole numeric patterns**: default-like,
rich-scene, first-mra, enable, mixed-controls or fallback127. These are exact
captured patterns, not combinations of individually allowed field values.
Changing any other field rejects preparation. UnitAddress, UnitName,
SerialNumber and Project are separately codec-validated identity inputs;
UnitAddress must equal the source unit in the receipt. The complete original
ordered layouts and defaults are pinned independently of the source pattern.
Added byte strides or endian changes are rejected. Descriptive specification
fields do not affect that layout/default fingerprint.

The additional captured sources contain types 2, 3, 4, 5, 6, 7, 8, 10, 14, 16,
127 and FF in specific configurations. This does not authorize arbitrary states
of those families. Initial Nav is FF in every accepted source. Metadata remains
caller-supplied: complete named lists and required positive facts are checked;
no groups are created and physical cache freshness is not verified.

## Exact phases

Preparation preserves the original expected source throughout. It performs the
original initial AfterLoad, conditional Project initialization, Reset component
sequence, a fresh AfterLoad of reset defaults, and Widget10 Time/Date insertion.
The resulting Reset still has literal `NavWidgetType=0xFF`. A separate
`after-global-tab-removal` phase then has `0x0`.

The original difference is a bound `MultiPage` getter when
`TabPages.Remove(tpGlobal)` exposes Widgets. The captured initial bindings,
panel setup and Reset on Global retain FF. Full raw snapshot captures were
checked for getter side effects; the read itself does not normalize Nav.
The model exposes `conditional-project-initialization` for the original
`after-conditional-project` capture label.

Reset recreates all 21 widget models and eight scene models. Old loaded scene
objects remain in the initial diagnostic state; they are not reused as reset
scene content. The fresh objects, their cached group identities and MRA state
are retained into BeforeSave. Terminal preparation consumes this state without
a third AfterLoad. It preserves `base.after_load` as initial-load evidence,
serializes reset scenes, emits the functional end marker, and calculates all
five OEM CRCs. Raw spelling, token arrays, dirty flags and initialization flags
are separate from numeric values throughout.

## Project sidecar and failure evidence

An empty eight-space Project has nine empty legacy tokens. Original conditional
initialization replaces the first token with the form project and retains eight
trailing spaces. This can exceed the physical eight-character codec. Nonempty
Project text retains its existing tail. The actual raw phases and
`project_assignment` preserve these values and backing state.

Only the unchanged original Project is substituted into the typed OEM
projection. The actual overlength raw Project is never passed through a relaxed
codec. This substitution does not authorize physical Project programming or
turn the model into a complete serializable device snapshot. Later cached
Network.ProjectName assignment and Global category payloads remain a separate
preparation stage.

The pure operation performs no PP I/O or retries. Failures during initial load,
Reset/tab removal or terminal save preserve the original exception and retain
completed raw phases in `last_evidence`, also attaching `edlt_reset_evidence`
when possible. A secondary export/attachment failure cannot replace an
interruption. Preflight clears stale evidence. No recovery or callback replay
occurs.

## Evidence and limits

The portable fixtures are
[the two original factory/trace captures](../research/fixtures/edlt-reset-factory-dependency-vectors.json)
and [the five rich source captures](../research/fixtures/edlt-reset-factory-rich-vectors.json).
Their source/report/executable hashes are retained in each artifact. The first
provides 12 complete parameter phases; the second provides 85 phases across five
sources. The focused differential checks all **84,778** raw value/token/dirty
parameter states, phase initialization flags where originally recorded, and
terminal CRCs. The rich evidence additionally records ten original all/empty
category workers; their output is evidence for the separate high-level bridge,
not an operation implemented by this dependency.

Original source and execution details are preserved under
`research/runtime/edlt-global-preamble/factory-bridge-patch-proposal.md`,
`tab-removal-analysis.json` and `factory-rich/analysis.json`. The original
handler/component arms agree at all shared phases; after tab removal they
match the independently executed actual factory at all 874 raw values, tokens
and dirty flags. Controlled peer diagnostics remain offline, including rejected
network-status requests. Earlier failed probes and explicit omitted stages
remain preserved. There is no claim of complete rendering, successful network
status, arbitrary form initialization or physical programming.

Final focused acceptance passed **68 tests on each Python version**, with no
skips: Python 3.13.14 in 201.932 seconds and Python 3.10.20 in 245.947 seconds.
All 38 selected source/input hashes remained unchanged. This includes the ten
new dependency tests, existing receipt/Project tests, all 44 original Reset
executions, the 2,124-case retained-lifecycle baseline, and original Blank
vectors. The separate ten-worker composition comparison also passed on both
versions. No Windows jobs or native I/O were performed by these dependency
acceptance runs. The compact acceptance record is
[edlt-reset-factory-dependency-acceptance.json](../research/fixtures/edlt-reset-factory-dependency-acceptance.json).
