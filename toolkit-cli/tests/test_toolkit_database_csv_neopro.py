"""NeoPro CSV source contracts, literal rows and public read-only CLI journeys.

All XML/PP data is synthetic. The public wire peer is an owned ephemeral
loopback service, never an original C-Gate instance or physical interface.
The same subprocess tests run with the source package or an installed wheel.
"""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit import toolkit_database_csv_registry as registry
from cbus_toolkit.toolkit_database_csv_native import (
    project_native_xml_selection, project_native_xml_unit,
)
from cbus_toolkit.toolkit_database_csv_projection import (
    CSVAreaObservation, PROFILE, admitted_profiles, project_cached_csv_unit,
)
from tests.test_cgate import peer


ROOT = Path(__file__).resolve().parents[2]
VECTOR = ROOT / 'rust/testdata/vectors/toolkit_database_csv_neopro.json'
CURRENT_REGISTRY = ROOT / 'toolkit-cli/research/fixtures/toolkit-database-csv-neopro-registry.json'
HISTORICAL_REGISTRY = ROOT / 'toolkit-cli/research/experiments/2026-09-30/csv-factory-registry-static.json'
DATA = json.loads(VECTOR.read_text(encoding='utf-8'))
TYPES = ('KEYB2', 'KEYB4', 'KEYB6')
COLUMNS = tuple(DATA['fixture']['columns'])
FIRST_PATH = '//NEOCSV/254/p/21'


def tree():
    return ET.fromstring(DATA['fixture']['xml'])


def first_unit(root):
    return root.find('Project/Network/Unit')


def parameter(unit, name):
    return next(row for row in unit.findall('PP') if row.get('Name') == name)


def application(root, address):
    return next(row for row in root.find('Project/Network').findall('Application')
                if row.findtext('Address') == str(address))


def xml(root):
    return ET.tostring(root, encoding='unicode')


def one_family(kind, *, mask=85, secondary=57, with_oids=True):
    root = tree()
    unit = first_unit(root)
    unit.find('UnitType').text = kind
    parameter(unit, 'SecondApplicationBlocks').set('Value', str(mask))
    parameter(unit, 'Application').set('Value', f'56 {secondary}')
    if not with_oids:
        for parent in root.iter():
            for child in list(parent):
                if child.tag == 'OID':
                    parent.remove(child)
    return root


def invoke(args, *, artifact_dir):
    # Keep the selected Python import context (including installed-wheel runs),
    # but never inherit an opt-in original/backend/registry research control.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('CBUS_', 'PYTEST_'))
           and key not in ('PYTHONHOME', 'PYTHONSTARTUP')}
    completed = subprocess.run([sys.executable, '-m', 'cbus_toolkit',
                                *map(str, args)], capture_output=True, text=True,
                               env=env, timeout=20)
    (artifact_dir / 'cli-stdout.txt').write_text(completed.stdout)
    (artifact_dir / 'cli-stderr.txt').write_text(completed.stderr)
    (artifact_dir / 'cli-execution.json').write_text(json.dumps({
        'argv': completed.args, 'returncode': completed.returncode,
        'owned_loopback_only': True, 'original_execution': False,
    }, indent=2) + '\n')
    stream = completed.stdout if completed.returncode == 0 else completed.stderr
    result = json.loads(stream)
    return completed.returncode, result


def reply(text):
    return (b'[1] 343-Begin XML snippet\r\n[1] 347-' + text.encode('utf-8')
            + b'\r\n[1] 344 End XML snippet\r\n')


