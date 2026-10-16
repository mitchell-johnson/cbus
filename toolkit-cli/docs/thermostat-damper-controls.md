# Thermostat damper controls

`cbus-toolkit thermostat settings preview|apply` accepts explicit damper events
in the same ordered `--output-operation` history as output Select, Add and Edit.
Each command creates a fresh model from the exact full PP and project snapshot.
The four retained damper caches belong only to that model history; a receipt
cannot be imported as a continuation from another command or Toolkit session.

Use a closed database unit and the existing exclusive-project settings owner.
Preview first and inspect `damper_controls`, group identities, proposed creations,
model overrides and final changed parameters. For a mutation, apply uses one
backup, at most one PP save and one target project save, then verifies a fresh
reload. An already-applied history writes nothing. An uncertain reply stops without
replay or automatic restoration. This is a database workflow.

| Record | Effect |
| --- | --- |
| `{"op":"damper-form-show"}` | Bind the explicit panel, initialize its checkbox with Click suppressed, enter four group callbacks in order and register after-show. |
| `{"op":"damper-after-show"}` | Enter the registered help-binding callback. Requires an earlier form-show. |
| `{"op":"damper-group-change","zone":1}` | Enter one zone callback using its current model object. Zone must be an integer from 1 through 4. |
| `{"op":"damper-modulation-binding","checked":true}` | Write the Boolean model property through the recovered checkbox binding. |
| `{"op":"damper-modulation-click","checked":true}` | Observe checkbox state and record warning request 7323/WHITE when checked. Click itself does not assign the model property. |
| `{"op":"damper-installed-zones","value":30}` | Assign the five InstalledZones Boolean properties in source order and record notification intents. Value must be an integer from 0 through 31. |
| `{"op":"damper-zone-update"}` | Enter UpdateDamperGroups using the current InstalledZones mask. It is a separate explicit event. |

Every record has exactly the listed fields. Checked values must be JSON Booleans;
zone and mask values must be JSON integers. Duplicate JSON keys, non-finite
constants, unknown operations and malformed records refuse before connection.
Binding, Click and group-change require an earlier form-show. Reopening the
panel keeps the history's existing caches.

For a single causal history, pass each record as a separate flag in order:

```sh
cbus-toolkit thermostat settings preview //PROJECT/NETWORK/p/UNIT \
  --spec-dir /path/to/decoded/specs --host HOST --port PORT --exclusive-project \
  --output-operation '{"op":"damper-form-show"}' \
  --output-operation '{"op":"damper-installed-zones","value":30}' \
  --output-operation '{"op":"damper-zone-update"}' \
  --output-operation '{"op":"damper-modulation-binding","checked":true}' \
  --output-operation '{"op":"damper-modulation-click","checked":true}'
```

Replace the path and specification directory with the actual selected endpoint's
values and include the normal C-Gate connection options. The example grants no
hardware target or physical programming authority.

A fresh model starts with empty caches. A nil/non-Group callback leaves its cache
and warning unchanged. A selected unused Group 255 hides its warning while
preserving its cache. A real Group stores the current model getter, independently
of the controller object's value. Shared Edit keeps those cached identities live.
The PC_TSA5/PC_TSB5 internal-relay exception follows the current relay identity.

Zone update visits zones 1 through 4. Removing a zone caches its real assignment
only if its cache is empty, then selects the unused group. Adding a zone first
tries its cache, then the generated ASCII name. Only a retained master with no
matching object creates a group, using the manager's first available address.
An existing unused group found by name is still an object and prevents creation.
Ambiguous generated names refuse. Existing OIDs and opaque Level.Value text remain
intact. InstalledZones and InternalPlantZones are separate properties; the latter
still controls the ordinary selector's eligibility.

The final form save serializes modulation through the recovered plant factor,
which may produce 0, 1, 2 or 3 rather than copying the checkbox Boolean directly.
ControlledZones follows the retained master state and final InstalledZones.
All callback edits share the settings transaction's final save.

These are explicit source-derived callbacks. The receipt does not claim automatic
subscriber dispatch, Windows message delivery, modal warning rendering, the
ExternalRelays grid rendering, quick-zone Include/Exclude controls, application
migration, a complete initialized original form or physical thermostats. Source
inspection, software backend acceptance, original software acceptance and hardware
acceptance are separate evidence boundaries.

## JSON operation admission

The `op` member must be a string. Array, object, null, Boolean and numeric
operation names return the structured `ThermostatTemplateError` before the CLI
constructs a C-Gate client, for both preview and apply. Unknown string names
retain the same refusal. All seven damper schemas and ordinary Select/Add/Edit
continue through their existing validation.

The focused schema follow-up passes 46 parent tests in source and 46 in a freshly
installed wheel, with no skips. It changes only the operation-name guard and its
tests; the earlier damper workflow receipts retain their original revision and
execution scope. This follow-up invokes no provider, backend or hardware.
