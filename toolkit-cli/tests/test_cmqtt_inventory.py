"""Fresh network eDLT label inventory, using only synthetic C-Gate replies."""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.cli import build_parser
from cbus_toolkit.cmqtt import edlt_label_inventory
from cbus_toolkit.edlt import configuration_crc


def native(lines, code):
    lines = (lines,) if isinstance(lines, str) else tuple(lines)
    return CGateResponse(lines, lines[-1], code)


def response(value):
    return CGateResponse(('200-' + json.dumps(value), '200 OK.'), '200 OK.', 200)


def observed():
    return {
        'format': 'cmqttd-observed-dynamic-labels-v1',
        'source': 'observed-sal-traffic',
        'complete': False,
        'device_readback': False,
        'reset_on_reconnect': True,
        'capacity': 4096,
        'observations': [],
    }


def identify4(serial):
    first, second = map(int, serial.split('.'))
    packed = (first << 12) | second
    data = bytearray(12)
    data[5:9] = packed.to_bytes(4, 'big')
    return bytes(data)


def memory():
    image = bytearray(9216)
    image[:2] = b'\x05\x01'
    image[16] = 56
    for scene in range(1, 9):
        image[0x2000 + scene * 2:0x2002 + scene * 2] = b'\xff\xff'
    image[0x1000:0x1008] = b'Kitchen\0'
    image[0x1040:0x104a] = b'Goodnight\0'
    image[0x2002:0x2004] = b'\0\0'
    image[0x2012:0x2017] = bytes([2, 1, 255, 0, 1])
    for widget, kind in ((6, 2), (7, 6), (8, 255)):
        start = 0x120 + (widget - 1) * 32
        image[start] = kind
        image[start + 1] = 0x33
    image[0x120 + 5 * 32 + 6] = 27
    image[0x120 + 6 * 32 + 11] = 7
    image[8:10] = configuration_crc(bytes(image[0x1000:0x1fff])).to_bytes(2, 'big')
    return bytes(image)


def labelled(text):
    image = bytearray(memory())
    data = text.encode()
    image[0x1000:0x1040] = data.ljust(64, b'\0')
    image[8:10] = configuration_crc(bytes(image[0x1000:0x1fff])).to_bytes(2, 'big')
    return bytes(image)


class InventoryClient:
    def __init__(self, identities, *, images=None, checks=None, observations=None,
                 physical_serials=None):
        self.identities = dict(identities)
        self.images = dict(images or {})
        self.checks = dict(checks or {address: 'Single unit detected' for address in identities})
        if observations is None:
            observations = observed()
            observations.update(observation_scope='network', recipient_verified=False,
                                requested_address='//TEST/254')
        self.observations = observations
        self.physical_serials = dict(physical_serials or {})
        self.serial_read_positions = {}
        self.calls = []

    def command(self, command):
        self.calls.append(command)
        words = command.split()
        if words[0] == 'GET':
            path, field = words[1:]
            if path == '//TEST/254':
                values = {
                    'InterfaceState': 'running', 'TargetInterfaceState': 'running',
                    'SyncState': 'idle', 'AutoUnravel': 'no', 'AutoUpdate': 'no',
                    'Units': ','.join(map(str, reversed(tuple(self.identities)))),
                }
            else:
                address = int(path.rsplit('/', 1)[1])
                unit_type, firmware, serial = self.identities[address]
                values = {'Address': str(address), 'Type': unit_type, 'Version': firmware,
                          'SerialNumber': serial, 'State': 'ok'}
            line = f'300-{path}: {field}={values[field]}'
            return native(line, 300)
        if words[:2] == ['NET', 'SYNC']:
            return native('200 OK.', 200)
        if words[:2] == ['NET', 'CHECKUNIT']:
            lines = [f'120-{status} at address: {address}'
                     for address, status in sorted(self.checks.items())]
            return native((*lines, '200 OK.'), 200)
        if words[:2] == ['UNIT', 'IDENTIFY']:
            address = int(words[2].rsplit('/', 1)[1])
            attribute = int(words[3])
            unit_type, firmware, serial = self.identities[address]
            if attribute == 4:
                values = self.physical_serials.get(address, serial)
                values = values if isinstance(values, tuple) else (values,)
                position = self.serial_read_positions.get(address, 0)
                self.serial_read_positions[address] = position + 1
                data = identify4(values[min(position, len(values) - 1)])
            else:
                data = (unit_type if attribute == 1 else firmware).encode().ljust(8, b' ')
            return response({'source': 'physical', 'address': words[2], 'attribute': attribute,
                             'data_hex': data.hex()})
        if words[:2] == ['UNIT', 'READMEM']:
            address = int(words[2].rsplit('/', 1)[1])
            start, count = map(int, words[3:])
            image = self.images[address]
            return response({'source': 'physical', 'address': words[2], 'physical_address': start,
                             'data_hex': image[start:start + count].hex()})
        if words[:2] == ['CMQTT', 'LABELS']:
            assert words[2] == '//TEST/254'
            return response(self.observations)
        raise AssertionError(f'Unexpected command: {command}')


