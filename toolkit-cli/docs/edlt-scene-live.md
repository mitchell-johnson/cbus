# One-shot eDLT scene capture and broadcast

`NativeEdltSceneLive` operates on the retained scene state for KEYGL5 / 5055EDL firmware 5.5.00. It captures current group levels or broadcasts stored levels through an explicitly selected C-Gate network. Capture can then use the existing verified database programming workflow. Broadcast never stages or saves PP data.

The separate [retained scene trigger](edlt-scene-trigger.md) command resolves a
scene's stored application-202 group/action pair and submits one native Trigger
event. It does not replace broadcast: broadcast directly drives the retained
lighting outputs, while a Trigger event can be observed by every configured
listener for that group/action pair.

The original Toolkit control sends broadcast requests asynchronously. This API deliberately sends one command at a time and waits for its terminal C-Gate response. It implements the observed request payloads and retained-model effects; it does not reproduce the WinForms checkbox timer, asynchronous dispatch timing, or physical device acceptance.

```python
from cbus_toolkit.edlt_scene_manager import EdltSceneManager
from cbus_toolkit.edlt_scene_live import NativeEdltSceneLive

manager = EdltSceneManager(spec)
state = manager.load(values, metadata=cache)
live = NativeEdltSceneLive(manager, client, network="//OWNED/254")

# Preflight does no I/O and accepts an unconnected client.
requests = live.validate_broadcast(state, scene=1, scope="all")

# Operations require an explicitly connected client.
captured = live.capture(state, scene=1)
if captured.complete:
    plan = manager.prepare_save(captured.state)
    staged = manager.apply(programming_session, plan)
    programming_session.save_to_source()

sent = live.broadcast(state, scene=1, scope="current", item=1)
```

The manager and state must belong to the same intact issuance chain. Scenes are 1–8. Group routes come from each retained item object, not from reloading the selected scene application: changing a scene to secondary application can leave its earlier primary group objects attached. Supported lighting applications are 48–127 and 136; groups are 0–254. An explicit network uses canonical `//PROJECT/NETWORK` form, with a one-to-eight-character alphanumeric/underscore project and network 0–255. No cache or database groups are created.

`validate_broadcast` returns immutable ordered request records with item position, retained item identity, route and command. It uses the same selection and guards as `broadcast`. `scope="all"` rejects an item selection. The core API defaults omitted current selection to the first item; the CLI requires `--item`. Empty scenes are successful zero-request operations. A disconnected client is never automatically connected or retried by the coordinator.

## Capture and partial state

Each item sends `GET //PROJECT/NETWORK/APPLICATION/GROUP Level`. A verified observation requires one terminal `300` response containing the exact addressed `Level` field and a parsed value in 0–255. The reply parser is bounded and accepts the evidenced signed decimal syntax, including ASCII surrounding spaces.

The original getter returns zero on a failed or nonnumeric GET, and its item setter clamps signed integer values to the byte range. The API retains those model effects but distinguishes their evidence:

| Reply | Stored review level | Observation |
|---|---:|---|
| `Level=37` | 37 | verified |
| `Level= +42 ` | 42 | verified |
| `Level=not-a-number` or an out-of-Int32 number | 0 | legacy zero fallback |
| definite 4xx/5xx rejection | 0 | legacy zero fallback |
| `Level=-1` | 0 | normalized, unverified |
| `Level=256` | 255 | normalized, unverified |
| missing/wrong addressed field, unsupported response, lost connection | unchanged current item | stop with already captured prefix |

A fallback can finish the sequence while `complete` remains false. Every unverified, incomplete or interrupted capture is issued as a nonpersistable review state. `prepare_save` rejects it; it cannot be silently accepted by subsequent edits. Branch explicitly from a prior complete state to start new work. Capture preserves scene identity, item identity, group references, ramps, editability, unrelated scenes and clipboard. It never changes a stored ramp to match a live reading.

The manager's `capture_levels` method is a pure supplied-observation transition. It validates an exact retained-item prefix, bounded history and explicit verification facts. Its receipt says `observation_source="supplied"` and makes no physical-verification claim. The live coordinator supplies the terminal-response evidence separately.

## Broadcast and failure boundaries

Broadcast sends each selected retained level using `RAMP ... LEVEL 0 FORCE`. Stored ramp codes remain unchanged in the model and are not used for this immediate broadcast. Syncing all scene levels is a separate explicit `sync-levels` edit; choosing all-item broadcast does not silently synchronize them.

