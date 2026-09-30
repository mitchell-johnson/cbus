"""Bounded repeat-load evidence from unchanged original eDLT model methods.

Only synthetic in-memory raw PP/cache data are used. This never constructs the
original form, resets a project, opens C-Gate, or saves/programs anything.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

from cbus_toolkit.edlt_lifecycle import EdltLifecycle, FORMAT
from cbus_toolkit.edlt_reset import EdltResetControls, _RawState
from cbus_toolkit.unitspec import UnitSpecStore
from research.edlt_template_original import DLL_SHA256, PINS, digest

METHODS = [
    'method\tEDLTUnit.AfterLoadPPData\t0x06000457\td06a8b3de4a8062fbede4c1cbbd0cc6183e5da0eb3649631a15886671ef64fdb',
    'method\tEDLTUnit.LoadWidgetsFromAttributes\t0x06000458\t34588822ca30c2a6bf899dfea18dfef01c645b0e6c72d344061897a45144617f',
    'method\tCBusBaseUnit.AfterLoadPPData\t0x06000227\t28423d82320e15f2eb727885ffac6bf6e3e35f8be74e6d590e8567b587e6f9b6',
    'method\tCBusBaseUnit.PopulatePrimarySecondaryApplication\t0x060001fe\t5dc2532ec5110ab882b524604b25b24ca78ababa14c11453ebb9a822c54a713f',
]

def decode(value):
    return base64.b64decode(value, validate=True).decode('utf-16-le')


def raw(value):
    return value if isinstance(value, str) else ' '.join(hex(n) for n in value)


def cases():
    rows = [
        {'id': 'unchanged', 'assignments': []},
        {'id': 'primary-fallback-config', 'assignments': [
            ['PrimaryApplication', '0xff'], ['InvertDisplay', '0x1'],
            ['ConfigVersionMajor', '0xff'], ['ConfigVersionMinor', '0xff']]},
        {'id': 'lighting-replacement', 'assignments': [
            ['Widget6WidgetType', '0x2'], ['Widget6WidgetByteValue1', '0x20'],
            ['Widget6WidgetByteValue6', '0x2a'], ['Widget6WidgetByteValue12', '0x0']]},
        {'id': 'hidden-tail-constructor', 'assignments': [
            ['Widget6WidgetType', '0xff'], ['Widget7WidgetType', '0x2'],
            ['Widget7WidgetByteValue1', '0x20'], ['Widget7WidgetByteValue6', '0x2a'],
            ['Widget7RestoreLevel', '0x4d'], ['Widget8WidgetType', '0xe'],
            ['Widget8WidgetByteValue9', '0x2a'], ['Widget8RestoreLevel', '0x58']]},
        {'id': 'secondary-fallback', 'assignments': [
            ['SecondaryApplication', '0xff'], ['Widget6WidgetType', '0x3'],
            ['Widget6WidgetByteValue1', '0x80'], ['Widget6WidgetByteValue6', '0x2a']]},
        {'id': 'mra-first-widget', 'assignments': [
            ['Widget2WidgetType', '0x7'], ['Widget2WidgetByteValue1', '0xed'],
            ['Widget6WidgetType', '0x8'], ['Widget6WidgetByteValue1', '0x12']]},
        {'id': 'ordered-duplicate', 'assignments': [
            ['Widget6WidgetType', '0x2'], ['Widget6WidgetType', '0xe'],
            ['Widget6WidgetByteValue9', '0x2a'], ['Widget6WidgetByteValue7', '0x0'],
            ['Widget6WidgetByteValue8', '0x0']]},
        {'id': 'retained-array-tail', 'assignments': [
            ['StaticTextString0', '0x41 0x42 0x43'], ['StaticTextString0', '0x58']]},
        {'id': 'scene-replacement', 'assignments': [
            ['Scene1StartAddress', '0x0'],
            ['SceneBucket', '0x2 0x1 0x2a 0x2 0x1a 0x0 0xc 0x7b']]},
        {'id': 'second-load-malformed-widget', 'assignments': [
            ['Widget6WidgetType', 'malformed']]},
    ]
    rows.extend({'id': 'widget-kind-' + str(kind), 'assignments': [
        ['Widget6WidgetType', hex(kind)]]}
        for kind in (0, 1, 4, 5, 6, 9, 10, 11, 12, 13, 15, 16, 17, 254, 255))
    return rows


def metadata(editor, snapshot):
    groups = []
    for row in editor.requirements(snapshot).as_dict()['groups']:
        group = row['group']
        exists = group in (0, 1, 2, 12, 42, 254, 255)
        entry = {'application': row['application'], 'group': group, 'exists': exists}
        if exists:
            entry.update(dynamic_images=[] if group == 255 else [False] * 4,
                         levels=[0, 1, 2, 42, 254, 255])
        groups.append(entry)
    return {'format': FORMAT, 'applications': [56, 57, 127, 136, 172, 202, 203, 255], 'groups': groups}


def parse_output(text):
    stages, snapshots, assignments, identities = {}, {}, [], {}
    current = {}
    result = {'stages': stages, 'assignments': assignments, 'same_identity': identities}
    for line in text.splitlines():
        cells = line.split('\t')
        if cells[0] == 'complete':
            result['complete'] = True
        elif cells[0] == 'failure':
            result['failure'] = {'stage': cells[1], 'type': cells[2], 'message': decode(cells[3])}
        elif cells[1] == 'assignment':
            assignments.append([cells[3], decode(cells[4])])
        elif cells[1] == 'identity':
            identities[cells[2]] = cells[3] == 'True'
        else:
            stage = stages.setdefault(cells[0], {'raw_delta': {}, 'state': {}, 'model': {}})
            if cells[1] == 'raw':
                value = decode(cells[3])
                stage['raw_delta'][cells[2]] = {'before': current.get(cells[2]), 'after': value}
                current[cells[2]] = value
            else:
                stage[cells[1]][cells[2]] = cells[3]
                if cells[1] == 'state' and cells[2] == 'pp-hash':
                    snapshots[cells[0]] = dict(current)
    return result, snapshots


def probe(logic_dll, mono_root, spec_dir, destination):
    dll, mono, specs = Path(logic_dll).resolve(), Path(mono_root).resolve(), Path(spec_dir).resolve()
    out = Path(destination).absolute()
    if digest(dll) != DLL_SHA256:
        raise ValueError('Requires pinned original CBusLogicModel.dll')
    for name, expected in PINS.items():
        if digest(mono / name) != expected:
            raise ValueError('Requires pinned owned Mono: ' + name)
    source = Path(__file__).with_name('edlt_template_model_probe.cs')
    editor = EdltLifecycle(UnitSpecStore(specs).load('KEYGL5.xml'))
    baseline = {name: raw(value) for name, value in editor.snapshot(editor.spec.defaults()).items()}
    module_root = Path(__file__).resolve().parents[1] / 'src/cbus_toolkit'
    tracked = [Path(__file__).resolve(), source, dll, specs / 'KEYGL5.xml',
               *(mono / name for name in PINS),
               *(module_root / name for name in ('edlt_lifecycle.py', 'edlt_reset.py', 'edlt.py', 'unitspec.py'))]
    before = {str(path): digest(path) for path in tracked}
    out.mkdir()
    baseline_path = out / 'baseline.tsv'
    baseline_path.write_text(''.join(name + '\t' + value + '\n' for name, value in baseline.items()))
    env = {key: value for key, value in os.environ.items() if not key.startswith(('CBUS_', 'MONO_', 'DYLD_')) and key not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(MONO_CFG_DIR=str(mono / 'etc'), MONO_PATH=str(dll.parent) + os.pathsep + str(mono / 'lib/mono/4.5'), DYLD_FALLBACK_LIBRARY_PATH=str(mono / 'lib'))
    runtime = [str(mono / 'bin/mono-sgen64')]
    report = {'format': 'cbus-edlt-template-model-original-v1', 'passed': False,
              'scope': 'Original in-memory model second AfterLoadPPData and application-list population; no form/reset/Apply/persistence',
              'network_denied': True, 'physical_io': False, 'before': before, 'commands': [], 'cases': []}
    def run(stage, args):
        command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', *runtime, *args]
        result = subprocess.run(command, env=env, capture_output=True, timeout=30)
        (out / (stage + '.stdout')).write_bytes(result.stdout)
        (out / (stage + '.stderr')).write_bytes(result.stderr)
        report['commands'].append({'stage': stage, 'returncode': result.returncode, 'network_denied': True})
        return result
    try:
        compiled = run('compile', [str(mono / 'lib/mono/4.5/mcs.exe'), '-r:' + str(dll), '-r:System.Drawing', '-r:System.Xml.Linq', '-out:' + str(out / 'Probe.exe'), str(source)])
        if compiled.returncode:
            raise RuntimeError('Compile failed: ' + compiled.stderr.decode())
        for case in cases():
            case_path = out / (case['id'] + '.tsv')
            case_path.write_text(''.join(name + '\t' + value + '\n' for name, value in case['assignments']))
            result = run(case['id'], [str(out / 'Probe.exe'), str(specs / 'KEYGL5.xml'), str(baseline_path), str(case_path)])
            parsed, snapshots = parse_output(result.stdout.decode())
            if case['id'] == 'second-load-malformed-widget':
                failure = parsed.get('failure', {})
                partial = parsed.get('stages', {}).get('partial', {})
                if (result.returncode != 1 or failure.get('stage') != 'second'
                        or failure.get('type') != 'System.FormatException'
                        or partial.get('model', {}).get('widget-count') != '5'
                        or partial.get('state', {}).get('initialise') != 'False'):
                    raise AssertionError('Expected malformed second-load partial graph was not observed')
            elif result.returncode or not parsed.get('complete'):
                raise RuntimeError(case['id'] + ': ' + str(parsed.get('failure')))
            else:
                retained = {'widget-list', 'scene-list', 'label-list'}
                if (len(parsed['same_identity']) != 100
                        or {name for name, same in parsed['same_identity'].items() if same} != retained
                        or snapshots['populated'] != snapshots['second']):
                    raise AssertionError('Unexpected model identity or application-population raw mutation')
            runtime_rows = result.stderr.decode().splitlines()
            if len(runtime_rows) != 7:
                raise AssertionError('Unexpected runtime evidence')
            for line, path, name in zip(runtime_rows[:3], [dll, mono / 'lib/mono/4.5/mscorlib.dll', out / 'Probe.exe'], ['CBusLogicModel.Units.EDLT.EDLTUnit', 'System.Object', 'EdltTemplateModelProbe']):
                cells = line.split('\t')
                if (cells[:2] != ['assembly', name] or Path(cells[2]).resolve() != path.resolve()
                        or cells[3:] != [digest(path), '64']):
                    raise AssertionError('Wrong runtime loaded')
            if runtime_rows[3:] != METHODS:
                raise AssertionError('Original methods changed')
            report['methods'] = runtime_rows[3:]
            parsed['comparison'] = {}
            for source_stage, result_stage in [('initial', 'first'), ('assigned', 'second')]:
                if result_stage not in snapshots:
                    continue
                source_values = editor.snapshot(snapshots[source_stage])
                loaded = editor.load(source_values, metadata=metadata(editor, source_values))
                actual = editor.snapshot(snapshots[result_stage])
                different = {name: [loaded.after_load[name], value] for name, value in actual.items() if loaded.after_load[name] != value}
                parsed['comparison'][result_stage] = {'parameter_count': len(actual), 'differences': different}
                if different:
                    raise AssertionError(case['id'] + ' model differs: ' + str(different))
                state = _RawState(snapshots[source_stage], parsed['stages'][source_stage]['state']['dirty'].split(',') if parsed['stages'][source_stage]['state']['dirty'] else ())
                EdltResetControls(editor.spec)._raw_load(state, loaded)
                raw_differences = {name: [state.raw()[name], value] for name, value in snapshots[result_stage].items() if state.raw()[name] != value}
                actual_dirty = parsed['stages'][result_stage]['state']['dirty'].split(',')
                dirty_difference = set(state.phase().dirty_parameters) ^ set(actual_dirty)
                parsed['comparison'][result_stage].update(raw_differences=raw_differences, dirty_difference=sorted(dirty_difference))
                if raw_differences or dirty_difference:
                    raise AssertionError(case['id'] + ' raw/dirty differs: ' + str((raw_differences, dirty_difference)))
            # Full raw initial values remain local; retain synthetic transitions and hashes.
            parsed['stages']['initial'].pop('raw_delta')
            report['cases'].append({**case, **parsed})
        report['after'] = {str(path): digest(path) for path in tracked}
        if report['after'] != before:
            raise AssertionError('Inputs mutated')
        report['passed'] = True
    except BaseException as error:
        report['failure'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        report['artifacts'] = {path.name: {'sha256': digest(path), 'bytes': path.stat().st_size} for path in out.iterdir() if path.is_file()}
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def fixture_document(report):
    """Retain only method evidence and synthetic transitions, never specs."""
    return {
        'format': 'cbus-edlt-template-model-original-vectors-v1',
        'scope': report['scope'],
        'original_form_executed': False,
        'original_reset_executed': False,
        'original_apply_executed': False,
        'network_denied': report['network_denied'],
        'physical_io': False,
        'private_baseline_included': False,
        'portable_comparison_scope': 'Shared synthetic raw transitions, dirty names and retained model summaries; full original 874-parameter hashes require explicit private KEYGL5 specification',
        'portable_initial_overrides': {
            'SecondaryApplication': '0xff', 'InvertDisplay': '0x0',
            'SceneBucket': ' '.join(['0xff'] * 232), 'ProximityMode': '0x1',
        },
        'methods': report['methods'],
        'cases': report['cases'],
    }


def verify_fixture(report, fixture):
    expected = json.loads(Path(fixture).read_text())
    if fixture_document(report) != expected:
        raise AssertionError('Fresh model observations differ from retained fixture')
    return len(expected['cases'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--logic-dll', required=True)
    parser.add_argument('--mono-root', required=True)
    parser.add_argument('--spec-dir', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--verify-fixture')
    args = parser.parse_args()
    report = probe(args.logic_dll, args.mono_root, args.spec_dir, args.output)
    verified = verify_fixture(report, args.verify_fixture) if args.verify_fixture else None
    print(json.dumps({'passed': report['passed'], 'cases': len(report['cases']), 'fixture_cases_verified': verified, 'output': args.output}))
