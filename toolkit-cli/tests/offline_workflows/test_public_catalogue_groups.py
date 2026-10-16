"""Catalogue/Group evidence through the public cbus-toolkit main entry point."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import socket

import pytest

from cbus_toolkit import cli

EXAMPLE = (Path(__file__).resolve().parents[2] / 'src' / 'cbus_toolkit' /
           'offline_workflows' / 'examples' / 'catalogue-groups.json')


@pytest.fixture
def tmp_path(tmp_path_factory):
    # The file boundary rejects symlink ancestors, including macOS /var aliases.
    return tmp_path_factory.mktemp('public-catalogue-groups').resolve()


@pytest.fixture(autouse=True)
def forbid_native_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Public offline catalogue/Group commands must not connect')
    monkeypatch.setattr(cli, 'run', forbidden)
    monkeypatch.setattr('cbus_toolkit.cgate.CGateClient', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def write_document(tmp_path, value=None):
    path = tmp_path / 'caller-input.json'
    if value is None:
        raw = EXAMPLE.read_bytes()
    else:
        raw = (json.dumps(value, ensure_ascii=True, indent=2) + '\n').encode('ascii')
    path.write_bytes(raw)
    return path, raw


def example():
    return json.loads(EXAMPLE.read_bytes())


def public_command(source, operation, *, output=None, expected=0):
    argv = ['offline-workflows', 'catalogue-groups', operation, '--input', str(source), '--compact']
    if output is not None:
        argv += ['--output', str(output)]
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        status = cli.main(argv)
    assert status == expected, (status, stdout.getvalue(), stderr.getvalue())
    emitted = stderr.getvalue() if expected == 2 else stdout.getvalue()
    assert (stdout.getvalue() == '') if expected == 2 else (stderr.getvalue() == '')
    assert len(emitted.splitlines()) == 1
    envelope = json.loads(emitted)
    assert envelope['format'] == 'cbus-offline-workflows-cli-v1'
    assert envelope['preparation_only'] is True
    for flag in ('execution_enabled', 'native_execution_enabled',
                 'original_compatibility_verified', 'external_persistence_verified'):
        assert envelope[flag] is False
    if expected != 2:
        assert envelope['workflow'] == 'catalogue-groups'
        assert envelope['operation'] == operation
        assert envelope['input_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
        report = envelope['report']
        for flag in ('unit_creation_admitted', 'default_pp_admitted',
                     'replacement_graph_admitted', 'native_compatibility_verified',
                     'external_effects_performed'):
            assert report[flag] is False
    return envelope, emitted.encode('ascii')


def rebind_default(value, catalogue):
    value['catalogue_hex'] = catalogue.hex()
    value['selection']['unit_id'] = hashlib.sha256(catalogue).hexdigest() + ':/CBusUnits/Units[1]/Unit[1]'


def test_public_inspect_validate_plan_preserve_exact_source_and_distinct_drafts(tmp_path):
    source, before = write_document(tmp_path)
    value = json.loads(before)
    raw_catalogue = bytes.fromhex(value['catalogue_hex'])
    inspected, _ = public_command(source, 'inspect')
    checked, _ = public_command(source, 'validate')
    output = tmp_path / 'new-local-plan.json'
    planned, emitted = public_command(source, 'plan', output=output)
    inspection, validation, plan = (result['report'] for result in (inspected, checked, planned))
    assert inspection['outcome'] == 'inspected' and not inspection['validation_passed']
    assert inspection['catalogue']['catalogue_sha256'] == hashlib.sha256(raw_catalogue).hexdigest()
    assert inspection['declared_operations'] == value['groups']['operations']
    assert inspection['draft']['rows'] == value['groups']['rows']
    assert 'group_validation' not in inspection and 'history' not in inspection
    revision = inspection['catalogue']['units'][0]['revisions'][0]
    expected_path = '/CBusUnits/Units[1]/Unit[1]/FirmwareRevisions[1]/Revision[1]'
    assert revision['source_path'] == expected_path
    assert revision['item_id'] == hashlib.sha256(raw_catalogue).hexdigest() + ':' + expected_path
    assert validation['outcome'] == plan['outcome'] == 'prepared'
    assert validation['validation_passed'] and plan['validation_passed']
    assert [row['address'] for row in validation['accepted_rows']] == [1, 2, 3]
    assert [(row['row_id'], row['address'], row['tag_name']) for row in plan['accepted_rows']] == [
        ('pantry', 1, 'Pantry'), ('hall', 4, 'Landing'), ('entry', 5, 'Entry')]
    assert plan['catalogue_selection']['item_id'] == revision['item_id']
    assert not plan['baseline_facts_verified']
    assert source.read_bytes() == before
    assert output.read_bytes() == emitted
    assert output.stat().st_mode & 0o777 == 0o600
    assert sorted(path.name for path in tmp_path.iterdir()) == ['caller-input.json', 'new-local-plan.json']


def test_public_explicit_revision_identity_distinguishes_duplicate_labels_and_specs(tmp_path):
    value = example()
    raw = bytes.fromhex(value['catalogue_hex'])
    unit = raw[raw.index(b'<Unit>'):raw.index(b'</Unit>') + len(b'</Unit>')]
    duplicated = raw.replace(b'</Units>', unit + b'</Units>')
    value['catalogue_hex'] = duplicated.hex()
    value.pop('selection')
    source, _ = write_document(tmp_path, value)
    inspection, _ = public_command(source, 'inspect')
    units = inspection['report']['catalogue']['units']
    assert len(units) == 2
    assert units[0]['catalog_number'] == units[1]['catalog_number']
    assert units[0]['revisions'][0]['spec_filename'] == units[1]['revisions'][0]['spec_filename']
    selected = units[1]['revisions'][0]
    assert units[0]['revisions'][0]['item_id'] != selected['item_id']
    value['selection'] = {'mode': 'explicit', 'profile': 'proposed-offline-catalogue-v1',
                          'item_id': selected['item_id'], 'firmware': '1.7'}
    source, before = write_document(tmp_path, value)
    envelope, _ = public_command(source, 'validate')
    result = envelope['report']['catalogue_selection']
    assert result['item_id'] == selected['item_id'] and result['firmware'] == '1.7'
    assert result['source_path'].startswith('/CBusUnits/Units[1]/Unit[2]/')
    assert source.read_bytes() == before


def test_public_stale_catalogue_identity_refuses_all_rows(tmp_path):
    value = example()
    raw = bytes.fromhex(value['catalogue_hex'])
    value['catalogue_hex'] = (raw + b'\n').hex()
    source, before = write_document(tmp_path, value)
    envelope, _ = public_command(source, 'plan', expected=3)
    result = envelope['report']
    assert result['outcome'] == 'refused' and not result['validation_passed']
    assert result['errors'][0]['code'] == 'unknown_item'
    assert result['accepted_rows'] == result['group_validation']['accepted_rows'] == []
    assert result['group_validation']['valid'] is True
    assert source.read_bytes() == before


def test_public_bulk_alias_and_baseline_collision_refuse_complete_batch(tmp_path):
    value = example()
    value['groups']['operations'] = []
    value['groups']['rows'] = [
        {'row_id': 'valid-first', 'address': 1, 'tag_name': 'Valid first'},
        {'row_id': 'alias-middle', 'address': '01', 'tag_name': 'Alias'},
        {'row_id': 'collision-last', 'address': 8, 'tag_name': 'Collision'},
    ]
    source, before = write_document(tmp_path, value)
    envelope, _ = public_command(source, 'validate', expected=3)
    result = envelope['report']
    assert result['errors'] == [
        {'component': 'group_draft', 'row_id': 'alias-middle', 'code': 'invalid_address'},
        {'component': 'group_draft', 'row_id': 'collision-last', 'code': 'existing_address_collision'},
    ]
    assert result['accepted_rows'] == result['group_validation']['accepted_rows'] == []
    assert result['draft']['rows'] == value['groups']['rows']
    assert source.read_bytes() == before


@pytest.mark.parametrize('component', ['selection', 'policy'])
def test_public_original_profiles_are_explicitly_unsupported(tmp_path, component):
    value = example()
    section = value['selection'] if component == 'selection' else value['groups']['policy']
    section['profile'] = 'original-toolkit'
    source, before = write_document(tmp_path, value)
    envelope, _ = public_command(source, 'plan', expected=3)
    result = envelope['report']
    assert result['outcome'] == 'unsupported' and result['errors'][0]['code'] == 'unsupported_profile'
    assert result['accepted_rows'] == []
    assert source.read_bytes() == before


def test_public_explicit_address_domain_never_guesses_reserved_policy(tmp_path):
    value = example()
    value['groups']['operations'] = []
    value['groups']['policy']['allowed_addresses'].remove(1)
    value['groups']['policy']['capacity'] = 15
    source, before = write_document(tmp_path, value)
    envelope, _ = public_command(source, 'validate', expected=3)
    result = envelope['report']
    assert result['errors'] == [{'component': 'group_draft', 'row_id': 'pantry', 'code': 'address_outside_policy'}]
    assert result['accepted_rows'] == []
    assert source.read_bytes() == before


@pytest.mark.parametrize('invalid', ['boolean-address', 'missing-policy', 'implicit-reserved-policy'])
def test_public_malformed_group_contracts_use_json_input_errors(tmp_path, invalid):
    value = example()
    if invalid == 'boolean-address':
        value['groups']['rows'][0]['address'] = True
    elif invalid == 'missing-policy':
        value['groups'].pop('policy')
    else:
        value['groups']['policy']['reserved_addresses'] = [255]
    source, before = write_document(tmp_path, value)
    envelope, _ = public_command(source, 'plan', expected=2)
    assert envelope['error']['code'] == 'invalid_input'
    assert source.read_bytes() == before


def test_public_missing_default_refuses_without_accepted_group_prefix(tmp_path):
    value = example()
    raw = bytes.fromhex(value['catalogue_hex']).replace(b'<IsDefault>true</IsDefault>', b'<IsDefault>false</IsDefault>')
    rebind_default(value, raw)
    source, before = write_document(tmp_path, value)
    envelope, _ = public_command(source, 'plan', expected=3)
    result = envelope['report']
    assert result['errors'][0]['code'] == 'ambiguous_default'
    assert result['accepted_rows'] == result['group_validation']['accepted_rows'] == []
    assert result['catalogue']['units'][0]['diagnostics'] == ['missing_default']
    assert source.read_bytes() == before


def test_public_cancel_retains_source_and_never_selects_or_accepts_invalid_draft(tmp_path):
    value = example()
    raw = bytes.fromhex(value['catalogue_hex']).replace(b'<IsDefault>true</IsDefault>', b'<IsDefault>false</IsDefault>')
    rebind_default(value, raw)
    value.pop('selection')
    value['groups']['rows'][0]['address'] = '01'
    value['groups']['operations'] = [{'op': 'cancel'}]
    source, before = write_document(tmp_path, value)
    envelope, _ = public_command(source, 'plan')
    result = envelope['report']
    assert result['outcome'] == 'cancelled' and not result['validation_passed']
    assert result['draft'] == {'state': 'cancelled', 'rows': []}
    assert result['accepted_rows'] == [] and not result['selection_evaluated']
    assert 'group_validation' not in result and 'catalogue_selection' not in result
    assert source.read_bytes() == before
