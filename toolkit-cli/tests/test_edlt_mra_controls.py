"""Private component checks against frozen independently reviewed literals.

Expected records, property intents and PP rows are literal inputs, not produced
by the implementation under test. No service or vendor instructions execute.
"""
from copy import copy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit import edlt_mra_control_properties as props
from cbus_toolkit import edlt_mra_controls as controls
from cbus_toolkit.edlt_scene_names import assign_name
from cbus_toolkit.edlt_static_grid import stored_row

VECTORS_PATH = Path(__file__).resolve().parents[1] / 'research/fixtures/edlt-mra-control-literal-vectors.json'
VECTORS = json.loads(VECTORS_PATH.read_text())
WIDGET = 6


def values_for(record, restore, names):
    values = {_field(WIDGET, i): (byte,) for i, byte in enumerate(record)}
    values[f'Widget{WIDGET}RestoreLevel'] = (restore,)
    values.update({f'StaticTextString{i}': tuple(stored_row(name)) for i, name in enumerate(names)})
    values['UnrelatedSentinel'] = (19, 27, 44)
    values['Scene8StartAddress'] = (65535,)
    values['UnrelatedString'] = 'Source text'
    return values


def translated(event, family):
    event = dict(event)
    if event['event'] == 'binding-write' and 'identity' in event:
        # Frozen vector IDs describe proposed abstract grammar; UI values and
        # all byte expectations remain the original independent literals.
        event['identity'] = controls.choice_identity(family, event['target'], event['value'])
    if event['event'] == 'read-properties' and 'hidden_absolute_bytes' in event['properties']:
        event['properties'] = [item for item in event['properties'] if item != 'hidden_absolute_bytes']
        event['properties'] += ['AbsoluteSource1', 'AbsoluteSource2']
    return event


class Runtime:
    def __init__(self, case):
        self.family = case['family']
        self.state = props.MRAPropertyState(self.family, bytes.fromhex(case['record_before_hex']), case['restore_before'])
        self.names = tuple(VECTORS['static_names_profiles'][case['static_names_profile']])
        self.values = values_for(self.state.record, self.state.restore_level, self.names)
        self.external = tuple(sorted(set(case.get('external_static_references', ()))))
        self.owner = object()
        self.continuation = None
        self.ordinal = 0

    def set_text(self, state, target, text):
        # Explicit trusted lifecycle callback: install its actual intermediate
        # model record before the source allocator observes old references.
        controls._install(self.values, WIDGET, state)
        assignment = assign_name(self.names, state.index(target), text,
            values=self.values, used_indices=lambda: set(self.external) | set(state.used_static_text()))
        self.names = assignment.names
        self.values.update(assignment.changes)
        outcome = (props.MRAPropertyResult(state) if assignment.ignored_null else
            props.write_mra_property(state, 'LabelValueIndex' if target == 'label' else 'StatusValueIndex', assignment.index))
        return outcome, assignment.as_dict()

    def step(self, event):
        self.ordinal += 1
        names_before = self.names
        kind = event['event']
        callback = None
        if kind == 'set-to-default':
            result, _, _ = props.default_mra_properties(self.state, set_text=self.set_text)
            self.state = result.state
            row = {'assignment_intents': [{'offset': i, 'value': value} for i, value in result.writes],
                   'notification_intents': list(result.notifications), 'observed': None}
        elif kind == 'direct-property-write':
            prop = event['property']
            if prop in ('LabelValueText', 'StatusValueText'):
                result, _ = self.set_text(self.state, 'label' if prop.startswith('Label') else 'status', event['value'])
            else:
                result = props.write_mra_property(self.state, prop, event['value'])
            self.state = result.state
            row = {'assignment_intents': [{'offset': i, 'value': value} for i, value in result.writes],
                   'notification_intents': list(result.notifications), 'observed': result.value}
        elif kind == 'before-save-mra-global':
            zone = props.write_mra_property(self.state, 'Zone', event['zone'])
            mux = props.write_mra_property(zone.state, 'Multiplexer', event['multiplexer'])
            self.state = mux.state
            row = {'assignment_intents': [{'offset': i, 'value': value} for i, value in (*zone.writes, *mux.writes)],
                   'notification_intents': [], 'observed': {
                       prop: props.read_mra_property(self.state, prop, names=self.names).value
                       for prop in ('Zone', 'Multiplexer', 'StatusDisplayType')}}
        else:
            event = translated(event, self.family)
            operation = {'op': self.family, 'mra_controls': [event]}
            binding = controls.issue_mra_control_binding(owner=self.owner, operation=operation,
                values=self.values, family=self.family, widget=WIDGET, retained_names=self.names,
                external_used_indices=self.external, operation_number=self.ordinal,
                initial_state=self.continuation)
            result = controls.project_mra_controls(binding, owner=self.owner,
                operation=operation, values=self.values, retained_names=self.names)
            self.state = props.MRAPropertyState(self.family, result.record, result.restore_level)
            self.names = result.retained_names
            self.values.update(dict(result.changes))
            self.continuation = result.state
            row = result.as_dict()['journal'][0]
            callback = row['control']
            if callback is not None:
                row['observed'] = {'display_text': callback['state']['text'],
                    'pending': callback['state']['pending'],
                    'bound_index': self.state.index(event['target'])}
            if kind == 'read-properties' and 'hidden_absolute_bytes' in event.get('properties', ()):
                raise AssertionError('Pseudo-property was not translated')
        controls._install(self.values, WIDGET, self.state)
        row['name_writes'] = [{'index': i, 'name': name} for i, name in enumerate(self.names) if name != names_before[i]]
        row['callback'] = callback
        return row


