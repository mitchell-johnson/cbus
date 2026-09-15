# Preference initial state

`constructor_state()` returns a fresh, complete `cbus-toolkit-preferences-state-v1` document. It contains exactly `format`, `values` (40 registered settings in original order) and `display_values` (five booleans). It is a pure function with no arguments or host-setting access.

```python
from cbus_toolkit.toolkit_preferences_initial_state import constructor_state

state = constructor_state()
```

The values represent Toolkit 1.18.0.2754's observed preference registration stage, before preference registry loading. The display booleans are the original explicit fallback values before display registry reads. This gives the existing preference reader and control planner a reproducible starting state.

Current values and registry defaults remain separate. `ShowProjectManager` initially equals false, while its boolean registry default equals true. Loading an empty store first writes the true default while retaining current false; a second load reads true. `SynchroniseFilters` and `LegacyDuplicateUnitsDetection` initially equal true. The original Java heap values are zero, language1 is1 and languages2–8 are-1. These are captured initial values, rather than recommendations for running C-Gate.

## CLI

```sh
cbus-toolkit preferences initial-state > initial-preferences.json
cbus-toolkit preferences controls initial-preferences.json
```

`initial-state` writes only the existing state JSON to stdout. Shell redirection chooses the destination. Registry loading and saving remain separate explicit operations using a state file.

## Original evidence and limits

The original PE initialization table contains 2,091 entries and is traversed forward. The observed preference registrations occur at ordinal388 (four Kipper settings),614 (28 global settings) and682 (eight language settings). Their constructor returns, type-initializer calls, registrations and final values were recorded independently. The manager and other module initializers are excluded from this bounded execution.

The original constructor and type-initializer bodies run with preallocated objects; allocation and AfterConstruction branches are explicitly skipped. A separate execution of original `System.TObject.InitInstance` starts with poisoned memory for the actual boolean, string and integer class layouts and verifies the VMT, complete zero initialization and untouched guard tails. Resource strings, managed-string storage, heap and collection insertion remain explicit research fixtures.

The five display globals occupy `.bss`. Original `LoadParametersFromRegistry` at `0x85B67C` resets them all to zero before its registry constructor. The self-contained acceptance probe stops at that boundary, without a registry call. Earlier independently pinned research also runs the original missing-value load against an isolated registry fixture and observes the same false defaults.

The package contains literal values and uses only its existing validation code. Vendor binaries, Unicorn and pefile are needed only for optional original-enabled tests. The [fixed vectors](../research/fixtures/toolkit-preferences-initial-state-vectors.json) and [original probe](../research/toolkit_preferences_initial_state_probe.py) pin the exact executable SHA256 and retain the constructor/layout/display boundaries. Installer settings, later module initialization, registry contents and full GUI startup are outside this state definition.

The [initial-state acceptance](../research/fixtures/toolkit-preferences-initial-state-acceptance.json) records eight module tests in the [combined 94-test acceptance](../research/fixtures/toolkit-preferences-expanded-acceptance.json), passing with zero skips on Python 3.13.14 (36.528s) and 3.10.20 (37.475s). Each run repeats the original constructor/layout/display-prefix probe, verifies reuse through the existing reader and controls, preserves first/second registry-load behavior, and exercises the initial-state CLI. An isolated standard-library-only subprocess verifies that the packaged helper has no research dependency. The tested source, fixtures, original executable and Windows provenance are archived with readback-verified hashes.
