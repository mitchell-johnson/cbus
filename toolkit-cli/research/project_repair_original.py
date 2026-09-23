"""Execute exact C-Gate repair methods on bounded, generated temporary files.

This research helper needs a local Java11 JDK and the operator-owned original
jar/stylesheets. No server, registry, VM or network endpoint is used.
"""
from pathlib import Path
import base64
import hashlib
import os
import subprocess
import tempfile

PINS = {
    'cgate.jar': '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630',
    'transform/repair.xslt': 'f61c3dbb75fca6f9487ec73e25ccc6aece817104dfb66a17071e38bf40ca52aa',
    'transform/tidyduplicategroups.xslt': '02f0f7f4ccb9130a78bd46e1fd0b0908b96ed6c5e15b3392087c55583bd36969',
}


def run_original(cases, *, java, javac, vendor, line_ending='lf'):
    if line_ending not in ('lf', 'crlf'):
        raise ValueError('Explicit LF or CRLF required')
    if not 1 <= len(cases) <= 5000:
        raise ValueError('One through5000 generated cases required')
    for case in cases:
        if case['operation'] not in ('manual', 'repair', 'tidy', 'full'):
            raise ValueError('Unknown original operation')
        data = bytes.fromhex(case['input_hex'])
        if len(data) > 1024 * 1024:
            raise ValueError('Generated case exceeds1MiB')
    vendor, java, javac = map(lambda p: Path(p).resolve(), (vendor, java, javac))
    for name, digest in PINS.items():
        if hashlib.sha256((vendor / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Exact original vendor hash required: ' + name)
    source = Path(__file__).with_name('RepairStageProbe.java')
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (source, Path(__file__), java, javac, *(vendor / name for name in PINS))}
    with tempfile.TemporaryDirectory(prefix='cbus-original-repair-') as name:
        work = Path(name)
        environment = {**os.environ, 'CGATE_HOME': str(work)}
        compiled = subprocess.run([str(javac), '-cp', str(vendor / 'cgate.jar'),
            '-d', str(work), str(source)], capture_output=True, cwd=work, env=environment, timeout=30)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr.decode('utf-8', 'replace'))
        ending = '\n' if line_ending == 'lf' else '\r\n'
        request = ''.join(case['operation'] + '\t' + str(i) + '\t' +
            base64.b64encode(bytes.fromhex(case['input_hex'])).decode() + '\n'
            for i, case in enumerate(cases)).encode()
        completed = subprocess.run([str(java), '-Dline.separator=' + ending, '-cp',
            str(work) + os.pathsep + str(vendor / 'cgate.jar'), 'RepairStageProbe',
            str(work), str(vendor / 'transform')], input=request,
            capture_output=True, cwd=work, env=environment, timeout=180)
        if completed.returncode:
            raise RuntimeError(completed.stderr.decode('utf-8', 'replace'))
        rows = []
        for line in completed.stdout.decode('utf-8').splitlines():
            fields = line.split('\t')
            if fields[0] != 'RESULT':
                continue
            if len(fields) != 6 or int(fields[1]) != len(rows) or fields[2] not in ('OK', 'ERROR'):
                raise RuntimeError('Malformed or reordered original stage reply')
            rows.append({'status': fields[2], 'output_hex': base64.b64decode(fields[3], validate=True).hex(),
                         'error': base64.b64decode(fields[4], validate=True).decode(),
                         'response': base64.b64decode(fields[5], validate=True).decode()})
        if len(rows) != len(cases):
            raise RuntimeError('Incomplete original stage replies')
        compiled_sha256 = hashlib.sha256((work / 'RepairStageProbe.class').read_bytes()).hexdigest()
    after = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in before}
    if after != before:
        raise RuntimeError('Original probe input changed during execution')
    return {'rows': rows, 'inputs': before, 'class_sha256': compiled_sha256,
            'line_ending': line_ending, 'stdout_sha256': hashlib.sha256(completed.stdout).hexdigest(),
            'stderr_sha256': hashlib.sha256(completed.stderr).hexdigest(),
            'java_exit_code': completed.returncode, 'temporary_directory_removed': not work.exists()}
