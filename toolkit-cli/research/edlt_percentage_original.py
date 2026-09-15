"""Execute pinned original percentage IL with Decimal fields on owned Mono.

This never constructs a WinForms control. The original NumericUpDown property
calls are replaced with four decimal-field accessors, then every written
opcode, branch target and call is checked before execution.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    'bin/mono-sgen64': '91b99fc4b1158785b43506f2d76f9998c31f0492128e5789fbaaab0e300afd49',
    'lib/mono/4.5/mcs.exe': '857bb3129c3e2a5e7f8410db8fa5eb78139e934bb6279a72428597962311d771',
    'lib/mono/4.5/mscorlib.dll': '86364b7803c92d8c88b590031f015f80b10b00641e9d067e07a529a131d815e4',
    'lib/mono/gac/Mono.Cecil/0.11.1.0__0738eb9f132ed756/Mono.Cecil.dll': '2df316dbdc0999b76dcd09029b6c966b8bce8f21845f551d4075daed208f2c38',
}
DLL_SHA256 = '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3'
PROOF = 'verified_instructions\t44\tbranches\t3\tproperty_calls_redirected\t6\n'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe(edlt_dll, mono_root, destination):
    """Write a fresh, bounded compiler/probe evidence directory; never reuse it."""
    dll, mono, out = Path(edlt_dll).resolve(), Path(mono_root).resolve(), Path(destination).absolute()
    if digest(dll) != DLL_SHA256:
        raise ValueError('Requires the exact original eDLT.dll')
    for name, expected in PINS.items():
        if digest(mono / name) != expected:
            raise ValueError('Requires the pinned owned Mono toolchain: ' + name)
    sources = {name: ROOT / ('research/' + name) for name in (
        'NativeEdltPercentageExtract.cs', 'NativeEdltPercentageVerify.cs', 'NativeEdltPercentageProbe.cs')}
    vectors_path = ROOT / 'research/fixtures/edlt-percentage-vectors.json'
    vectors = json.loads(vectors_path.read_text())
    inputs = [Path(__file__).resolve(), vectors_path, dll, *sources.values(), *(mono / name for name in PINS)]
    before = {str(path): digest(path) for path in inputs}
    out.mkdir()  # A previous run, including a failed run, is never overwritten.
    data = '\n'.join('\t'.join(row.split('\t')[3:]) for row in vectors['supplement_rows']) + '\n'
    input_path = out / 'input.tsv'; input_path.write_text(data, encoding='ascii')
    cecil = mono / next(name for name in PINS if name.endswith('/Mono.Cecil.dll'))
    env = {key: value for key, value in os.environ.items() if not key.startswith(('MONO_', 'DYLD_'))}
    env.update(MONO_CFG_DIR=str(mono / 'etc'), MONO_PATH=str(cecil.parent) + os.pathsep + str(mono / 'lib/mono/4.5'),
               DYLD_FALLBACK_LIBRARY_PATH=str(mono / 'lib'))
    runtime = [str(mono / 'bin/mono-sgen64')]
    compiler = runtime + [str(mono / 'lib/mono/4.5/mcs.exe')]
    commands = [
        ('compile-extractor', compiler + ['-r:' + str(cecil), '-out:' + str(out / 'Extract.exe'), str(sources['NativeEdltPercentageExtract.cs'])]),
        ('compile-fixture', compiler + ['-out:' + str(out / 'Fixture.exe'), str(sources['NativeEdltPercentageProbe.cs'])]),
        ('extract', runtime + [str(out / 'Extract.exe'), str(dll), str(out / 'Fixture.exe'), str(out / 'OriginalPercentage.exe')]),
        ('compile-verifier', compiler + ['-r:' + str(cecil), '-out:' + str(out / 'Verify.exe'), str(sources['NativeEdltPercentageVerify.cs'])]),
        ('verify-written', runtime + [str(out / 'Verify.exe'), str(dll), str(out / 'OriginalPercentage.exe')]),
        ('run', runtime + [str(out / 'OriginalPercentage.exe'), str(input_path)]),
    ]
    report = {'format': 'cbus-edlt-percentage-original-v1', 'before': before, 'commands': [], 'passed': False}
    for stage, args in commands:
        result = subprocess.run(args, env=env, capture_output=True, timeout=30)
        (out / (stage + '.stdout')).write_bytes(result.stdout)
        (out / (stage + '.stderr')).write_bytes(result.stderr)
        report['commands'].append({'stage': stage, 'returncode': result.returncode, 'args': args})
        if result.returncode:
            (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            raise AssertionError('Original percentage stage failed: ' + stage)
        if stage == 'verify-written' and (result.stdout.decode() != PROOF or result.stderr):
            raise AssertionError('Actual written original percentage IL verification failed')
    report['after'] = {str(path): digest(path) for path in inputs}
    report['rows'] = (out / 'run.stdout').read_text().splitlines()
    runtime_lines = (out / 'run.stderr').read_text().splitlines()
    if len(runtime_lines) != 2:
        raise AssertionError('Unexpected original runtime evidence')
    decimal = runtime_lines[0].split('\t'); executable = runtime_lines[1].split('\t')
    if (len(decimal) != 6 or decimal[0] != 'decimal_runtime' or decimal[2] != 'mscorlib, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089'
            or Path(decimal[1]).resolve() != (mono / 'lib/mono/4.5/mscorlib.dll').resolve()
            or decimal[3] != PINS['lib/mono/4.5/mscorlib.dll'] or decimal[4:] != ['pointer_bits', '64']):
        raise AssertionError('Wrong actually loaded Decimal runtime')
    if (len(executable) != 3 or executable[0] != 'executable' or Path(executable[1]).resolve() != (out / 'OriginalPercentage.exe').resolve()
            or executable[2] != digest(out / 'OriginalPercentage.exe')):
        raise AssertionError('Wrong executed original percentage artifact')
    report['runtime_evidence'] = runtime_lines
    report['artifacts'] = {path.name: digest(path) for path in out.iterdir() if path.is_file()}
    report['passed'] = report['before'] == report['after'] and report['rows'] == vectors['original_rows'] + vectors['supplement_rows']
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if not report['passed']:
        raise AssertionError('Original percentage inputs changed or literal results differed')
    return report
