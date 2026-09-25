# Invoke a retained eDLT scene trigger

`cbus-toolkit cgate edlt-scene-trigger` resolves one scene's stored Trigger
Control binding from a complete KEYGL5 / 5055EDL / firmware 5.5.00 parameter
export and sends exactly one native Trigger event through C-Gate.

```sh
cbus-toolkit cgate --host 127.0.0.1 edlt-scene-trigger snapshot.json \
  --metadata scene-cache.json --network //PROJECT/254 --scene 1

# FORCE is explicit and is useful when the same selector may already be active.
cbus-toolkit cgate --host 127.0.0.1 edlt-scene-trigger snapshot.json \
  --metadata scene-cache.json --network //PROJECT/254 --scene 1 --force
```

The source and metadata use the same formats as the retained
[SceneManager](edlt-scene-manager.md). Before opening the connection, the
command verifies the exact profile, intact scene state, scene number, canonical
network, existing Trigger application 202 group and existing action selector.
A missing, disabled or stale binding fails without network I/O. It never creates
an application, group or level and does not write or save programmable
parameters.

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
`physical_scene_execution_verified` and `device_verified` stay false. A 4xx or
5xx response is a definite `rejected` result. A lost reply or unsupported
response is incomplete and outcome-uncertain. The coordinator never reconnects,
retries, rolls back, rewrites the retained source or substitutes immediate
lighting ramps.

The result identifies the resolved scene, Trigger group, selector, exact
command and response lines. `attempted_count` is zero if the client was not
connected and one after submission. `automatic_retries`, `pp_writes` and
`saved` are always zero/false.

This workflow composes two independently retained behaviors: original
SceneManager trigger/action getter semantics and the existing native Trigger
Control sender. The focused tests pin both scene 1 and scene 2 routes, missing
and stale bindings, forged/incomplete state rejection, exact tagged socket
bytes, native rejection, malformed replies, transport uncertainty, CLI exit
status and pre-connection validation. No new claim is made about an original
Toolkit button, physical display response or scene execution.

## Remaining boundary

Physical acceptance still needs a configured eDLT (and any other listeners),
observed Trigger traffic, rendered/output behavior and power-cycle persistence.
Scene learning, complete SceneManager control binding, automatic metadata
creation, other eDLT firmware profiles and classic DLT profiles also remain
outside this command.
