"""Whole-parent regression oracles for source-owned MRA callback composition."""
from copy import deepcopy
from dataclasses import replace

import pytest

from cbus_toolkit.edlt import EdltError, _field, _render
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from tests.test_edlt import Session
from tests.test_edlt_parent_cache_panels import fixture
from tests.test_edlt_parent_metadata import MetadataClient
from tests.test_edlt_scene import prepared

UNIT = '//TEST/254/p/20'
KINDS = {'zone-control': 7, 'source-select': 8, 'source-control': 9}


def model(records=(), *, spec=None):
    spec = fixture() if spec is None else spec
    editor = EdltParentTransaction(spec)
    source = editor.snapshot(prepared(spec.defaults()))
    source['NavWidgetType'] = (1,)
    for slot, record in records:
        for offset, value in enumerate(record):
            source[_field(slot, offset)] = (value,)
        source[f'Widget{slot}RestoreLevel'] = (213,)
    client = MetadataClient(spec)
    client.values = {name: _render(value) for name, value in source.items()}
    client.saved_values = deepcopy(client.values)
    return editor, client, source


def native(editor, client, source, operations):
    if len(operations) == 1:
        operations = (*operations, {'op': 'static-text-dialog', 'edits': []})
    return plan_native_parent_metadata(client.xml(), UNIT, source, editor, operations)


def operation(family, events, slot=6, **kwargs):
    return {'op': family, 'page': 1 + (slot - 6) // 4,
            'position': 1 + (slot - 6) % 4, 'page_mode': 'multiple',
            'mra_controls': events, **kwargs}


def raw(family):
    data = bytearray(range(32))
    data[0] = KINDS[family]
    data[1] = 0xFF
    data[6] = 199
    if family == 'zone-control':
        data[7:13] = (99, 100, 231, 219, 200, 201)
    elif family == 'source-select':
        data[7:11] = (210, 211, 200, 201)
    else:
        data[7:11] = (200, 211, 212, 213)
    return bytes(data)


@pytest.mark.parametrize('family', tuple(KINDS))
def test_readonly_callback_retains_all_hidden_raw_fields_and_restore(family):
    before = raw(family)
    editor, client, source = model(((6, before),))
    plan = native(editor, client, source,
        (operation(family, [{'event': 'get-view'}]), {'op': 'static-text-dialog', 'edits': []}))
    controls = plan.parent_plan.after_controls
    assert bytes(controls[_field(6, i)][0] for i in range(32)) == before
    assert controls['Widget6RestoreLevel'] == (213,)
    row = plan.parent_plan.as_dict()['operation_results'][0]
    assert row['macro_normalized'] is False
    assert row['mra_controls']['pending'] is False
    assert row['mra_control_base']['converted'] is False
    assert plan.parent_plan.as_dict()['execution_counts']['terminal_crc_passes'] == 1


def test_zone_macro_getter_repairs_only_when_explicitly_requested():
    editor, client, source = model(((6, raw('zone-control')),))
    plan = native(editor, client, source,
        (operation('zone-control', [{'event': 'get-zone-macro'}]), {'op': 'static-text-dialog', 'edits': []}))
    after = bytes(plan.parent_plan.after_controls[_field(6, i)][0] for i in range(32))
    expected = bytearray(raw('zone-control')); expected[7:9] = (15, 16)
    assert after == expected
    journal = plan.parent_plan.as_dict()['operation_results'][0]['mra_controls']['journal']
    assert journal[0]['assignment_intents'] == [{'offset': 7, 'value': 15}, {'offset': 8, 'value': 16}]


def test_hidden_select_status_keeps_old_reference_during_label_allocation():
    record = bytearray(raw('source-select')); record[6] = 0; record[9:11] = (255, 63)
    editor, client, source = model(((6, bytes(record)),))
    plan = native(editor, client, source,
        (operation('source-select', [{'event': 'input', 'target': 'label', 'text': 'New label'},
                                    {'event': 'enter', 'target': 'label'}]), {'op': 'static-text-dialog', 'edits': []}))
    controls = plan.parent_plan.after_controls
    assert controls[_field(6, 9)] == (62,)
    assert controls[_field(6, 10)] == (63,)
    assert bytes(controls['StaticTextString62']).split(b'\0', 1)[0] == b'New label'


def test_full_retained_long_name_reuse_crosses_two_mra_families():
    editor, client, source = model()
    text = 'Long retained label ' + 'é' * 40
    events = [{'event': 'input', 'target': 'label', 'text': text},
              {'event': 'enter', 'target': 'label'}]
    plan = native(editor, client, source,
        (operation('source-control', events, 6), operation('zone-control', events, 7)))
    after = plan.parent_plan.after_controls
    assert after[_field(6, 7)] == after[_field(7, 11)] == (63,)
    assert bytes(after['StaticTextString63']) == (text.encode('utf8')[:63] + b'\0').ljust(64, b'\0')
    assert plan.parent_plan.as_dict()['operation_results'][1]['mra_controls']['allocations'][0]['reused']


