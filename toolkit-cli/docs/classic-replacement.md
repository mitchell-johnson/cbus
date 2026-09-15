# Classic database-unit replacement

`ClassicReplacement` implements an offline replacement workflow for all nine directed pairs among KEY1, KEY2 and KEY4. It preserves the source address, tag, description, database unit name and other source metadata; installs the requested target type, firmware, catalogue and serial; transfers the supported classic programming; and saves the project. No physical network is opened and no hardware is programmed.

```python
from cbus_toolkit.classic_replacement import ClassicReplacement, LearnedHistory

replacement = ClassicReplacement(client, source_spec, target_spec)
plan = replacement.plan(
    "//PROJECT/254/p/20",
    target_firmware="1.2.67",
    target_catalog="5031N",
    target_serial="",                      # explicit unassigned replacement serial
    learned_policy="frontend",
    learned_history=LearnedHistory(current=False, original=True),
)
print(plan.as_dict())
result = replacement.apply(plan)           # creates a backup project automatically
print(result["backup_project"])
```

`replace(source, **options)` combines planning and application. An explicit `backup_project` can be supplied to `apply` or `replace`; otherwise a new eight-character backup name is generated. Backups cannot be disabled by this API. C-Gate rejects an existing destination backup name, avoiding overwrite. Blank `target_serial` clears the old hardware serial instead of attaching it to the replacement device. Catalogue/type/firmware compatibility is checked through the native catalogue command and the supplied exact unit specification.

Planning opens only temporary offline PP sessions. It returns a JSON-safe review via `plan.as_dict()`, including alignment changes, retained fields, physical-key differences, learned policy and the source snapshot hash. Application rejects stale source snapshots or modified plans before staging. A source XML hash is a concurrency precondition; it does not replace a backup.

The operation follows this sequence:

1. Revalidate the source and target defaults, save the project, and make a native project backup.
2. Use `DBCOPYSAFE` to copy the source to a free database unit address, retaining its metadata. A network therefore needs one free database unit slot.
3. Change the staged target identity, reset its programming through C-Gate, restore source project/network identity and the original source address, apply the classic alignment, and apply the explicit learned policy.
4. Save the staged unit, open a fresh PP session, and verify all destination parameters and preserved metadata. The original source still exists untouched at this point.
5. Recheck the source snapshot, then promote the validated XML with `DBSETXML` at the original source address. The replacement gets a fresh OID, distinct from the staging unit and original source.
6. Verify the promoted XML and programming, remove the staging unit, save the project, and verify the persisted programming again.

The 26 configuration attributes and unsupported families are described in [offline-conversion.md](offline-conversion.md). The replacement additionally handles UnitAddress, Project, NetworkAddress, target serial and explicit LearnedFlag state. Other factory/checksum fields keep native target defaults. Source tag/description/database unit name are preserved independently of the PP UnitName.

## LearnedFlag semantics

`learned_policy` is required. It accepts:

| Policy | Result |
| --- | --- |
| `frontend` | Requires `LearnedHistory(current, original)`. Copies the source flag only when current is false and original is true; otherwise keeps the native target default. |
| `preserve_source` | Always copies the source flag. This is an explicit user-selected policy. |
| `target_default` | Keeps the new target's native default flag. This is an explicit user-selected policy. |

The history inputs describe the target frontend model at the conversion hook. They are not inferred from two PP snapshots. The exact Toolkit `TCBusLearnUnitCGateAgent.BeforeUnitConversionSave` routine (MAP offset `006C4F70`, VA `0x00CC5F70`) uses this current/original predicate. `TCoreKeyInputUnit.LearnModePropertiesEnabled` uses firmware threshold `1.2.63`, which is also the minimum of the supported specifications. An opt-in test checks the actual branch bytes and threshold in the original executable.

## Metadata and recovery limits

The implementation preserves and compares metadata structurally, including namespaces, attributes, nested element order and opaque text. It never invents meanings for unknown fields. C-Gate's `DBSETXML` silently drops XML fields absent from its model; therefore every source field that survives a native `DBGETXML` snapshot must also survive staging and promotion, or the operation fails. Unknown or duplicate PP parameters, extra PP attributes/content, and unmodeled source-OID references are rejected before replacement. Neo, DLT, sensor and other conversion families remain unsupported.

If promotion or verification fails, the captured original XML is reapplied to restore the original OID, metadata and programming. The restored XML and parameters are checked, the staging unit is removed when its identity is still ours, and the restored project is saved. `ReplacementError.details` exposes the backup project, rollback errors and any staging address needing attention. An uncertain promotion outcome is treated as potentially applied and restored. If the connection also prevents restoration, the error reports that failure; it does not claim successful rollback.

This spans multiple C-Gate commands rather than a project-wide transaction. Source snapshots are rechecked immediately before promotion, but C-Gate does not expose a compare-and-swap operation for arbitrary simultaneous database writers. The operation must not be treated as serializable with unrelated clients editing the same unit concurrently. The backup remains available after success or failure.

Project reloads can materialize default metadata such as DeviceName. Native persistence tests normalize the original fixture through save/reopen before testing exact rollback, and independently verify the final replacement through a fresh connection.

## Verification

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p test_classic_replacement.py -v
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
PYTHONPATH=src python3 -m unittest discover -s tests -p test_classic_replacement.py -v
```

Native acceptance covers every directed classic pair, metadata and serial behavior, all copied parameters, fixed press/release bytes, fresh-connection/project-reopen persistence, backup content, stale-plan rejection and default learned policy. Injected backend failures cover staging, metadata loss, uncertain promotion, an error after project save, and a failed rollback connection. Each run creates disposable uniquely named projects and closed loopback networks.
