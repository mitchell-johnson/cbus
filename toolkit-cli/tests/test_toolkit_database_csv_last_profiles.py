"""Final source-derived CSV orders, conditional modes and hidden dependencies."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.toolkit_database_csv_native import project_native_xml_unit
from cbus_toolkit.toolkit_database_csv_projection import (
    SOURCE_PROFILE, family_profile, loads_cached_projection,
)
from cbus_toolkit.toolkit_database_csv_registry import REGISTRATIONS


ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / 'rust/testdata/vectors/toolkit_database_csv_last_profiles.json').read_text())
COLUMNS = tuple(DATA['columns'])


def tree():
    return ET.fromstring(DATA['fixture']['xml'])


def text(root):
    return ET.tostring(root, encoding='unicode')


def unit(root, path):
    return next(row for row in root.find('Project/Network').findall('Unit')
                if row.findtext('Address') == path.rsplit('/', 1)[1])


def parameter(node, name):
    return next(row for row in node.findall('PP') if row.get('Name') == name)


def case(klass, *, primary=None, count=None):
    return next(row for row in DATA['fixture']['units'] if row['class'] == klass
                and (primary is None or row['primary_address'] == primary)
                and (count is None or row['groups'] == count))


def application(root, address):
    return next(row for row in root.find('Project/Network').findall('Application')
                if row.findtext('Address') == str(address))


def remove_group(root, app, address):
    owner = application(root, app)
    owner.remove(next(row for row in owner.findall('Group')
                      if row.findtext('Address') == str(address)))


def cached(native):
    result = native.cached
    return {'format': SOURCE_PROFILE, 'unit': result.unit.as_dict(),
            'group_cache': [replace(group, references=()).as_dict() for group in result.groups],
            'application_context': result.application_context.as_dict(),
            'area_observations': [] if result.raw_area is None else
                [{'raw': result.raw_area, 'completed': True}] * 2,
            'group_save': None}


def project(root, row):
    return project_native_xml_unit(text(root), row['path'], columns=COLUMNS)


def group_tags(result):
    labels = {group.identity: group.tag for group in result.cached.groups}
    return [labels[identity] for identity in result.cached.unit.group_identities]


def test_distinct_receipt_binds_all_static_types_and_preserves_historical_denominators():
    paths = [ROOT / ('toolkit-cli/research/fixtures/' + name) for name in (
        'toolkit-database-csv-families-registry.json',
        'toolkit-database-csv-completion-registry.json',
        'toolkit-database-csv-last-registry.json')]
    receipts = [json.loads(path.read_text()) for path in paths]
    assert [receipt['summary']['admitted_types'] for receipt in receipts] == [126, 214, 262]
    assert receipts[-1]['summary']['admitted_registrations'] == 424
    assert receipts[-1]['summary']['static_registrations'] == 425
    omit = {'admitted', 'admitted_firmware', 'association_model', 'refusal_reason'}
    def facts(receipt):
        return [{key: value for key, value in row.items() if key not in omit}
                for row in receipt['registrations']]
    assert facts(receipts[0]) == facts(receipts[1]) == facts(receipts[2])
    assert hashlib.sha256(paths[1].read_bytes()).hexdigest() == DATA['source_evidence']['historical_registry_sha256']
    assert hashlib.sha256(paths[2].read_bytes()).hexdigest() == DATA['source_evidence']['registry_sha256']
    proof_path = ROOT / 'toolkit-cli/research/fixtures/toolkit-database-csv-last-source-proof.json'
    proof = json.loads(proof_path.read_text())
    assert hashlib.sha256(proof_path.read_bytes()).hexdigest() == DATA['source_evidence']['source_proof_sha256']
    assert proof['registry_sha256'] == DATA['source_evidence']['registry_sha256']
    assert proof['original_inputs'] == receipts[-1]['original_inputs']
    assert not proof['original_execution'] and not receipts[-1]['original_execution']
    refused = [row for row in receipts[-1]['registrations'] if not row['admitted']]
    assert [(row['unit_type'], row['class'], row['agent']) for row in refused] == [('KEYGL5', 'TKEYGL5', None)]
    assert REGISTRATIONS == tuple((row['unit_type'], row['firmware_min'], row['firmware_max'],
        row['class'], row['agent'] or '', '' if row['admitted'] else row['refusal_reason'])
        for row in receipts[-1]['registrations'])


@pytest.mark.skipif(not (os.environ.get('CBUS_TOOLKIT_EXE') and os.environ.get('CBUS_TOOLKIT_MAP')),
                    reason='Pinned original Toolkit EXE/MAP not provisioned')
def test_fresh_static_proof_regeneration_matches_committed_receipt():
    from research.csv_last_profiles_static import recover

    registry_path = ROOT / 'toolkit-cli/research/fixtures/toolkit-database-csv-last-registry.json'
    registry = json.loads(registry_path.read_text())
    actual = recover(os.environ['CBUS_TOOLKIT_EXE'], os.environ['CBUS_TOOLKIT_MAP'], registry)
    actual['registry_sha256'] = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    expected = ROOT / 'toolkit-cli/research/fixtures/toolkit-database-csv-last-source-proof.json'
    assert json.dumps(actual, ensure_ascii=False, indent=2) + '\n' == expected.read_text()


@pytest.mark.parametrize('row', DATA['fixture']['units'], ids=lambda row: row['path'])
def test_all_new_shapes_have_independent_literal_native_and_cached_rows(row):
    native = project_native_xml_unit(DATA['fixture']['xml'], row['path'], columns=COLUMNS)
    assert native.cached.selected_class == row['class']
    assert native.report.rows == (DATA['fixture']['rows'][0], row['row'])
    raw = cached(native)
    before = deepcopy(raw)
    assert loads_cached_projection(json.dumps(raw).encode(), columns=COLUMNS).report.utf8_bytes == native.report.utf8_bytes
    assert raw == before


@pytest.mark.parametrize('row', DATA['range_cases'], ids=lambda row: row['kind'] + '-' + row['firmware'])
def test_every_new_registration_endpoint_keeps_its_exact_class_and_literal_row(row):
    root = tree()
    node = unit(root, row['template_path'])
    node.find('FirmwareVersion').text = row['firmware']
    before = text(root)
    result = project_native_xml_unit(before, row['template_path'], columns=COLUMNS)
    assert result.cached.selected_class == row['class']
    assert result.report.rows[1] == row['row']
    assert text(root) == before


@pytest.mark.parametrize('klass', ('TBridge1', 'TCBusWirelessGatewayUnit', 'TCBusWirelessPCIUnit'))
@pytest.mark.parametrize('raw,primary,secondary', [('', 255, 255), ('56', 56, 255), ('56 57', 56, 57)])
def test_infrastructure_formatters_use_real255_and_their_exact_empty_default(klass, raw, primary, secondary):
    row = case(klass)
    root = tree()
    parameter(unit(root, row['path']), 'Application').set('Value', raw)
    result = project(root, row)
    context = result.cached.application_context
    by_id = {app.identity: app.address for app in context.applications}
    assert (by_id[context.primary_identity], by_id[context.secondary_identity]) == (primary, secondary)
    assert result.cached.unit.group_identities == ()
    application(root, secondary).find('Address').text = '254'
    with pytest.raises(ValueError, match='Application at address ' + str(secondary)):
        project(root, row)


@pytest.mark.parametrize('klass', ('TSENLL', 'TSENTEMP'))
def test_scalar_sensors_keep_repeated_unused_associations_in_source_order(klass):
    row = case(klass)
    root = tree()
    profile = family_profile(row['kind'], row['firmware'])
    for name, value in zip(profile['group_parameter'], ('255', '2', '2')):
        parameter(unit(root, row['path']), name).set('Value', value)
    assert group_tags(project(root, row)) == ['PUnused', 'P02', 'P02']
    remove_group(root, 56, 2)
    with pytest.raises(ValueError, match='group reference is absent'):
        project(root, row)


@pytest.mark.parametrize('klass,outputs', [('TIOPE1R1', 1), ('TIOPE2R2', 2), ('TIOPE2C4', 4)])
def test_iope_checks_secondary_block_dependencies_before_primary_report_reload(klass, outputs):
    row = case(klass)
    root = tree()
    assert group_tags(project(root, row)) == [f'P{x:02d}' for x in range(8, 0, -1)] + [f'P{x:02d}' for x in range(12, 12 - outputs, -1)]
    remove_group(root, 57, 8)
    before = text(root)
    with pytest.raises(ValueError, match='Group at address 8'):
        project(root, row)
    assert text(root) == before
    parameter(unit(root, row['path']), 'SecondApplicationBlocks').set('Value', '0')
    assert group_tags(project(root, row))[0] == 'P08'


@pytest.mark.parametrize('parameter_name,count', [('InputGroupAddress', 8), ('OutputGroupAddress', 4)])
def test_iope_short_nonempty_arrays_default_missing_tail_to255(parameter_name, count):
    row = case('TIOPE2C4')
    root = tree()
    parameter(unit(root, row['path']), parameter_name).set('Value', '3')
    result = project(root, row)
    labels = group_tags(result)
    selected = labels[:8] if parameter_name == 'InputGroupAddress' else labels[8:]
    assert selected == ['P03', *['PUnused'] * (count - 1)]
    remove_group(root, 56, 255)
    with pytest.raises(ValueError, match='Group at address 255|group reference is absent'):
        project(root, row)


@pytest.mark.parametrize('primary,count,name', [(25, 1, 'TemperatureGroup'), (172, 1, 'GroupAddress'), (228, 0, None)])
def test_temperature_application_modes_consume_hidden_unused_group_and_the_exact_parameter(primary, count, name):
    row = case('TSENTEMPPro', primary=primary)
    root = tree()
    result = project(root, row)
    assert len(result.cached.unit.group_identities) == count
    if name:
        node = unit(root, row['path'])
        node.remove(parameter(node, name))
        with pytest.raises(ValueError, match=name):
            project(root, row)
        root = tree()
    remove_group(root, primary, 255)
    with pytest.raises(ValueError, match='Group at address 255'):
        project(root, row)


def test_temperature_cached_count_cannot_be_reinterpreted_as_another_application_mode():
    row = case('TSENTEMPPro', primary=25)
    raw = cached(project(tree(), row))
    app = next(app for app in raw['application_context']['applications'] if app['address'] == 25)
    app['address'] = 56
    before = deepcopy(raw)
    with pytest.raises(ValueError, match='primary Application mode'):
        loads_cached_projection(json.dumps(raw).encode(), columns=COLUMNS)
    assert raw == before


@pytest.mark.parametrize('count', (0, 1, 4, 16))
def test_wireless_fan_reports_outputs_only_and_each_independent_routing_bit(count):
    row = case('TWRD4F1', count=count)
    result = project(tree(), row)
    assert group_tags(result) == [('S' if x % 2 else 'P') + f'{count-x:02d}' for x in range(count)]
    assert result.cached.raw_area is None
    assert not any(name.startswith('Block') for name in row['parameters'])


@pytest.mark.parametrize('name,value', [('InstalledChannels', '17'), ('InstalledKeys', '17'),
    ('ChannelRelayMask', '2'), ('OutputGroupSecondary', '2'), ('OutputGroup', ''),
    ('OutputGroupSecondary', '0 1')])
def test_wireless_fan_invalid_consumed_state_refuses_without_changing_snapshot(name, value):
    row = case('TWRD4F1', count=1)
    root = tree()
    parameter(unit(root, row['path']), name).set('Value', value)
    before = text(root)
    with pytest.raises(ValueError):
        project(root, row)
    assert text(root) == before


@pytest.mark.parametrize('klass', ('TPC_GIM', 'TSENCT4', 'TKEYSCEN4', 'TSCNCTL5', 'TDMXDO12'))
def test_empty_group_managers_still_run_their_independent_primary_area_provider(klass):
    row = case(klass)
    result = project(tree(), row)
    assert result.cached.unit.group_identities == ()
    assert result.cached.csv_unit.area == 'P42'
    assert [event.event for event in result.cached.events].count('area_load') == 2
    root = tree()
    remove_group(root, 56, 42)
    with pytest.raises(ValueError, match='Area group is absent'):
        project(root, row)


def test_late_bytecraft_partition_keeps_twelve_prefix_groups_and_defaulted_tail():
    row = case('TDIMPR12L1')
    root = tree()
    node = unit(root, row['path'])
    parameter(node, 'GroupAddress').set('Value', '2')
    assert group_tags(project(root, row)) == ['P02', *['PUnused'] * 11]
    node.find('FirmwareVersion').text = '1.9.02'
    assert project(root, row).cached.selected_class == 'TDIMPR12'


@pytest.mark.parametrize('kind,firmware', [('WGATE5F', '1.1.1'), ('WGATE5N', '1.4.91.5'),
    ('SENLL', '0.9'), ('DIMPR12', '1.9.2.5'), ('PC_SHAC', '999'), ('KEYGL5', '5.4.99')])
def test_no_nearby_profile_is_guessed_for_factory_gaps_or_duplicate_no_agent(kind, firmware):
    row = case('TPCSHAC')
    root = tree()
    node = unit(root, row['path'])
    node.find('UnitType').text = kind
    node.find('FirmwareVersion').text = firmware
    with pytest.raises(ValueError):
        project(root, row)
