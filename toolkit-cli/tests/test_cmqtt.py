"""Physical label reader contracts, using synthetic memory, never site files."""
import json
from unittest.mock import Mock
import pytest
from cbus_toolkit.cmqtt import decode_edlt_labels, edlt_labels, read_memory
from cbus_toolkit.edlt import configuration_crc
from cbus_toolkit.cgate import CGateResponse


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


@pytest.mark.parametrize('position,value',[(0,3),(0x1000,88),(0x2002,254)])
def test_rejects_incompatible_corrupt_or_malformed_memory(position,value):
    image = bytearray(memory()); image[position]=value
    with pytest.raises(ValueError): decode_edlt_labels(bytes(image))


def test_reads_via_cgate_only_and_checks_live_identity_and_stability():
    client = Mock(); image = memory(); address='//TEST/254/p/5'; calls=[]
    def command(text):
        calls.append(text); words=text.split()
        if words[:2] == ['CMQTT','UNIT']: return response({'name':'Fixture'})
        if words[:2] == ['UNIT','IDENTIFY']:
            attribute=int(words[3]); data=b'KEYGL5  ' if attribute==1 else b'05.05.00'
            return response(dict(source='physical',address=address,attribute=attribute,data_hex=data.hex()))
        assert words[:2] == ['UNIT','READMEM']
        start,count=map(int,words[3:]); return response(dict(source='physical',address=address,physical_address=start,data_hex=image[start:start+count].hex()))
    client.command.side_effect=command
    result=edlt_labels(client,address)
    assert result['source']=='physical-via-cmqttd'
    assert result['widgets'][1]['label']=='Goodnight'
    assert calls[-1]==f'UNIT READMEM {address} 0 16'
    assert not any('WRITE' in call for call in calls)


@pytest.mark.parametrize('value',[{'source':'database'},{'source':'physical','address':'//OTHER/254/p/5'},{'source':'physical','address':'//TEST/254/p/5','physical_address':0,'data_hex':'aa'}])
def test_rejects_wrong_source_address_and_short_reads(value):
    client=Mock(); client.command.return_value=response(value)
    with pytest.raises(ValueError): read_memory(client,'//TEST/254/p/5',0,16)


def test_rejects_command_injection_before_io():
    client=Mock()
    with pytest.raises(ValueError): edlt_labels(client,'//TEST/254/p/5\nON //TEST/254/56/1')
    client.command.assert_not_called()
