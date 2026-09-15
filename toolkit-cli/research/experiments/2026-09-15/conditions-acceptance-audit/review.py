"""Read-only acceptance artifact verification; does not rerun any test."""
from pathlib import Path
import hashlib
import json
import tarfile

ROOT = Path('/Users/mitchell/source/cbus/toolkit-cli')
OUT = Path(__file__).resolve().parent
FIXTURE = ROOT / 'research/fixtures/toolkit-update-conditions-acceptance.json'
digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
fixture = json.loads(FIXTURE.read_text())
manifest_path = Path(fixture['input_manifest']['path'])
assert digest(manifest_path) == fixture['input_manifest']['sha256']
before = json.loads(manifest_path.read_text())
assert len(before) == fixture['input_manifest']['input_count'] == 347
archive_path = Path(fixture['accepted_input_archive']['path'])
assert digest(archive_path) == fixture['accepted_input_archive']['sha256']
with tarfile.open(archive_path, 'r:gz') as archive:
    entries = archive.getmembers()
    assert len(entries) == fixture['accepted_input_archive']['files'] == 348
    for index, (path, expected) in enumerate(before.items()):
        member = archive.getmember(str(index) + '/' + Path(path).name)
        assert member.isfile()
        stream = archive.extractfile(member)
        assert stream is not None
        with stream:
            assert hashlib.sha256(stream.read()).hexdigest() == expected
reports = {}
for version, declared in fixture['runs'].items():
    path = Path(declared['report'])
    assert digest(path) == declared['report_sha256']
    report = json.loads(path.read_text())
    assert report['passed'] and report['tests'] == declared['tests'] == 61
    assert report['failures'] == report['errors'] == report['skips'] == []
    assert report['python_version'] == declared['python_version']
    assert report['seconds'] == declared['elapsed_seconds']
    assert report['no_original_processes'] and report['no_vm_or_shared_service_calls']
    assert report['public_network_calls'] is False
    for loaded, expected in report['loaded_files'].items():
        assert before[loaded] == expected
    assert before[report['python_executable']] == digest(report['python_executable'])
    reports[version] = {'report_sha256': digest(path), 'tests': report['tests'],
                        'loaded_files_correlated': len(report['loaded_files'])}
document = fixture['published_document']
assert digest(ROOT / document['path']) == document['sha256']
changed = [path for path, expected in before.items() if digest(path) != expected]
assert set(changed) <= {str(ROOT / 'docs/toolkit-update-conditions.md'),
                        str(ROOT / 'src/cbus_toolkit/capabilities.json')}
result = {'scope': 'Read-only independent acceptance artifact verification; no test rerun',
          'passed': True, 'fixture_sha256': digest(FIXTURE), 'input_files': len(before),
          'archive_sha256': digest(archive_path), 'reports': reports,
          'later_documentation_changes_outside_snapshot': changed,
          'review_script_sha256': digest(__file__)}
with (OUT / 'report.json').open('x') as stream:
    stream.write(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
