"""Actual caller-document adapter tests; all catalogue/Group data is synthetic."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from cbus_toolkit.offline_workflows.catalogue_groups_input import INPUT_FORMAT, RESULT_FORMAT, evaluate
from cbus_toolkit.offline_workflows.cli_support import InputError, decode_json

EXAMPLE = Path(__file__).parents[2] / 'src/cbus_toolkit/offline_workflows/examples/catalogue-groups.json'


def revision(default='true'):
    return ('<Revision><UnitType>KEYTEST</UnitType><MinVersion>1.0</MinVersion>'
            '<MaxVersion>2.9</MaxVersion><UnitSpecName>test.xml</UnitSpecName>'
            f'<IsDefault>{default}</IsDefault></Revision>')


def source(revisions=None, extra=''):
    return ('<CBusUnits><Units><Unit><CatalogNumber>SYNTHETIC</CatalogNumber>'
            '<UnitTitle>Family=Wired;Category=Input;HideInCatalog=false</UnitTitle>'
            '<IsAddressable>true</IsAddressable><FirmwareRevisions>'
            + (revision() if revisions is None else revisions)
            + '</FirmwareRevisions>' + extra + '</Unit></Units></CBusUnits>').encode()


def document(catalogue=None):
    catalogue = source() if catalogue is None else catalogue
    return {'format': INPUT_FORMAT, 'catalogue_hex': catalogue.hex(),
            'selection': {'mode': 'default', 'profile': 'proposed-offline-catalogue-v1',
                          'unit_id': hashlib.sha256(catalogue).hexdigest() + ':/CBusUnits/Units[1]/Unit[1]'},
            'groups': {'rows': [{'row_id': 'one', 'address': 1, 'tag_name': 'One'}],
                       'operations': [], 'existing_groups': [],
                       'policy': {'profile': 'proposed-offline-groups-v1', 'allowed_addresses': list(range(16)),
                                  'capacity': 16, 'duplicate_names': 'reject-exact'},
                       'target_identity': '//SYNTH/254/56', 'baseline_sha256': '0' * 64}}


def assert_unadmitted(result):
    assert result['unit_creation_admitted'] is False
    assert result['default_pp_admitted'] is False
    assert result['replacement_graph_admitted'] is False
    assert result['native_compatibility_verified'] is False
    assert result['external_effects_performed'] is False


def test_actual_versioned_example_inspect_validate_and_plan():
    value = decode_json(EXAMPLE.read_bytes())
    inspect = evaluate(value, 'inspect')
    assert inspect['format'] == RESULT_FORMAT
    assert inspect['outcome'] == 'inspected' and not inspect['validation_passed']
    assert 'history' not in inspect and 'group_validation' not in inspect
    assert inspect['draft']['rows'] == value['groups']['rows']
    assert inspect['declared_operations'] == value['groups']['operations']
    checked = evaluate(value, 'validate')
    planned = evaluate(value, 'plan')
    assert checked['outcome'] == planned['outcome'] == 'prepared'
    assert checked['validation_passed'] and planned['validation_passed']
    assert [row['address'] for row in checked['accepted_rows']] == [1, 2, 3]
    assert [(row['row_id'], row['address'], row['tag_name']) for row in planned['accepted_rows']] == [
        ('pantry', 1, 'Pantry'), ('hall', 4, 'Landing'), ('entry', 5, 'Entry')]
    assert planned['initial_draft']['rows'] == value['groups']['rows']
    assert planned['catalogue_selection']['firmware'] == '1.0'
    assert_unadmitted(planned)


def test_explicit_item_identity_and_firmware_are_not_inferred_from_labels():
    value = document()
    facts = evaluate(value, 'inspect')
    item_id = facts['catalogue']['units'][0]['revisions'][0]['item_id']
    value['selection'] = {'mode': 'explicit', 'profile': 'proposed-offline-catalogue-v1',
                          'item_id': item_id, 'firmware': '1.7'}
    assert evaluate(value, 'validate')['catalogue_selection']['firmware'] == '1.7'
    value['selection']['item_id'] = 'test.xml'
    result = evaluate(value, 'plan')
    assert result['outcome'] == 'refused'
    assert result['accepted_rows'] == result['group_validation']['accepted_rows'] == []
    assert result['errors'][0]['code'] == 'unknown_item'


@pytest.mark.parametrize('mutate', [
    lambda value: value.update(extra=True),
    lambda value: value['groups'].update(source_file='ignored.xml'),
    lambda value: value['groups']['rows'][0].update(extra=True),
    lambda value: value['groups']['rows'][0].update(address=True),
    lambda value: value['groups']['rows'][0].update(address=1.0),
    lambda value: value['groups']['rows'][0].update(tag_name=None),
    lambda value: value['groups']['policy'].update(capacity=True),
    lambda value: value['groups']['policy'].update(allowed_addresses=[True]),
    lambda value: value['groups']['policy'].update(max_tag_name_chars=False),
    lambda value: value['groups']['policy'].update(reserved_addresses=[]),
    lambda value: value['selection'].update(firmware='1.5'),
    lambda value: value['selection'].pop('unit_id'),
    lambda value: value.update(catalogue_hex='not hex'),
    lambda value: value.update(catalogue_hex='aa '),
    lambda value: value.update(catalogue_hex=source()),
    lambda value: value['groups'].update(operations=[{'op': 'cancel', 'ignored': True}]),
    lambda value: value['groups'].update(operations=[{'op': 'add', 'row': {'row_id': 'valid', 'address': 2, 'tag_name': 'Valid'}}, {'op': 'edit', 'row_id': 'valid', 'address': False, 'tag_name': 'Invalid'}]),
])
def test_malformed_unknown_fields_and_boolean_types_never_accept_a_prefix(mutate):
    value = document()
    before = deepcopy(value)
    mutate(value)
    with pytest.raises(InputError):
        evaluate(value, 'plan')
    assert before['groups']['rows'][0]['address'] == 1


def test_unknown_profiles_and_original_modes_remain_unsupported():
    for component in ('selection', 'policy'):
        value = document()
        (value['selection'] if component == 'selection' else value['groups']['policy'])['profile'] = 'original-toolkit'
        result = evaluate(value, 'validate')
        assert result['outcome'] == 'unsupported' and not result['validation_passed']
        assert result['accepted_rows'] == []
    value = document()
    value['selection']['mode'] = 'native-default'
    assert evaluate(value, 'plan')['outcome'] == 'unsupported'
    value = document()
    value['groups']['operations'] = [{'op': 'paste'}]
    assert evaluate(value, 'plan')['outcome'] == 'unsupported'


@pytest.mark.parametrize('catalogue,code', [
    (source(revision('false')), 'ambiguous_default'),
    (source(revision() + revision()), 'ambiguous_default'),
    (source().replace(b'HideInCatalog=false', b'HideInCatalog=true'), 'catalogue_ineligible'),
    (source().replace(b'</Units>', b'<Wrapper><Unit/></Wrapper></Units>'), 'unsupported_catalogue_shape'),
    (b'<broken', 'invalid_catalogue'),
    (b'<!DOCTYPE CBusUnits [<!ENTITY x "bad">]><CBusUnits/>', 'invalid_catalogue'),
])
def test_missing_defaults_hidden_wrapped_and_malformed_catalogues_refuse(catalogue, code):
    result = evaluate(document(catalogue), 'validate')
    assert not result['validation_passed'] and result['accepted_rows'] == []
    assert result['errors'][0]['code'] == code
    assert_unadmitted(result)


def test_selection_and_entire_group_draft_are_checked_with_no_accepted_subset():
    value = document(source(revision('false')))
    value['groups']['existing_groups'] = [{'row_id': 'existing', 'address': '03', 'tag_name': 'Existing'}]
    value['groups']['rows'] += [{'row_id': 'alias', 'address': '01', 'tag_name': 'Alias'},
                               {'row_id': 'collision', 'address': 3, 'tag_name': 'Collision'}]
    result = evaluate(value, 'validate')
    assert [item['code'] for item in result['errors']] == [
        'ambiguous_default', 'invalid_address', 'existing_address_collision']
    assert result['accepted_rows'] == result['group_validation']['accepted_rows'] == []
    assert result['draft']['rows'] == value['groups']['rows']


def test_operations_apply_only_in_plan_and_refuse_late_errors_atomically():
    value = document()
    value['groups']['operations'] = [
        {'op': 'add', 'row': {'row_id': 'two', 'address': 2, 'tag_name': 'Two'}},
        {'op': 'edit', 'row_id': 'two', 'address': 1, 'tag_name': 'Two'},
    ]
    assert evaluate(value, 'validate')['validation_passed']
    result = evaluate(value, 'plan')
    assert not result['validation_passed'] and result['accepted_rows'] == []
    assert result['errors'][0]['code'] == 'duplicate_staged_address'
    value['groups']['operations'][1]['row_id'] = 'absent'
    result = evaluate(value, 'plan')
    assert result['outcome'] == 'refused' and result['errors'][0]['code'] == 'unknown_row'
    assert result['accepted_rows'] == [] and 'draft' not in result
    assert value['groups']['rows'] == [{'row_id': 'one', 'address': 1, 'tag_name': 'One'}]


def test_cancel_discards_only_local_rows_without_selection_or_initial_validation():
    value = document(source(revision('false')))
    value.pop('selection')
    value['groups']['rows'][0]['address'] = '01'
    value['groups']['operations'] = [{'op': 'add', 'row': {'row_id': 'two', 'address': 2, 'tag_name': 'Two'}}, {'op': 'cancel'}]
    result = evaluate(value, 'plan')
    assert result['outcome'] == 'cancelled' and not result['validation_passed']
    assert result['draft'] == {'state': 'cancelled', 'rows': []}
    assert result['accepted_rows'] == [] and not result['selection_evaluated']
    assert 'group_validation' not in result
    value['groups']['operations'].append({'op': 'add', 'row': {'row_id': 'after', 'address': 3, 'tag_name': 'After'}})
    result = evaluate(value, 'plan')
    assert result['outcome'] == 'refused' and result['errors'][0]['code'] == 'draft_cancelled'


def test_inspect_can_reveal_ids_and_default_diagnostics_without_selecting():
    value = document(source(revision('false')))
    value.pop('selection')
    result = evaluate(value, 'inspect')
    assert result['outcome'] == 'inspected' and not result['validation_passed']
    assert result['catalogue']['units'][0]['diagnostics'] == ['missing_default']
    assert result['declared_selection'] is None
    with pytest.raises(InputError):
        evaluate(value, 'validate')


def test_evaluate_is_defensive_and_performs_zero_io(monkeypatch):
    value = document()
    value['groups']['operations'] = [{'op': 'add', 'row': {'row_id': 'two', 'address': 2, 'tag_name': 'Two'}}]
    original = deepcopy(value)
    def forbidden(*args, **kwargs):
        raise AssertionError('Pure adapter performed I/O')
    monkeypatch.setattr('builtins.open', forbidden)
    monkeypatch.setattr(Path, 'open', forbidden)
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    for operation in ('inspect', 'validate', 'plan'):
        result = evaluate(value, operation)
        assert_unadmitted(result)
        if operation == 'inspect':
            result['declared_operations'][0]['row']['tag_name'] = 'Changed'
        else:
            result['accepted_rows'][0]['tag_name'] = 'Changed'
    assert value == original


def test_unknown_root_format_operation_and_empty_bytes_do_not_guess():
    value = document()
    value['format'] = 'original-toolkit-input'
    with pytest.raises(InputError) as caught:
        evaluate(value, 'plan')
    assert caught.value.code == 'unsupported_format'
    with pytest.raises(InputError):
        evaluate(document(), 'apply')
    result = evaluate(document(b''), 'validate')
    assert result['outcome'] == 'refused' and not result['validation_passed']


def test_pathological_bounded_xml_and_firmware_return_refusals_not_exceptions():
    deep = (b'<CBusUnits><Units>' + b'<Unit><SubUnits>' * 1100 + b'<Unit/>'
            + b'</SubUnits></Unit>' * 1100 + b'</Units></CBusUnits>')
    huge_component = source().replace(b'<MinVersion>1.0</MinVersion>',
                                     b'<MinVersion>' + b'1' * 5000 + b'</MinVersion>')
    for catalogue in (deep, huge_component):
        result = evaluate(document(catalogue), 'inspect')
        assert result['outcome'] == 'refused' and result['errors'][0]['code'] == 'invalid_catalogue'
        assert not result['validation_passed'] and result['accepted_rows'] == []
    value = document()
    item_id = evaluate(value, 'inspect')['catalogue']['units'][0]['revisions'][0]['item_id']
    value['selection'] = {'mode': 'explicit', 'profile': 'proposed-offline-catalogue-v1',
                          'item_id': item_id, 'firmware': '1' * 5000}
    result = evaluate(value, 'validate')
    assert result['errors'][0]['code'] == 'invalid_firmware'
    assert result['accepted_rows'] == result['group_validation']['accepted_rows'] == []