def test_pending_text_and_detached_binding_refuse_before_staging():
    editor, client, source = model()
    before = list(client.commands)
    with pytest.raises(EdltError, match='pending'):
        native(editor, client, source,
            (operation('source-control', [{'event': 'input', 'target': 'label', 'text': 'Pending'}]),))
    assert client.commands == before
    native_plan = native(editor, client, source,
        (operation('source-control', [{'event': 'get-view'}]),))
    plan = native_plan.parent_plan
    with pytest.raises(EdltError, match='owner'):
        editor.plan(source, metadata=native_plan.cache, operations=plan.operations,
                    _mra_control_bindings=(plan.mra_control_bindings[0].as_dict(),))


def test_status_callback_survives_later_global_projection():
    first = bytearray(raw('source-control')); first[1] = 0xC7; first[7] = 255
    second = bytearray(raw('zone-control')); second[1] = 0x08; second[11] = 255
    editor, client, source = model(((6, bytes(first)), (7, bytes(second))))
    plan = native(editor, client, source,
        (operation('zone-control', [{'event': 'binding-write', 'target': 'status-type',
                                    'value': 2, 'identity': 'mra-status:2'}], 7),
         operation('source-control', [{'event': 'get-view'}], 6)))
    assert plan.parent_plan.after_controls[_field(7, 1)] == (0x0A,)
    assert plan.parent_plan.before_save[_field(7, 1)] == (0xC2,)


def test_discarded_terminator_tail_does_not_supply_new_mra_globals():
    tail = bytearray(raw('source-control')); tail[1] = 0xAD; tail[7] = 255
    editor, client, source = model(((7, bytes(tail)),))
    source[_field(6)] = (255,)
    source[_field(6, 1)] = (255,)
    client.values = {name: _render(value) for name, value in source.items()}
    plan = native(editor, client, source,
        (operation('source-control', [{'event': 'get-view'}]),))
    assert plan.parent_plan.after_controls[_field(6, 1)][0] & 0xF8 == 0xF8
    assert plan.parent_plan.before_save[_field(6, 1)][0] & 0xF8 == 0


def test_canonical_apply_uses_original_instance_and_single_parameter_writes():
    editor, client, source = model()
    plan = native(editor, client, source,
        (operation('source-select', [{'event': 'binding-write', 'target': 'variant',
            'value': 2, 'identity': 'mra-source-select-variant:2'},
            {'event': 'binding-write', 'target': 'source1', 'value': 6, 'identity': 'mra-source:6'}]),)).parent_plan
    session = Session(editor.spec); session.current = dict(source)
    result = editor.apply(session, plan)
    assert result['verified']
    assert len(session.calls) == len({name for name, _ in session.calls})
    copied = replace(plan, mra_control_bindings=(replace(plan.mra_control_bindings[0]),))
    with pytest.raises(EdltError, match='issued|issuer|owner'):
        editor.apply(session, copied)


def test_initialized_globals_survive_removal_of_last_loaded_mra_before_conversion():
    initial = bytearray(raw('zone-control')); initial[1] = 0xAD
    initial[6] = 0; initial[7:13] = (15, 16, 3, 13, 255, 255)
    editor, client, source = model(((8, bytes(initial)),))
    for slot in (6, 7):
        source[_field(slot)] = (0,)
    source[_field(9)] = (255,)
    source[_field(6, 1)] = (0xA5,)
    client.values = {name: _render(value) for name, value in source.items()}
    plan = native(editor, client, source,
        ({'op': 'blank', 'page': 1, 'position': 3},
         operation('source-control', [{'event': 'get-view'}])))
    assert plan.parent_plan.after_controls[_field(6, 1)][0] & 0xF8 == 0xA0
    assert plan.parent_plan.before_save[_field(6, 1)][0] & 0xF8 == 0xA8
    view = plan.parent_plan.as_dict()['operation_results'][1]['mra_controls']['journal'][0]['observed']
    assert view['Zone'] == 4 and view['Multiplexer'] == 2


def test_unrelated_ordinary_panel_retains_existing_raw_reference_refusal():
    editor, client, source = model(((6, raw('source-control')),))
    with pytest.raises(EdltError, match='Invalid static reference'):
        native(editor, client, source,
            (operation('source-control', [{'event': 'get-view'}]), {'op': 'general'}))


def test_explicit_global_controls_are_deferred_past_readonly_callbacks():
    editor, client, source = model(((6, raw('source-control')),))
    plan = native(editor, client, source,
        (operation('source-control', [{'event': 'get-view'}]),
         {'op': 'mra-globals', 'multiplexer': 1, 'zone': 2}))
    assert plan.parent_plan.after_controls[_field(6, 1)] == (255,)
    assert plan.parent_plan.before_save[_field(6, 1)] == (15,)


