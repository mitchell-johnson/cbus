# Classic DLT fallback, brightness and nightlight controls

`dlt indicators` implements seven coupled controls from the original classic
DLT Indicators component. The workflow initializes its state, replays explicit
operations in order, and stages the resulting database PP values. It uses the
same admitted KEYBL5, KEYML5 and KEYDL4 identities as the other classic DLT
editors.

| Control | Values | Original availability |
|---|---|---|
| `page_fallback` | `yes`, `no` | Always |
| `pressed_enabled` | `yes`, `no` | Always |
| `duration_seconds` | 2..15 | Fallback or pressed brightness enabled |
| `pressed_level` | 0..15, raw brightness slider | Pressed brightness enabled |
| `nightlight_keys` | `yes`, `no` | Pressed brightness enabled |
| `nightlight_toggle` | `yes`, `no` | Pressed brightness enabled |
| `first_key_throwaway` | `yes`, `no` | At least one nightlight selected |

The raw pressed-level slider is independent of the normal brightness setting.
An operation targeting a disabled control fails before any PP writes. Repeating
a control is supported and the supplied order is retained.

```sh
cbus-toolkit dlt indicators show --file neo.json
cbus-toolkit dlt indicators plan --file neo.json \
  --indicator-control page_fallback=yes \
  --indicator-control duration_seconds=5 \
  --indicator-control pressed_enabled=yes \
  --indicator-control pressed_level=12 \
  --indicator-control nightlight_keys=yes \
  --indicator-control first_key_throwaway=yes > indicators-plan.json
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 \
  dlt-labels --show-indicators
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 \
  --dry-run dlt-labels --plan indicators-plan.json
cbus-toolkit cgate unit --lock-address //P1/254 --source /db//P1/254/p/20 \
  dlt-labels --indicator-control pressed_enabled=no
```

Offline inputs also support a native project XML document with `--project-xml`
and `--unit`, or a bare PP mapping with explicit identity. Supply decoded
vendor specifications through `--spec-dir` or `CBUS_UNITSPEC_DIR`. Native edits
retain the existing database-only destination guard. Indicator operations,
display settings and label controls use separate invocations.

## Original ordering and normalization

Original load treats fallback and pressed brightness as disabled whenever the
stored timer is zero. Component initialization selects the stored duration if
it is greater than one, otherwise the first dropdown value, two seconds. It
then updates dependencies and stores that value if either feature is enabled;
otherwise it stores zero. Thus opening this component can normalize a stored
one-second timer to two, or a timer with neither feature enabled to zero.

Enabling fallback from a zero timer selects the last duration item, 15 seconds.
Disabling pressed brightness clears both nightlights and their dependent
first-key suppression. The last nightlight being cleared also clears that
suppression. Both nightlight controls are visible in the admitted component;
the original first-key gate checks their visibility and checked state.

The callbacks differ: changing the pressed checkbox stores duration after
updating dependencies, while changing fallback only updates dependencies.
Starting with both features enabled, turning fallback off and then pressed
brightness off stores zero. Reversing those operations retains the previous
positive duration even though both flags are off. Reopening the component then
normalizes that timer to zero. The transaction preserves this original behavior.

Plans expose `loaded`, `before`, each ordered `steps` entry, `after`, enabled
controls, and `initialization_changes`. `save_normalizations` separately reports
the original agent's forced clearing of `EnableNightlight` at byte `0x34` bit 0.
There is no generic edit for that inherited bit. Named fields sharing bytes
`0x33`/`0x34` bind the plan; timer flash, nightlight-control source, all other PP
and the prior display/label settings remain unchanged.

## Verification boundary

The immutable `cbus-classic-dlt-indicator-plan-v1` format is re-derived on apply.
Exact types, identity, native layout and the complete relevant snapshot are
checked before writes. Two raw bytes and all named fields are verified after
staging. A partial or uncertain write is reported without retry, rollback or
save. `raw_verification_scope` explicitly identifies staging before save.

Retained independent evidence:

- [`classic-dlt-brightness-original.json`](../research/fixtures/classic-dlt-brightness-original.json)
  executes inherited numeric load/save and DLT flag handling across 1,280
  original instruction cases.
- [`classic-dlt-indicators-gui-original.json`](../research/fixtures/classic-dlt-indicators-gui-original.json)
  executes original initialization and callbacks for 32 cases and compares
  their intermediate states with the portable implementation. GUI primitive
  access and active, unlocked immediate Flash binding are synthetic hooks;
  the source receipt pins their behavior and control definitions.
- [`classic-dlt-indicators-native.json`](../research/fixtures/classic-dlt-indicators-native.json)
  verifies five classic identities against owned original C-Gate database
  units. It covers initialization, both event orders, dependent clearing,
  both nightlights, duration/level edits and preservation. All PP values and
  both complete raw bytes survive PP save and project save/close/load.

Run the focused `test_dlt_indicators.py`, `test_cli_dlt_indicators.py`,
`test_dlt_indicators_native.py`, `test_classic_dlt_brightness_original.py` and
`test_classic_dlt_indicators_gui_original.py` tests with `PYTHONPATH=src:tests:.`.
Native settings follow [classic label controls](classic-dlt-label-controls.md);
`CBUS_DLT_INDICATORS_REPORT` writes the native receipt. Original replay requires
the pinned executable/map and decoded specifications.

The complete Windows parent form, normal brightness group selection, physical
display effects, label delivery and power-cycle persistence remain unverified.
