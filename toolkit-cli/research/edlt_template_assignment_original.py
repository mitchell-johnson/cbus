"""Original PPAttribute setters plus a source-pinned template-loop proxy.

Every case runs in a new network-denied process with a newly constructed graph.
No original form or CBusBaseUnit lookup is executed; the probe declares those
proxy boundaries. Vendor code is loaded unchanged and never redistributed.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

from edlt_template_original import DLL_SHA256, PINS, digest


def cases():
    result = []

    def add(name, tokens, operations, *, initial=False, dirty=False, list_throw=0,
            property_throw=False, extra=()):
        result.append({'id': name, 'initial_initialize_mode': initial,
                       'list_listener_throw_on_event': list_throw,
                       'property_listener_throws': property_throw,
                       'attributes': [{'name': 'Value', 'tokens': tokens, 'dirty': dirty}, *extra],
                       'operations': [{'mode': mode, 'name': attr, 'value': value, 'index': index}
                                      for mode, attr, value, index in operations]})

    def op(value, mode='template', attr='Value', index=0):
        return (mode, attr, value, index)

    for name, tokens, value in [
        ('template-short-retains-tail', ['A', 'B', 'C'], 'X'),
        ('template-long-appends', ['A'], 'X Y Z'),
        ('template-identical-no-dirty', ['A', 'B'], 'A B'),
        ('template-identical-preserves-dirty', ['A', 'B'], 'A B'),
        ('template-leading-empty-token', ['A', 'B', 'C'], ' X'),
        ('template-double-space', ['A', 'B', 'C'], 'X  Y'),
        ('template-trailing-space', ['A', 'B', 'C'], 'X '),
        ('template-empty-retains-tail', ['A', 'B'], ''),
        ('template-tab-is-one-token', ['A', 'B'], 'X\tY'),
        ('template-normalize-dollar', ['0xAB', 'tail'], '$ab'),
        ('template-normalize-dollar-x', ['0xab', 'tail'], '$xab'),
        ('template-normalize-minus-one', ['0xff', 'tail'], '0xffffffff'),
        ('template-uppercase-minus-one-unchanged', ['A'], '0xFFFFFFFF'),
        ('template-uppercase-prefix-minus-one-unchanged', ['A'], '0Xffffffff'),
        ('template-dollar-letter-i', ['A'], '$i'),
        ('template-dollar-sharp-s', ['A'], '$\u00df'),
        ('template-dollar-dotless-i', ['A'], '$\u0131'),
        ('template-dollar-x-sharp-s', ['A'], '$x\u00df'),
        ('template-dollar-empty-suffix', ['A'], '$'),
        ('template-dollar-x-empty-suffix', ['A'], '$x'),
        ('template-dollar-uppercase-x', ['A'], '$Xab'),
        ('template-dollar-ignorable-prefix', ['A'], '$\u200dxab'),
        ('template-dollar-leading-ignorable-prefix', ['A'], '\u200d$xab'),
        ('template-empty-baseline', [], 'A'),
        ('template-raw-null-baseline', [None, 'B'], 'X'),
        ('template-null-input-failure', ['A'], None),
        ('template-empty-raw-join', ['', '', 'B', ''], 'B '),
    ]:
        add(name, tokens, [op(value)], dirty=name == 'template-identical-preserves-dirty')
    add('template-duplicates-last-prefix-retains-tail', ['A', 'B', 'C'], [op('X Y'), op('Z')])
    add('template-unknown-no-mutation', ['A'], [op('X', attr='Unknown')])
    add('template-case-sensitive-lookup', ['A'], [op('X', attr='value')])
    add('template-stale-initialize-cleared', ['A'], [op('A')], initial=True)
    add('template-first-duplicate-baseline-name', ['A'], [op('X')],
        extra=({'name': 'Value', 'tokens': ['B'], 'dirty': False},))
    for name, value in [('normal', '48 202'), ('short', '48'), ('empty', ''),
                        ('negative', '-1 202'), ('double-space', '48  202')]:
        add('application-' + name, ['A'], [op(value, attr='Application')],
            extra=({'name': 'Application', 'tokens': ['0xff', '0xff', 'TAIL'], 'dirty': False},))
    add('application-unknown-malformed-fails-before-lookup', ['A'], [op('48  202', attr='Application')])
    add('application-malformed-retains-stale-initialize', ['A'], [op('48  202', attr='Application')], initial=True)
    for name, initial in [('direct-normal', False), ('direct-initialize', True)]:
        add(name, ['A', 'B', 'C'], [op('X Y', mode='set_value')], initial=initial)
    for name, mode, value in [('full-clears-tail', 'set_full', 'X Y'),
                              ('value-null-fails-before-write', 'set_value', None),
                              ('full-null-clears-then-fails', 'set_full', None),
                              ('full-dollar-uppercases-whole-string', 'set_full', '$ab cd')]:
        add(name, ['A', 'B'], [op(value, mode=mode)])
    add('item-beyond-end-appends-one', ['A'], [op('Z', mode='set_item', index=7)])
    add('item-negative-fails', ['A'], [op('Z', mode='set_item', index=-1)])
    add('direct-property-listener-failure', ['A', 'B'], [op('X Y', mode='set_value')], property_throw=True)
    add('template-property-listener-suppressed', ['A', 'B'], [op('X Y')], property_throw=True)
    add('direct-list-listener-failure', ['A', 'B', 'C'], [op('X Y', mode='set_value')], list_throw=2)
    add('template-list-listener-failure-stale-init', ['A', 'B', 'C'], [op('X Y'), op('Z')], list_throw=2)
    add('template-second-attribute-failure', ['A'], [op('X'), op('Y', attr='Other')], list_throw=2,
        extra=({'name': 'Other', 'tokens': ['B'], 'dirty': False},))
    for name, tokens, mode in [('int-empty', [], 'get_int'), ('int-null', [None], 'get_int'),
                               ('int-signed-hex', ['0xffffffff', 'tail'], 'get_int'),
                               ('int-hex-whitespace', ['0x ff '], 'get_int'),
                               ('int-decimal-whitespace', [' 48 '], 'get_int'),
                               ('int-bad', ['nope'], 'get_int'),
                               ('bool-empty', [], 'get_bool'), ('bool-zero', ['0x0'], 'get_bool'),
                               ('bool-upper-zero', ['0X0'], 'get_bool'), ('bool-decimal-zero', ['0'], 'get_bool'),
                               ('values-little-endian', ['0x01', '0x02'], 'get_values_int')]:
        add('getter-' + name, tokens, [op('', mode=mode)])
    add('getter-outside-is-null', ['A'], [op('', mode='get_item', index=3)])
    add('getter-negative-fails', ['A'], [op('', mode='get_item', index=-1)])
    for name, value in [('negative', '-1'), ('overflow', '256')]:
        add('integer-setter-clamp-' + name, ['A', 'B'], [op(value, mode='set_int')])
    return result


def encode(value):
    return 'N' if value is None else 'S' + base64.b64encode(value.encode('utf-16-le')).decode('ascii')


def decode(value):
    return None if value == 'N' else base64.b64decode(value[1:], validate=True).decode('utf-16-le')


def boolean(value):
    if value not in ('True', 'False'):
        raise ValueError('Invalid Boolean receipt')
    return value == 'True'


def serialize(case):
    lines = [['case', case['id'], str(case['initial_initialize_mode']),
              str(case['list_listener_throw_on_event']), str(case['property_listener_throws'])]]
    lines += [['attribute', encode(row['name']), str(row['dirty']), *map(encode, row['tokens'])]
              for row in case['attributes']]
    lines += [['operation', row['mode'], encode(row['name']), encode(row['value']), str(row['index'])]
              for row in case['operations']]
    return '\n'.join('\t'.join(row) for row in lines) + '\n'


def tokens(fields, start):
    count = int(fields[start])
    # The writer retains a tab even for a zero-token snapshot.
    raw = fields[start + 1:] if count else []
    if len(raw) != count:
        raise ValueError('Token count mismatch')
    return list(map(decode, raw))


def observations(stdout):
    result = []
    for line in stdout.splitlines():
        f = line.split('\t')
        if f[0] == 'state':
            row = {'kind': 'state', 'phase': f[1], 'initialize_mode': boolean(f[2]),
                   'attribute_index': int(f[3]), 'name': decode(f[4]), 'value': decode(f[5]),
                   'value_full': decode(f[6]), 'value1': decode(f[7]), 'dirty': boolean(f[8]), 'tokens': tokens(f, 9)}
        elif f[:2] == ['event', 'list']:
            row = {'kind': 'list_event', 'attribute_index': int(f[2]), 'change_type': f[3],
                   'new_index': int(f[4]), 'old_index': int(f[5]), 'initialize_mode': boolean(f[6]),
                   'dirty': boolean(f[7]), 'tokens': tokens(f, 8)}
        elif f[:2] == ['event', 'property']:
            row = {'kind': 'property_event', 'attribute_index': int(f[2]), 'property': decode(f[3]),
                   'initialize_mode': boolean(f[4]), 'dirty': boolean(f[5]), 'tokens': tokens(f, 6)}
        elif f[0] == 'operation':
            row = {'kind': 'operation', 'operation_index': int(f[1]), 'mode': f[2],
                   'name': decode(f[3]), 'value': decode(f[4]), 'index': int(f[5])}
        elif f[0] == 'getter':
            row = {'kind': 'getter', 'type': f[1], 'value': decode(f[2]) if f[1] == 'string' else boolean(f[2]) if f[1] == 'bool' else int(f[2])}
        elif f[0] == 'result':
            row = {'kind': 'result', 'status': f[1], 'operation_index': int(f[2]),
                   'boundary': f[3], 'initialize_mode': boolean(f[4])}
            if f[1] == 'error':
                row['error'] = f[5]
        else:
            raise ValueError('Unexpected observation: ' + line)
        result.append(row)
    return result


def probe(logic_dll, mono_root, destination, verify_fixture=None):
    dll, mono, out = Path(logic_dll).resolve(), Path(mono_root).resolve(), Path(destination).absolute()
    if digest(dll) != DLL_SHA256:
        raise ValueError('Requires pinned original assembly')
    for name, expected in PINS.items():
        if digest(mono / name) != expected:
            raise ValueError('Requires pinned owned runtime: ' + name)
    source = Path(__file__).with_name('edlt_template_assignment_probe.cs')
    tracked = [Path(__file__).resolve(), Path(__file__).with_name('edlt_template_original.py'), source, dll,
               *(mono / name for name in PINS)]
    before = {str(path): digest(path) for path in tracked}
    out.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith(('CBUS_', 'MONO_', 'DYLD_')) and key not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(MONO_CFG_DIR=str(mono / 'etc'), MONO_PATH=str(dll.parent) + os.pathsep + str(mono / 'lib/mono/4.5'), DYLD_FALLBACK_LIBRARY_PATH=str(mono / 'lib'))
    runtime = [str(mono / 'bin/mono-sgen64')]
    report = {'format': 'cbus-edlt-template-assignment-original-v1', 'passed': False, 'before': before,
              'scope': 'Unchanged PPAttribute constructors/accessors; synthetic template assignment-loop and lookup proxies; fresh process per case',
              'commands': [], 'cases': [], 'network_denied': True, 'original_dialog_executed': False,
              'original_parent_lifecycle_executed': False, 'original_unit_lookup_executed': False}

    def execute(stage, command):
        args = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', *command]
        completed = subprocess.run(args, env=env, capture_output=True, timeout=30)
        (out / (stage + '.stdout')).write_bytes(completed.stdout)
        (out / (stage + '.stderr')).write_bytes(completed.stderr)
        report['commands'].append({'stage': stage, 'returncode': completed.returncode, 'network_denied': True})
        if completed.returncode:
            raise RuntimeError('Probe stage failed: ' + stage)
        return completed

    try:
        execute('compile', runtime + [str(mono / 'lib/mono/4.5/mcs.exe'), '-r:' + str(dll),
                                     '-out:' + str(out / 'Probe.exe'), str(source)])
        expected_methods = None
        for case in cases():
            path = out / (case['id'] + '.tsv')
            path.write_text(serialize(case), encoding='ascii')
            result = execute(case['id'], runtime + [str(out / 'Probe.exe'), str(path)])
            lines = result.stderr.decode().splitlines()
            for line, type_name, assembly_path in zip(lines[:3], ('CBusLogicModel.PPAttribute', 'System.Object', 'EdltTemplateAssignmentProbe'), (dll, mono / 'lib/mono/4.5/mscorlib.dll', out / 'Probe.exe')):
                fields = line.split('\t')
                if (len(fields) != 5 or fields[:2] != ['assembly', type_name] or Path(fields[2]).resolve() != assembly_path.resolve()
                        or fields[3:] != [digest(assembly_path), '64']):
                    raise AssertionError('Wrong loaded assembly')
            methods = lines[3:]
            if not methods or any(not row.startswith('method\t') for row in methods):
                raise AssertionError('Missing original method body receipts')
            if expected_methods is None:
                expected_methods = methods
            if expected_methods != methods:
                raise AssertionError('Original method receipts changed across processes')
            report['cases'].append({**case, 'observations': observations(result.stdout.decode()),
                                    'stdout_sha256': hashlib.sha256(result.stdout).hexdigest()})
        report['method_receipts'] = expected_methods
        report['after'] = {str(path): digest(path) for path in tracked}
        if before != report['after']:
            raise AssertionError('Probe inputs changed')
        if verify_fixture and report['cases'] != json.loads(Path(verify_fixture).read_text())['cases']:
            raise AssertionError('Original assignment observations differ from fixture')
        report['fixture_cases_verified'] = len(report['cases']) if verify_fixture else None
        report['passed'] = True
    except BaseException as error:
        report['failure'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        report['artifacts'] = {p.name: digest(p) for p in out.iterdir() if p.is_file()}
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--logic-dll', required=True)
    parser.add_argument('--mono-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--verify-fixture')
    args = parser.parse_args()
    report = probe(args.logic_dll, args.mono_root, args.output, args.verify_fixture)
    print(json.dumps({'passed': report['passed'], 'cases': len(report['cases']),
                      'fixture_cases_verified': report['fixture_cases_verified'], 'output': args.output}))
