"""Causal native adapter composition and one owning parent save."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.edlt import EdltError, _field, _render
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from cbus_toolkit.edlt_scene_label_images import parse_project_images
from tests.test_edlt import Session
from tests.test_edlt_parent_cache_panels import fixture
from tests.test_edlt_parent_metadata import MetadataClient, oid
from tests.test_edlt_scene import prepared
from tests.test_edlt_scene_label_images import export_bytes

OFFSETS = {'enable': 11, 'timer': 17, 'shutter': 10,
           'multilevel': 9, 'fan': 9, 'room-courtesy': 8}
UNIT = '//TEST/254/p/20'


def model():
    spec = fixture()
    client = MetadataClient(spec)
    tags = tuple({'variant': i, 'type': 'FONT' if i == 1 else 'TEXT',
                  'value': '0001,Current image' if i == 1 else 'Plain ' + str(i)}
                 for i in range(4))
    for app in (56, 203):
        client.applications.setdefault(app, {'oid': oid(app), 'tag': 'Application', 'groups': {}})
        client.applications[app]['groups'][42] = {
            'oid': oid(app * 100 + 42), 'tag': 'Current group', 'levels': (), 'tags': tags}
    client.applications[56]['groups'][12] = {'oid': oid(5612), 'tag': 'Output', 'levels': ()}
    client.applications[202]['groups'][42] = {
        'oid': oid(20242), 'tag': 'Trigger', 'levels': (88,), 'level_names': {88: 'Action'}}
    editor = EdltParentTransaction(spec)
    source = editor.snapshot(prepared(spec.defaults()))
    source['NavWidgetType'] = (1,)
    client.values = {name: _render(value) for name, value in source.items()}
    client.saved_values = deepcopy(client.values)
    raw = export_bytes('TEST')
    images = parse_project_images(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
    return editor, client, source, images


def operation(family, slot=0):
    app = 203 if family == 'enable' else 56
    result = {'op': family, 'page': 1 + slot // 4, 'position': 1 + slot % 4,
              'page_mode': 'multiple', 'label_controls': [
                  {'target': 'label', 'type': 10, 'events': [
                      {'event': 'selected-row', 'index': 1,
                       'identity': f'label:{app}/42/1', 'value': 1}]}]}
    if family == 'enable':
        result.update(variable=42, level=128)
    else:
        result['group'] = 42
    return result


def native_plan(editor, client, source, images, operations):
    return plan_native_parent_metadata(client.xml(), UNIT, source, editor,
                                       operations, project_images=images)


@pytest.mark.parametrize('family', tuple(OFFSETS))
def test_each_app_group_family_gets_exact_native_image_and_replays_owner(family):
    editor, client, source, images = model()
    plan = native_plan(editor, client, source, images,
                       (operation(family), {'op': 'general', 'debounce_ms': 50}))
    parent = plan.parent_plan
    assert parent.after_controls[_field(6, OFFSETS[family])] == (1,)
    assert parent.after_controls[_field(6, 1)][0] & 0x70 == 0x20
    assert len(parent.app_group_label_bindings) == 1
    assert parent.as_dict()['operation_results'][0]['label_controls']['pending'] is False
    assert parent.as_dict()['execution_counts']['terminal_crc_passes'] == 1
    session = Session(editor.spec)
    session.current = dict(source)
    result = editor.apply(session, parent)
    assert result['verified']
    assert len(session.calls) == len({name for name, _ in session.calls})


def test_six_families_share_exact_causal_metadata_and_one_terminal_parent():
    editor, client, source, images = model()
    plan = native_plan(editor, client, source, images,
                       tuple(operation(family, slot) for slot, family in enumerate(OFFSETS)))
    parent = plan.parent_plan
    assert tuple(binding.operation_number for binding in parent.app_group_label_bindings) == tuple(range(1, 7))
    for slot, family in enumerate(OFFSETS):
        assert parent.after_controls[_field(6 + slot, OFFSETS[family])] == (1,)
        assert parent.after_controls[_field(6 + slot, 1)][0] & 0x70 == 0x20
    assert parent.as_dict()['execution_counts']['terminal_normalization_passes'] == 1
    assert parent.as_dict()['execution_counts']['terminal_crc_passes'] == 1
    assert parent.before_save['Widget12WidgetType'] == (255,)


def test_app_group_json_binding_and_other_owner_cannot_stage_a_parent():
    editor, client, source, images = model()
    native = native_plan(editor, client, source, images,
                         (operation('enable'), {'op': 'general'}))
    parent = native.parent_plan
    other = EdltParentTransaction(editor.spec)
    for owner, bindings in ((editor, (parent.app_group_label_bindings[0].as_dict(),)),
                            (other, parent.app_group_label_bindings)):
        with pytest.raises(EdltError, match='owner'):
            owner.plan(source, metadata=native.cache, operations=parent.operations,
                       _app_group_label_bindings=bindings)


def test_pending_app_group_text_refuses_before_native_staging():
    editor, client, source, images = model()
    selected = operation('timer')
    selected['label_controls'] = [{'target': 'label', 'type': 3,
                                  'events': [{'event': 'input', 'text': 'Pending'}]}]
    before = list(client.commands)
    with pytest.raises(EdltError, match='pending'):
        native_plan(editor, client, source, images, (selected, {'op': 'general'}))
    assert client.commands == before


def test_scene_selection_refreshes_final_reference_in_canonical_parent():
    editor, client, source, images = model()
    selected = {'op': 'scene', 'page': 1, 'position': 1, 'page_mode': 'multiple',
                'scene': 1, 'label_type': 'blank', 'status_type': 'blank',
                'scene_controls': [{'event': 'scene-selected', 'index': 1,
                                    'identity': 'scene:2', 'value': 1}]}
    native = native_plan(editor, client, source, images, (selected, {'op': 'general'}))
    parent = native.parent_plan
    assert parent.after_controls[_field(6, 6)] == (1,)
    assert parent.as_dict()['operation_results'][0]['scene_reference']['scene'] == 2
    assert parent.scene_widget_bindings[0].operation_number == 1
    session = Session(editor.spec)
    session.current = dict(source)
    assert editor.apply(session, parent)['verified']


def test_earlier_scene_name_change_is_visible_to_scene_controls():
    editor, client, source, images = model()
    selected = {'op': 'scene', 'page': 1, 'position': 1, 'page_mode': 'multiple',
                'scene': 2, 'label_type': 'blank', 'status_type': 'blank',
                'scene_controls': [{'event': 'get-view'}]}
    native = native_plan(editor, client, source, images, (
        {'op': 'scene-manager', 'operations': [{'op': 'set-name-text', 'scene': 2, 'text': 'Earlier scene'}]},
        selected))
    binding = native.parent_plan.scene_widget_bindings[0].as_dict()
    assert any(row['name'] == '2 - Earlier scene' for row in binding['scene_rows'])


def test_scene_receipt_cannot_replace_issued_binding_during_apply():
    editor, client, source, images = model()
    selected = {'op': 'scene', 'page': 1, 'position': 1, 'page_mode': 'multiple',
                'scene': 2, 'label_type': 'blank', 'status_type': 'blank',
                'scene_controls': [{'event': 'get-view'}]}
    native = native_plan(editor, client, source, images, (selected, {'op': 'general'}))
    parent = native.parent_plan
    forged = replace(parent, scene_widget_bindings=(parent.scene_widget_bindings[0].as_dict(),))
    session = Session(editor.spec)
    session.current = dict(source)
    with pytest.raises(EdltError, match='owner'):
        editor.apply(session, forged)
    assert session.calls == []


@pytest.mark.parametrize('family', tuple(OFFSETS))
@pytest.mark.parametrize('language_first', (True, False), ids=('earlier-language', 'later-language'))
def test_app_group_choices_consume_only_their_causal_language(family, language_first):
    editor, client, source, images = model()
    for app in (56, 203):
        client.applications[app]['groups'][42]['tags'] += tuple(
            {'language': 2, 'variant': i, 'type': 'TEXT', 'value': 'Old text ' + str(i)}
            for i in range(4))
    document = ET.fromstring(client.xml())
    network = document.find('Project/Network')
    ET.SubElement(network, 'OID').text = oid(7039)
    collection = ET.SubElement(network, 'Languages')
    ET.SubElement(collection, 'OID').text = oid(7040)
    for identifier, name in ((0, '2'), (1, 'English'), (2, 'English (Australia)')):
        row = ET.SubElement(collection, 'Language')
        for field, value in (('OID', oid(7041 + identifier)), ('ID', identifier), ('TagValue', name)):
            ET.SubElement(row, field).text = str(value)
    language = {'op': 'add-language-dialog', 'selected_ids': [1], 'preferences': 'registered-defaults'}
    widget = operation(family)
    operations = (language, widget) if language_first else (widget, language)
    native = plan_native_parent_metadata(ET.tostring(document, encoding='unicode'), UNIT,
        source, editor, operations, project_images=images)
    binding = native.parent_plan.app_group_label_bindings[0].as_dict()
    assert binding['operation'] == (2 if language_first else 1)
    assert binding['provider_provenance']['current_default_language'] == (1 if language_first else 2)
    assert binding['dynamic_rows'][1]['name'] == ('0001,Current image' if language_first else 'Old text 1')
    assert binding['dynamic_rows'][1]['image_present'] is language_first
    assert native.parent_plan.after_controls[_field(6, 1)][0] & 0x70 == (0x20 if language_first else 0x10)
    session = Session(editor.spec)
    session.current = dict(source)
    assert editor.apply(session, native.parent_plan)['verified']


def _later_explicit_widget_control(kind):
    if kind == 'fan':
        return operation('fan', 1)  # widget7, distinct from intermediate widget6
    return {'op': 'scene', 'page': 1, 'position': 2,
            'page_mode': 'multiple', 'scene': 2,
            'label_type': 'blank', 'status_type': 'blank',
            'scene_controls': [{'event': 'get-view'}]}


def _checked_native_parent_replay(editor, source, native):
    parent = native.parent_plan
    session = Session(editor.spec)
    session.current = dict(source)
    assert editor.apply(session, parent)['verified']
    assert len(session.calls) == len({name for name, _ in session.calls})
    counts = parent.as_dict()['execution_counts']
    assert counts['terminal_normalization_passes'] == 1
    assert counts['terminal_crc_passes'] == 1
    return parent


@pytest.mark.parametrize('ordinary_kind', ('timer', 'scene'))
@pytest.mark.parametrize('later_kind', ('fan', 'scene'))
def test_native_controls_consume_intervening_ordinary_widget_after_scene_manager(ordinary_kind, later_kind):
    editor, client, source, images = model()
    if ordinary_kind == 'timer':
        intermediate = {'op': 'timer', 'page': 1, 'position': 1,
                        'page_mode': 'multiple', 'group': 42}
    else:
        intermediate = {'op': 'scene', 'page': 1, 'position': 1,
                        'page_mode': 'multiple', 'scene': 2,
                        'label_type': 'blank', 'status_type': 'blank'}
    operations = (
        {'op': 'scene-manager', 'operations': [
            {'op': 'set-name-text', 'scene': 2, 'text': 'Earlier scene'}]},
        intermediate, _later_explicit_widget_control(later_kind))
    commands = list(client.commands)
    native = native_plan(editor, client, source, images, operations)
    assert client.commands == commands  # pure native planning never performs I/O
    parent = _checked_native_parent_replay(editor, source, native)
    assert parent.after_controls[_field(6)] == ((5,) if ordinary_kind == 'timer' else (6,))
    assert parent.after_controls[_field(6, 6)] == ((42,) if ordinary_kind == 'timer' else (1,))
    assert parent.after_controls['StaticTextString63'] == tuple(b'Earlier scene'.ljust(64, b'\0'))
    if ordinary_kind == 'timer':
        # Independent Timer acceptance/source default Fan allocation; preceding
        # SceneManager owns63, the Timer reserves62 before the later control.
        assert parent.after_controls[_field(6, 17)] == (62,)
        assert parent.after_controls['StaticTextString62'] == tuple(b'Fan'.ljust(64, b'\0'))
        assert parent.after_controls[_field(6, 1)] == (0x34,)
        assert parent.after_controls[_field(6, 12)] == (60,)
        assert parent.after_controls[_field(6, 13)] == (0,)
    bindings = parent.app_group_label_bindings if later_kind == 'fan' else parent.scene_widget_bindings
    assert len(bindings) == 1 and bindings[0].operation_number == 3
    if later_kind == 'scene':
        assert bindings[0].as_dict()['scene_rows'][1]['name'] == '2 - Earlier scene'
    # Both source contexts and opaque bytes belong to the same parent replay.
    for offset in (4, 5, *range(22, 32)):
        assert parent.after_controls[_field(6, offset)] == source[_field(6, offset)]
        assert parent.after_controls[_field(7, offset)] == source[_field(7, offset)]


@pytest.mark.parametrize('already_blank', (True, False), ids=('no-op-blank', 'changed-blank'))
@pytest.mark.parametrize('later_kind', ('fan', 'scene'))
def test_native_widget_control_binding_consumes_exact_retained_blank_transition(already_blank, later_kind):
    editor, client, source, images = model()
    if not already_blank:
        timer = editor._editor('timer').plan(source, page=1, position=1,
                                            page_mode='multiple', group=42)
        source = {**timer.expected, **timer.changes}
    source[_field(6)] = (0,) if already_blank else (5,)
    source['Widget6RestoreLevel'] = (77,)
    client.values = {name: _render(value) for name, value in source.items()}
    client.saved_values = deepcopy(client.values)
    operations = (
        {'op': 'scene-manager', 'operations': [
            {'op': 'set-name-text', 'scene': 2, 'text': 'Earlier scene'}]},
        {'op': 'blank', 'page': 1, 'position': 1},
        _later_explicit_widget_control(later_kind))
    commands = list(client.commands)
    native = native_plan(editor, client, source, images, operations)
    assert client.commands == commands
    parent = _checked_native_parent_replay(editor, source, native)
    # Source Select Blank changes Restore only when the model type changes;
    # full-owner PP digest at the later control must agree with canonical replay.
    assert parent.after_controls[_field(6)] == (0,)
    assert parent.after_controls['Widget6RestoreLevel'] == ((77,) if already_blank else (0,))
    assert parent.before_save['Widget6RestoreLevel'] == ((77,) if already_blank else (0,))
    for offset in range(1, 32):
        assert parent.after_controls[_field(6, offset)] == parent.after_load[_field(6, offset)]
    bindings = parent.app_group_label_bindings if later_kind == 'fan' else parent.scene_widget_bindings
    assert len(bindings) == 1 and bindings[0].operation_number == 3


def test_ordinary_history_without_widget_controls_keeps_existing_plan_contract():
    editor, client, source, images = model()
    operations = (
        {'op': 'scene-manager', 'operations': [
            {'op': 'set-name-text', 'scene': 2, 'text': 'Earlier scene'}]},
        {'op': 'timer', 'page': 1, 'position': 1,
         'page_mode': 'multiple', 'group': 42})
    native = native_plan(editor, client, source, images, operations)
    parent = _checked_native_parent_replay(editor, source, native)
    assert parent.app_group_label_bindings == ()
    assert parent.scene_widget_bindings == ()
    assert parent.after_controls[_field(6)] == (5,)