@pytest.mark.parametrize('case', VECTORS['cases'], ids=lambda case: case['case_id'])
def test_independent_complete_record_histories(case):
    runtime = Runtime(case)
    for step in case['steps']:
        assert runtime.state.record.hex().upper() == step['record_before_hex']
        result = runtime.step(step['operation'])
        assert runtime.state.record.hex().upper() == step['expected_record_after_hex']
        assert runtime.state.restore_level == step['expected_restore_after']
        assert result['assignment_intents'] == step['expected_byte_write_sequence']
        assert result['notification_intents'] == step['expected_notifications']
        assert result['name_writes'] == step['expected_static_name_writes']
        if 'expected_result' in step:
            expected, observed = step['expected_result'], result['observed']
            if isinstance(expected, dict) and 'hidden_absolute_bytes' in expected:
                observed = dict(observed)
                observed['hidden_absolute_bytes'] = [observed.pop('AbsoluteSource1'), observed.pop('AbsoluteSource2')]
            assert observed == expected
        if 'expected_control_state' in step:
            assert result['callback']['state'] == step['expected_control_state']
        if result['callback'] is not None:
            literal_actions = [('Binding.WriteValue' if action.startswith('Binding.WriteValue') else 'Binding.ReadValue')
                               for action in step['expected_source_actions']
                               if action.startswith(('Binding.WriteValue', 'Binding.ReadValue'))]
            assert ['Binding.' + entry['action'] for entry in result['callback']['binding_callbacks']] == literal_actions
        for expected in step.get('expected_static_PP_row_writes', []):
            assert bytes(runtime.values[f'StaticTextString{expected["index"]}']).hex().upper() == expected['row_hex']
    assert runtime.state.record.hex().upper() == case['expected_record_after_hex']
    assert runtime.state.restore_level == case['expected_restore_after']
    assert runtime.values['UnrelatedSentinel'] == (19, 27, 44)
    if 'expected_used_static_text' in case:
        assert set(runtime.state.used_static_text()) == set(case['expected_used_static_text']['indices'])


def simple_binding(events, *, family='zone-control', names=None, external=()):
    case = next(c for c in VECTORS['cases'] if c['family'] == family)
    names = tuple(names or VECTORS['static_names_profiles']['retained64'])
    values = values_for(bytes.fromhex(case['record_before_hex']), case['restore_before'], names)
    owner = object()
    operation = {'op': family, 'mra_controls': events}
    binding = controls.issue_mra_control_binding(owner=owner, operation=operation,
        values=values, family=family, widget=WIDGET, retained_names=names,
        external_used_indices=external, project_sha256='1' * 64, provider_sha256='2' * 64)
    return owner, operation, values, names, binding


