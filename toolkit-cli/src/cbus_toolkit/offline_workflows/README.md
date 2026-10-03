# Offline workflow preparation

The component models and JSON adapters provide pure, immutable preparation under
explicitly named proposed CLI policies. They consume caller-supplied bytes,
identities and scripted observations with zero I/O. The standalone CLI reads one
explicit local JSON file and prints its report, optionally publishing that report
to a new file. No entry point connects to a server, opens a device, saves a
project or establishes original Toolkit compatibility.

Five components preserve the reviewed handoff boundaries:

- `copy_paste`: source-bound intent, explicit target/profile admission and refusal
  history. Unsupported object routes cannot become executable clipboard actions.
- `neo_editor`: separate opening, locally applied and working snapshots for the
  exact synthetic KEYM4 / 2.5.00 / 5054NL policy. Apply accepts a local draft;
  Edit and Cancel preserve that accepted draft without claiming database saving.
- `catalogue_groups`: exact source catalogue identities and revision/default
  selection; complete ordered Group draft validation under an explicit policy.
  Catalogue selection does not admit Unit creation or default PP initialization.
- `discovery_session`: separate discovery, network-opening and shell-session
  histories. Generation-bound scripted callbacks cannot rebind a new selection;
  cancellation retains completed observations and never proves absence.
- `transfer_restore`: independent advanced intent, direction choice, quick
  progress, restore decisions and restore results. Original direction, mixed-row
  eligibility, Replace/Rename execution and batch effects stay capture-gated.

The reviewed design bundle was pinned at `2cc1454`; this implementation starts
from freshly fetched `origin/main` at
`c519ce5d8ddfa070817df202c15af9d211539dac`. The bundle SHA-256 is
`4467e6d2f96d7a963af630940a60d23977fe2067492ef1ab7d55f504f732ba9b`.
Portable tests are evidence for these proposed offline policies only. Original
terminal/control histories, native persistence, archive interchange and physical
acceptance require their own evidence.

## Use caller-supplied JSON

The installed public command is `cbus-toolkit offline-workflows`. Use Python
3.13+ and supply an explicit caller JSON file. Each invocation reads that file;
its contents determine the report:

```sh
cbus-toolkit offline-workflows copy-paste inspect --input /absolute/path/copy-paste.json --compact
cbus-toolkit offline-workflows copy-paste validate --input /absolute/path/copy-paste.json --compact
cbus-toolkit offline-workflows copy-paste plan --input /absolute/path/copy-paste.json --output /absolute/existing/directory/new-report.json --compact
```

Use a new output filename in an existing directory. `--compact` works before
`offline-workflows` or after its arguments. `cbus-toolkit --help` lists the public
command; `cbus-toolkit offline-workflows --help` lists all five workflows and
three operations. See [the public command guide](../../../docs/offline-workflows.md).

