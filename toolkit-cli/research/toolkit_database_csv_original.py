"""Bounded original CSV instruction execution with explicit cached providers.

The original database objects, constructors, Delphi string allocator, native
file writer and exception unwinder are outside this fixture's scope.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
EXE_SHA = '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
LIBRARIES = frozenset((
    '016084c6e70d929249a2abb22f1afda95095294e6cd70f509964ffc54006bf94',
    '7207c8e3d7a63118fb0bca73e01816797fd51b1d8a39a4cbc7abfd562ee59c85',
))


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(65536): hasher.update(block)
    return hasher.hexdigest()


def _finish_report(out, report, primary=None):
    if primary is not None:
        report['passed'] = False
        try: message = str(primary)
        except BaseException: message = '<exception message unavailable>'
        report['error'] = {'type': type(primary).__name__, 'message': message[:2048]}
    try:
        report['artifacts'] = {p.name: digest(p) for p in out.iterdir() if p.is_file()}
        pending = out / 'report.pending.json'
        handle = pending.open('x'); first = None
        try: handle.write(json.dumps(report, indent=2) + '\n')
        except BaseException as error: first = error; raise
        finally:
            try: handle.close()
            except BaseException:
                if first is None: raise
        os.replace(pending, out / 'report.json')
    except BaseException:
        report['passed'] = False
        if primary is None: raise


def _run(command, environment, out, report):
    """Retain partial output on interruption without replacing the first error."""
    state = {'attempted': False, 'started': False, 'reaped': False,
             'returncode': None, 'cleanup_errors': []}
    report['process'] = state
    streams = []; process = None; first = None

    def secondary(error):
        try: message = str(error)
        except BaseException: message = '<exception message unavailable>'
        state['cleanup_errors'].append({'type': type(error).__name__, 'message': message[:2048]})

    try:
        stdout = (out / 'stdout.txt').open('xb'); streams.append(stdout)
        stderr = (out / 'stderr.txt').open('xb'); streams.append(stderr)
        state['attempted'] = True
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, env=environment)
        state.update(started=True, pid=process.pid)
        process.communicate(timeout=75)
        state.update(reaped=True, returncode=process.returncode)
    except BaseException as error:
        first = error
    finally:
        if process is not None and not state['reaped']:
            try:
                if process.poll() is None: process.kill()
            except BaseException as error:
                secondary(error)
                if first is None: first = error
            try:
                state['returncode'] = process.wait(timeout=5)
                state['reaped'] = True
            except BaseException as error:
                secondary(error)
                if first is None: first = error
        for stream in reversed(streams):
            try: stream.close()
            except BaseException as error:
                secondary(error)
                if first is None: first = error
    if first is not None: raise first
    return state['returncode']


def probe(executable, destination):
    """Fresh macOS network-denied observation of all 88 literal original cases."""
    exe, out = Path(executable).resolve(strict=True), Path(destination).absolute()
    if exe.stat().st_size > 64 * 1024 * 1024 or digest(exe) != EXE_SHA:
        raise ValueError('Requires the exact original Toolkit executable')
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise ValueError('This original instruction fixture requires macOS network denial')
    if out.parent.resolve(strict=True) != out.parent:
        raise ValueError('Output parent must be an existing resolved directory')
    source = ROOT / 'research/NativeToolkitDatabaseCSVProbe.py'
    fixture = ROOT / 'research/fixtures/toolkit-database-csv-original-vectors.json'
    vectors = json.loads(fixture.read_bytes())
    if vectors['original_executable_sha256'] != EXE_SHA or len(vectors['vectors']) != 88:
        raise ValueError('Unexpected original CSV fixture')
    cases = [{**row['input'], 'expected': row['output']} for row in vectors['vectors']]
    raw = (json.dumps(cases, ensure_ascii=True, indent=2) + '\n').encode()
    if len(raw) > 256 * 1024: raise ValueError('Original case inputs exceed their bound')
    paths = [Path(__file__).resolve(), source, fixture, exe, Path(sys.executable).resolve()]
    for name in ('capstone', 'unicorn', 'pefile'):
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.origin: raise ValueError('Missing original fixture dependency: ' + name)
        entry = Path(spec.origin).resolve(); paths.append(entry)
        if name != 'pefile':
            paths.extend(sorted(entry.parent.rglob('*.py')))
            paths.extend(sorted(entry.parent.rglob('*.dylib')))
    paths = list(dict.fromkeys(paths))
    before = {str(path): digest(path) for path in paths}
    loaded_library_pins = {digest(p) for p in paths if p.suffix == '.dylib'}
    if not LIBRARIES <= loaded_library_pins:
        raise ValueError('Requires the pinned original instruction engine libraries')
    out.mkdir()  # No successful or failed namespace is reused.
    input_path = out / 'cases.json'; input_path.write_bytes(raw)
    paths.append(input_path); before[str(input_path)] = digest(input_path)
    report = {'format': 'cbus-toolkit-database-csv-original-acceptance-v1', 'passed': False,
              'before': before, 'cases': 88, 'vm_calls': False, 'shared_service_calls': False,
              'source_scope': vectors['scope']}
    try:
        with tarfile.open(out / 'inputs.tar.gz', 'x:gz') as archive:
            for i, path in enumerate(paths): archive.add(path, arcname=str(i) + '/' + path.name)
        with tarfile.open(out / 'inputs.tar.gz', 'r:gz') as archive:
            for i, path in enumerate(paths):
                data = archive.extractfile(str(i) + '/' + path.name).read()
                if hashlib.sha256(data).hexdigest() != before[str(path)]:
                    raise AssertionError('Pre-execution input archive mismatch')
        environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONHOME', 'PYTHONPATH')}
        environment.update(PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(out), TMP=str(out), TEMP=str(out))
        command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)',
                   str(Path(sys.executable).absolute()), '-I', str(source), str(input_path),
                   str(out / 'observation'), str(exe)]
        report['command'] = command
        report['exit_code'] = _run(command, environment, out, report)
        if report['exit_code'] or (out / 'stderr.txt').stat().st_size:
            raise AssertionError('Original CSV process failed; artifacts retained')
        observation = json.loads((out / 'observation/report.json').read_text())
        if (not observation['passed'] or len(observation['results']) != 88
                or not all(row['completed'] for row in observation['results'])
                or set(observation['actual_libraries'].values()) != LIBRARIES
                or observation['original_spans'] != vectors['original_spans']):
            raise AssertionError('Original CSV completion/provenance mismatch')
        for row, vector in zip(observation['results'], vectors['vectors']):
            actual = row['quoted'] if vector['input']['kind'] == 'quote' else row['rows']
            if row['id'] != vector['input']['id'] or actual != vector['output']:
                raise AssertionError('Fresh original differs from captured CSV literal')
        report['observation'] = {'path': str(out / 'observation/report.json'),
                                 'sha256': digest(out / 'observation/report.json')}
        report['after'] = {str(path): digest(path) for path in paths}
        if before != report['after']: raise AssertionError('Original CSV inputs changed')
        report['passed'] = True
    except BaseException as error:
        _finish_report(out, report, error)
        raise
    _finish_report(out, report)
    return report
