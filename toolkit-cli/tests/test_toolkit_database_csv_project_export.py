"""Whole-project composition with source-backed per-network manager sort."""
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit import toolkit_database_csv_cli as boundary
from cbus_toolkit import toolkit_database_csv_native as native
from cbus_toolkit.toolkit_database_csv import COLUMNS, MAX_CAPTURE_BYTES
from tests.test_cgate import peer
from tests.test_toolkit_database_csv_native import native_xml, oid
from tests import test_toolkit_database_csv_selection_export as selection_tests
from tests import test_toolkit_database_csv_keye_family as keye_tests
from tests import test_toolkit_database_csv_keygl5 as keygl5_tests
from tests import test_toolkit_database_csv_senpiria as senpiria_tests

invoke = selection_tests.DatabaseCSVSelectionCLITests().invoke
ORDER_FIXTURE = (Path(__file__).resolve().parents[1] / 'research' / 'fixtures' /
                 'toolkit-database-csv-manager-order-synthetic.xml')


def project_xml(*, unsupported=False, oids=False):
    """Two networks with same-address units and independent admitted profiles."""
    root = ET.fromstring(native_xml(with_oids=oids))
    project = root.find('Project')
    project.find('Network/Unit/TagName').text = 'First'
    second = ET.fromstring(native_xml(unit_type='KEYE3', secondary_address=57,
        secondary_blocks=1, with_oids=oids)).find('Project/Network')
    second.find('Address').text = '1'
    second.find('Unit/TagName').text = 'Second, "room"'
    if oids:
        second.find('Unit/OID').text = oid(501)
    if unsupported:
        second.find('Unit/FirmwareVersion').text = 'unobserved'
    project.append(second)
    return ET.tostring(root, encoding='unicode')


def text(root):
    return ET.tostring(root, encoding='unicode')


def all_admitted_families_xml():
    """Compose the already tested unit fixtures in one OID-less project."""
    sources = (
        native_xml(with_oids=False),
        native_xml(unit_type='OWNED_UNKNOWN', with_oids=False),
        keye_tests.family_xml(),
        native_xml(unit_type='DIMDN8', with_oids=False),
        native_xml(unit_type='RELDN12', with_oids=False),
        native_xml(unit_type='SENPIROA', with_oids=False),
        senpiria_tests.synthetic(),
        keygl5_tests.synthetic(),
    )
    root = ET.Element('Installation')
    project = ET.SubElement(root, 'Project')
    ET.SubElement(project, 'Address').text = 'CSVTEST'
    for index, source in enumerate(sources):
        network = ET.fromstring(source).find('Project/Network')
        network.find('Address').text = str(254 - index)
        if index == 2:
            # The five-unit fixture covers KEYE4 and KEYEIR1-4. The same
            # captured TKEYEx shape also admits KEYE1-3.
            template = network.find('Unit')
            for offset, kind in enumerate(('KEYE1', 'KEYE2', 'KEYE3'), start=9):
                unit = copy.deepcopy(template)
                unit.find('Address').text = str(offset)
                unit.find('UnitType').text = kind
                network.append(unit)
        for parent in network.iter():
            for object_id in parent.findall('OID'):
                parent.remove(object_id)
        project.append(network)
    return text(root)


def test_project_keeps_network_document_order_and_secondary_associations():
    xml = project_xml()
    with patch.object(native, '_container', wraps=native._container) as parse:
        result = native.project_native_xml_selection(xml, project_path='//CSVTEST',
            columns=('group_1', 'tag_name', 'secondary', 'address'))
    assert parse.call_count == 1
    # Literal expected rows compose retained serializer and KEYE contracts.
    assert result.report.csv_text == (
        'Unit Address,Tag Name,Secondary Application,Group 1,\r\n'
        '4,First,,Group1,\r\n'
        '4,"Second, ""room""",HVAC,Secondary1,\r\n\r\n')
    evidence = result.as_dict()
    assert evidence['unit_paths'] == ['//CSVTEST/254/p/4', '//CSVTEST/1/p/4']
    assert evidence['project_path'] == '//CSVTEST'
    assert evidence['network_path'] is None
    assert evidence['unit_order'] == 'project_network_document_unit_address_ascending'
    assert evidence['original_manager_enumeration_verified'] is False
    assert evidence['native_database_mutated'] is False
    assert evidence['xml_sha256'] == hashlib.sha256(xml.encode()).hexdigest()
    assert all(item['xml_sha256'] == evidence['xml_sha256'] for item in evidence['projections'])