def test_neopro_source_vector_and_registry_preserve_static_denominator():
    assert DATA['source_evidence']['original_instructions_executed'] is False
    assert DATA['source_evidence']['fresh_static_original_bytes_inspected'] is True
    assert hashlib.sha256(CURRENT_REGISTRY.read_bytes()).hexdigest() == DATA[
        'source_evidence']['registry_sha256']
    assert hashlib.sha256(HISTORICAL_REGISTRY.read_bytes()).hexdigest() == DATA[
        'source_evidence']['historical_registry_sha256']
    assert hashlib.sha256(DATA['fixture']['xml'].encode()).hexdigest() == DATA[
        'fixture']['xml_sha256']
    current = json.loads(CURRENT_REGISTRY.read_text())
    old = json.loads(HISTORICAL_REGISTRY.read_text())
    admission_fields = {'admitted', 'admitted_firmware', 'association_model', 'refusal_reason'}
    assert [{k: v for k, v in row.items() if k not in admission_fields}
            for row in current['registrations']] == [
                {k: v for k, v in row.items() if k not in admission_fields}
                for row in old['registrations']]
    assert current['summary']['static_registrations'] == 425
    assert current['summary']['unit_types'] == 262
    assert current['summary']['admitted_types'] == old['summary']['admitted_types'] + 3
    new = [row for row in current['registrations'] if row['unit_type'] in TYPES and row['admitted']]
    assert new == DATA['source_evidence']['registrations']
    assert {(kind, '2.5.00', f'T{kind}') for kind in TYPES} <= set(admitted_profiles())
    for kind in TYPES:
        slots = DATA['source_evidence']['unit_vmt_slots'][kind]
        assert slots['0x16c'].endswith('TCBusNeoInputUnit.MaximumBlockCount')
        assert slots['0xf4'].endswith('TCoreNeoProInputUnit.HasApplication2')
        assert slots['0x10c'].endswith('TCBusNeoInputUnit.IsInteractionGroup')
        row, = registry.registrations_for(kind, '2.5.00')
        assert row[3:] == (f'T{kind}', 'TCBusNeoProInputCGateAgent', '')


@pytest.mark.parametrize('kind', TYPES)
@pytest.mark.parametrize('case', DATA['mask_cases'], ids=lambda row: f"mask-{row['mask']}")
def test_neopro_all_eight_blocks_and_primary_area_follow_literal_masks(kind, case):
    root = one_family(kind, mask=case['mask'])
    before = xml(root)
    result = project_native_xml_unit(before, FIRST_PATH, columns=COLUMNS)
    assert result.complete
    assert result.cached.selected_class == f'T{kind}'
    assert len(result.cached.unit.group_identities) == 8
    expected = ('21,' + kind + ',Lighting,"HVAC, west",AreaPrimary,'
                + ','.join(case['group_tags']) + ',<N/A>,<N/A>,')
    assert result.report.rows == (DATA['fixture']['csv_rows'][0], expected)
    # Repeated associations remain repeated; groups with the same address in
    # the two applications retain their separate object identities.
    by_identity = {group.identity: group.tag for group in result.cached.groups}
    assert [by_identity[value] for value in result.cached.unit.group_identities] == case['group_tags']
    assert by_identity[result.cached.area_identity] == 'AreaPrimary'
    assert [event.event for event in result.cached.events].count('area_load') == 2
    narrow = project_native_xml_unit(before, FIRST_PATH, columns=('address',))
    assert [event.event for event in narrow.cached.events].count('area_load') == 2
    assert narrow.cached.area_identity == result.cached.area_identity
    assert narrow.report.rows == ('Unit Address,', '21,')
    assert result.as_dict()['native_database_mutated'] is False
    assert result.as_dict()['network_io_performed'] is False
    assert xml(root) == before


@pytest.mark.parametrize('kind', TYPES)
@pytest.mark.parametrize('with_oids', (False, True), ids=('paths', 'oids'))
def test_neopro_oid_or_canonical_path_keeps_cross_application_identity(kind, with_oids):
    root = one_family(kind, with_oids=with_oids)
    result = project_native_xml_unit(xml(root), FIRST_PATH, columns=COLUMNS)
    identities = result.cached.unit.group_identities
    assert identities[0] == identities[2]
    assert identities[0] != identities[1]
    assert len(set(identities)) == 7
    if not with_oids:
        assert identities == ('//NEOCSV/254/57/8', '//NEOCSV/254/56/1',
                              '//NEOCSV/254/57/8', '//NEOCSV/254/56/255',
                              '//NEOCSV/254/57/2', '//NEOCSV/254/56/7',
                              '//NEOCSV/254/57/3', '//NEOCSV/254/56/6')
        assert result.cached.area_identity == '//NEOCSV/254/56/255'