def test_icon_binding_uses_causal_display_setting_and_preserves_coupled_order():
    editor, client, source = model()
    source['UseBigIcon'] = (0,)
    client.values = {name: _render(value) for name, value in source.items()}
    with pytest.raises(EdltError, match='UseBigIcon'):
        native(editor, client, source,
            (operation('source-control', [{'event': 'binding-write', 'target': 'icon-on', 'value': 141}]),))
    plan = native(editor, client, source,
        ({'op': 'display', 'big_icons': True},
         operation('source-control', [{'event': 'binding-write', 'target': 'icon-on', 'value': 141}])))
    assert plan.parent_plan.after_controls[_field(6, 2)] == (141,)
    assert plan.parent_plan.after_controls[_field(6, 3)] == (141,)
    journal = plan.parent_plan.as_dict()['operation_results'][1]['mra_controls']['journal']
    assert journal[0]['assignment_intents'] == [{'offset': 3, 'value': 141}, {'offset': 2, 'value': 141}]


def test_genuinely_issued_other_widget_binding_cannot_own_selected_record():
    from cbus_toolkit.edlt_mra_controls import issue_mra_control_binding
    from cbus_toolkit.edlt_mra_parent_controls import (plan_control_base,
        initial_global_context, external_references, retained_names,
        project_owned_controls)
    record = bytearray(raw('source-control')); record[7] = 255
    editor, _client, source = model(((6, bytes(record)), (7, bytes(record))))
    selected = operation('source-control', [{'event': 'binding-write',
                          'target': 'variant', 'value': 1,
                          'identity': 'mra-source-control-variant:1'}])
    widget_plan, _receipt = plan_control_base(editor._editor('source-control'), source,
        kind='source-control', options={k: v for k, v in selected.items()
        if k not in ('op', 'mra_controls')}, controls=selected['mra_controls'],
        global_context=initial_global_context(source))
    values = {**widget_plan.expected, **widget_plan.changes}
    wrong = issue_mra_control_binding(owner=editor, operation=selected,
        values=values, family='source-control', widget=7,
        retained_names=retained_names(values),
        external_used_indices=external_references(editor.common, values, 7))
    with pytest.raises(EdltError, match='owning operation family/widget'):
        project_owned_controls(editor, wrong, selected, values, widget_plan)


def test_explicit_ordinary_scalar_precedes_callbacks_without_early_globals():
    first = bytearray(raw('source-control')); first[1] = 0xA7; first[7] = 255
    second = bytearray(raw('zone-control')); second[1] = 0x08
    second[6] = 0; second[7:13] = (15, 16, 3, 13, 255, 255)
    editor, client, source = model(((6, bytes(first)), (7, bytes(second))))
    plan = native(editor, client, source,
        (operation('zone-control', [{'event': 'get-view'}], 7,
                   variant='bass', status_type='percent'),
         {'op': 'static-text-dialog', 'edits': []}))
    assert plan.parent_plan.after_controls[_field(7, 1)] == (0x0A,)
    assert plan.parent_plan.after_controls[_field(7, 6)] == (2,)
    assert plan.parent_plan.before_save[_field(7, 1)] == (0xA2,)
    view = plan.parent_plan.as_dict()['operation_results'][0]['mra_controls']['journal'][0]['observed']
    assert view['FunctionVariant'] == 2 and view['StatusDisplayType'] == 2
    assert view['Zone'] == 1 and view['Multiplexer'] == 0


def test_reset_uses_fresh_globals_and_static_names_for_new_mra_controls():
    initial = bytearray(raw('source-control')); initial[0] = 0; initial[1] = 0xAD; initial[7] = 63
    from tests.test_edlt_parent_blank_reset import complete_spec
    base = complete_spec()
    parameters = dict(base.parameters)
    extended = fixture()
    additions = [name for name in extended.parameters if name not in parameters]
    padding = [name for name in parameters if name.startswith('OwnedPadding')]
    for name in padding[:len(additions)]:
        del parameters[name]
    for name, parameter in extended.parameters.items():
        if name != 'NavWidgetType' and not name.endswith('WidgetType'):
            parameters[name] = parameter
    assert len(parameters) == 874
    spec = replace(base, parameters=parameters)
    editor, client, source = model(((6, bytes(initial)),), spec=spec)
    from tests.test_edlt_parent_metadata import oid
    client.applications[203] = {'oid': oid(203), 'tag': 'Enable Control', 'groups': {}}
    client.applications[56]['groups'][42] = {'oid': oid(5642), 'tag': 'Owned group', 'levels': ()}
    source['StaticTextString63'] = tuple(b'Old retained name\0'.ljust(64, b'\0'))
    client.values = {name: _render(value) for name, value in source.items()}
    plan = native(editor, client, source,
        ({'op': 'reset', 'active_tab': 'widgets', 'binding_variant': 'audited-local-wiring'},
         operation('source-control', [{'event': 'input', 'target': 'label', 'text': 'New name'},
                                      {'event': 'enter', 'target': 'label'}])))
    assert plan.parent_plan.before_save[_field(6, 1)][0] & 0xF8 == 0
    assert bytes(plan.parent_plan.before_save['StaticTextString63']).split(b'\0', 1)[0] == b'New name'
    assert len(plan.parent_plan.mra_control_bindings) == 1