@pytest.mark.parametrize('case', [c for c in VECTORS['refusal_candidates'] if c['case_id'] not in (
    'source-select-default-transient-count64-refuses-before-Source-index-write',
    'framework-ambiguous-whitespace180E', 'caller-owned-binding-clone', 'stale-64Names-with-identical-PP')],
    ids=lambda case: case['case_id'])
def test_independent_refused_callback_profiles(case):
    event = dict(case['operation'])
    events = event.get('events', [event])
    if case['case_id'] == 'name-surrogate-input':
        events = [{'event': 'input', 'target': 'label', 'text': '\ud800'}]
    if case['case_id'] == 'pending-close-not-inferred':
        events = [events[0], {'event': 'close', 'target': 'label'}]
    with pytest.raises(EdltError):
        owner, operation, values, names, binding = simple_binding(events, family=case['family'])
        controls.project_mra_controls(binding, owner=owner, operation=operation, values=values, retained_names=names)


def test_default_transient_capacity_failure_is_local_and_atomic():
    case = VECTORS['refusal_candidates'][0]
    runtime = Runtime(case)
    original_record, original_names = runtime.state.record, runtime.names
    with pytest.raises(EdltError, match='capacity'):
        runtime.step(case['operation'])
    assert runtime.state.record == original_record
    assert runtime.names == original_names


def test_input180e_is_pending_but_explicit_blank_commit_refuses():
    events = [{'event': 'input', 'target': 'label', 'text': '\u180e'}]
    owner, op, values, names, binding = simple_binding(events)
    result = controls.project_mra_controls(binding, owner=owner, operation=op, values=values, retained_names=names)
    assert result.pending and result.record == bytes.fromhex(VECTORS['cases'][0]['record_before_hex'])
    with pytest.raises(EdltError, match='pending'):
        controls.prepare_mra_projection(result, owner=owner)
    op = {'op': 'zone-control', 'mra_controls': [{'event': 'enter', 'target': 'label'}]}
    next_binding = controls.issue_mra_control_binding(owner=owner, operation=op, values=values,
        family='zone-control', widget=WIDGET, retained_names=names, external_used_indices=(),
        operation_number=2, project_sha256='1' * 64, provider_sha256='2' * 64, initial_state=result.state)
    with pytest.raises(EdltError, match='Unicode table'):
        controls.project_mra_controls(next_binding, owner=owner, operation=op, values=values, retained_names=names)


@pytest.mark.parametrize('forgery', ('clone', 'copy', 'owner', 'position', 'source', 'operation', 'names', 'refs', 'project', 'provider'))
def test_binding_identity_payload_and_full_name_guards(forgery):
    owner, op, values, names, binding = simple_binding([{'event': 'get-view'}])
    if forgery == 'clone': binding = replace(binding)
    elif forgery == 'copy': binding = copy(binding)
    elif forgery == 'owner': owner = object()
    elif forgery == 'position': object.__setattr__(binding, 'operation_number', 99)
    elif forgery == 'source': values = {**values, 'UnrelatedSentinel': (1,)}
    elif forgery == 'operation': op = {**op, 'extra': True}
    elif forgery == 'names': names = (*names[:3], names[3] + 'Long suffix with identical truncated PP', *names[4:])
    elif forgery == 'refs': object.__setattr__(binding, 'external_used_indices', (63,))
    elif forgery == 'project': object.__setattr__(binding, 'project_sha256', '3' * 64)
    elif forgery == 'provider': object.__setattr__(binding, 'provider_sha256', '3' * 64)
    with pytest.raises(EdltError):
        controls.project_mra_controls(binding, owner=owner, operation=op, values=values, retained_names=names)


def test_owner_none_cannot_issue_or_project():
    owner, op, values, names, binding = simple_binding([{'event': 'get-view'}])
    with pytest.raises(EdltError):
        controls.issue_mra_control_binding(owner=None, operation=op, values=values,
            family='zone-control', widget=WIDGET, retained_names=names, external_used_indices=())
    with pytest.raises(EdltError):
        controls.project_mra_controls(binding, owner=None, operation=op, values=values, retained_names=names)


