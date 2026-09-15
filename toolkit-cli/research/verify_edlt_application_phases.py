"""Capture original application controls without implicit dependency getters."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'research'))
from windows_bridge import WindowsModelProbe


def digest(data): return hashlib.sha256(data).hexdigest()


def cases():
    captured = json.loads((ROOT / 'research/fixtures/edlt-application-observations.json').read_text())
    original = [row['input_case'] for row in captured['vectors'] if row['mode'] == 'global']
    names = ['choices-normal', 'choices-secondary-unused', 'choices-equal-existing', 'choices-raw-outside-range',
        'primary-noop-ui-commit', 'secondary-noop-ui-commit', 'primary-special-ui-commit',
        'secondary-special-ui-commit', 'primary-collision-ui-commit', 'secondary-disable-ui-commit',
        'secondary-disable-standby', 'secondary-disable-hidden-functional', 'secondary-disable-enable-fixed',
        'secondary-disable-blank-residual', 'secondary-disable-terminator-residual',
        'secondary-disable-scene-current', 'secondary-disable-scene-not-current',
        'secondary-disable-scene-missing-trigger', 'secondary-disable-scene-missing-action',
        'secondary-disable-widget-missing-group', 'secondary-disable-cross-app-restore',
        'global-QuickStatusGroup-missing', 'swap-via-disable-ui-commit', 'disable-restore-ui-commit']
    names += [f'widget-{kind}-variant1-secondary255' for kind in (2, 3, 4, 5, 15, 16)]
    result = [row for name in names for row in original if row['id'] == name]
    if len(result) != len(names): raise ValueError('Original case selection changed')
    template = next(row for row in original if row['id'] == 'disable-restore-ui-commit')
    for kind in (7, 8, 9):
        for scene in (False, True):
            fixture = {**template['fixture'], 'widget_type': kind}
            if scene: fixture.update(scene_variant=1, scene_ui_current=True)
            result.append({**template, 'id': f'mra{kind}-disable-restore' + ('-scene' if scene else ''), 'fixture': fixture})
    for kind in (4, 16):
        for scene in (False, True):
            fixture = {**template['fixture'], 'widget_type': kind, 'widget_control': 134}
            if scene: fixture.update(scene_variant=1, scene_ui_current=True)
            result.append({**template, 'id': f'status6-type{kind}-disable-restore' + ('-scene' if scene else ''), 'fixture': fixture})
    return result


def rows(selected):
    output = []
    for row in selected:
        data = dict(row['fixture']); action = row['action']
        def pack(value):
            return value['kind'] if value['kind'] == 'bind-only' else ','.join((value['kind'], value['field'], str(value['value'])))
        data['actions'] = ';'.join(pack(value) for value in action['steps']) if action['kind'] == 'sequence' else pack(action)
        for key, value in data.items():
            if isinstance(value, list): value = ','.join(map(str, value))
            elif isinstance(value, bool): value = str(value).lower()
            else: value = str(value)
            if any(character in value for character in '\t\r\n'): raise ValueError('Invalid case value')
            data[key] = value
        output.append('\t'.join([row['id'], *(key + '=' + value for key, value in data.items())]))
    return ('\n'.join(output) + '\n').encode()


def run(destination):
    selected = cases(); destination.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'research/NativeEdltApplicationPhasesProbe.cs'
    files = {'KEYGL5.xml': (ROOT / 'research/vendor/unitspec-plain/KEYGL5.xml').read_bytes(),
             'values.tsv': (ROOT / 'research/runtime/edlt-lifecycle/defaults.tsv').read_bytes(),
             'cases.tsv': rows(selected)}
    for name, data in files.items(): (destination / name).write_bytes(data)
    (destination / source.name).write_bytes(source.read_bytes())
    (destination / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    metadata = {'format': 'cbus-original-application-phases-v1', 'status': 'preparing',
        'cases': selected, 'source_sha256': digest(source.read_bytes()), 'input_sha256': {k: digest(v) for k, v in files.items()},
        'driver_sha256': digest(Path(__file__).read_bytes()),
        'bridge_sha256': digest((ROOT / 'research/windows_bridge.py').read_bytes()),
        'composition': 'global application controls; explicit dependency getters omitted; original save and CRC',
        'physical_device_verified': False}
    def record(): (destination / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    record(); probe = WindowsModelProbe(source, ROOT / 'research/vendor/toolkit/app', references=('eDLT.dll',))
    metadata.update(status='compiled', vendor_manifest=probe.vendor_manifest,
        executable_sha256=digest(probe.bridge.pull('vendor\\' + probe.prefix + '.exe')))
    record(); result = probe.run_result(arguments=('KEYGL5.xml', 'values.tsv', 'cases.tsv', 'global'), files=files)
    for name in ('stdout', 'stderr'):
        raw = result.pop(name); (destination / (name + '.txt')).write_bytes(raw); result[name + '_sha256'] = digest(raw)
    metadata.update(status='returned', result=result); record()
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    path = args.output or ROOT / 'research/runtime/edlt-application-phases' / ('original-' + uuid.uuid4().hex[:10])
    result = run(path); print(json.dumps({'directory': str(path), 'cases': len(result['cases']), 'result': result['result']}))