@pytest.mark.parametrize('kind', TYPES)
def test_neopro_unused_or_same_secondary_application_is_explicit(kind):
    unused = project_native_xml_unit(xml(one_family(kind, mask=0, secondary=255)),
                                     FIRST_PATH, columns=COLUMNS)
    assert unused.report.rows[1] == ('21,' + kind + ',Lighting,,AreaPrimary,'
                                    + ','.join(DATA['mask_cases'][0]['group_tags'])
                                    + ',<N/A>,<N/A>,')
    same = project_native_xml_unit(xml(one_family(kind, secondary=56)),
                                   FIRST_PATH, columns=COLUMNS)
    assert same.report.rows[1] == ('21,' + kind + ',Lighting,Lighting,AreaPrimary,'
                                  + ','.join(DATA['mask_cases'][0]['group_tags'])
                                  + ',<N/A>,<N/A>,')


@pytest.mark.parametrize('kind', TYPES)
@pytest.mark.parametrize('count', (7, 9))
def test_neopro_cached_projection_refuses_partial_or_extra_block_collections(kind, count):
    result = project_native_xml_unit(xml(one_family(kind)), FIRST_PATH, columns=COLUMNS)
    unit = result.cached.unit
    identities = unit.group_identities[:count] if count == 7 else unit.group_identities + (unit.group_identities[0],)
    with pytest.raises(ValueError, match='exactly eight stored groups'):
        project_cached_csv_unit(replace(unit, group_identities=identities),
            group_cache=result.cached.groups,
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            columns=COLUMNS)
    with pytest.raises(ValueError, match='Loader association history'):
        project_cached_csv_unit(replace(unit, loader_associations=unit.group_identities),
            group_cache=result.cached.groups,
            area_observations=(CSVAreaObservation('255'), CSVAreaObservation('255')),
            columns=COLUMNS)


def damage(root, case):
    unit = first_unit(root)
    if case == 'old-firmware':
        unit.find('FirmwareVersion').text = '1.5.02'
    elif case == 'other-firmware':
        unit.find('FirmwareVersion').text = '2.5.01'
    elif case == 'other-family':
        unit.find('UnitType').text = 'KEYH2'
    elif case == 'group-count':
        parameter(unit, 'GroupAddress').set('Value', '1 2 3 4 5 6 7 8 9')
    elif case == 'short-groups':
        parameter(unit, 'GroupAddress').set('Value', '1 2 3 4 5 6 7')
    elif case == 'bad-mask':
        parameter(unit, 'SecondApplicationBlocks').set('Value', '256')
    elif case == 'missing-mask':
        unit.remove(parameter(unit, 'SecondApplicationBlocks'))
    elif case == 'duplicate-pp':
        ET.SubElement(unit, 'PP', {'Name': 'Application', 'Value': '56 57'})
    elif case == 'unconfigured-secondary':
        parameter(unit, 'Application').set('Value', '56 255')
    elif case == 'missing-secondary':
        root.find('Project/Network').remove(application(root, 57))
    elif case == 'missing-primary':
        root.find('Project/Network').remove(application(root, 56))
    elif case == 'duplicate-application':
        app = ET.SubElement(root.find('Project/Network'), 'Application')
        ET.SubElement(app, 'Address').text = '57'
        ET.SubElement(app, 'TagName').text = 'Ambiguous'
    elif case == 'missing-selected-group':
        app = application(root, 57)
        app.remove(next(row for row in app.findall('Group') if row.findtext('Address') == '8'))
    elif case == 'duplicate-group':
        app = application(root, 57)
        app.append(ET.fromstring(ET.tostring(app.find('Group'))))
    elif case == 'duplicate-oid':
        application(root, 57).find('Group/OID').text = application(root, 56).findtext('Group/OID')
    elif case == 'unsupported-area':
        parameter(unit, 'AreaGroupAddress').set('Value', '12')
    elif case == 'missing-primary-area':
        app = application(root, 56)
        app.remove(next(row for row in app.findall('Group') if row.findtext('Address') == '255'))
        parameter(unit, 'SecondApplicationBlocks').set('Value', '255')
    else:
        raise AssertionError(case)


