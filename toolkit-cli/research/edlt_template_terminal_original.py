"""Reproduce the bounded original-IL terminal branch proxy without a form.

Copies six branch bodies to an owned assembly, replacing original UI/model
dependencies with recording stubs. This is not execution of the original form,
validators, default binding/focus behavior, callback subscriber or persistence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

import pefile

PINS = {
    'bin/mono-sgen64': '91b99fc4b1158785b43506f2d76f9998c31f0492128e5789fbaaab0e300afd49',
    'lib/mono/4.5/mcs.exe': '857bb3129c3e2a5e7f8410db8fa5eb78139e934bb6279a72428597962311d771',
    'lib/mono/4.5/mscorlib.dll': '86364b7803c92d8c88b590031f015f80b10b00641e9d067e07a529a131d815e4',
    'lib/mono/4.5/System.dll': '5d5c56e3a70e873e8f8c514cc5db15c8647c8b0933b7eeae11a5e9705f5c8386',
    'lib/mono/4.5/System.Core.dll': '18507d65f274356ca237e7ff69eae1bd5f4e3ef3ad4c611b83cb65eebdbcf65f',
    'lib/mono/gac/Mono.Cecil/0.11.1.0__0738eb9f132ed756/Mono.Cecil.dll': '2df316dbdc0999b76dcd09029b6c966b8bce8f21845f551d4075daed208f2c38',
}
EDLT_SHA256 = '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3'
LOGIC_SHA256 = '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823'
CONTAINER_SHA256 = '5cba17be19a783e4b0c1e99025c9556fea605b97003ed6a3e9f3f182fb2c3ed0'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected_cases():
    serial = ['serial-valid']
    scene = [*serial, 'widgets', 'scene-valid:6,6']
    unit = [*scene, 'unit-valid']
    request = [*unit, 'save-request:false']
    result = [
        ('serial-rejected', 'false', serial),
        ('scene-rejected', 'false', scene),
        ('unit-rejected', 'false', [*unit, 'invalid-form:Multiple validation errors have occurred: |first|second|']),
        ('save-dispatched', 'true', request),
        ('save-no-subscriber', 'true', unit),
        ('apply-dispatched', 'void', request),
        ('ok-dispatched', 'void', [*unit, 'save-request:true']),
        ('ok-global-no-parent', 'void', ['parent']),
        ('ok-global-parent', 'void', ['parent', 'parent', 'parent-close']),
        ('cancel', 'void', ['closed:null']),
    ]
    result += [(stage + '-throws', 'System.InvalidOperationException:' + stage, events)
               for stage, events in [('serial', serial), ('scene', scene), ('unit', unit), ('callback', request)]]
    return [{'id': name, 'result': value, 'events': events} for name, value, events in result]


def method_proofs(path, output):
    raw = path.read_bytes()
    pe = pefile.PE(data=raw, fast_load=True)
    methods = {}
    for line in output.splitlines():
        fields = line.split('\t')
        if fields[0] == 'method':
            _, name, token, rva = fields
            offset = pe.get_offset_from_rva(int(rva, 16))
            if raw[offset] & 3 == 2:
                header, size = 1, raw[offset] >> 2
            else:
                header = (struct.unpack_from('<H', raw, offset)[0] >> 12) * 4
                size = struct.unpack_from('<I', raw, offset + 4)[0]
            methods[token] = {
                'assembly': path.name, 'method': name, 'metadata_token': '0x' + token,
                'rva': '0x' + rva, 'il_size': size,
                'il_sha256': hashlib.sha256(raw[offset + header:offset + header + size]).hexdigest(),
                'calls': [], 'exception_handlers': [],
            }
        elif fields[0] == 'call':
            _, token, offset, opcode, callee = fields
            methods[token]['calls'].append({'offset': offset, 'opcode': opcode, 'callee': callee})
        elif fields[0] == 'handler':
            _, token, kind, start, end, handler_start, handler_end = fields
            methods[token]['exception_handlers'].append({
                'kind': kind, 'try_start': start, 'try_end': end,
                'handler_start': handler_start, 'handler_end': handler_end})
        else:
            raise AssertionError('Unexpected metadata output')
    return list(methods.values())


def probe(app_root, mono_root, destination):
    app, mono, out = Path(app_root).resolve(), Path(mono_root).resolve(), Path(destination).absolute()
    originals = [app / name for name in ('eDLT.dll', 'CBusLogicModel.dll', 'SharpContainer.dll')]
    if [digest(path) for path in originals] != [EDLT_SHA256, LOGIC_SHA256, CONTAINER_SHA256]:
        raise ValueError('Requires pinned original eDLT, CBusLogicModel and SharpContainer assemblies')
    for name, expected in PINS.items():
        if digest(mono / name) != expected:
            raise ValueError('Requires pinned owned Mono/Cecil: ' + name)
    source = Path(__file__).with_name('edlt_template_terminal_probe.cs')
    tracked = [Path(__file__).resolve(), source, *originals, *(mono / name for name in PINS)]
    before = {str(path): digest(path) for path in tracked}
    out.mkdir()
    runtime = [str(mono / 'bin/mono-sgen64')]
    cecil = mono / 'lib/mono/gac/Mono.Cecil/0.11.1.0__0738eb9f132ed756/Mono.Cecil.dll'
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('CBUS_', 'MONO_', 'DYLD_')) and key not in ('PYTHONPATH', 'PYTHONHOME')}
    # The runtime path deliberately omits the vendor app directory.
    env.update(MONO_CFG_DIR=str(mono / 'etc'),
               MONO_PATH=str(cecil.parent) + os.pathsep + str(mono / 'lib/mono/4.5'),
               DYLD_FALLBACK_LIBRARY_PATH=str(mono / 'lib'))
    report = {'format': 'cbus-edlt-template-terminal-proxy-v1', 'passed': False,
              'scope': __doc__.strip(), 'before': before, 'commands': [], 'methods': [],
              'original_assembly_runtime_loaded': False, 'original_full_form_executed': False,
              'original_validators_executed': False, 'binding_focus_validated': False,
              'persistence_attempted': False, 'physical_device_verified': False}

    def run(stage, arguments):
        command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', *runtime, *arguments]
        completed = subprocess.run(command, env=env, capture_output=True, timeout=30)
        (out / (stage + '.stdout')).write_bytes(completed.stdout)
        (out / (stage + '.stderr')).write_bytes(completed.stderr)
        report['commands'].append({'stage': stage, 'returncode': completed.returncode, 'network_denied': True})
        if completed.returncode:
            raise RuntimeError('Terminal branch proxy failed: ' + stage + ': ' + completed.stderr.decode(errors='replace')[:2000])
        return completed.stdout.decode('utf-8')

    try:
        helper, proxy = out / 'TerminalProbe.exe', out / 'TerminalProxy.exe'
        run('compile', [str(mono / 'lib/mono/4.5/mcs.exe'), '-r:' + str(cecil), '-r:System.Core',
                        '-out:' + str(helper), str(source)])
        for original in originals:
            metadata = run('inspect-' + original.stem, [str(helper), 'inspect', str(original)])
            report['methods'].extend(method_proofs(original, metadata))
        copied = run('build', [str(helper), 'build', str(originals[0]), str(proxy)])
        report['copied_methods'] = []
        for line in copied.splitlines():
            prefix, name, token, rva, count = line.split('\t')
            if prefix != 'copy':
                raise AssertionError('Unexpected copy report')
            report['copied_methods'].append({'method': name, 'metadata_token': '0x' + token,
                                             'rva': '0x' + rva, 'instruction_count': int(count),
                                             'opcodes_preserved': True, 'dependency_operands_rebound': True})
        actual = []
        report['runtime_assemblies'] = []
        for line in run('run', [str(proxy), 'run']).splitlines():
            if line.startswith('runtime\t'):
                _, name, path = line.split('\t')
                path = Path(path).resolve()
                if name == 'TerminalProbe':
                    if path != proxy.resolve():
                        raise AssertionError('Wrong proxy executable loaded')
                elif not path.is_relative_to(mono):
                    raise AssertionError('Runtime assembly was not from the owned Mono root')
                report['runtime_assemblies'].append({'name': name, 'path': str(path), 'sha256': digest(path)})
                continue
            prefix, name, result, events = line.split('\t')
            if prefix != 'case':
                raise AssertionError('Unexpected runtime report')
            actual.append({'id': name, 'result': result, 'events': events.split(';') if events else []})
        report['cases'] = actual
        if not any(row['name'] == 'TerminalProbe' for row in report['runtime_assemblies']):
            raise AssertionError('Missing runtime identity')
        if actual != expected_cases():
            raise AssertionError('Terminal proxy cases differ from explicit expectations')
        report['after'] = {str(path): digest(path) for path in tracked}
        if report['after'] != before:
            raise AssertionError('Inputs changed')
        report['passed'] = True
    except BaseException as error:
        report['failure'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        report['artifacts'] = {path.name: digest(path) for path in out.iterdir() if path.is_file()}
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def verify_evidence(report, path):
    evidence = json.loads(Path(path).read_text())
    if evidence['cases'] != report['cases'] or evidence['copied_methods'] != report['copied_methods']:
        raise AssertionError('Fresh branch observations differ from retained evidence')
    actual = [{key: value for key, value in method.items() if key != 'calls'}
              for method in report['methods']]
    if actual != evidence['method_proofs']:
        raise AssertionError('Fresh original methods differ from retained evidence')
    return len(report['cases'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', required=True)
    parser.add_argument('--mono-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--verify-evidence')
    args = parser.parse_args()
    report = probe(args.app_root, args.mono_root, args.output)
    verified = verify_evidence(report, args.verify_evidence) if args.verify_evidence else None
    print(json.dumps({'passed': report['passed'], 'cases': len(report['cases']),
                      'copied_methods': len(report['copied_methods']),
                      'evidence_cases_verified': verified, 'output': args.output}))