def test_whole_project_composes_every_admitted_family_offline_and_live(tmp_path):
    xml = all_admitted_families_xml()
    columns = ('unit_type', 'secondary', 'group_1', 'group_16')
    root = ET.fromstring(xml)
    expected_paths = tuple(
        f'//CSVTEST/{network.findtext("Address")}/p/{address}'
        for network in root.findall('Project/Network')
        for address in sorted(int(unit.findtext('Address')) for unit in network.findall('Unit')))
    # Each family's standalone row is already pinned by its profile tests;
    # this comparison checks selection, order and one shared serialization.
    expected_rows = tuple(native.project_native_xml_unit(xml, path, columns=columns)
                          .report.rows[1] for path in expected_paths)
    expected = ('Unit Type,Secondary Application,Group 1,Group 16,\r\n'
                + '\r\n'.join(expected_rows) + '\r\n\r\n').encode()
    source, offline, live = (tmp_path / name for name in
                             ('project.xml', 'offline.csv', 'live.csv'))
    source.write_text(xml)
    before = source.read_bytes()
    code, receipt = invoke(['toolkit-database-csv', source, '--native-xml-project',
        '//CSVTEST', '--columns', *columns, '--output', offline])
    assert code == 0, receipt
    assert offline.read_bytes() == expected
    assert source.read_bytes() == before
    assert receipt['projection']['unit_paths'] == list(expected_paths)
    assert receipt['projection']['xml_sha256'] == hashlib.sha256(before).hexdigest()
    assert receipt['projection']['original_manager_enumeration_verified'] is False
    assert [item['cached_projection']['selected_class'] for item in
            receipt['projection']['projections']] == (
        ['TRELAY4', 'TCBusUnitGeneric'] + ['TKEYEx'] * 8 +
        ['TDIMDN8', 'TRELDN12', 'TST7SENPIROA', 'TST7SENPIRSS', 'TCBusEDLTUnit'])

    response = (b'[1] 343-Begin XML snippet\r\n' + b''.join(
        (b'[1] 347-' if index == 0 else b'[1] ') + line + b'\r\n'
        for index, line in enumerate(before.splitlines())) +
        b'[1] 344 End XML snippet\r\n')
    with peer([[response]]) as ((host, port), sent):
        code, receipt = invoke(['cgate', '--host', host, '--port', port,
            'database-csv', '--project', '//CSVTEST', '--columns', *columns,
            '--output', live], offline=False)
    assert code == 0, receipt
    assert sent == [b'[1] DBGETXML //CSVTEST\r\n']
    assert live.read_bytes() == expected
    assert source.read_bytes() == before
    assert receipt['projection']['unit_paths'] == list(expected_paths)
    assert receipt['native_database_mutated'] is False


