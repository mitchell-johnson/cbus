"""Physical label reader contracts, using synthetic memory, never site files."""
import json
from unittest.mock import Mock
import pytest
from cbus_toolkit.cmqtt import decode_edlt_labels, decode_observed_labels, edlt_labels, read_memory
from cbus_toolkit.edlt import configuration_crc
from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.labels import encode_dynamic_icon, encode_label, encode_unicode_label


def memory():
    image = bytearray(9216)
    image[:2] = b'\x05\x01'
    image[16] = 56
    for i in range(1, 9):
        image[0x2000+i*2:0x2002+i*2] = b'\xff\xff'
    image[0x1000:0x1008] = b'Kitchen\0'
    image[0x1040:0x104a] = b'Goodnight\0'
    image[0x2002:0x2004] = b'\0\0'
    image[0x2012:0x2017] = bytes([2,1,255,0,1])
    for widget,kind in ((6,2),(7,6),(8,255)):
        start = 0x120 + (widget-1)*32
        image[start] = kind
        image[start+1] = 0x33
    image[0x120+5*32+6] = 27
    # Scene selector is byte 6, not byte 11.
    image[0x120+6*32+11] = 7
    image[8:10] = configuration_crc(bytes(image[0x1000:0x1fff])).to_bytes(2,'big')
    return bytes(image)


def response(value):
    return CGateResponse(('200-'+json.dumps(value),'200 OK'),'200 OK',200)


def observed(*payloads):
    return {'format': 'cmqttd-observed-dynamic-labels-v1', 'source': 'observed-sal-traffic',
            'complete': False, 'device_readback': False, 'reset_on_reconnect': True,
            'capacity': 4096, 'observations': [
                {'sequence': sequence, 'direction': 'sent-confirmed', 'source_unit': None,
                 'application': application, 'payload_hex': payload.hex()}
                for sequence, (application, payload) in enumerate(payloads)]}


def test_decodes_scene_selector_and_all_64_strings():
    result = decode_edlt_labels(memory())
    assert [w['label'] for w in result['widgets']] == ['Kitchen','Goodnight']
    assert result['widgets'][0]['group'] == 27
    assert result['widgets'][1]['scene'] == 1
    assert len(result['static_strings']) == 64
    assert result['static_text_crc_verified']
    assert not result['dynamic_labels_verified']


def test_toolkit_crc_ignores_old_bytes_after_shortened_string_terminator():
    image = bytearray(memory())
    image[0x1000 + 20] = ord('x')  # stale physical tail, after Kitchen\0
    result = decode_edlt_labels(bytes(image))
    assert result['widgets'][0]['label'] == 'Kitchen'
    assert result['static_text_crc_verified']
    assert not result['raw_static_text_crc_verified']
    assert result['static_text_crc_method'] == 'toolkit-zero-padded-strings'


def test_assembles_observed_standard_unicode_icons_and_language_without_claiming_readback():
    packets = [(56, encode_label(1, 0, 0, b'Lounge', variant=2))]
    packets.extend((202, payload) for payload in encode_unicode_label(8, 2, '東京'.encode(), variant=1, sequence=14))
    packets.append((203, encode_label(9, 0, 2, b'\x01\x01\x02', action_selector=0)))
    packets.extend((56, payload) for payload in encode_dynamic_icon(3, 7, 65535, 8, 7,
                   b'\x01\x02\x04\x08\x10\x20\x40', vertical_offset=2))
    packets.append((56, encode_label(1, 3, 6, b'')))
    result = decode_observed_labels(observed(*packets))
    assert not result['complete'] and not result['device_readback']
    assert result['observation_count'] == len(packets)
    assert result['incomplete_transactions'] == 0
    assert not result['errors']
    by_kind = {item['kind']: item for item in result['entries']}
    assert by_kind['standard']['text'] == 'Lounge'
    assert by_kind['standard']['variant'] == 2
    assert by_kind['unicode-text']['text'] == '東京'
    assert by_kind['built-in-icon']['icon'] == 258
    assert by_kind['built-in-icon']['action_selector'] == 0
    assert by_kind['dynamic-icon']['icon'] == 65535
    assert by_kind['dynamic-icon']['data_hex'] == '01020408102040'
    assert result['language_selections'][0]['language'] == 3


def test_observed_cache_retains_incomplete_and_rejects_unsafe_provenance():
    first = encode_unicode_label(8, 2, b'a' * 20, sequence=4)[0]
    result = decode_observed_labels(observed((202, first)))
    assert result['incomplete_transactions'] == 1
    assert not result['entries']
    bad = observed((56, encode_label(1, 0, 0, b'X'))); bad['complete'] = True
    with pytest.raises(ValueError): decode_observed_labels(bad)


@pytest.mark.parametrize('position,value',[(0,3),(0x1000,88),(0x2002,254)])
def test_rejects_incompatible_corrupt_or_malformed_memory(position,value):
    image = bytearray(memory()); image[position]=value
    with pytest.raises(ValueError): decode_edlt_labels(bytes(image))


def test_reads_via_cgate_only_and_checks_live_identity_and_stability():
    client = Mock(); image = memory(); address='//TEST/254/p/5'; calls=[]
    def command(text):
        calls.append(text); words=text.split()
        if words[:2] == ['CMQTT','UNIT']: return response({'name':'Fixture'})
        if words[:2] == ['CMQTT','LABELS']: return response(observed())
        if words[:2] == ['UNIT','IDENTIFY']:
            attribute=int(words[3]); data=b'KEYGL5  ' if attribute==1 else b'05.05.00'
            return response(dict(source='physical',address=address,attribute=attribute,data_hex=data.hex()))
        assert words[:2] == ['UNIT','READMEM']
        start,count=map(int,words[3:]); return response(dict(source='physical',address=address,physical_address=start,data_hex=image[start:start+count].hex()))
    client.command.side_effect=command
    result=edlt_labels(client,address)
    assert result['source']=='physical-via-cmqttd'
    assert result['widgets'][1]['label']=='Goodnight'
    assert calls[-2]==f'UNIT READMEM {address} 0 16'
    assert calls[-1]==f'CMQTT LABELS {address}'
    assert not result['dynamic_labels_observed']
    assert not result['observed_dynamic_labels']['complete']
    assert not any('WRITE' in call for call in calls)


@pytest.mark.parametrize('value',[{'source':'database'},{'source':'physical','address':'//OTHER/254/p/5'},{'source':'physical','address':'//TEST/254/p/5','physical_address':0,'data_hex':'aa'}])
def test_rejects_wrong_source_address_and_short_reads(value):
    client=Mock(); client.command.return_value=response(value)
    with pytest.raises(ValueError): read_memory(client,'//TEST/254/p/5',0,16)


def test_rejects_command_injection_before_io():
    client=Mock()
    with pytest.raises(ValueError): edlt_labels(client,'//TEST/254/p/5\nON //TEST/254/56/1')
    client.command.assert_not_called()
