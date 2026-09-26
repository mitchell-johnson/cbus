# Invoke a retained eDLT scene trigger

`cbus-toolkit cgate edlt-scene-trigger` resolves one scene's stored Trigger
Control binding from a complete KEYGL5 / 5055EDL / firmware 5.5.00 parameter
export and sends exactly one native Trigger event through C-Gate. The source
must retain the exact `cbus-cli-parameters-v1` identity envelope; a bare
parameter mapping is rejected.

```sh
cbus-toolkit cgate --host 127.0.0.1 edlt-scene-trigger snapshot.json \
  --metadata scene-cache.json --network //PROJECT/254 --scene 1

# FORCE is explicit and is useful when the same selector may already be active.
cbus-toolkit cgate --host 127.0.0.1 edlt-scene-trigger snapshot.json \
  --metadata scene-cache.json --network //PROJECT/254 --scene 1 --force
```

The source and metadata use the same formats as the retained
[SceneManager](edlt-scene-manager.md). Before opening the connection, the
command verifies the envelope's unit type, catalog number and firmware, the
intact scene state, scene number, canonical network, existing Trigger
application 202 group and existing action selector. A missing or disabled
binding, or one absent from the supplied cache, fails without network I/O. It
never creates an application, group or level and does not write or save
programmable parameters. Successful plan and outcome evidence therefore records
`source_profile_identity_verified: true`.

The parameter export and cache are caller-supplied retained facts. The command
does not compare them with a physical eDLT before sending, so
`source_snapshot_freshness_verified`, `metadata_cache_freshness_verified` and
`physical_binding_readback` remain false in both plan and outcome evidence.

For a scene bound to group 42 and selector 1, the two possible requests are:

```text
TRIGGER EVENT //PROJECT/254/202/42 1
TRIGGER EVENT //PROJECT/254/202/42 1 FORCE
```

The event is addressed to the Trigger Control group and selector. It is not
point-to-point to the eDLT whose parameter export supplied the binding. Every
C-Bus listener configured for that pair can respond.

## Outcome and failure boundary

One single-line terminal `200` response produces `status: "accepted"` and
`native_command_accepted: true`. This proves that C-Gate accepted the request;
`physical_scene_execution_verified` and `device_verified` stay false. A complete
4xx response other than `408` produces `status: "native-rejected"` and confirms
only the protocol rejection. A `408` or any 5xx response produces
`status: "native-outcome-uncertain"` with `outcome_uncertain: true`: for example,
cmqttd can return `502` after sending the SAL packet but losing its PCI delivery
confirmation. Transport loss and unsupported responses are also uncertain.
Every submitted result records `device_side_effect_possible: true`, including a
protocol rejection, because the client cannot prove that no listener acted. The
coordinator never reconnects, retries, rolls back, rewrites the retained source
or substitutes immediate lighting ramps.

The result identifies the resolved scene, Trigger group, selector, exact
command and response lines. `attempted_count` is zero if the client was not
connected and one after submission. `automatic_retries`, `pp_writes` and
`saved` are always zero/false.

The same source boundary applies to the Python API:

```python
manager = EdltSceneManager(spec)
state = manager.load_export(parameter_export, metadata=scene_cache)
sender = NativeEdltSceneTrigger(manager, client, network="//PROJECT/254")
plan = sender.plan(state, scene=1, force=False)  # no network I/O
outcome = sender.trigger(state, scene=1, force=False)  # connected client
```

`manager.load(...)` remains available for offline SceneManager editing, but a
state loaded from a raw mapping is deliberately refused by `live_trigger` and
`NativeEdltSceneTrigger`.

This workflow composes two independently retained behaviors: original
SceneManager trigger/action getter semantics and the existing native Trigger
Control sender. The focused tests pin both scene 1 and scene 2 routes, missing
bindings and cache references, forged/incomplete state rejection, exact tagged socket
bytes, native rejection, malformed replies, transport uncertainty, CLI exit
status and pre-connection validation. No new claim is made about an original
Toolkit button, physical display response or scene execution. The focused tests
also reject raw and wrong-profile sources before client construction and retain
uncertainty for native `408` and `502` replies.

## Remaining boundary

Physical acceptance still needs a configured eDLT (and any other listeners),
observed Trigger traffic, rendered/output behavior and power-cycle persistence.
Scene learning, complete SceneManager control binding, automatic metadata
creation during this read/submit command, missing trigger-group creation, other
eDLT firmware profiles and classic DLT profiles also remain outside this
command. Exact missing action-level creation is available separately through
the database-only [automatic SceneManager transaction](edlt-scene-metadata.md).