def test_out_of_order_native_fixture_sorts_each_network_but_not_explicit_selection(tmp_path):
    xml = ORDER_FIXTURE.read_text()
    project = native.project_native_xml_selection(xml, project_path='//CSVTEST',
                                                  columns=('address',))
    assert project.unit_paths == ('//CSVTEST/254/p/4', '//CSVTEST/254/p/9',
                                  '//CSVTEST/1/p/2', '//CSVTEST/1/p/7')
    assert project.report.csv_text == 'Unit Address,\r\n4,\r\n9,\r\n2,\r\n7,\r\n\r\n'
    assert project.as_dict()['original_manager_enumeration_verified'] is False
    explicit = native.project_native_xml_selection(xml,
        unit_paths=('//CSVTEST/1/p/7', '//CSVTEST/254/p/9', '//CSVTEST/1/p/2'),
        columns=('address',))
    assert explicit.report.csv_text == 'Unit Address,\r\n7,\r\n9,\r\n2,\r\n\r\n'
    assert explicit.as_dict()['unit_order'] == 'explicit_selection'

    for flags, expected, unit_order in (
        (['--native-xml-network', '//CSVTEST/254'], b'Unit Address,\r\n4,\r\n9,\r\n\r\n',
         'network_unit_address_ascending'),
        (['--native-xml-project', '//CSVTEST'], b'Unit Address,\r\n4,\r\n9,\r\n2,\r\n7,\r\n\r\n',
         'project_network_document_unit_address_ascending')):
        output = tmp_path / ('network.csv' if '--native-xml-network' in flags else 'project.csv')
        code, result = invoke(['toolkit-database-csv', ORDER_FIXTURE, *flags,
                               '--columns', 'address', '--output', output])
        assert code == 0, result
        assert output.read_bytes() == expected
        assert result['projection']['unit_order'] == unit_order
        assert result['projection']['original_manager_enumeration_verified'] is False


def test_out_of_order_fixture_duplicate_address_rejects_before_output(tmp_path):
    root = ET.fromstring(ORDER_FIXTURE.read_bytes())
    units = root.findall('Project/Network/Unit')
    units[0].find('Address').text = '4'
    source, output = tmp_path / 'duplicate.xml', tmp_path / 'should-not-exist.csv'
    source.write_bytes(ET.tostring(root))
    code, result = invoke(['toolkit-database-csv', source, '--native-xml-project',
                           '//CSVTEST', '--columns', 'address', '--output', output])
    assert code == 1
    assert 'duplicate unit addresses' in result['error']['message']
    assert result['toolkit_database_csv_evidence']['output_create_attempted'] is False
    assert not output.exists()


@pytest.mark.parametrize('networks', [0, 1, 2])
def test_empty_project_or_empty_networks_produce_original_header_only(networks):
    root = ET.Element('Installation')
    project = ET.SubElement(root, 'Project')
    ET.SubElement(project, 'Address').text = 'CSVTEST'
    for address in range(networks):
        network = ET.SubElement(project, 'Network')
        ET.SubElement(network, 'Address').text = str(address)
    result = native.loads_native_xml_selection(text(root).encode(),
        project_path='//CSVTEST', columns=('address',))
    assert result.report.csv_text == 'Unit Address,\r\n\r\n'
    assert result.unit_paths == ()


@pytest.mark.parametrize('bad', ['', 'CSVTEST', '//', '//TOOLONG99', '//CSVTEST/254',
                                  '//bad-name', '//CSVTEST\n', 42])
def test_invalid_project_selector_is_rejected_before_parse(bad):
    with patch.object(native, '_container', side_effect=AssertionError('No parse')):
        with pytest.raises(ValueError):
            native.project_native_xml_selection('not XML', project_path=bad, columns=COLUMNS)


@pytest.mark.parametrize('other', [{'network_path': '//CSVTEST/254'},
                                   {'unit_paths': ('//CSVTEST/254/p/4',)}])
def test_project_cannot_be_combined_with_other_selectors(other):
    with pytest.raises(ValueError, match='exactly one'):
        native.project_native_xml_selection('not XML', project_path='//CSVTEST', columns=COLUMNS, **other)


def test_unsupported_late_unit_rejects_whole_project_but_network_remains_usable():
    xml = project_xml(unsupported=True)
    assert native.project_native_xml_selection(xml, network_path='//CSVTEST/254', columns=COLUMNS).complete
    with pytest.raises(ValueError, match='//CSVTEST/1/p/4.*captured'):
        native.project_native_xml_selection(xml, project_path='//CSVTEST', columns=COLUMNS)


