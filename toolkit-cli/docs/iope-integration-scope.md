# IOPE integration scope

Import the linear audited chain 690b0965198bf64fcba9834296eae34eb0441080 →
1b512236bc6df56c910fb1710cdf14e2502fa7d0 →
3847d49952acc8c8ed5e4f6381ac7c81a2f07474 →
18d78566ae6db93c7f0cd5e8fd7d99bf62d29cda before applying central registration.
The owner tip contains no newer commit. Shared production CLI registration is
additive parser/dispatch only; preserve firmware, DALI and wireless preflights.

Keep `sensors-wizard-semantics` in progress and strict parity obligations
unchanged. Eight component workflows are not full IOPE/whole-form parity.
Read [workflow boundaries](iope-workflows.md).

Historical summaries bind their own commits: `iope-workflow-acceptance-summary`
690b0965, `iope-editor-followup-acceptance-summary` 1b512236,
`iope-graph-editors-acceptance-summary` 3847d499, and
`iope-scene-levels-acceptance-summary` 18d78566. All referenced repository
hashes match those commits. Final native fixture implementation hashes match
the owner tip. Preserve historical fingerprints; do not replace them with
current-source hashes without separate execution evidence.

## Focused acceptance selection

Run the same nine portable modules from source and an isolated installed wheel:

- `tests/test_iope_environment.py`
- `tests/test_iope_output_settings.py`
- `tests/test_iope_logic.py`
- `tests/test_iope_join_recovery.py`
- `tests/test_iope_block_timer.py`
- `tests/test_iope_join_groups.py`
- `tests/test_iope_scene_selectors.py`
- `tests/test_iope_scene_levels.py`
- `tests/test_iope_workflow_cli.py`

Their source contains 104 test methods: 100 ordinary methods and four gated
static-source checks. Static checks require explicit `CBUS_TOOLKIT_EXE`, its
MAP and decoded UnitSpecs. They inspect bytes, never execute original code.
The separate `research/verify_iope_workflow_sources.py` verifies all ten source
receipts, including input/template audit receipts that add no input API.

Run these four native modules as one sequential selection from source and wheel:

- `tests/test_iope_workflow_native.py`
- `tests/test_iope_logic_native.py`
- `tests/test_iope_join_groups_native.py`
- `tests/test_iope_scene_levels_native.py`

They provide eight test methods: four owned-process nine-profile matrices and
four receipt checks. Provision `CBUS_NATIVE_SERVICE_BACKEND=local`,
`CBUS_CGATE_JAVA`, `CBUS_LOCAL_CGATE_VENDOR` and `CBUS_UNITSPEC_DIR` explicitly;
missing inputs skip and do not count as acceptance. No existing service is
adopted. Projects and groups are synthetic, networks closed and PP paths /db.
The native release manifest may select these modules after current integration
passes; regenerate/check the skip census separately. Do not hand-edit generated
skip or parity outputs to manufacture a pass.

Include existing `tests/test_iope_settings.py` and
`tests/test_cli.py` for shared-editor and parser regressions. The added `tests/test_cli_iope_workflow_alias.py` checks registered parser/dispatch
and real CLI JSON against the same standalone command inputs, including
preconnection refusals and a synthetic dry-run without saves.
Use the same wheel package bytes in native and portable checks and verify
imported module hashes. These checks do not require hardware or JIT.

Complete original input-function/template initialization, whole Environment
serialization, whole SceneManager accepted SaveNeoScenes/IOPE SaveScenes,
external scene-table/session branches, missing group/action creation, live
scene mode, dependent ramp/recall/scene timer expiry and physical device/power-cycle acceptance remain
open. Do not invoke original instruction replay while accepting this component
batch; private-source checks are static only.
