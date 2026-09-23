"""One finite child process, archived inputs, network denied; no retry."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import zipfile

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from process_harness import Failures, run_process
from probe import read, sha, TOKEN, EXE_SHA

EXE = Path('/Users/mitchell/source/cbus/toolkit-cli/research/vendor/toolkit/app/CBusToolkit.exe')
MAP = EXE.with_suffix('.map')
CASE_SHA = '1d03dccff01026f7071d248711d53aa84400bd943250970d95ee578c2886e616'
LIBRARIES = {'016084c6e70d929249a2abb22f1afda95095294e6cd70f509964ffc54006bf94',
             '7207c8e3d7a63118fb0bca73e01816797fd51b1d8a39a4cbc7abfd562ee59c85'}

def associate(child, expected, cases, before, partial):
    assert child['format'] == 'thermostat-original-selection-v1'
    assert child['inputs_before'] == expected
    rows = child['results']; assert type(rows) is list and len(rows) <= len(cases)
    assert [r['id'] for r in rows] == [c['id'] for c in cases[:len(rows)]]
    for key in ('runtime_before', 'runtime_after'):
        if key not in child:
            assert partial
            continue
        actual = child[key]
        assert actual['python'] == sys.version and before[actual['executable']] == actual['executable_sha256']
        assert set(actual['libraries'].values()) == LIBRARIES
        assert all(before.get(path) == value for path, value in actual['libraries'].items())
        assert all(before.get(v['path']) == v['sha256'] for v in actual['loaded_python_modules'].values())
    if not partial:
        assert len(rows) == len(cases) and child['inputs_after'] == expected
        assert child['runtime_before'] == child['runtime_after']
    return {'source_inputs_associated': True, 'ordered_case_prefix_associated': True, 'actual_runtime_associated': 'runtime_before' in child, 'partial': partial}

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--release', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.release != TOKEN or sys.platform != 'darwin' or sys.version_info[:2] not in ((3, 10), (3, 13)): raise ValueError('Reviewed release/runtime required')
    out = Path(args.output).absolute()
    if out.parent.resolve(strict=True) != BASE or out.exists() or out.is_symlink(): raise ValueError('Fresh direct owned output required')
    import capstone, unicorn, pefile
    from unicorn.unicorn_py3 import unicorn as uc_core
    libraries = [Path(capstone._cs._name).resolve(), Path(uc_core.uclib._name).resolve()]
    runtimes = [Path(sys.executable).resolve(), *libraries, Path(pefile.__file__).resolve()]
    for package in (capstone, unicorn): runtimes.extend(sorted(Path(package.__file__).resolve().parent.rglob('*.py')))
    runtimes = list(dict.fromkeys(runtimes))
    sources = [BASE / n for n in ('probe.py', 'run.py', 'process_harness.py', 'make_cases.py', 'cases.json', 'PLAN.md')]
    paths = [*sources, *runtimes, EXE, MAP]
    raw = {str(p): read(p, 64 * 1024 * 1024) for p in paths}; before = {p: sha(v) for p, v in raw.items()}
    assert before[str(EXE)] == EXE_SHA and before[str(BASE / 'cases.json')] == CASE_SHA
    assert before[str(MAP)] == 'f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb'
    assert {before[str(p)] for p in libraries} == LIBRARIES
    assert before[str(BASE / 'process_harness.py')] == '52e87ad4cab2f441479186ec521ed9b2fefea9a63ed89e89bb5ff71e527479d6'
    expected = {str(out / name): before[str(BASE / name)] for name in ('probe.py', 'cases.json')}
    expected[str(EXE)] = EXE_SHA; cases = json.loads(raw[str(BASE / 'cases.json')]); staged = {}
    out.mkdir(); report = {'format': 'thermostat-selection-driver-v1', 'passed': False, 'inputs_before': before, 'process': None}; failures = Failures()
    try:
        with zipfile.ZipFile(out / 'inputs.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
            for i, (path, data) in enumerate(raw.items()): archive.writestr(str(i) + '/' + Path(path).name, data)
        with zipfile.ZipFile(out / 'inputs.zip') as archive:
            for i, (path, data) in enumerate(raw.items()): assert archive.read(str(i) + '/' + Path(path).name) == data
        report['archive_sha256'] = sha(read(out / 'inputs.zip', 128 * 1024 * 1024))
        for name in ('probe.py', 'cases.json'):
            staged[str(out / name)] = expected[str(out / name)]
            with (out / name).open('xb') as stream: stream.write(raw[str(BASE / name)])
            assert read(out / name, 256 * 1024) == raw[str(BASE / name)]
        report['staged_before'] = dict(staged)
        (out / 'tmp').mkdir(); (out / 'home').mkdir()
        command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', sys.executable, '-I', '-B', str(out / 'probe.py'), TOKEN, str(out / 'cases.json'), str(out / 'capture'), str(EXE), CASE_SHA]
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(out / 'home'), 'TMPDIR': str(out / 'tmp') + '/', 'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'en_US.UTF-8'}
        report['process'] = run_process('original', command, destination=out, environment=environment, failures=failures, timeout=45)
        failures.raise_first(); assert report['process']['exit_code'] == 0
        child = json.loads(read(out / 'capture/report.json', 4 * 1024 * 1024))
        report['child_association'] = associate(child, expected, cases, before, partial=False)
        assert child['passed'] and child['original_executed'] and child['inputs_before'] == child['inputs_after'] == expected
        cases = json.loads(raw[str(BASE / 'cases.json')]); assert [r['id'] for r in child['results']] == [c['id'] for c in cases]
        assert all(set(r['arms']) == {'selected', 'required'} and all(a['completed'] for a in r['arms'].values()) for r in child['results'])
        assert child['runtime_before'] == child['runtime_after']
        actual = child['runtime_after']; assert actual['python'] == sys.version and before[actual['executable']] == actual['executable_sha256']
        assert set(actual['libraries'].values()) == LIBRARIES
        assert all(before.get(path) == value for path, value in actual['libraries'].items())
        assert all(before.get(v['path']) == v['sha256'] for v in actual['loaded_python_modules'].values())
        report['passed'] = True
    except BaseException as error:
        if failures.first is not error: failures.remember('pilot', error)
    finally:
        report['inputs_after'] = {}
        for path in raw:
            def verify(path=path):
                value = sha(read(path, 64 * 1024 * 1024)); report['inputs_after'][path] = value
                assert value == before[path]
            failures.attempt('input ' + path, verify)
        report['staged_after'] = {}
        for path, expected_sha in staged.items():
            def verify_staged(path=path, expected_sha=expected_sha):
                value = sha(read(path, 256 * 1024)); report['staged_after'][path] = value
                assert value == expected_sha
            failures.attempt('staged input ' + path, verify_staged)
        def retain():
            path = out / 'capture/report.json'
            if path.exists():
                data = read(path, 4 * 1024 * 1024); child = json.loads(data)
                report['retained_child'] = {'path': str(path), 'sha256': sha(data), 'passed': child.get('passed'), 'error': child.get('error'), 'case_count': len(child.get('results', []))}
                report['retained_child']['association'] = associate(child, expected, cases, before, partial=True)
        failures.attempt('retain child report', retain)
        report['passed'] = report['passed'] and failures.first is None; report['failures'] = list(failures.records)
        stream = None
        try:
            stream = (out / 'report.json').open('x'); stream.write(json.dumps(report, indent=2) + '\n')
        except BaseException as error: failures.remember('report.write', error)
        finally:
            if stream is not None: failures.attempt('report.close', stream.close)
    failures.raise_first()
    print(json.dumps({'passed': report['passed'], 'report': str(out / 'report.json')}))

if __name__ == '__main__': main()