@pytest.mark.parametrize('case', ['network-address', 'unit-address', 'unit-oid', 'wrong-project'])
def test_ambiguous_or_wrong_project_rejected(case):
    root = ET.fromstring(project_xml(oids=True))
    first, second = root.findall('Project/Network')
    if case == 'network-address':
        second.find('Address').text = '254'
    elif case == 'unit-address':
        second.append(copy.deepcopy(second.find('Unit')))
    elif case == 'unit-oid':
        second.find('Unit/OID').text = first.findtext('Unit/OID')
    else:
        root.find('Project/Address').text = 'OTHER'
    with pytest.raises(ValueError):
        native.project_native_xml_selection(text(root), project_path='//CSVTEST', columns=COLUMNS)


def test_total_unit_bound_applies_across_networks_before_projection():
    with patch.object(native, 'MAX_UNITS', 1), patch.object(
            native, '_project_native_xml_unit', side_effect=AssertionError('No projection')):
        with pytest.raises(ValueError, match='exceeds 4096'):
            native.project_native_xml_selection(project_xml(), project_path='//CSVTEST', columns=COLUMNS)


def test_network_bound_includes_empty_networks():
    root = ET.fromstring(project_xml())
    project = root.find('Project')
    for network in list(project.findall('Network')):
        project.remove(network)
    for _ in range(257):
        ET.SubElement(project, 'Network')
    with pytest.raises(ValueError, match='exceeds 256'):
        native.project_native_xml_selection(text(root), project_path='//CSVTEST', columns=COLUMNS)


def test_offline_project_export_preserves_source_and_refuses_overwrite(tmp_path):
    source, output = tmp_path / 'input.xml', tmp_path / 'output.csv'
    source.write_text(project_xml())
    before = source.read_bytes()
    args = ['toolkit-database-csv', source, '--native-xml-project', '//CSVTEST',
            '--columns', 'address', '--output', output]
    code, result = invoke(args)
    assert code == 0
    assert result['projection']['project_path'] == '//CSVTEST'
    assert result['report']['unit_count'] == 2
    saved = output.read_bytes()
    assert saved == b'Unit Address,\r\n4,\r\n4,\r\n\r\n'
    assert source.read_bytes() == before
    code, result = invoke(args)
    assert code == 1
    assert output.read_bytes() == saved
    assert result['toolkit_database_csv_evidence']['output_created'] is False


def test_offline_invalid_project_before_source_read():
    with patch.object(boundary.os, 'lstat', side_effect=AssertionError('No source read')):
        code, result = invoke(['toolkit-database-csv', 'not-read.xml',
            '--native-xml-project', '//CSVTEST/254', '--output', 'not-created.csv'])
    assert code == 1
    assert result['toolkit_database_csv_evidence']['stage'] == 'validate'


@pytest.mark.parametrize('live', [False, True])
def test_late_failure_leaves_no_partial_project_export(tmp_path, live):
    output = tmp_path / 'output.csv'
    xml = project_xml(unsupported=True)
    if live:
        response = b'[1] 343-Begin XML snippet\r\n[1] 347-' + xml.encode() + b'\r\n[1] 344 End XML snippet\r\n'
        with peer([[response]]) as ((host, port), sent):
            code, _ = invoke(['cgate', '--host', host, '--port', port, 'database-csv',
                '--project', '//CSVTEST', '--output', output], offline=False)
        assert sent == [b'[1] DBGETXML //CSVTEST\r\n']
    else:
        source = tmp_path / 'input.xml'
        source.write_text(xml)
        code, _ = invoke(['toolkit-database-csv', source, '--native-xml-project',
                           '//CSVTEST', '--output', output])
    assert code == 1
    assert not output.exists()