For source use from `toolkit-cli`, the equivalent is:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m cbus_toolkit offline-workflows copy-paste plan --input src/cbus_toolkit/offline_workflows/examples/copy-paste.json --compact
```

The standalone `python -m cbus_toolkit.offline_workflows` entry remains available
with the same input, reports and exit statuses. The five JSON fixtures in
`examples/` are source deliverables and are not packaged wheel resources. Copy
one to a regular file and edit its explicit identities, bytes, policies or
action history. A report's `input_sha256` binds it to the exact input bytes.
Output uses sorted keys and deterministic JSON; no timestamp or random
identifier appears in reports.

| Workflow / input `format` | Caller supplies | Local example result |
| --- | --- | --- |
| `copy-paste` / `cbus-offline-copy-paste-input-v1` | Source bytes and owner, explicit profile, target and ordered actions | Preserves address `0042`, owner and exact snapshot hash in a prepared draft |
| `neo-editor` / `cbus-offline-neo-editor-input-v1` | Complete synthetic profile, spec, opening snapshot and ordered actions | Local Apply of A, edit B, then Cancel returns to A |
| `catalogue-groups` / `cbus-offline-catalogue-groups-input-v1` | Exact catalogue bytes, selection, complete Group draft and explicit policy | Plans rows 1/4/5 while retaining catalogue source identities |
| `discovery-session` / `cbus-offline-discovery-session-input-v1` | Surface, generations, rows, symbolic dispatches and fully bound callbacks | Cancel retains the first observation and suppresses a late reply |
| `transfer-restore` / `cbus-offline-transfer-restore-input-v1` | One explicit surface, bindings and ordered history | Restore rename choice followed by local cancellation |

`inspect` checks the document shape and reports the initial model and declared
history without applying that history. `validate` evaluates the declared local
policy; catalogue Group validation checks the supplied starting draft.
`plan` produces local draft/history proposals; catalogue Group planning applies
its declared edits first. Outcomes distinguish `prepared`, `refused`,
`unsupported`, `uncertain` and `cancelled`. Inspection and intentional local
cancellation can exit successfully while `validation_passed` remains false.
Every report keeps `execution_enabled`, `native_execution_enabled`,
`original_compatibility_verified` and `external_persistence_verified` false.
Unknown contracts require an unsupported result or explicit profile gate.

| Exit status | Meaning |
| --- | --- |
| 0 | Inspection, intentional local cancellation or admitted local preparation |
| 2 | Invalid arguments, malformed input or input bounds exceeded |
| 3 | Refused, unsupported or uncertain local policy; JSON report is review material |
| 4 | File boundary, output bounds or report I/O failure; JSON error is on stderr |

The boundary accepts one UTF-8 JSON object, at most 4 MiB, 64 levels deep and
100,000 values. Duplicate keys, nonfinite numbers, invalid Unicode, unknown
fields and authority inputs are rejected. Reports are limited to 16 MiB.
Input must be a stable regular file. Stdin, symlinks in any path component,
parent traversal, directories, sockets, FIFOs and devices are refused. On
systems where `/tmp` is a symlink, use its canonical directory path.

`--output` publishes complete serialized bytes using an exclusive same-directory
hard link, mode 0600. Existing files, links and special objects are never
replaced. Temporary-file collisions preserve existing bytes. The file and
parent directory are synced; a failure after publication reports
`output_published_unconfirmed`, so inspect the existing report before retrying.
A saved report is evidence about a local proposal, not external persistence.

## Run the standalone demo

From `toolkit-cli`, use an existing Python 3.13+ environment:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m cbus_toolkit.offline_workflows.demo --compact all
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m cbus_toolkit.offline_workflows.demo neo-editor
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m cbus_toolkit.offline_workflows.demo discovery-session
```

The demo uses only explicitly synthetic in-memory data. Its output labels the
expectation origin and keeps execution, original/native/hardware acceptance and
external persistence false. The public command and standalone entry share the same offline file boundary
and retain every profile/refusal gate.

## Focused validation

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src python -m pytest --noconftest -p no:cacheprovider tests/offline_workflows
```

This selection bypasses the repository's native-service conftest and disables
pytest's cache. Installed-wheel tests require `CBUS_OFFLINE_INSTALLED_TARGET`
pointing at an isolated installation of the freshly built task wheel; otherwise
that acceptance subset is skipped. Build/install only this task's wheel with
existing read-only tooling, no dependency installation or network access. No
full suite, vendor runtime, native service or hardware acceptance belongs to
this preparatory milestone.

## Read the complete example

`all` returns five named scenario reports with the same explicitly synthetic
project/key/group vocabulary. Catalogue selection retains its source revision;
Group validation accepts every row or returns no accepted prefix. Copy intent
shows default-contract refusal, explicit offline admission and collision refusal.
The Neo history shows local A (`b0`, Group 1), dirty B (`f0`, Group 2), editor
Cancel returning to A, and destination Cancel retaining dirty B for a later
explicit local acceptance. Graph bytes, opaque PP and sparse memory validity
remain preserved.

Discovery Cancel retains the first completion and records a late second reply
without presenting it. CNI silence retains `absence_proven=false`. Network
opening stops after an accepted observation without inventing readiness or
closing a network. Shell selection A → B suppresses A's stale callback; a dirty
B snapshot remains detached through a fresh connection generation. All results
come from scripted facts and symbolic requests.

Advanced transfer, its direction choice and quick progress remain separate.
Restore selection/conflict decisions and supplied results also remain separate.
The example freezes explicit names and histories but reports transfer/restore
execution as unsupported. A completed row supplied to a results history does
not turn the decision planner into an executor or verify persistence.
