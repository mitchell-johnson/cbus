# Factory Global Programming from the CLI

The explicit `--factory-context` option selects the bounded [original factory preparation](edlt-global-factory.md) for KEYGL5 / 5055EDL / firmware 5.5.00. Omitting it keeps the existing unbound Global Programming behavior. This workflow prepares and copies database parameters; it does not open a physical C-Bus network or execute a Toolkit form.

Export an already materialized source from a closed, caller-owned project, retaining the exact export file:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20033 unit \
  --lock-address //PROJECT/254 --source /db//PROJECT/254/p/20 \
  export source.json
```

The input must be a `cbus-cli-parameters-v1` export with exactly `format`, `unit_type`, `firmware`, `catalog_number` and `parameters`. All 874 parameter values must remain original PP strings, in the original specification order. Do not sort its keys, convert numbers, trim strings or substitute the Reset command's separate raw-envelope format. Even numerically equivalent respelling fails the native source comparison. A fresh export is the way to obtain the required order; `--parameter-order` cannot reorder a factory export.

Create `factory-context.json` with exactly these three strings:

```json
{
  "source": "//PROJECT/254/p/20",
  "form_project": "PROJECT",
  "cached_network_project": "NetPrj"
}
```

`source` identifies the original database unit. `form_project` supplies the original form's project context, while `cached_network_project` supplies the cached network object's Project name used before the original worker. They are explicit evidence inputs, not a request to change a database path. Project names accept one to eight ASCII letters, digits or underscores, starting with a letter. The source address must match the raw UnitAddress. The model retains the original Project token tail separately from its bounded physical-memory projection.

Supply `--metadata application-cache.json` using the complete `cbus-edlt-application-cache-v1` envelope, including lifecycle facts and ordered named application/group lists. The CLI does not fetch or create this metadata. Unknown, absent and incomplete facts remain distinct. The exact source-family and cache restrictions are documented in the [factory helper scope](edlt-global-factory.md); the six supported whole source patterns cannot be combined field by field.

```sh
cbus-toolkit edlt --spec-dir decoded-specs global-plan source.json \
  --factory-context factory-context.json --metadata application-cache.json \
  --category key-settings --category standby --category colour --category general

cbus-toolkit cgate --host 127.0.0.1 --port 20033 edlt-global source.json \
  --spec-dir decoded-specs --factory-context factory-context.json \
  --metadata application-cache.json --source-database //PROJECT/254/p/20 \
  --destination //PROJECT/254/p/21 --destination //PROJECT/254/p/22 \
  --exclusive-project --category key-settings --category standby \
  --category colour --category general --dry-run
```

For native use, `--source-database` is mandatory and must exactly match the context's source, including spelling. The source is excluded from destinations. All destinations must already exist in one closed project. `--exclusive-project` declares the caller's exclusive control of project editing and reloading; it does not prove server-wide session exclusivity.

The preview reads source and target preconditions without creating a backup or saving targets. To apply, remove `--dry-run`; optionally add `--backup-project NEWNAME` to choose the new backup's name. Existing backup names are rejected. The backup remains available afterward. Selected categories write their original literal values in source attribute order. All four categories produce 50 writes per target; an empty category selection still writes the two CRC parameters.

Input validation and a local factory preparation happen before connection. The native coordinator then creates its own issued preparation: there are four model-load calls across these two independent preparations, two in each. Neither preparation reloads its retained model during save. No state from the first engine is passed off as an object owned by the second.

Results include the original raw source and phase evidence, factory preparation scope, ordered literal payload, backup and per-target outcomes. The destination receives source OverallCRC and zero GlobalParameterCRC, retaining its other section CRCs; full destination-image CRC validity and physical behavior remain unverified. A failed batch can retain earlier verified destinations. It does not retry or replay writes.

Preparation failures appear in `edlt_global_programming_evidence` with their original phase evidence and `cli_failure_stage`. KeyboardInterrupt/SystemExit retain their original object identity; the CLI keeps fallback evidence when an exception rejects attribute attachment. A connection cleanup error after a confirmed operation retains its completed backup and target outcomes while marking the overall operation incomplete. Review exports are not resumable apply files.

The dedicated [CLI tests](../tests/test_cli_edlt_global_factory.py) compare actual original all/empty literal payloads, strict raw/context/cache inputs, preconnection guards, preparation and cleanup failures, and disposable native preview/save/close/load with full 874-parameter backup and target comparisons. They also reject changed raw source spelling before mutation. Original assembly and factory evidence remain in the [core acceptance records](edlt-global-factory.md); CLI execution adds no full-form or physical-device claim.

The [final factory acceptance](../research/fixtures/edlt-global-factory-acceptance.json) passed all 77 combined tests on Python 3.13.14 and 3.10.20 in 217.219 and 263.052 seconds, with no skips, failures or errors. These include the seven dedicated factory CLI tests. Both runs retained identical 53-source and 285-input hashes and used separate fresh native C-Gate children with six verified loopback listeners and complete cleanup. The record also preserves the earlier shared-service project-save rejection, the first isolated fixture's insufficient access role, and the successful seven-test pilot; none is silently relabeled as a successful final run.
