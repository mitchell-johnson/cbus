# Offline workflow preparation

`cbus-toolkit offline-workflows` inspects, validates or plans an explicit caller
JSON file under proposed local policies. It prepares reviewable drafts and
histories. Every report keeps backend execution, native execution, original
compatibility and external project persistence false.

```sh
cbus-toolkit offline-workflows --help
cbus-toolkit offline-workflows copy-paste inspect --input /absolute/path/copy-paste.json --compact
cbus-toolkit offline-workflows copy-paste validate --input /absolute/path/copy-paste.json --compact
cbus-toolkit offline-workflows copy-paste plan --input /absolute/path/copy-paste.json --output /absolute/existing/directory/new-report.json --compact
```

The five workflow names are `copy-paste`, `neo-editor`, `catalogue-groups`,
`discovery-session` and `transfer-restore`; each accepts `inspect`, `validate`
and `plan`. Inspection reports the initial model and declared history.
Validation evaluates the local policy. Planning proposes local changes or
histories. Catalogue Group validation checks the starting draft, while planning
applies the supplied edits first. Unknown native contracts retain explicit
unsupported/profile gates. Cancellation discards only local draft authority.

Start with the five [source JSON examples](../src/cbus_toolkit/offline_workflows/examples/)
and edit their explicit inputs. These examples are separate source deliverables;
the installed command accepts any explicit caller file and does not require
package resources. The [input contracts and complete scenarios](../src/cbus_toolkit/offline_workflows/README.md)
describe source identities, snapshots, policies, action shapes and per-workflow
results. The standalone `python -m cbus_toolkit.offline_workflows` interface has
the same reports and statuses. From `toolkit-cli`, use
`PYTHONPATH=src python -m cbus_toolkit offline-workflows ...` for source execution.

Input is one strict UTF-8 JSON object, at most 4 MiB, 64 levels and 100,000
values. Duplicate keys, nonfinite numbers, unknown fields and authority inputs
are refused. Input must be a stable regular file; stdin, symlinks in any path
component, parent traversal, pipes, devices and directories are refused. Use a
canonical directory path on systems where `/tmp` is a symlink.

Reports include the exact input SHA-256 and deterministic sorted JSON, bounded
to 16 MiB. `--compact` works globally before `offline-workflows` or after the
command arguments. Optional `--output` exclusively publishes a new complete
report, mode 0600, in an existing directory. It never replaces an existing path.
Changed temporary-file identities fail closed and foreign files are preserved.
A post-publication failure reports `output_published_unconfirmed`; inspect that
file before retrying.

| Exit | Meaning |
| --- | --- |
| 0 | Inspection, intentional local cancellation or admitted local preparation |
| 2 | Invalid arguments, malformed input or input bounds exceeded; JSON error on stderr |
| 3 | Refused, unsupported or uncertain local policy; JSON report on stdout |
| 4 | File boundary, output bounds or report I/O failure; JSON error on stderr |

Successful inspection/cancellation can have `validation_passed=false`.
A prepared draft or saved report does not establish native GUI behavior,
database saving, archive interchange or hardware acceptance. Those require
separate captured evidence; this command performs no backend action.
