# eDLT retained terminal model and database receipt prerequisite

`edlt_template_terminal_stage.py` completes one narrow local model step: it
consumes an intact issued second-model or combined assignment/model stage,
calls that issuer's retained `EdltLifecycle.prepare_save` once, and publishes
the complete numeric PP image and all five configuration CRC fields. It does
not reload or reconstruct the retained graph. It performs no I/O.

This is not full template Apply/OK. The original terminal evidence in
[edlt-template-terminal-recovery.md](edlt-template-terminal-recovery.md)
distinguishes UI/model validation, void SaveDialog dispatch, native save, and
project persistence. `prepare_save` executes the database-only model
normalization and CRC calculation; it does not execute the active-control
focus/binding flush, `ValidateSerialNumber`, `ValidateSceneWidgetConfig`, or
`EDLTUnit.IsValid`. The receipt names those unexecuted steps and keeps
`apply_allowed`, `original_save_validation_verified`,
`complete_parent_lifecycle_verified`, and `saved` false. Both issuer and
receipt `apply(target=None)` raise before examining a target.

## Callable local contract

With an existing `EdltTemplateModelStage` issuer and its intact receipt:

```python
terminal = EdltTemplateTerminalStage(model_issuer)
receipt = terminal.stage(
    second_model,
    current_source=post_assignment_raw_strings,
    metadata=original_cache_facts,
    dirty_parameters=original_dirty_names,
)
terminal.validate(
    receipt,
    current_source=post_assignment_raw_strings,
    metadata=original_cache_facts,
    dirty_parameters=original_dirty_names,
)
```

With an existing `EdltTemplateLifecycleStage` issuer, pass its intact combined
receipt and the original `TemplatePpSnapshot` as `current_source`; omit
`dirty_parameters`, because the assignment stage issues those facts. A
standalone/deserialized receipt without its issuer cannot enter this API.

The issuer validates the entire upstream chain both before and after terminal
preparation, and on later `validate`. This preserves exact source token
spelling/order where supported by the upstream issuer, specification and cache
identity, inherited dirty facts, retained graph identity, and upstream
cancellation guards. Receipt cloning, replacement, mutation, stale input, or a
foreign issuer are rejected. The terminal stage allows one projection;
reentrant staging and cancellation during staging are rejected. Failure or
interruption publishes no candidate and records detached failure evidence.
`cancel()` discards this local terminal result without cancelling the upstream
issuer or claiming to reproduce original Cancel behavior.

`receipt.final` contains all numeric/string PP values, `receipt.before_crc`
records terminal values before CRC insertion, and `receipt.crcs` names the five
CRC fields. `receipt.rendered_parameters` provides lossless decimal PP
rendering. It does not claim original raw setter spelling or raw token/dirty
effects. Diagnostic JSON is not a model resumption or persistence authority.

## Owned native durability proof

[edlt_template_terminal_native.py](../research/edlt_template_terminal_native.py)
uses the existing `LocalCGate` harness with an explicitly selected existing
Java 11 and pinned original C-Gate 3.4.0 build 2001 jar. It creates its own
process/workspace and a uniquely named synthetic project. Its only CNI address
is a loopback sentinel; the network is never opened. It does not adopt an
existing service or project.

The fixture starts from a newly created KEYGL5/5055EDL/5.5.00 database unit,
loads a fresh PP session, and builds caller-owned Lighting/MRA/static-text and
blank-scene model inputs. Cache metadata is explicitly synthetic, not a claim
that applications/groups were created or observed in the project. The helper
does not parse/import a template or call template Apply.

The successful first execution is retained in
[edlt_template_terminal_native_attempt1.json](../research/edlt_template_terminal_native_attempt1.json).
It verified:

- All 874 staged PP values, all five CRCs, and eight raw regions (widget 6,
  static text 0, scene bucket, and each CRC field).
- One `PP SAVE_TO_SOURCE` with native reply 200, followed by PP session cleanup.
- `PROJECT SAVE`, `PROJECT CLOSE`, `PROJECT LOAD`, then a newly opened PP
  session comparing all 874 values, all five CRCs, and the same eight regions.
- The same complete-image SHA-256 before and after reload:
  `c2d8e9ebf42b2da84cfcbf90db4dd6cd6d413506739eb80c3046a1a676b08219`.
- Network state `new` before save and after reload; zero sentinel connections.
- Owned listener/process identity, disposable project deletion, confirmed
  process exit, workspace removal, and unchanged source/spec fingerprints.

Only 43 changed parameters required PP writes. The report separately records
PP save attempted/confirmed/uncertain, project save attempted/confirmed/uncertain,
fresh reload attempted/verified, and cleanup. Uncertain writes are never
retried. Cleanup errors are recorded without replacing a primary operation
failure. This is a project-close/reload image-durability proof; it does not
test process restart, power-loss recovery, real cache provenance, original
WinForms validation, full template lifecycle completion, or physical devices.

Reproduce from `toolkit-cli`, choosing a fresh exclusive output path:

```sh
PYTHONPATH=src .venv/bin/python \
  -m research.edlt_template_terminal_native \
  --vendor "$CBUS_LOCAL_CGATE_VENDOR" \
  --java "$CBUS_CGATE_JAVA" \
  --spec-dir "$CBUS_UNITSPEC_DIR" \
  --output /tmp/edlt-terminal-native-new-receipt.json
```

The reusable native seam is `Programmer(client).load(network, db_source)` →
stage and verify a complete image → `save_to_source()` → end/unlock →
`NativeProjects.operation('save'/'close'/'load', project)` → a fresh `load` and
full comparison. Do not pass the terminal image through
`EdltLifecycle.apply`: that method rederives a plan by loading again. Do not
use `NativeTemplateTransaction`: its contract intentionally accepts classic
unit families only. A production persistence adapter remains a separate task;
this research helper never grants a template stage permission to save.

Targeted local verification:

```sh
PYTHONPATH=src .venv/bin/python \
  -m unittest tests.test_edlt_template_terminal_stage tests.test_edlt_template_terminal_native
```

All 17 tests passed. They cover one retained preparation/CRC pass without
reload; issuance, stale source/cache/schema/dirty/graph guards; upstream and
local cancellation; publication failures; reentrancy; no-target-access Apply
refusal; nonattachable interruption evidence; and primary-failure preservation
during owned cleanup. These tests start no native service.

Historical reproduction coordinates were normalized to portable environment
references before publication. Set the three explicit vendor/runtime/specification
variables to your separately supplied local inputs. Original technical fingerprints
and outcomes are unchanged; no execution was repeated by this documentation edit.
