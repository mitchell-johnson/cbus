# Thermostat templates

`cbus-toolkit thermostat template` reproduces the PP overlay performed by the Toolkit thermostat **Load Template** dialog. It applies the overlay to one closed database unit. The Toolkit's later object-model adjustments are not replayed.

```sh
export CBUS_UNITSPEC_DIR=/private/decoded/unitspec

cbus-toolkit thermostat template list --unit-type PC_TSB

cbus-toolkit thermostat template preview //HOME/254/p/4 --template 2 \
  --host 127.0.0.1 --port 20023 --exclusive-project

cbus-toolkit thermostat template apply //HOME/254/p/4 --template 2 \
  --host 127.0.0.1 --port 20023 --exclusive-project --backup-project HOMEBAK
```

Template specifications are read from `--spec-dir`, or from `CBUS_UNITSPEC_DIR` when that option is omitted. They are never bundled. The connected C-Gate must also hold the same files in its own unit specification directory, because the apply step asks it to load one of them.

## Compatibility

The original installation list depends only on the thermostat class:

| Unit types | Class | Offered templates |
| --- | --- | --- |
| PC_TSA, PC_TSA5 | TProgrammableThermostat | `THERMOSTATA_TEMPLATE01`–`09` |
| PC_TSB, PC_TSB5 | TBasicThermostat | `THERMOSTAT_TEMPLATE01`, `04`, `05`, `06`, `08`, `09` |

The CLI refuses other unit types and the templates the original never offers. This includes basic templates 2, 3 and 7, even though C-Gate contains those files. Native `PP LOAD_FROM_FILE` itself accepts any file with any unit type, so the refusal happens before any I/O. Every template declares firmware `0`–`9`. The CLI checks that range, while the original performs no firmware check. Each `THERMOSTATA` template includes the `THERMOSTAT` template with the same number, then overrides and extends it.

The catalogue loader also requires each template parameter to meet these checks:

- It is one byte with a default value.
- Its name and address match the unit specification (`THERMOSTATA.xml` or `THERMOSTATB.xml`).
- It is within that specification's range.
- It does not alias any other parameter byte.

## Overlay semantics

The Toolkit sends `PP LOAD_FROM_FILE <session> <template>` with no `PP RESET_TO_DEFAULTS` first. C-Gate writes only the template's declared bytes, which are 59 parameters for basic templates and 61 for programmable ones. Every other parameter keeps its current value. Preview computes this overlay independently from the specification and reports the following:

- The parameters that change, with before and after values.
- The template parameters that already match.
- The number of parameters that are preserved.

The original dialog then changes its in-memory model:

- It clears retained damper groups.
- It sets a master/slave value of 1 to 0.
- It reruns the normal AfterLoad.
- It reassigns output and relay groups for the plant type, and may create groups.
- On programmable units, it clears `EvapProgramEnabled`, and clears `NonEvapProgramEnabled` for internal plant enum 0 or 2.

Those changes persist only when the form is later saved. This command **does not replay them**. Its result is therefore the native PP state immediately after the original load, not the state after the original form saves. Every output reports `original_post_load_adjustments_replayed: false` and lists these steps. See the [static receipt](../research/experiments/2026-09-29/thermostat-template-static.md).

## Apply

The unit path is `//PROJECT/network/p/unit`. Every network in the project must be closed with synchronization idle. `--exclusive-project` declares that the caller controls all editing and reloading of the project; the command does not acquire a server-wide lock. Planning makes these reads:

- The unit XML.
- One read-only PP snapshot. The command rejects it if the read changed the database XML.

Apply takes these steps:

1. Recheck the unit XML, PP snapshot and network inventory.
2. If nothing would change, return `already_applied` without writing anything.
3. Otherwise, save the project and copy it to a backup. The backup name is either `--backup-project` or a random new name.
4. Recheck the unit.
5. Open a PP session and issue the original `LOAD_FROM_FILE`.
6. Compare every staged parameter with the plan. Any template mismatch or unrelated change stops the operation before saving.
7. Issue one `PP SAVE_TO_SOURCE` and one target `PROJECT SAVE`.
8. Close and reload the project.
9. Verify the result in a fresh session. The template values must match the plan, every other parameter must be unchanged, and the unit identity (OID, type, firmware, catalogue number) and its non-PP XML must be unchanged.

The command makes no retry and no automatic rollback. `pp_save_attempted`, `pp_save_confirmed`, `target_save_attempted`, `target_save_confirmed` and `outcome_uncertain` identify an interrupted save. Inspect those fields and the backup before any recovery. Each plan allows one apply attempt.

The Python API is `NativeThermostatTemplates(client, ThermostatTemplateCatalog(spec_dir)).plan(path, number, exclusive_project=True)`, followed by `apply(plan, backup_project=...)`. The offline helpers are `plan_overlay` and `compare_overlay`.

## Evidence and limits

- **Static review.** [thermostat-template-static.json](../research/experiments/2026-09-29/thermostat-template-static.json) pins the installation table, the class chains, the no-reset `LoadFromTemplate` sequence, the post-load call order and the help topics searched against the original EXE and MAP.
- **Offline tests.** Six tests with four subtests use synthetic specifications (`tests/test_thermostat_templates.py`).
- **Native acceptance.** Owned C-Gate 3.4.0.2001 passed three tests: [receipt](../research/experiments/2026-09-29/thermostat-template-native-acceptance.json).
  - All 15 offered pairs were applied: 9 programmable templates on PC_TSA/PC_TSA5 and 6 basic templates on PC_TSB/PC_TSB5.
  - Before each apply, every template parameter was set one step away from its template value, and three unrelated parameters were set to non-default values.
  - After save, close and reload, every template value equalled an expected value that the test computed independently from the raw template XML. Every other parameter was unchanged.
  - The test refused basic templates 2, 3 and 7 and a KEY4 unit, and the project stayed byte-identical.
  - A public CLI preview and apply also passed.
  - No CNI connection occurred. The service stayed on loopback, and its process and storage were removed.

The following remain open:

- Replay of the original post-load model adjustments and form save.
- Captions and images shown in the dialog.
- Per-byte protection that `LOAD_FROM_FILE` copies from the template.
- cmqttd `LOAD_FROM_FILE` overlay parity. Staged verification refuses to save a non-overlay result.
- Physical thermostats.