REFUSALS = ('old-firmware', 'other-firmware', 'other-family', 'group-count',
            'short-groups', 'bad-mask', 'missing-mask', 'duplicate-pp',
            'unconfigured-secondary', 'missing-secondary', 'missing-primary',
            'duplicate-application', 'missing-selected-group', 'duplicate-group',
            'duplicate-oid', 'unsupported-area', 'missing-primary-area')


@pytest.mark.parametrize('kind', TYPES)
@pytest.mark.parametrize('case', REFUSALS)
def test_neopro_unsupported_or_ambiguous_inputs_refuse_without_snapshot_mutation(kind, case):
    root = one_family(kind)
    damage(root, case)
    before = xml(root)
    with pytest.raises(ValueError):
        project_native_xml_unit(before, FIRST_PATH, columns=COLUMNS)
    assert xml(root) == before


def test_neopro_whole_project_and_explicit_selection_preserve_declared_order():
    raw = DATA['fixture']['xml']
    result = project_native_xml_selection(raw, project_path='//NEOCSV', columns=COLUMNS)
    assert result.unit_paths == tuple(DATA['fixture']['project_unit_paths'])
    assert result.report.rows == tuple(DATA['fixture']['csv_rows'])
    assert result.report.utf8_bytes == DATA['fixture']['csv_utf8'].encode()
    assert hashlib.sha256(result.report.utf8_bytes).hexdigest() == DATA['fixture']['csv_sha256']
    assert result.as_dict()['unit_order'] == 'project_network_document_unit_address_ascending'
    assert result.as_dict()['original_manager_enumeration_verified'] is False
    reverse = tuple(reversed(result.unit_paths))
    selected = project_native_xml_selection(raw, unit_paths=reverse, columns=COLUMNS)
    assert selected.unit_paths == reverse
    assert selected.report.rows == (result.report.rows[0], *reversed(result.report.rows[1:]))


@pytest.mark.parametrize('live', (False, True), ids=('offline', 'owned-wire'))
@pytest.mark.parametrize('mode', ('project', 'network', 'units'))
def test_public_neopro_csv_cli_exports_exact_rows_with_one_read_and_no_writes(tmp_path, live, mode):
    raw = DATA['fixture']['xml']
    source = tmp_path / 'synthetic.xml'
    source.write_text(raw, encoding='utf-8')
    before = source.read_bytes()
    output = tmp_path / 'report.csv'
    paths = DATA['fixture']['project_unit_paths']
    if mode == 'project':
        flags = ['--project', '//NEOCSV'] if live else ['--native-xml-project', '//NEOCSV']
        rows = DATA['fixture']['csv_rows']
    elif mode == 'network':
        flags = ['--network', '//NEOCSV/254'] if live else ['--native-xml-network', '//NEOCSV/254']
        rows = DATA['fixture']['csv_rows'][:-1]
    else:
        flags = ['--units', paths[2], paths[0]] if live else ['--native-xml-units', paths[2], paths[0]]
        rows = [DATA['fixture']['csv_rows'][0], DATA['fixture']['csv_rows'][3], DATA['fixture']['csv_rows'][1]]
    if live:
        with peer([[reply(raw)]]) as ((host, port), sent):
            code, result = invoke(['cgate', '--host', host, '--port', port,
                'database-csv', *flags, '--columns', *COLUMNS, '--output', output], artifact_dir=tmp_path)
        (tmp_path / 'wire.json').write_text(json.dumps([row.hex() for row in sent]) + '\n')
        assert sent == [DATA['wire']['request'].encode()]
        assert result['native_database_mutated'] is False
    else:
        code, result = invoke(['toolkit-database-csv', source, *flags,
                              '--columns', *COLUMNS, '--output', output], artifact_dir=tmp_path)
    assert code == 0, result
    assert output.read_bytes() == ('\r\n'.join(rows) + '\r\n\r\n').encode()
    assert result['report']['unit_count'] == len(rows) - 1
    assert source.read_bytes() == before


