"""Source-pinned owned Windows file/CLI acceptance; no runtime installation."""
from pathlib import Path
import hashlib
import io
import json
import sys
import uuid
import zipfile

from research.windows_bridge import WindowsBridge
from research.windows_provenance import resolve_windows_provenance

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).with_name('windows_project_repair_cases.py')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run_native_repair_files(output_directory, *, architecture='x86'):
    if architecture not in ('x86', 'amd64'):
        raise ValueError('architecture must be x86 or amd64')
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=False)
    import cbus_toolkit
    package = Path(cbus_toolkit.__file__).resolve().parent
    paths = {'cbus_toolkit/' + p.name: p for p in sorted(package.iterdir())
             if p.is_file() and p.suffix in ('.py', '.json')}
    paths.update({'cases.py': CASES,
                  'runtime.json': ROOT / ('research/fixtures/windows-python-runtime' + ('-amd64' if architecture == 'amd64' else '') + '.json'),
                  '_host/gateway.py': Path(__file__).resolve(),
                  '_host/windows_bridge.py': ROOT / 'research/windows_bridge.py',
                  '_host/windows_provenance.py': ROOT / 'research/windows_provenance.py'})
    source = {name: path.read_bytes() for name, path in paths.items()}
    if any(path.read_bytes() != source[name] for name, path in paths.items()):
        raise RuntimeError('Input changed during snapshot capture; no Windows operation attempted')
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in source.items():
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, content)
    archive = data.getvalue()
    (directory / 'inputs.zip').write_bytes(archive)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert {name: digest(z.read(name)) for name in z.namelist()} == {name: digest(value) for name, value in source.items()}
    identifier = uuid.uuid4().hex[:16]
    prefix = 'repair-native-' + identifier
    namespace = 'repair-files-' + identifier
    runtime = json.loads(source['runtime.json'])
    manifest = {'format': 'cbus-windows-repair-file-inputs-v1', 'architecture': architecture,
                'inputs': {name: {'path': str(paths[name]), 'sha256': digest(value)} for name, value in source.items()},
                'archive_sha256': digest(archive), 'namespace': namespace, 'prefix': prefix,
                'runtime_relative_executable': runtime['relative_executable']}
    (directory / 'input-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    bridge = WindowsBridge()
    provenance = resolve_windows_provenance(ROOT, bridge)
    (directory / 'provenance.json').write_text(json.dumps(provenance.as_dict(), indent=2) + '\n')
    for name, path in provenance.paths.items():
        (directory / ('provenance-' + name)).write_bytes(path.read_bytes())
    bridge.push(prefix + '.zip', archive)
    bridge.push(prefix + '.py', source['cases.py'])
    script = ('@echo off\n"' + bridge.path(runtime['relative_executable']) + '" -I -S "' +
              bridge.path(prefix + '.py') + '" "' + bridge.path(prefix + '.zip') + '" ' + namespace + '\n')
    (directory / 'job.cmd').write_bytes(script.encode('utf-8'))
    job = bridge.submit(script)
    (directory / 'submission.json').write_text(json.dumps({'job_id': job, 'namespace': namespace}, indent=2) + '\n')
    result = bridge.wait(job)
    # Preserve the already returned execution output before any diagnostic pulls.
    for key in ('stdout', 'stderr'):
        if isinstance(result.get(key), bytes):
            (directory / (key + '.txt')).write_bytes(result[key])
    primary = None
    secondary = []
    interrupted = False
    for suffix in ('.admitted.json', '.ready.json', '.result.json', '.stdout.txt', '.stderr.txt'):
        try:
            content = bridge.pull(job + suffix, missing_ok=True)
            if content is not None:
                (directory / (job + suffix)).write_bytes(content)
        except BaseException as error:
            if primary is None:
                primary = error
            secondary.append({'artifact': suffix, 'type': type(error).__name__})
            if not isinstance(error, Exception):
                interrupted = True
                break
    if not interrupted:
        try:
            provenance.verify(bridge)
        except BaseException as error:
            if primary is None:
                primary = error
            secondary.append({'artifact': 'generation verification', 'type': type(error).__name__})
    try:
        native = None
        try:
            native = json.loads(result['stdout'].decode('utf-8-sig'))
        except (ValueError, AttributeError, KeyError):
            pass
        outcome = {'format': 'cbus-windows-project-repair-files-v1', 'architecture': architecture,
               'job_id': job, 'complete': result.get('complete'), 'exit_code': result.get('exit_code'),
               'wait_evidence': result.get('wait_evidence'),
               'archive_sha256': digest(archive), 'snapshot_inputs': manifest['inputs'],
               'live_inputs_still_match': all(path.read_bytes() == source[name] for name, path in paths.items()),
               'provenance': provenance.as_dict(), 'diagnostic_errors': secondary, 'native': native}
        outcome['passed'] = bool(primary is None and result.get('complete') is True and result.get('exit_code') == 0
                                 and native and native.get('passed') is True and native.get('archive_sha256') == digest(archive))
        (directory / 'result.json').write_text(json.dumps(outcome, indent=2) + '\n')
    except BaseException as error:
        if primary is None:
            primary = error
        secondary.append({'artifact': 'final report', 'type': type(error).__name__})
    if primary is not None:
        try:
            primary.windows_project_repair_gateway_evidence = {'job_id': job, 'archive_sha256': digest(archive),
                                                              'diagnostic_errors': secondary, 'report_directory': str(directory)}
        except BaseException:
            pass
        raise primary
    return outcome


if __name__ == '__main__':
    result = run_native_repair_files(Path(sys.argv[1]), architecture=sys.argv[2] if len(sys.argv) > 2 else 'x86')
    print(json.dumps({key: result[key] for key in ('passed', 'architecture', 'job_id', 'archive_sha256')}))
    if result['native']:
        print(json.dumps({key: result['native'][key] for key in ('tests_run', 'failures', 'errors', 'skipped', 'architecture', 'cleanup')}))
    raise SystemExit(0 if result['passed'] else 1)