def test_uncommitted_pending_refusal_does_not_adopt_names_or_mutate_pp():
    events = [{'event': 'input', 'target': 'label', 'text': 'Committed first'},
              {'event': 'enter', 'target': 'label'},
              {'event': 'input', 'target': 'status', 'text': 'Still pending'}]
    owner, op, values, names, binding = simple_binding(events)
    before = dict(values)
    result = controls.project_mra_controls(binding, owner=owner, operation=op, values=values, retained_names=names)
    assert result.pending and result.retained_names[63] == 'Committed first'
    with pytest.raises(EdltError, match='pending'):
        controls.prepare_mra_projection(result, owner=owner)
    assert values == before and names == tuple(VECTORS['static_names_profiles']['retained64'])


@pytest.mark.parametrize('clone', (False, True))
def test_continuation_result_authority_and_pending_save_guard(clone):
    owner, op, values, names, binding = simple_binding([{'event': 'input', 'target': 'label', 'text': 'Continued'}])
    result = controls.project_mra_controls(binding, owner=owner, operation=op, values=values, retained_names=names)
    nextop = {'op': 'zone-control', 'mra_controls': [{'event': 'enter', 'target': 'label'}]}
    resume = replace(result.state) if clone else result.state
    kwargs = dict(owner=owner, operation=nextop, values=values, family='zone-control', widget=WIDGET,
        retained_names=names, external_used_indices=(), operation_number=2,
        project_sha256='1' * 64, provider_sha256='2' * 64, initial_state=resume)
    if clone:
        with pytest.raises(EdltError, match='continuation'): controls.issue_mra_control_binding(**kwargs)
    else:
        nextbinding = controls.issue_mra_control_binding(**kwargs)
        resolved = controls.project_mra_controls(nextbinding, owner=owner, operation=nextop, values=values, retained_names=names)
        assert not resolved.pending and resolved.record[11] == 63 and resolved.retained_names[63] == 'Continued'
        controls.prepare_mra_projection(resolved, owner=owner)
        with pytest.raises(EdltError): controls.prepare_mra_projection(replace(resolved), owner=owner)


def test_closed_control_cannot_resume_and_display_does_not_implicitly_refresh():
    owner, op, values, names, binding = simple_binding([
        {'event': 'input', 'target': 'label', 'text': 'Pending'},
        {'event': 'list-refresh', 'target': 'label', 'change_type': 'reset',
         'selected_index': 0, 'new_index': -1, 'old_index': -1},
        {'event': 'close', 'target': 'label'}, {'event': 'enter', 'target': 'label'}])
    with pytest.raises(EdltError, match='explicit close'):
        controls.project_mra_controls(binding, owner=owner, operation=op, values=values, retained_names=names)


def test_source_control_used_indices_ignore_opaque9_and10():
    case = next(c for c in VECTORS['cases'] if c['case_id'] == 'source-control-allocator-opaque-status-exact-occupancy')
    runtime = Runtime(case)
    for step in case['steps']: runtime.step(step['operation'])
    assert runtime.state.record[7] == 63


@pytest.mark.parametrize('family,property', (
    ('source-control', 'StatusValueText'), ('source-control', 'StatusValueIndex'),
    ('zone-control', 'AbsoluteSource1'), ('source-select', 'RampRate'),
))
def test_absent_family_properties_refuse_during_shape_validation(family, property):
    with pytest.raises(EdltError):
        controls.normalize_mra_controls([{'event': 'get-property', 'property': property}], family=family)


def test_macro_repair_is_explicit_and_readonly_view_leaves_invalid_pair_unchanged():
    owner, op, values, names, binding = simple_binding([{'event': 'get-view'}])
    values[_field(WIDGET, 7)], values[_field(WIDGET, 8)] = (254,), (253,)
    binding = controls.issue_mra_control_binding(owner=owner, operation=op, values=values,
        family='zone-control', widget=WIDGET, retained_names=names, external_used_indices=())
    result = controls.project_mra_controls(binding, owner=owner, operation=op, values=values, retained_names=names)
    assert result.record[7:9] == bytes((254, 253)) and not result.changes
    assert result.as_dict()['journal'][0]['observed']['RampRateEditable'] is False
    op = {'op': 'zone-control', 'mra_controls': [{'event': 'get-zone-macro'}, {'event': 'get-zone-macro'}]}
    binding = controls.issue_mra_control_binding(owner=owner, operation=op, values=values,
        family='zone-control', widget=WIDGET, retained_names=names, external_used_indices=())
    result = controls.project_mra_controls(binding, owner=owner, operation=op, values=values, retained_names=names)
    journal = result.as_dict()['journal']
    assert result.record[7:9] == bytes((15, 16))
    assert journal[0]['assignment_intents'] == [{'offset': 7, 'value': 15}, {'offset': 8, 'value': 16}]
    assert journal[1]['assignment_intents'] == []


