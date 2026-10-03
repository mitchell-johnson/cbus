"""AppGroup and Scene explicit callbacks through both owned public backends."""
import json
from xml.etree import ElementTree as ET

import pytest

from test_cgate_barcode_database_interop import FaultGate, graph
from test_cgate_edlt_global_images_interop import assert_lost_successful_save
import test_cgate_edlt_parent_add_dialog_interop as parent
from test_cgate_edlt_lighting_images_interop import invoke, provision
from test_cgate_edlt_scene_add_dialog_interop import snapshot

FAMILIES = ('enable', 'timer', 'shutter', 'multilevel', 'fan', 'room-courtesy')
OFFSETS = {'enable': 11, 'timer': 17, 'shutter': 10,
           'multilevel': 9, 'fan': 9, 'room-courtesy': 8}
TYPES = {'enable': 14, 'timer': 5, 'shutter': 3,
         'multilevel': 16, 'fan': 4, 'room-courtesy': 15}
BYTE1 = {'enable': 0x10, 'timer': 0x24, 'shutter': 0x20,
         'multilevel': 0x25, 'fan': 0x25, 'room-courtesy': 0x20}
INTERVENING_PROFILES = ('scene-name-timer-before-fan', 'scene-name-timer-before-scene')
PROFILES = (*FAMILIES, 'all-six', 'fan-four-status', 'scene-select',
            'scene-cycle', 'scene-name-before', *INTERVENING_PROFILES, 'pending')


def app_operation(family, slot=7):
    app = 203 if family == 'enable' else 56
    operation = {'op': family, 'page': 1 + (slot - 6) // 4,
                 'position': 1 + (slot - 6) % 4, 'page_mode': 'multiple',
                 'label_controls': [{'target': 'label', 'type': 10, 'events': [
                     {'event': 'selected-row', 'index': 1,
                      'identity': f'label:{app}/0/1', 'value': 1}]}]}
    if family == 'enable':
        operation.update(variable=0, level=128)
    else:
        operation['group'] = 0
    return operation


def profile_operations(profile):
    if profile in FAMILIES:
        return [app_operation(profile), parent.widget()]
    if profile == 'all-six':
        return [*(app_operation(family, 7 + index) for index, family in enumerate(FAMILIES)),
                parent.widget()]
    if profile in ('fan-four-status', 'pending'):
        operation = app_operation('fan' if profile == 'fan-four-status' else 'timer')
        operation['label_controls'] = ([{'target': target, 'events': [
            {'event': 'input', 'text': text}, {'event': 'enter'}]}
            for target, text in (('status', 'Owned stopped'), ('status-low', 'Owned quiet'),
                                 ('status-medium', 'Owned normal'), ('status-high', 'Owned fast'))]
            if profile == 'fan-four-status' else [{'target': 'label', 'type': 3,
                'events': [{'event': 'input', 'text': 'Pending owning control'}]}])
        return [operation, parent.widget()]
    if profile in INTERVENING_PROFILES:
        later = (app_operation('fan', 8) if profile == 'scene-name-timer-before-fan'
                 else {'op': 'scene', 'page': 1, 'position': 3, 'page_mode': 'multiple',
                       'scene': 2, 'label_type': 'blank', 'status_type': 'blank',
                       'scene_controls': [{'event': 'get-view'}]})
        return [{'op': 'scene-manager', 'operations': [
            {'op': 'set-name-text', 'scene': 2, 'text': 'Earlier owned scene'}]},
            {'op': 'timer', 'page': 1, 'position': 2,
             'page_mode': 'multiple', 'group': 0}, later, parent.widget()]
    selected = {'op': 'scene', 'page': 1, 'position': 2, 'page_mode': 'multiple',
                'scene': 1, 'label_type': 'blank', 'status_type': 'blank',
                'scene_controls': [{'event': 'scene-selected', 'index': 1,
                                    'identity': 'scene:2', 'value': 1}]}
    if profile == 'scene-cycle':
        selected.pop('scene')
        selected.update(mode='cycle', scenes=[1, 2, 1], scene_controls=[
            {'event': 'get-cycle'}, {'event': 'cycle-current', 'index': 1,
             'identity': 'cycle-slot:1', 'value': 1}, {'event': 'cycle-delete'},
            {'event': 'cycle-variant-checked', 'radio': 'select', 'checked': True}])
    if profile == 'scene-name-before':
        selected['scene_controls'] = [{'event': 'get-view'}]
        return [{'op': 'scene-manager', 'operations': [
            {'op': 'set-name-text', 'scene': 2, 'text': 'Earlier owned scene'}]},
            selected, parent.widget()]
    return [selected, parent.widget()]


