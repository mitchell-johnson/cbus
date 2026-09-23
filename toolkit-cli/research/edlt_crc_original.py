"""Bounded, network-denied execution of the unchanged original CRC method."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DLL_SHA256 = '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823'
PINS = {
    'bin/mono-sgen64': '91b99fc4b1158785b43506f2d76f9998c31f0492128e5789fbaaab0e300afd49',
    'lib/mono/4.5/mcs.exe': '857bb3129c3e2a5e7f8410db8fa5eb78139e934bb6279a72428597962311d771',
    'lib/mono/4.5/mscorlib.dll': '86364b7803c92d8c88b590031f015f80b10b00641e9d067e07a529a131d815e4',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _finish_report(out, report, primary=None):
    """Evidence collection must never replace a failed operation's first error."""
    if primary is not None:
        report['passed'] = False
        try:
            message = str(primary)
        except BaseException:
            message = '<exception message unavailable>'
        report['failure'] = {'type': type(primary).__name__, 'message': message}
    try:
        report['artifacts'] = {path.name: digest(path) for path in out.iterdir() if path.is_file()}
        pending = out / 'report.pending.json'
        handle = pending.open('x')
        write_error = None
        try:
            handle.write(json.dumps(report, indent=2) + '\n')
        except BaseException as error:
            write_error = error
            raise
        finally:
            try:
                handle.close()
            except BaseException:
                if write_error is None:
                    raise
        os.replace(pending, out / 'report.json')
    except BaseException:
        report['passed'] = False
        if primary is None:
            raise


def probe(logic_dll, mono_root, destination):
    """Create fresh evidence; never construct controls or contact the VM/service."""
    dll, mono = Path(logic_dll).resolve(), Path(mono_root).resolve()
    out = Path(destination).absolute()
    if digest(dll) != DLL_SHA256:
        raise ValueError('Requires the exact original CBusLogicModel.dll')
    for name, expected in PINS.items():
        if digest(mono / name) != expected:
            raise ValueError('Requires pinned owned Mono: ' + name)
    if out.parent.resolve(strict=True) != out.parent:
        raise ValueError('Output parent must be an existing resolved directory')
    source = ROOT / 'research/NativeEdltCrcProbe.cs'
    fixture = ROOT / 'research/fixtures/edlt-crc-original-vectors.json'
    vectors = json.loads(fixture.read_text())
    table = base64.b64decode(vectors['two_byte_crc_be_base64'], validate=True)
    buffers = [base64.b64decode(row['data_base64'], validate=True) for row in vectors['long_cases']]
    if len(table) != 131072 or len(buffers) != 52 or any(len(data) > 65536 for data in buffers):
        raise ValueError('CRC fixture exceeds the proved case domain')
    expected = table + b''.join(row['crc'].to_bytes(2, 'big') for row in vectors['long_cases'])
    inputs = [Path(__file__).resolve(), source, fixture, dll, *(mono / name for name in PINS)]
    before = {str(path): digest(path) for path in inputs}
    out.mkdir()  # Existing successful or failed evidence is never reused.
    input_path = out / 'buffers.b64'
    input_path.write_bytes(b'\n'.join(base64.b64encode(data) for data in buffers) + b'\n')
    inputs.append(input_path); before[str(input_path)] = digest(input_path)
    report = {'format': 'cbus-edlt-crc-original-v1', 'before': before, 'commands': [], 'passed': False,
              'scope': 'Unchanged Crc16Ccitt.checkCrc16; no control/model construction, VM or service calls'}
    try:
        with tarfile.open(out / 'inputs.tar.gz', 'x:gz') as archive:
            for i, path in enumerate(inputs):
                archive.add(path, arcname=str(i) + '/' + path.name)
        with tarfile.open(out / 'inputs.tar.gz', 'r:gz') as archive:
            for i, path in enumerate(inputs):
                raw = archive.extractfile(str(i) + '/' + path.name).read()
                if hashlib.sha256(raw).hexdigest() != before[str(path)]:
                    raise AssertionError('Pre-execution input archive mismatch')
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('CBUS_', 'MONO_', 'DYLD_')) and key not in ('PYTHONPATH', 'PYTHONHOME')}
        env.update(MONO_CFG_DIR=str(mono / 'etc'), MONO_PATH=str(dll.parent) + os.pathsep + str(mono / 'lib/mono/4.5'),
                   DYLD_FALLBACK_LIBRARY_PATH=str(mono / 'lib'))
        runtime = [str(mono / 'bin/mono-sgen64')]
        commands = [
            ('compile', runtime + [str(mono / 'lib/mono/4.5/mcs.exe'), '-r:' + str(dll),
                                   '-out:' + str(out / 'Probe.exe'), str(source)]),
            ('run', runtime + [str(out / 'Probe.exe'), str(input_path)]),
        ]
        for stage, command in commands:
            args = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', *command]
            result = subprocess.run(args, env=env, capture_output=True, timeout=30)
            (out / (stage + '.stdout')).write_bytes(result.stdout)
            (out / (stage + '.stderr')).write_bytes(result.stderr)
            report['commands'].append({'stage': stage, 'args': args, 'returncode': result.returncode})
            if result.returncode:
                raise AssertionError('Original CRC stage failed: ' + stage)
        lines = (out / 'run.stderr').read_text().splitlines()
        actual_paths = [dll, mono / 'lib/mono/4.5/mscorlib.dll', out / 'Probe.exe']
        if len(lines) != 3:
            raise AssertionError('Unexpected original CRC runtime evidence')
        for line, path, name in zip(lines, actual_paths, ('CBusLogicModel.Crc16Ccitt', 'System.Object', 'Probe')):
            fields = line.split('\t')
            if (len(fields) != 4 or fields[0] != name or Path(fields[1]).resolve() != path.resolve()
                    or fields[2] != digest(path) or fields[3] != '64'):
                raise AssertionError('Wrong actually loaded CRC runtime')
        raw = (out / 'run.stdout').read_bytes()
        report.update(actual_runtime=lines, two_byte_cases=65536, long_cases=len(buffers),
                      result_sha256=hashlib.sha256(raw).hexdigest(), result_matches=raw == expected)
        if raw != expected:
            raise AssertionError('Fresh unchanged original CRC differs from literal vectors')
        report['after'] = {str(path): digest(path) for path in inputs}
        if before != report['after']:
            raise AssertionError('Original CRC inputs changed during execution')
        report['passed'] = True
    except BaseException as error:
        _finish_report(out, report, error)
        raise
    _finish_report(out, report)
    return report
