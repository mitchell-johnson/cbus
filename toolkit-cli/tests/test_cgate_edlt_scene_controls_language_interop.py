"""Explicit buttons and Language boundaries through closed owned services.

Inputs and expected PP/label facts are synthetic and independently supplied.
The public CLI must preserve the entire project and acknowledge uncertainty;
none of these journeys executes an original GUI or a physical device.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.file_transfer import prepare_upload, upload
from test_cgate_barcode_database_interop import FaultGate, graph
import test_cgate_edlt_scene_inventory_interop as inventory


selector = inventory.selector
BACKENDS = inventory.BACKENDS
BUTTON_PROFILES = (
    'action-new-retains-old-items', 'action-old-selected-trigger-new-raw-trigger',
    'action-cancel', 'trigger-new-explicit-write', 'trigger-cancel',
    'lighting-zero-address', 'lighting-one-address', 'lighting-two-address',
    'lighting-secondary-zero-address', 'lighting-no-selected-row',
    'lighting-multiple-selected-rows',
)
LANGUAGE_PROFILES = (
    'language-valid-getter-retains-old-labels', 'language-explicit-setter',
    'language-explicit-refresh', 'language-cancel', 'language-noop',
    'later-language-cannot-enter-earlier-view', 'language-and-action-old-binding',
)
PROFILES = BUTTON_PROFILES + LANGUAGE_PROFILES
MUTATIONS = inventory.MUTATIONS
LANGUAGE_OPERATION = {'op': 'add-language-dialog', 'selected_ids': [1],
                      'preferences': 'registered-defaults'}
MEASUREMENT_RECORD = (42, 1, 2, 1, 0, 0, 0, 0, 0, 255, 255, 135, 64)
CRCS = {'OverallCRC', 'GlobalParameterCRC', 'WidgetsCRC', 'StaticTextCRC',
        'ScenesCheckSum'}


def bind(*, selected_trigger=True):
    events = [{'event': 'scene-current-changed', 'current': True}]
    if selected_trigger:
        events.append({'event': 'trigger-selected', 'value': 42,
                       'choice_index': 0, 'choice_identity': 'trigger:202/42'})
    return {'op': 'scene-selector-control', 'scene': 1, 'events': events}


def button(name, *, cancel=False, selected=None):
    row = {'op': 'scene-button-control', 'scene': 1, 'button': name,
           'dialog': {'cancel': cancel}}
    if not cancel:
        row['dialog']['name'] = 'Added action' if name == 'add-action-selector' else 'Added group'
    if selected is not None:
        row['selected_scenes'] = selected
    return row


def declared_profile(name):
    """Literal expectations; no product planner produces this oracle."""
    result = {'name': name, 'scene_operations': [], 'creations': [],
              'reserve_lighting': [], 'language': name in LANGUAGE_PROFILES,
              'final_default': 2, 'trigger': 42, 'action': 7, 'application': 0}
    rows = result['scene_operations']
    if name.startswith('action-') or name == 'language-and-action-old-binding':
        rows.append(bind())
        if name == 'action-old-selected-trigger-new-raw-trigger':
            rows.append({'op': 'set-trigger', 'scene': 1, 'group': 43})
            result['trigger'] = 43
        rows.append(button('add-action-selector', cancel=name == 'action-cancel'))
        if name != 'action-cancel':
            result['creations'].append(('Level', 202, 42, 2, 'Added action'))
    elif name.startswith('trigger-'):
        rows.extend([bind(), button('add-trigger-group', cancel=name == 'trigger-cancel')])
        if name == 'trigger-new-explicit-write':
            result['trigger'] = 0
            result['creations'] = [('Group', 202, None, 0, 'Added group'),
                                   ('Level', 202, 0, 7, 'Action Selector 7')]
    elif name.startswith('lighting-'):
        if name == 'lighting-secondary-zero-address':
            rows.append({'op': 'set-application', 'scene': 1, 'selector': 1})
        rows.append(bind())
        selected = ([] if name == 'lighting-no-selected-row' else
                    [1, 2] if name == 'lighting-multiple-selected-rows' else [1])
        rows.append(button('new-lighting-group', selected=selected))
        address = {'lighting-one-address': 1, 'lighting-two-address': 2}.get(name, 0)
        result['reserve_lighting'] = list(range(address))
        if len(selected) == 1:
            application = 57 if name == 'lighting-secondary-zero-address' else 56
            result['creations'] = [('Group', application, None, address, 'Added group')]
            result['application'] = 1 if address == 1 else 0
    else:
        rows.append({'op': 'get-selector-view', 'scene': 1})
        if name == 'language-explicit-setter':
            rows.append({'op': 'set-action', 'scene': 1, 'action': 7})
        elif name == 'language-explicit-refresh':
            rows.extend([bind(), {'op': 'scene-selector-control', 'scene': 1,
                                 'events': [{'event': 'trigger-current-changed'}]}])
    rows.append({'op': 'get-selector-view', 'scene': 1})
    parent = [{'op': 'scene-manager', 'operations': rows}, selector.parent.widget()]
    if result['language']:
        language = deepcopy(LANGUAGE_OPERATION)
        if name == 'language-cancel':
            language.update(cancel=True, selected_ids=[])
        elif name == 'language-noop':
            language['selected_ids'] = [2, 1]
        else:
            result['final_default'] = 1
        parent.insert(1 if name == 'later-language-cannot-enter-earlier-view' else 0, language)
    result['parent_operations'] = parent
    return result


@contextmanager
def journey(backend, variable, profile, tmp_path):
    case = inventory.case_named('populated-history-unchanged')
    try:
        with inventory.journey(backend, variable, case, tmp_path) as data:
            owner, relay, evidence, specs, endpoint, original = data
            root = ET.fromstring(original)
            network = root.find('Project/Network')
            if profile['language']:
                previous = network.find('Languages')
                if previous is not None:
                    network.remove(previous)
                languages = ET.SubElement(network, 'Languages')
                selector.scalar(languages, 'OID', uuid.uuid4())
                for identifier, name in ((0, '2'), (2, 'English (Australia)'), (1, 'English')):
                    node = ET.SubElement(languages, 'Language')
                    for key, value in (('OID', uuid.uuid4()), ('ID', identifier), ('TagValue', name)):
                        selector.scalar(node, key, value)
                for group in network.findall("Application[Address='202']/Group"):
                    for level in group.findall('Level'):
                        tags = level.find('TagsDLT')
                        if tags is None:
                            tags = ET.SubElement(level, 'TagsDLT')
                        for index in range(1, 5):
                            tag = ET.SubElement(tags, 'TagDLT')
                            text = f"Alternate {group.findtext('Address')}/{level.findtext('Address')}/{index}"
                            for key, value in (('LanguageID', 2), ('FlavourID', index),
                                               ('TagType', 'TEXT'), ('TagValue', text)):
                                selector.scalar(tag, key, value)
            app = network.find("Application[Address='56']")
            if profile['name'].startswith('lighting-'):
                for node in list(app.findall('Group')):
                    app.remove(node)
                unit = network.find("Unit[Address='20']")
                for name in ('CorridorLinkingLinkGroup', 'CorridorLinkingOfficeGroup',
                             'QuickStatusGroup', 'StandbyGroup'):
                    node = unit.find(f"PP[@Name='{name}']")
                    if node is not None:
                        node.set('Value', '255')
            for address in profile['reserve_lighting']:
                assert app.find(f"Group[Address='{address}']") is None
                node = ET.SubElement(app, 'Group')
                for key, value in (('OID', uuid.uuid4()), ('Address', address),
                                   ('TagName', f'Reserved group {address}')):
                    selector.scalar(node, key, value)
            project = tmp_path/'controls-language-synthetic.xml'
            project.write_bytes(ET.tostring(root))
            assert upload(prepare_upload('Projects/archived/'+project.name, project), owner)['upload_completed']
            for command in ('PROJECT CLOSE TEST', 'PROJECT DELETE TEST',
                            'PROJECT RESTORE TEST '+project.name, 'PROJECT USE TEST', 'PROJECT SAVE TEST'):
                assert owner.command(command).code == 200
            before = selector.snapshot(owner)
            evidence.update(format='cbus-edlt-scene-controls-language-owned-v1',
                case_id=profile['name'], declared_expectations=deepcopy(profile),
                fixture_sha256=hashlib.sha256(project.read_bytes()).hexdigest(),
                snapshots={'before': before})
            yield owner, relay, evidence, specs, endpoint, before
    finally:
        path = tmp_path/'scene-inventory-evidence.json'
        if path.exists():
            path.rename(tmp_path/'scene-controls-language-evidence.json')


def invoke(relay, evidence, specs, tmp_path, profile, **options):
    return inventory.invoke(relay, evidence, specs, tmp_path,
        profile['scene_operations'], parent_operations=profile['parent_operations'], process_timeout=90, **options)


def inspect_views(result, profile):
    nested = selector.selector_operation(result)['nested_operation_results']
    views = [row['view'] for row in nested if row['operation']['op'] == 'get-selector-view']
    assert views and views[-1]['trigger_group'] == profile['trigger']
    assert views[-1]['raw_action_selector'] == profile['action']
    assert views[-1]['application_selector'] == profile['application']
    buttons = [row['scene_button_control'] for row in nested
               if row['operation']['op'] == 'scene-button-control']
    for receipt in buttons:
        assert not receipt['scene_items_changed_by_handler']
        assert not receipt['implicit_callbacks_inferred'] and not receipt['modal_dialog_executed']
        assert receipt['original_instructions_executed'] == receipt['framework_instructions_executed'] == 0
        writes = [row for row in receipt['callbacks'] if row['action'] == 'WriteValue']
        if profile['name'].startswith('action-') or profile['name'] == 'language-and-action-old-binding':
            assert writes == [] and receipt['selected_item'] is None
            if profile['name'] != 'action-cancel':
                assert receipt['request']['arguments'] == ['202', '42']
                assert receipt['request']['returned_value'] == '2'
        elif profile['name'] == 'trigger-new-explicit-write':
            assert len(writes) == 1 and writes[0]['control'] == 'trigger'
            assert writes[0]['item']['value'] == '0'
        elif profile['name'] in ('lighting-no-selected-row', 'lighting-multiple-selected-rows'):
            assert receipt['early_return'] and receipt['callbacks'] == [] and receipt['request'] is None
        elif profile['name'].startswith('lighting-'):
            expected = [] if profile['name'] == 'lighting-two-address' else [profile['application']]
            assert [int(row['item']['value']) for row in writes] == expected
    if profile['language']:
        fresh = profile['name'] in ('language-explicit-setter', 'language-explicit-refresh')
        expected = (['Evening on', 'Evening wait', 'Evening off', ''] if fresh else
                    [f'Alternate 42/7/{index}' for index in range(1, 5)])
        assert [row['name'] for row in views[-1]['dynamic_labels']] == expected


def inspect_saved(before, after, profile, commands):
    old, new = ET.fromstring(before), ET.fromstring(after)
    baseline, actual = selector.parent.values(old), selector.parent.values(new)
    assert len(baseline) == len(actual) == 844
    assert set(actual) == set(baseline)
    expected_bucket = list(baseline['SceneBucket'])
    expected_bucket[0] = 2 | profile['application']
    expected_bucket[2:4] = [profile['trigger'], profile['action']]
    assert actual['SceneBucket'] == expected_bucket and len(expected_bucket) == 232
    assert actual['SceneCount'] == [8]
    assert [actual[f'Scene{i}StartAddress'][0] for i in range(1, 9)] == list(range(0, 40, 5))
    assert all(actual[f'StaticTextString{i}'] == baseline[f'StaticTextString{i}'] for i in range(64))
    assert actual['Widget6WidgetType'] == [12]
    assert [actual[f'Widget6WidgetByteValue{i}'][0] for i in range(1, 14)] == list(MEASUREMENT_RECORD)
    allowed = CRCS | {'SceneBucket', 'Widget6WidgetType',
                     *[f'Widget6WidgetByteValue{i}' for i in range(1, 14)]}
    assert {name for name in actual if actual[name] != baseline[name]} <= allowed
    for kind, application, group, address, name in reversed(profile['creations']):
        app = new.find(f"Project/Network/Application[Address='{application}']")
        parent = app if kind == 'Group' else app.find(f"Group[Address='{group}']")
        node = parent.find(f"{kind}[Address='{address}']")
        assert node is not None and node.findtext('TagName') == name
        assert node.findtext('OID') not in before
        if kind == 'Level':
            assert node.get('Value') == str(address)
        inventory.inspect_blank_variants(node)
        parent.remove(node)
    if profile['language']:
        network = new.find('Project/Network')
        languages = network.find('Languages')
        rows = [(int(row.findtext('ID')), row.findtext('TagValue')) for row in languages.findall('Language')]
        assert next(value for identifier, value in rows if identifier == 0) == str(profile['final_default'])
        assert {identifier for identifier, _ in rows if identifier} == ({1} if profile['final_default'] == 1 else {1, 2})
        expected_languages = deepcopy(old.find('Project/Network/Languages'))
        if profile['final_default'] == 1:
            expected_languages.find("Language[ID='0']/TagValue").text = '1'
            expected_languages.remove(expected_languages.find("Language[ID='2']"))
        assert graph(ET.tostring(languages, encoding='unicode')) == graph(
            ET.tostring(expected_languages, encoding='unicode'))
        location = list(network).index(languages)
        network.remove(languages)
        network.insert(location, deepcopy(old.find('Project/Network/Languages')))
    old_pp = {row.get('Name'): row for row in old.find("Project/Network/Unit[Address='20']").findall('PP')}
    for row in new.find("Project/Network/Unit[Address='20']").findall('PP'):
        if row.get('Name') in allowed:
            row.set('Value', old_pp[row.get('Name')].get('Value'))
    assert graph(ET.tostring(new, encoding='unicode')) == graph(before)
    assert sum(command.startswith('DBADDSAFE ') for command in commands) == len(profile['creations'])
    assert sum(command.startswith('PP SAVE_TO_SOURCE ') for command in commands) == 1
    assert commands.count('PROJECT SAVE TEST') == 2
    assert commands.count('PROJECT COPY TEST PABACKUP') == 1
    assert commands.count('PROJECT CLOSE TEST') == commands.count('PROJECT LOAD TEST') == 1


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
@pytest.mark.parametrize('name', PROFILES)
def test_public_controls_language_preview_apply_fresh(backend, variable, name, tmp_path, request):
    profile = declared_profile(name)
    with journey(backend, variable, profile, tmp_path) as data:
        owner, relay, evidence, specs, _endpoint, before = data
        evidence.update(nodeid=request.node.nodeid, test_kind='controls-language-preview-apply-fresh')
        preview, read = invoke(relay, evidence, specs, tmp_path, profile, dry_run=True)
        inspect_views(preview, profile)
        assert not any(command.startswith(MUTATIONS) for command in read['commands'])
        assert selector.snapshot(owner) == before
        result, call = invoke(relay, evidence, specs, tmp_path, profile)
        assert result['saved'] and result['persistence_verified'] and result['target_project_save_confirmed']
        inspect_views(result, profile)
        after = selector.snapshot(owner)
        inspect_saved(before, after, profile, call['commands'])
        fresh = inventory.fresh_state(after, specs, tmp_path, evidence)
        assert fresh['state']['scenes'][0]['items'] == []
        assert fresh['operation_results'][0]['view']['trigger_group'] == profile['trigger']
        assert fresh['operation_results'][0]['view']['raw_action_selector'] == profile['action']
        if profile['language']:
            expected = (['Evening on', 'Evening wait', 'Evening off', ''] if profile['final_default'] == 1 else
                        [f'Alternate 42/7/{index}' for index in range(1, 5)])
            assert [row['name'] for row in fresh['operation_results'][0]['view']['dynamic_labels']] == expected
        assert selector.snapshot(owner) == after
        evidence['snapshots'].update(after_preview=before, after=after)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
@pytest.mark.parametrize('name', ('action-new-retains-old-items', 'language-explicit-setter'))
def test_public_controls_language_known_failure_restores_source(backend, variable, name, tmp_path, request):
    profile = declared_profile(name)
    with journey(backend, variable, profile, tmp_path) as data:
        owner, _relay, evidence, specs, endpoint, before = data
        evidence.update(nodeid=request.node.nodeid, test_kind='controls-language-known-rollback')
        with FaultGate(endpoint, 'PP SET', 'refuse') as fault:
            result, call = invoke(fault, evidence, specs, tmp_path, profile, expected=1)
            assert fault.matches == 2
            state = result['edlt_parent_metadata_evidence']
            assert state['rollback_attempted'] and state['rollback_verified'] and state['automatic_retries'] == 0
            sets = [(command, call['statuses'][index]) for index, command in enumerate(call['commands'])
                    if command.startswith('PP SET ')]
            assert len(sets) == 2 and [status for _, status in sets] == [408, 200]
            assert not any(command.startswith('PP SAVE') for command in call['commands'])
            assert sets[0][0] != sets[1][0]
            session = sets[0][0].split(' ', 4)[2]
            source_crc = selector.parent.values(ET.fromstring(before))['OverallCRC']
            proposed_crc = state['plan']['parent_transaction']['changes']['OverallCRC']
            expected_set = lambda values: 'PP SET ' + session + ' OverallCRC "' + '\\ '.join(map(str, values)) + '"'
            assert sets == [(expected_set(proposed_crc), 408), (expected_set(source_crc), 200)]
            evidence['fault_wires'] = fault.evidence()
        assert graph(selector.snapshot(owner)) == graph(before)
        evidence['snapshots']['after_rollback'] = selector.snapshot(owner)


@pytest.mark.parametrize('backend,variable', BACKENDS, ids=('mock', 'daemon'))
@pytest.mark.parametrize('name', ('action-new-retains-old-items', 'language-explicit-setter'))
@pytest.mark.parametrize('phase', ('PP SAVE_TO_SOURCE', 'PROJECT SAVE'), ids=('pp-save', 'project-save'))
def test_public_controls_language_lost_success_never_replayed(backend, variable, name, phase, tmp_path, request):
    profile = declared_profile(name)
    with journey(backend, variable, profile, tmp_path) as data:
        owner, _relay, evidence, specs, endpoint, _before = data
        evidence.update(nodeid=request.node.nodeid, fault_phase=phase, test_kind='controls-language-lost-save')
        with FaultGate(endpoint, phase, 'drop', occurrence=2 if phase == 'PROJECT SAVE' else 1) as fault:
            result, call = invoke(fault, evidence, specs, tmp_path, profile, expected=1)
            indexes = [index for index, command in enumerate(call['commands']) if command.startswith(phase)]
            assert len(indexes) == fault.matches == (2 if phase == 'PROJECT SAVE' else 1)
            assert not any(command.startswith(('PP SET', 'PP SAVE', 'PROJECT SAVE', 'PROJECT CLOSE', 'PROJECT LOAD', 'DBDELETE'))
                           for command in call['commands'][indexes[-1]+1:])
            lost = [row for row in fault.evidence() if row.get('fault')]
            assert len(lost) == 1
            assert bytes.fromhex(lost[0]['lost_backend_terminal_hex']).decode() == f"[{lost[0]['fault']['tag']}] 200 OK\r\n"
            state = result['edlt_parent_metadata_evidence']
            assert state['state'] == 'uncertain' and state['database_state_uncertain']
            assert not state['saved'] and not state['persistence_verified'] and state['automatic_retries'] == 0
            assert state['pp_save_outcome_uncertain'] is (phase == 'PP SAVE_TO_SOURCE')
            assert state['target_project_save_outcome_uncertain'] is (phase == 'PROJECT SAVE')
            evidence['lost_save_wires'] = fault.evidence()
        evidence['snapshots']['after_lost_save'] = selector.snapshot(owner)