def test_live_project_uses_exactly_one_snapshot(tmp_path):
    response = b'[1] 343-Begin XML snippet\r\n[1] 347-' + project_xml().encode() + b'\r\n[1] 344 End XML snippet\r\n'
    output = tmp_path / 'output.csv'
    with peer([[response]]) as ((host, port), sent):
        code, result = invoke(['cgate', '--host', host, '--port', port, 'database-csv',
            '--project', '//CSVTEST', '--columns', 'address', '--output', output], offline=False)
    assert code == 0
    assert sent == [b'[1] DBGETXML //CSVTEST\r\n']
    assert result['projection']['project_path'] == '//CSVTEST'
    assert result['native_database_mutated'] is False
    assert output.read_bytes() == b'Unit Address,\r\n4,\r\n4,\r\n\r\n'


def test_live_project_accepts_one_large_bounded_xml_wire_line(tmp_path):
    xml = project_xml().replace('</Project>', '<!--' + 'x' * 1_100_000 + '--></Project>')
    assert 1024 * 1024 < len(xml.encode()) < MAX_CAPTURE_BYTES
    response = b'[1] 343-Begin XML snippet\r\n[1] 347-' + xml.encode() + b'\r\n[1] 344 End XML snippet\r\n'
    output = tmp_path / 'large.csv'
    with peer([[response]]) as ((host, port), sent):
        code, result = invoke(['cgate', '--host', host, '--port', port, 'database-csv',
            '--project', '//CSVTEST', '--columns', 'address', '--output', output], offline=False)
    assert code == 0, result
    assert sent == [b'[1] DBGETXML //CSVTEST\r\n']
    assert result['report']['unit_count'] == 2
    assert output.read_bytes() == b'Unit Address,\r\n4,\r\n4,\r\n\r\n'


def test_live_project_rejects_aggregate_xml_over_8_mib_before_parse_or_output(tmp_path):
    head, tail = project_xml().split('</Project>', 1)
    parts = (head + '<!--' + 'x' * 3_000_000,
             'x' * 3_000_000,
             'x' * 3_000_000 + '--></Project>' + tail)
    xml = '\n'.join(parts)
    assert MAX_CAPTURE_BYTES < len(xml.encode()) < 16 * 1024 * 1024
    assert max(len(part.encode()) for part in parts) < MAX_CAPTURE_BYTES
    with patch.object(native, '_container', side_effect=AssertionError('Oversize XML was parsed')):
        with pytest.raises(ValueError, match='8 MiB'):
            native.project_native_xml_selection(xml, project_path='//CSVTEST',
                                                columns=('address',))
        with pytest.raises(ValueError, match='8 MiB'):
            native.project_native_xml_unit(xml, '//CSVTEST/254/p/4', columns=('address',))

        response = (b'[1] 343-Begin XML snippet\r\n' +
                    b'[1] 347-' + parts[0].encode() + b'\r\n' +
                    b'[1] ' + parts[1].encode() + b'\r\n' +
                    b'[1] ' + parts[2].encode() + b'\r\n' +
                    b'[1] 344 End XML snippet\r\n')
        output = tmp_path / 'oversize.csv'
        with peer([[response]]) as ((host, port), sent):
            code, receipt = invoke(['cgate', '--host', host, '--port', port,
                'database-csv', '--project', '//CSVTEST', '--columns', 'address',
                '--output', output], offline=False)
    assert code == 1
    assert sent == [b'[1] DBGETXML //CSVTEST\r\n']
    assert '8 MiB' in str(receipt)
    assert not output.exists()


@pytest.mark.parametrize('options', [{'unit': '//CSVTEST/254/p/4'},
    {'network': '//CSVTEST/254'}, {'units': ['//CSVTEST/254/p/4']},
    {'apply_missing_area': True, 'backup_project': 'BACKUP'}, {'backup_project': 'BACKUP'}])
def test_live_project_rejects_conflict_or_mutation_before_connection(options):
    args = dict(area='cgate', action='database-csv', unit=None, units=None, network=None,
        project='//CSVTEST', columns=None, apply_missing_area=False, backup_project=None)
    args.update(options)
    factory = Mock()
    with pytest.raises(ValueError):
        boundary.live(SimpleNamespace(**args), factory, None)
    factory.assert_not_called()