def prepare_scenes(owner):
    root = ET.fromstring(snapshot(owner))
    unit = root.find("Project/Network/Unit[Address='20']")
    changes = {'SceneBucket': [2, 0, 7, 0, 255, 2, 0, 7, 2, 255]
                              + [2, 0, 255, 255, 255] * 6 + [255] * 192,
               'SceneCount': [8]}
    changes.update({f'Scene{scene}StartAddress': [(scene - 1) * 5] for scene in range(1, 9)})
    for row in unit.findall('PP'):
        if row.get('Name') in changes:
            row.set('Value', ' '.join(map(str, changes[row.get('Name')])))
    assert owner.command_document('DBSETXML //TEST/254/p/20', ET.tostring(unit, encoding='unicode')).code == 301
    assert owner.command('PROJECT SAVE TEST').code == 200


def preserve(before, after, profile):
    old, new = ET.fromstring(before), ET.fromstring(after)
    previous, current = parent.values(old), parent.values(new)
    assert len(previous) == len(current) == 844
    slots = (tuple(range(7, 13)) if profile == 'all-six' else
             (7, 8) if profile in INTERVENING_PROFILES else (7,))
    assert current['NavWidgetType'] == [1]
    assert current[f'Widget{max(slots) + 1}WidgetType'] == [255]
    allowed = {'NavWidgetType', 'WidgetGroups', 'OverallCRC', 'GlobalParameterCRC',
               'WidgetsCRC', 'StaticTextCRC', 'ScenesCheckSum', 'Widget6WidgetByteValue1',
               'Widget6WidgetByteValue2', f'Widget{max(slots) + 1}WidgetType'}
    for slot in slots:
        assert current[f'Widget{slot}RestoreLevel'] == previous[f'Widget{slot}RestoreLevel']
        allowed.update({f'Widget{slot}WidgetType', f'Widget{slot}RestoreLevel',
                        *(f'Widget{slot}WidgetByteValue{i}' for i in range(1, 32))})
        for offset in (4, 5, *range(22, 32)):
            assert current[f'Widget{slot}WidgetByteValue{offset}'] == previous[f'Widget{slot}WidgetByteValue{offset}']
    if profile in FAMILIES or profile == 'all-six':
        for slot, family in zip(slots, FAMILIES if profile == 'all-six' else (profile,)):
            assert current[f'Widget{slot}WidgetType'] == [TYPES[family]]
            assert current[f'Widget{slot}WidgetByteValue1'] == [BYTE1[family]]
            assert current[f'Widget{slot}WidgetByteValue6'] == [0]
            assert current[f'Widget{slot}WidgetByteValue{OFFSETS[family]}'] == [1]
    if profile == 'scene-select':
        assert current['Widget7WidgetByteValue6'] == [1]
    if profile == 'scene-cycle':
        assert [current[f'Widget7WidgetByteValue{i}'][0] for i in range(13, 22)] == [0, 0] + [255] * 7
        assert current['Widget7WidgetByteValue1'] == [128]
    if profile in INTERVENING_PROFILES:
        # Unchanged Toolkit Timer default/bound-default literals supply Fan,
        # duration60 and control0x34; the earlier SceneName reserves row63.
        assert current['Widget7WidgetType'] == [5]
        assert current['Widget7WidgetByteValue1'] == [0x34]
        assert current['Widget7WidgetByteValue6'] == [0]
        assert current['Widget7WidgetByteValue12'] == [60]
        assert current['Widget7WidgetByteValue13'] == [0]
        assert current['Widget7WidgetByteValue17'] == [62]
        if profile == 'scene-name-timer-before-fan':
            assert current['Widget8WidgetType'] == [4]
            assert current['Widget8WidgetByteValue1'] == [0x25]
            assert current['Widget8WidgetByteValue6'] == [0]
            assert current['Widget8WidgetByteValue9'] == [1]
        else:
            assert current['Widget8WidgetType'] == [6]
            assert current['Widget8WidgetByteValue6'] == [1]
    defaults = {'timer': {63: 'Fan'}, 'shutter': {63: 'Blind'},
                'multilevel': {63: 'Off', 62: 'Low', 61: 'Medium', 60: 'High'},
                'fan': {63: 'Off', 62: 'Low', 61: 'Medium', 60: 'High', 59: 'Fan'},
                'all-six': {63: 'Off', 62: 'Low', 61: 'Medium', 60: 'High', 59: 'Fan'},
                'fan-four-status': {63: 'Owned quiet', 62: 'Owned normal', 61: 'Owned fast',
                                    60: 'High', 59: 'Fan', 58: 'Owned stopped'},
                'scene-name-before': {63: 'Earlier owned scene'},
                'scene-name-timer-before-fan': {63: 'Earlier owned scene', 62: 'Fan',
                                               61: 'Off', 60: 'Low', 59: 'Medium', 58: 'High'},
                'scene-name-timer-before-scene': {63: 'Earlier owned scene', 62: 'Fan'}}
    for index, text in defaults.get(profile, {}).items():
        name = 'StaticTextString' + str(index)
        allowed.add(name)
        assert current[name] == list(text.encode().ljust(64, b'\0')), (profile, name, current[name])
    if profile == 'scene-name-before' or profile in INTERVENING_PROFILES:
        expected_bucket = list(previous['SceneBucket'])
        expected_bucket[9] = 63
        assert current['SceneBucket'] == expected_bucket
        allowed.add('SceneBucket')
    changed = {name for name in current if current[name] != previous[name]}
    assert changed <= allowed, changed - allowed
    for row in new.find("Project/Network/Unit[Address='20']").findall('PP'):
        if row.get('Name') in allowed:
            before_row = old.find("Project/Network/Unit[Address='20']/PP[@Name='" + row.get('Name') + "']")
            row.set('Value', before_row.get('Value'))
    if profile in ('enable', 'all-six'):
        application = new.find("Project/Network/Application[Address='203']")
        created = application.find("NetVar[Address='0']")
        assert created is not None and created.findtext('OID') not in before
        application.remove(created)
    assert graph(ET.tostring(new, encoding='unicode')) == graph(before)