def test_network_inventory_refreshes_once_orders_units_and_observes_once():
    identities = {
        16: ('KEYE1', '2.5.00', '100.16'),
        9: ('KEYGL5', '5.5.00', '100.9'),
        5: ('KEYGL5', '05.05.00', '100.5'),
    }
    client = InventoryClient(identities, images={5: labelled('Five'), 9: labelled('Nine')})
    result = edlt_label_inventory(client, '//TEST/254')

    assert result['complete']
    assert result['supported_addresses'] == [5, 9]
    assert [unit['address'] for unit in result['units']] == [
        '//TEST/254/p/5', '//TEST/254/p/9']
    assert [unit['static_strings'][0]['text'] for unit in result['units']] == ['Five', 'Nine']
    assert [unit['physical_serial_evidence']['serial'] for unit in result['units']] == [
        '100.5', '100.9']
    assert all(unit['physical_serial_verified'] for unit in result['units'])
    assert [unit['inventory_identity']['serial'] for unit in result['units']] == ['100.5', '100.9']
    assert [unit['address'] for unit in result['other_units']] == [16]
    assert all('observed_dynamic_labels' not in unit for unit in result['units'])
    assert client.calls.count('NET SYNC //TEST/254 fast') == 1
    assert client.calls.count('NET CHECKUNIT //TEST/254 *') == 1
    assert client.calls.count('CMQTT LABELS //TEST/254') == 1
    assert client.calls.count('UNIT IDENTIFY //TEST/254/p/5 4') == 2
    assert client.calls.count('UNIT IDENTIFY //TEST/254/p/9 4') == 2
    assert not any(call.startswith('CMQTT LABELS //TEST/254/p/') for call in client.calls)
    assert not any(call.startswith('CMQTT UNIT ') for call in client.calls)
    assert not result['network_snapshot_atomic']
    assert not result['device_dynamic_label_cache_readback']
    assert result['observed_dynamic_labels']['observation_scope'] == 'network'
    assert result['observed_dynamic_labels']['recipient_verified'] is False
    assert result['observed_dynamic_labels']['requested_address'] == '//TEST/254'


def test_unsupported_unknown_and_ambiguous_records_make_inventory_incomplete():
    identities = {
        5: ('KEYGL5', '5.5.00', '100.5'),
        7: ('KEYGL5', '5.5.00', '100.7'),
        9: ('KEYGL5', '5.4.00', '100.9'),
        11: ('', '', '100.11'),
        13: ('KEYGL5', '5.5.00', '0.0'),
    }
    checks = {5: 'Single unit detected', 7: 'Duplicate units detected',
              9: 'Single unit detected', 11: 'Single unit detected',
              13: 'Single unit detected'}
    client = InventoryClient(identities, images={5: labelled('Five')}, checks=checks)
    result = edlt_label_inventory(client, '//TEST/254')

    assert not result['complete'] and not result['selection_complete']
    assert result['supported_addresses'] == [5]
    assert [item['address'] for item in result['unsupported']] == [9]
    assert [item['address'] for item in result['unknown']] == [11, 13]
    assert [item['address'] for item in result['ambiguous']] == [7]
    assert client.calls.count('CMQTT LABELS //TEST/254') == 1
    assert not any(call.startswith('UNIT IDENTIFY //TEST/254/p/13') for call in client.calls)


