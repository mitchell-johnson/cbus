# eDLT template second model load

The bounded original runtime probe closes the in-memory model reload prerequisite
of the template workflow. It does not execute `TemplatesDialog`, `ResetUnit`, the
WinForms parent, control callbacks, Apply, Cancel, a C-Gate session, or a device.

`edlt_template_model_probe.cs` constructs an unchanged original `EDLTUnit` with
synthetic in-memory application/group/level objects and a complete PP baseline
from an explicitly supplied private KEYGL5 specification. It runs:

1. Original `EDLTUnit.AfterLoadPPData` on that baseline.
2. Ordered synthetic PP assignments using the template's per-assignment
   initialization flag, raw equality check, original `PPAttribute.Value` setter,
   and explicit `HasBeenChanged=true` behavior.
3. Original `EDLTUnit.AfterLoadPPData` on the same retained unit a second time.
4. Original `PopulatePrimarySecondaryApplication` separately.

Every process runs under a deny-network sandbox. No original assemblies or unit
specifications are bundled. Input hashes are checked before and after. Runtime
assembly locations, architecture, SHA-256 values, method tokens, and IL hashes
are verified. The probe retains full raw PP output locally; the committed fixture
contains only synthetic transitions, model observations, and snapshot hashes.

The 25 cases cover unchanged reload, primary/config normalization, Lighting,
hidden-tail constructor effects, secondary fallback, MRA, duplicate assignment
order, retained array tails, scene replacement, widget kinds 0 through 17 plus
254 and 255, and a malformed widget failure. There are 49 successful load phases:
all 874 numeric parameter values, all 874 exact raw strings, and the complete
dirty-name set match `EdltLifecycle.load` plus `EdltResetControls._raw_load` in
each phase (42,826 comparisons for each representation). These are original
Mono executions of the unchanged managed model, not a Windows form acceptance.

The second load retains the widget, scene, and static-label list containers but
allocates 21 fresh widget objects, eight fresh scenes, 64 fresh static-label
objects, a fresh page widget, and fresh primary, secondary, and proximity model
wrappers. The first-load objects cannot be treated as the post-template graph.
The separate primary/secondary population call fills the application list and
makes no raw PP changes in these fixtures. No binding reset or redraw follows
in this probe.

The original base `AfterLoadPPData` sets `PPAttribute.bInitialiseMode=false`
before constructing its lists. Model normalization therefore adds dirty fields,
and existing dirty fields survive the second load. The unchanged baseline
already marks ConfigVersionMajor/Minor and all 21 WidgetType fields dirty during
first-load normalization.

The malformed Widget6 type raises `System.FormatException` during the second
load. The unit is left with five widgets, eight scenes, 64 static labels, an
empty primary/secondary list, initialization mode false, and list events enabled.
The raw malformed value remains. This is observable partial state, not rollback;
an isolated staged candidate must be discarded on this failure.

The exact residual boundary is the original parent form's SetupForm, recursive
control Before/AfterChange callbacks and conditional initialization, application
binding/reset, selected-widget/page/navigation refresh, and delayed redraw.
Persistence and Cancel/Apply recovery require their separate evidence. This
fixture alone does not authorize exposing template Apply.

Reproduce with Python 3.13, an explicit private specification directory, and the
pinned owned Mono runtime (all arguments are local paths):

```sh
PYTHONPATH=toolkit-cli/src:toolkit-cli python3.13 \
  toolkit-cli/research/edlt_template_model_original.py \
  --logic-dll "$LOGIC_DLL" --mono-root "$MONO_ROOT" \
  --spec-dir "$SPEC_DIR" --output "$NEW_OUTPUT_DIRECTORY" \
  --verify-fixture toolkit-cli/research/fixtures/edlt-template-model-original-vectors.json
```

The portable stage tests use an independent synthetic 874-field schema. Their
shared-field transition/model assertions do not compare the private baseline's
full PP hash; the fixture describes that boundary and gives the small explicit
initial overrides used to align those shared cases.