def public_journey(backend, variable, profile, tmp_path, *, lost_save=False):
    with parent.journey(backend, variable, tmp_path, {}) as (owner, relay, evidence, specs, endpoint):
        provision(owner, tmp_path, 'project-font-image')
        if profile.startswith('scene-'):
            prepare_scenes(owner)
        before = snapshot(owner)
        export = tmp_path / 'images.json'
        exported, _call = invoke(relay, evidence, ['edlt-project-images', 'TEST', '--output', export])
        operations = tmp_path / 'operations.json'
        operations.write_text(json.dumps(profile_operations(profile)))
        argv = ['unit', '--lock-address', '//TEST/254', '--source', '/db//TEST/254/p/20',
                'edlt-parent-transaction', '--spec-dir', specs, '--auto-metadata',
                '--exclusive-project', '--operations', operations, '--project-images-export', export,
                '--project-images-sha256', exported['sha256']]
        evidence.update(format='cbus-edlt-widget-controls-owned-v1', profile=profile)
        if profile == 'pending':
            result, call = invoke(relay, evidence, argv, expected=1)
            assert 'pending' in result['error']
            assert not any(c.startswith(('PP SET ', 'PP SAVE', 'PROJECT SAVE ', 'PROJECT COPY ', 'DBADD', 'DBSET', 'DBDELETE'))
                           for c in call['commands'])
            assert graph(snapshot(owner)) == graph(before)
            return
        preview, preview_call = invoke(relay, evidence, ['unit', '--dry-run', *argv[1:]])
        assert not any(c.startswith(('PP SET ', 'PP SAVE', 'PROJECT SAVE ', 'PROJECT COPY ', 'DBADD', 'DBSET', 'DBDELETE'))
                       for c in preview_call['commands'])
        assert graph(snapshot(owner)) == graph(before)
        if profile in ('scene-name-before', 'scene-name-timer-before-scene'):
            binding = preview['parent_transaction']['scene_widget_bindings'][0]
            assert binding['scene_rows'][1]['name'] == '2 - Earlier owned scene'
        if lost_save:
            with FaultGate(endpoint, 'PP SAVE_TO_SOURCE', 'drop') as fault:
                result, call = invoke(fault, evidence, [*argv, '--backup-project', 'WLOST'], expected=1, complete=False)
                assert fault.matches == 1
                assert_lost_successful_save(fault)
                assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in call['commands']) == 1
                saved = next(i for i, c in enumerate(call['commands']) if c.startswith('PP SAVE_TO_SOURCE '))
                assert not any(c.startswith(('PP SET ', 'PP SAVE', 'PROJECT SAVE ', 'PROJECT CLOSE ', 'PROJECT LOAD ', 'DBDELETE'))
                               for c in call['commands'][saved + 1:])
                evidence['lost_save_wires'] = fault.evidence()
        else:
            result, call = invoke(relay, evidence, [*argv, '--backup-project', 'WBACKUP'])
            assert result['saved'] and result['persistence_verified']
            assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in call['commands']) == 1
        after = snapshot(owner)
        preserve(before, after, profile)
        if profile == 'fan-four-status':
            values = parent.values(ET.fromstring(after))
            assert [bytes(values['StaticTextString' + str(values[f'Widget7WidgetByteValue{i}'][0])]).split(b'\0')[0]
                    for i in (10, 11, 12, 13)] == [b'Owned stopped', b'Owned quiet', b'Owned normal', b'Owned fast']
        evidence['snapshots'] = {'before': before, 'after': after}
        if not lost_save:
            for command in ('PROJECT CLOSE TEST', 'PROJECT LOAD TEST'):
                assert owner.command(command).code == 200
            assert graph(snapshot(owner)) == graph(after)


@pytest.mark.parametrize('backend,variable', parent.BACKENDS, ids=('mock', 'daemon'))
@pytest.mark.parametrize('profile', PROFILES)
def test_public_widget_control_histories_one_save_and_preservation(backend, variable, profile, tmp_path):
    public_journey(backend, variable, profile, tmp_path)


@pytest.mark.parametrize('backend,variable', parent.BACKENDS, ids=('mock', 'daemon'))
def test_public_widget_controls_lost_successful_save_is_not_replayed(backend, variable, tmp_path):
    public_journey(backend, variable, 'all-six', tmp_path, lost_save=True)