def test_absent_probe_candidate_is_resolved_without_making_selection_incomplete():
    identities = {5: ('KEYGL5', '5.5.00', '100.5')}
    checks = {0: 'No units detected', 5: 'Single unit detected'}
    client = InventoryClient(identities, images={5: labelled('Five')}, checks=checks)

    result = edlt_label_inventory(client, '//TEST/254')

    assert result['complete']
    assert result['selection_complete']
    assert result['inventory_complete']
    assert result['fresh_inventory']['complete']
    assert [item['address'] for item in result['absent']] == [0]
    assert result['unknown'] == []
    assert result['supported_addresses'] == [5]
    assert not any('/p/0' in call for call in client.calls)


def test_read_failure_retains_prior_success_and_network_observations():
    identities = {5: ('KEYGL5', '5.5.00', '100.5'), 6: ('KEYGL5', '5.5.00', '100.6')}
    corrupt = bytearray(labelled('Six'))
    corrupt[0x1000] ^= 1
    client = InventoryClient(identities, images={5: labelled('Five'), 6: bytes(corrupt)})
    result = edlt_label_inventory(client, '//TEST/254')

    assert not result['complete']
    assert [unit['address'] for unit in result['units']] == ['//TEST/254/p/5']
    assert result['read_errors'][0]['address'] == '//TEST/254/p/6'
    assert 'CRC mismatch' in result['read_errors'][0]['error']
    assert result['observed_dynamic_labels']['complete'] is False
    assert client.calls.count('CMQTT LABELS //TEST/254') == 1


@pytest.mark.parametrize(
    ('physical_serials', 'error'),
    [({5: '101.5'}, 'differs from fresh inventory serial'),
     ({5: ('100.5', '101.5')}, 'during the configuration read')],
)
def test_serial_mismatch_never_attaches_stale_inventory_identity(physical_serials, error):
    identities = {
        5: ('KEYGL5', '5.5.00', '100.5'),
        6: ('KEYGL5', '5.5.00', '100.6'),
    }
    client = InventoryClient(identities, images={5: labelled('Five'), 6: labelled('Six')},
                             physical_serials=physical_serials)

    result = edlt_label_inventory(client, '//TEST/254')

    assert not result['complete']
    assert [unit['address'] for unit in result['units']] == ['//TEST/254/p/6']
    assert result['units'][0]['inventory_identity']['serial'] == '100.6'
    assert result['units'][0]['physical_serial_evidence']['serial'] == '100.6'
    assert result['read_errors'][0]['address'] == '//TEST/254/p/5'
    assert error in result['read_errors'][0]['error']
    assert client.calls.count('NET SYNC //TEST/254 fast') == 1
    assert client.calls.count('CMQTT LABELS //TEST/254') == 1


def test_network_inventory_rejects_absent_or_mismatched_observation_request():
    identities = {5: ('KEYGL5', '5.5.00', '100.5')}
    for requested_address in (None, '//TEST/253', '//TEST/254/p/5'):
        observations = observed()
        if requested_address is not None:
            observations.update(observation_scope='network', recipient_verified=False,
                                requested_address=requested_address)
        client = InventoryClient(identities, images={5: labelled('Five')},
                                 observations=observations)

        result = edlt_label_inventory(client, '//TEST/254')

        assert not result['complete']
        assert result['observed_dynamic_labels'] is None
        assert result['observation_error']['address'] == '//TEST/254'
        assert client.calls.count('NET SYNC //TEST/254 fast') == 1
        assert client.calls.count('NET CHECKUNIT //TEST/254 *') == 1
        assert client.calls.count('CMQTT LABELS //TEST/254') == 1


@pytest.mark.parametrize('network', [
    '//TEST/254/p/5', '//TEST/256', '//BAD-NAME/254', '//TOO_LONG9/254',
    '//BAD NAME/254', 'TEST/254',
])
def test_invalid_network_rejects_before_io(network):
    client = Mock()
    with pytest.raises(ValueError):
        edlt_label_inventory(client, network)
    client.command.assert_not_called()


def test_cli_keeps_unit_form_and_adds_explicit_network_form():
    parser = build_parser()
    unit = parser.parse_args(['cgate', 'edlt-labels', '//TEST/254/p/5'])
    assert unit.address == '//TEST/254/p/5' and unit.network is None
    network = parser.parse_args(['cgate', 'edlt-labels', '--network', '//TEST/254'])
    assert network.address is None and network.network == '//TEST/254'
    with pytest.raises(SystemExit):
        parser.parse_args(['cgate', 'edlt-labels'])
    with pytest.raises(SystemExit):
        parser.parse_args(['cgate', 'edlt-labels', '//TEST/254/p/5', '--network', '//TEST/254'])