A single terminal `200` marks one native command accepted. A definite 4xx/5xx rejection is recorded and the serial coordinator continues with later selected items, returning `complete=false`. An uncertain transport or unsupported/malformed response stops future submissions immediately. There is no reconnect, resend, rollback, implicit OFF/STOP, abort or cancellation command. Native acceptance alone does not prove receipt or execution by physical hardware.

Outcomes expose ordered attempted requests, reply lines, verified/fallback status, sequence completion, uncertainty and retained state. `last_outcome`, `last_evidence` and `last_error` retain the latest operation; preflight/operation entry clears previous evidence. Ordinary transport and parser failures return incomplete outcomes while preserving the exact exception in `last_error`. A failed final state transition returns an incomplete outcome without an issuable state; a first evidence-export failure is raised with retained fallback evidence. KeyboardInterrupt and SystemExit are rethrown unchanged after recording the prefix. Evidence serialization or rejected exception-attribute assignment cannot replace the first interruption; `last_evidence` is the fallback.

The original pending-timer cancellation behavior was researched separately. Unchecking its Live Levels box does not stop a pending timer; its single-item callback can still send while unchecked, whereas the all-item branch checks the checkbox. Those bounded manual-callback observations are not implemented as a background CLI behavior.

## CLI

```sh
cbus-toolkit cgate unit --lock-address //OWNED/253 --source /db//OWNED/253/p/20 --dry-run edlt-scene-capture --metadata cache.json --network //OWNED/254 --scene 1
cbus-toolkit cgate edlt-scene-broadcast source.json --metadata cache.json --network //OWNED/254 --scene 1 --scope current --item 1
cbus-toolkit cgate edlt-scene-broadcast source.json --metadata cache.json --network //OWNED/254 --scene 1 --scope all
cbus-toolkit cgate edlt-scene-trigger wrapped-export.json --metadata cache.json --network //OWNED/254 --scene 1 --force
```

Capture requires a database destination. Its dry run performs live GET reads, stages and verifies temporary PP changes, and discards them without persistent SAVE. It does not issue RAMP. Without `--dry-run`, a complete verified capture is staged, checked and explicitly saved through the established programming finalization path. Failed/partial capture makes no PP SET or SAVE attempt. Evidence survives later plan, staging, save and cleanup failures.

Broadcast reads an exact-profile source export and cache, validates the entire request before connecting, and only sends the selected RAMP commands. It does not save the source or invoke the programming-session workflow. CLI exit status reflects incomplete capture/broadcast and cleanup failure.

Trigger invocation has a stricter source boundary than broadcast: it requires
the exact identity-bearing `cbus-cli-parameters-v1` envelope. See the dedicated
[scene trigger](edlt-scene-trigger.md) outcome taxonomy; in particular, a `408`
or 5xx reply does not prove that no device side effect occurred.

## Evidence and limits

The owned `research/NativeEdltSceneLiveProbe.cs` executes unchanged original Toolkit 1.18.0 assemblies. Its original factory is pinned to one numeric-loopback recording peer before model/control construction and remains pinned until process exit. It rejects unexpected requests, withholds the first broadcast reply until the actual checkbox handler returns, waits for every retained original response to leave its pending list, and records final result status rather than a transient status field. Timer, form, control, connection and peer cleanup are independently checked. No real CNI or existing project is accessed.

The frozen literal fixture is `research/fixtures/edlt-scene-live-vectors.json`. It contains fourteen distinct original cases: verified/bad/rejected/missing-field and four numeric capture cases; empty capture; current/all/rejected/all-with-first-rejection/cross-application broadcasts. Each records all 874 final PP fields, exact ordered requests and original configuration CRCs. Historical cancellation and failed harness pilots remain research evidence and are not silently promoted as passing production tests.

Native corroboration uses C-Gate 3.4.0 build 2001, a disposable database and an independent synthetic PCI receiver with explicitly declared application/group membership. Complete capture of levels 37/203 matches all 874 original final parameters, the 232 raw SceneBucket bytes and all five CRC fields, then survives SAVE, project save/close/load, and full readback with metadata preserved. Broadcast delivers independently asserted SAL group/level bytes on retained applications 56 and 57; receiver persistence is reloaded and compared. This establishes the synthetic receiver path, not physical hardware parity.

The default original oracle remains explicit Docker; the separately selected Windows bridge runs the same owned probe with pinned original assemblies. Native tests require explicit C-Gate and unit-spec environment gates. No fallback silently changes the oracle backend. The final focused suite includes eleven module tests and six CLI tests on each supported interpreter, plus nine existing SceneManager model regressions. Exact interpreter, input, report and log hashes are recorded in `research/fixtures/edlt-scene-live-acceptance.json`.