def test_original_control_state_fingerprint_mutation_cannot_bypass_pending_save():
    owner, op, values, names, binding = simple_binding([{'event': 'input', 'target': 'label', 'text': 'Pending'}])
    result = controls.project_mra_controls(binding, owner=owner, operation=op, values=values, retained_names=names)
    object.__setattr__(result.state.controls[0][1], 'pending', False)
    with pytest.raises(EdltError, match='unchanged'):
        controls.prepare_mra_projection(result, owner=owner)


@pytest.mark.parametrize('bad', ({'event': []}, {'event': 'binding-write', 'target': [], 'value': 0},
    {'event': 'get-property', 'property': []}, {'event': 'read-properties', 'properties': [False]},
    {'event': 'binding-write', 'target': 'variant', 'value': True, 'identity': 'mra-zone-control-variant:1'}))
def test_malformed_shapes_fail_closed_with_edlt_error(bad):
    with pytest.raises(EdltError):
        controls.normalize_mra_controls([bad], family='zone-control')


def test_static_rows_and_record_remain_byte_strict_with_generic16bit_pp_allowed():
    owner, op, values, names, binding = simple_binding([{'event': 'get-view'}])
    controls.project_mra_controls(binding, owner=owner, operation=op, values=values, retained_names=names)
    assert values['Scene8StartAddress'] == (65535,)
    for key, bad in ((_field(WIDGET, 5), (65535,)), ('StaticTextString1', (65535,) * 64)):
        with pytest.raises(EdltError):
            controls.issue_mra_control_binding(owner=owner, operation=op, values={**values, key: bad},
                family='zone-control', widget=WIDGET, retained_names=names, external_used_indices=())


def test_later_allocation_failure_preserves_input_values_and_retained_cache():
    events = [{'event': 'binding-write', 'target': 'status-type', 'value': 5, 'identity': 'mra-status:5'},
        {'event': 'input', 'target': 'label', 'text': 'Zone label'}, {'event': 'enter', 'target': 'label'},
        {'event': 'input', 'target': 'status', 'text': 'New would exceed capacity'}, {'event': 'enter', 'target': 'status'}]
    owner, op, values, names, binding = simple_binding(events, external=tuple(range(64)))
    before = dict(values)
    with pytest.raises(EdltError, match='capacity'):
        controls.project_mra_controls(binding, owner=owner, operation=op, values=values, retained_names=names)
    assert values == before and names == tuple(VECTORS['static_names_profiles']['retained64'])


@pytest.mark.parametrize('family,foreign', (
    ('zone-control', 'source-select'),
    ('source-select', 'source-control'),
    ('source-control', 'zone-control'),
))
def test_binding_requires_actual_ordinary_operation_family(family, foreign):
    owner, operation, values, names, _ = simple_binding([{'event': 'get-view'}], family=family)
    with pytest.raises(EdltError, match='operation identity'):
        controls.issue_mra_control_binding(owner=owner,
            operation={**operation, 'op': foreign}, values=values, family=family,
            widget=WIDGET, retained_names=names, external_used_indices=())


def test_complete_pp_preserves_project_and_unit_unicode_strings():
    owner, operation, values, names, _ = simple_binding([{'event': 'get-view'}])
    values = {**values, 'UnitName': 'Kitchen ā', 'Project': 'SITE'}
    binding = controls.issue_mra_control_binding(owner=owner, operation=operation,
        values=values, family='zone-control', widget=WIDGET,
        retained_names=names, external_used_indices=())
    result = controls.project_mra_controls(binding, owner=owner,
        operation=operation, values=values, retained_names=names)
    _, changes, _ = controls.prepare_mra_projection(result, owner=owner)
    assert values['UnitName'] == 'Kitchen ā' and values['Project'] == 'SITE'
    assert 'UnitName' not in changes and 'Project' not in changes
    assert values['Scene8StartAddress'] == (65535,)
