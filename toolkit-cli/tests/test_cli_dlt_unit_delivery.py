"""Public offline unit-label lifecycle entry points and file/input boundaries."""
import argparse
from copy import deepcopy
import json

import pytest

from cbus_toolkit import dlt_unit_delivery_cli
from test_cli_dlt_controls import cli


def request():
    return {'format': 'cbus-classic-dlt-unit-delivery-request-v1',
            'project': 'LAB', 'network': 254, 'unit_application': 56, 'unit_address': 10,
            'default_language': 1, 'save_labels': True, 'transfer': False,
            'block_dynamic_updates': True, 'kfi_enabled': False, 'reblock_session_open': False,
            'keys': [{'key': 1, 'kfi': 0, 'role': 'ordinary', 'target_state': 'present',
                      'flavour': {'format': 'cbus-classic-dlt-broadcast-request-v1',
                                  'project': 'LAB', 'network': 254, 'application': 56,
                                  'application_oid': None, 'group': 1, 'level': None,
                                  'language': 1, 'variant': 1, 'tag_type': 'TEXT',
                                  'tag_value': 'Kitchen', 'already_broadcast': True, 'bitmap': None}}]}


def write_json(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def plan_request(tmp_path, supplied=None, status=0):
    path = write_json(tmp_path, 'input.json', request() if supplied is None else supplied)
    return cli('dlt', 'unit-delivery', 'plan', '--input', path, status=status)


def supplied_outcomes(plan, operations):
    return {'format': 'cbus-classic-dlt-unit-delivery-outcomes-v1',
            'plan_sha256': plan['plan_sha256'], 'operations': operations}


def assess(tmp_path, plan, outcomes, status=0):
    plan_file = write_json(tmp_path, 'plan.json', plan)
    outcomes_file = write_json(tmp_path, 'outcomes.json', outcomes)
    return cli('dlt', 'unit-delivery', 'assess', '--plan', plan_file,
               '--outcomes', outcomes_file, status=status)


def parse(*arguments):
    parser = argparse.ArgumentParser()
    dlt_unit_delivery_cli.options(parser.add_subparsers(dest='action', required=True))
    return parser.parse_args(['unit-delivery', *map(str, arguments)])


def test_parser_exposes_only_offline_reports():
    assert parse('plan', '--input', 'request.json').unit_delivery_action == 'plan'
    assert parse('assess', '--plan', 'plan.json', '--outcomes', 'outcomes.json').unit_delivery_action == 'assess'
    for arguments in (('execute', '--input', 'request.json'),
                      ('plan', '--input', 'request.json', '--host', '127.0.0.1'),
                      ('plan', '--input', 'request.json', '--apply'),
                      ('plan', '--input', 'request.json', '--output', 'output.json'),
                      ('assess', '--plan', 'plan.json')):
        with pytest.raises(SystemExit) as error:
            parse(*arguments)
        assert error.value.code == 2


def test_public_plan_and_empty_assessment_preserve_inputs(tmp_path):
    source = write_json(tmp_path, 'source.json', request())
    original = source.read_bytes()
    plan = cli('dlt', 'unit-delivery', 'plan', '--input', source)
    assert plan['format'] == 'cbus-classic-dlt-unit-delivery-plan-v1'
    assert plan['io_performed'] is False
    assert plan['operations']
    result = assess(tmp_path, plan, supplied_outcomes(plan, []))
    assert result['format'] == 'cbus-classic-dlt-unit-delivery-assessment-v1'
    assert result['io_performed'] is False
    assert source.read_bytes() == original
    assert {item.name for item in tmp_path.iterdir()} == {'source.json', 'plan.json', 'outcomes.json'}


def test_public_assessment_accepts_explicit_returned_operations_without_claiming_io(tmp_path):
    plan = plan_request(tmp_path)
    rows = [{'id': operation['id'], 'operation_sha256': operation['operation_sha256'], 'outcome': 'returned'}
            for operation in plan['operations']]
    result = assess(tmp_path, plan, supplied_outcomes(plan, rows))
    assert result['io_performed'] is False
    assert result['device_verified'] is False


def test_public_plan_rejects_unsafe_numeric_and_context_inputs(tmp_path):
    for name, value in (('unit_address', True), ('unit_application', '56'),
                        ('save_labels', 1), ('project', 'LAB\nPROJECT DELETE LAB'),
                        ('default_language', None)):
        supplied = request()
        supplied[name] = value
        assert 'error' in plan_request(tmp_path, supplied, status=1)


def test_public_assessment_rejects_forged_plan_and_outcome_identity(tmp_path):
    plan = plan_request(tmp_path)
    changed = deepcopy(plan)
    changed['io_performed'] = True
    assert 'error' in assess(tmp_path, changed, supplied_outcomes(plan, []), status=1)
    changed = supplied_outcomes(plan, [])
    changed['plan_sha256'] = '0' * 64
    assert 'error' in assess(tmp_path, plan, changed, status=1)
    operation = plan['operations'][0]
    changed = supplied_outcomes(plan, [{'id': operation['id'], 'operation_sha256': '0' * 64,
                                       'outcome': 'returned'}])
    assert 'error' in assess(tmp_path, plan, changed, status=1)


@pytest.mark.parametrize('payload', [
    '{"format":"a","format":"b"}', '{"nested":{"x":1,"x":2}}',
    '{"number":NaN}', '{"number":Infinity}', '{"number":-Infinity}', '{"number":1e9999}',
])
def test_public_reader_refuses_duplicate_and_nonfinite_json(tmp_path, payload):
    source = tmp_path / 'bad.json'
    source.write_text(payload, encoding='utf-8')
    with pytest.raises(ValueError, match='Duplicate JSON key|Non-finite JSON number'):
        dlt_unit_delivery_cli.offline(parse('plan', '--input', source))


def test_public_reader_refuses_symlink_and_nonregular_input(tmp_path):
    source = write_json(tmp_path, 'source.json', request())
    link = tmp_path / 'link.json'
    link.symlink_to(source)
    for path in (link, tmp_path):
        with pytest.raises((ValueError, OSError)):
            dlt_unit_delivery_cli.offline(parse('plan', '--input', path))