@pytest.mark.parametrize('live', (False, True), ids=('offline', 'owned-wire'))
@pytest.mark.parametrize('case', ('unsupported-late', 'ambiguous-late', 'missing-group-late'))
def test_public_neopro_csv_late_project_failure_is_atomic_before_output(tmp_path, live, case):
    root = tree()
    late = root.findall('Project/Network')[-1]
    if case == 'unsupported-late':
        late.find('Unit/FirmwareVersion').text = '2.5.01'
    elif case == 'ambiguous-late':
        late.append(ET.fromstring(ET.tostring(late.find('Unit'))))
    else:
        app = next(row for row in late.findall('Application') if row.findtext('Address') == '56')
        app.remove(next(row for row in app.findall('Group') if row.findtext('Address') == '8'))
    raw = xml(root)
    source = tmp_path / 'synthetic.xml'
    source.write_text(raw)
    before = source.read_bytes()
    output = tmp_path / 'never.csv'
    if live:
        with peer([[reply(raw)]]) as ((host, port), sent):
            code, result = invoke(['cgate', '--host', host, '--port', port,
                'database-csv', '--project', '//NEOCSV', '--output', output], artifact_dir=tmp_path)
        (tmp_path / 'wire.json').write_text(json.dumps([row.hex() for row in sent]) + '\n')
        assert sent == [DATA['wire']['request'].encode()]
    else:
        code, result = invoke(['toolkit-database-csv', source,
            '--native-xml-project', '//NEOCSV', '--output', output], artifact_dir=tmp_path)
    assert code == 1, result
    if live:
        # The established live path reports generic pre-output validation
        # errors; the offline operation carries the explicit creation flag.
        assert result['type'] == 'ValueError'
        assert isinstance(result['error'], str) and result['error']
        assert 'toolkit_database_csv_evidence' not in result
    else:
        assert result['toolkit_database_csv_evidence']['output_create_attempted'] is False
    assert not output.exists()
    assert source.read_bytes() == before


@pytest.mark.parametrize('kind', TYPES)
def test_public_neopro_cached_json_refuses_missing_primary_application_identity(tmp_path, kind):
    # Even a cache derived from a valid native snapshot loses the Application
    # identity in v1 JSON, so its same-address Area Groups are ambiguous.
    native = project_native_xml_unit(xml(one_family(kind, mask=255)),
                                     FIRST_PATH, columns=COLUMNS)
    cached = native.cached
    value = {'format': PROFILE, 'unit': cached.unit.as_dict(),
             'group_cache': [group.as_dict() for group in cached.groups],
             'area_observations': [{'raw': '255', 'completed': True}] * 2,
             'group_save': None}
    source = tmp_path / 'cached.json'
    source.write_text(json.dumps(value), encoding='utf-8')
    before = source.read_bytes()
    output = tmp_path / 'never.csv'
    code, result = invoke(['toolkit-database-csv', source, '--cached-projection',
                          '--output', output], artifact_dir=tmp_path)
    assert code == 1
    assert result['error'] == {'type': 'ValueError', 'message': (
        'NeoPro cached v1 JSON cannot establish primary Application identity; '
        'use cached v2 or an explicit native XML snapshot')}
    assert result['toolkit_database_csv_evidence']['output_create_attempted'] is False
    assert result['toolkit_database_csv_evidence']['network_io_attempted'] is False
    assert not output.exists()
    assert source.read_bytes() == before
    assert native.complete and native.cached.area_identity


def test_public_neopro_csv_server_refusal_is_not_retried_and_creates_no_output(tmp_path):
    output = tmp_path / 'never.csv'
    with peer([[DATA['wire']['server_refusal']['response'].encode()]]) as ((host, port), sent):
        code, result = invoke(['cgate', '--host', host, '--port', port,
            'database-csv', '--project', '//NEOCSV', '--output', output], artifact_dir=tmp_path)
    (tmp_path / 'wire.json').write_text(json.dumps([row.hex() for row in sent]) + '\n')
    assert code == DATA['wire']['server_refusal']['cli_exit']
    assert sent == [DATA['wire']['request'].encode()]
    assert result['type'] == 'CGateError'
    assert result['error'] == 'C-Gate error: 401 Bad object or device ID'
    assert 'toolkit_database_csv_evidence' not in result
    assert not output.exists()
