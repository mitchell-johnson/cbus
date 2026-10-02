"""Exact database identities through the public saved/native report commands.

Complete invented projects use owned loopback Rust processes and a closed CNI
trap. Literal Address/Number references are independent of the report producer.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

import test_cgate_project_documentation_interop as helpers
from test_cgate_barcode_database_interop import cli

VECTOR = Path(__file__).resolve().parents[1] / 'research/fixtures/project-documentor-native-addresses-literal.json'
DATA = json.loads(VECTOR.read_text())


def input_xml(kind,trap):
    root=ET.fromstring(DATA['owned_server_provisioning_profiles']['xml'][kind])
    for row in root.iter():
        if row.tag in {'Project','Network','Application','Group','Level','Unit'} and row.find('OID') is None:
            ET.SubElement(row,'OID').text=str(uuid.uuid4())
    for n in root.find('Project').findall('Network'):
        interface=n.find('Interface')
        if interface is None:interface=ET.SubElement(n,'Interface')
        for tag,value in [('OID',uuid.uuid4()),('InterfaceType','cni'),('InterfaceAddress',trap)]:
            child=interface.find(tag)
            if child is None:child=ET.SubElement(interface,tag)
            child.text=str(value)
    return ET.tostring(root,encoding='utf-8')


def literals(kind,raw,result):
    assert raw.startswith(b'\xef\xbb\xbf<html>\r\n') and raw.endswith(b'</html>\r\n')
    assert b'\n' not in raw.replace(b'\r\n',b'')
    assert b'Network Number: 255</br>\r\n' in raw
    if kind=='thermostat':
        for line in DATA['literal_anchors']:assert line.encode() in raw
        assert ('\r\n'.join(DATA['thermostat_body_lines'])+'\r\n').encode() in raw
        assert b'name="255_202_7_42"' not in raw
        assert result['units']==[{'network':'RoomA','unit':10,'unit_type':'PC_TSB',
                                 'documentor':'TThermostatDocumentor','status':'recovered'}]
    else:
        for lines in DATA['wireless_body_lines'].values():
            assert ('\r\n'.join(lines)+'\r\n').encode() in raw
        assert len(result['units'])==10 and all(x['status']=='recovered' for x in result['units'])
        assert b'Adjacent Network: <a href="#254">Adjacent</a><br/>' in raw
        assert b'Send Messages to Remote Network: <a href="#255">Route 2</a><br/>' in raw
    assert result['networks']==['RoomA'] and result['sha256']==hashlib.sha256(raw).hexdigest()
    assert not result['parity']['original_toolkit_executed']


@pytest.mark.parametrize('kind',['thermostat','wireless'])
@pytest.mark.parametrize('backend,variable',helpers.BACKENDS,ids=('mock','daemon'))
def test_public_native_report_exact_named_identity_and_physical_references(kind,backend,variable,tmp_path):
    with patch.object(helpers,'VECTOR',VECTOR),patch.object(helpers,'synthetic_xml',lambda trap:input_xml(kind,trap)):
        with helpers.journey(backend,variable,tmp_path) as (owner,relay,evidence,_endpoint):
            evidence['format']='cbus-native-document-network-address-owned-v1'
            evidence['provisioning_changed_fields']=DATA['owned_server_provisioning_profiles']['changed_fields'][kind]
            evidence['backend_admission_boundary']=DATA['owned_server_provisioning_profiles']['boundary']
            evidence['missing_number_live_acceptance']=False
            evidence['general_hex_number_live_acceptance']=False
            before=helpers.snapshot(owner)
            evidence['report_source_profile']='actual owned backend exported XML with explicit admitted Numbers'
            for index,(selector,identity) in enumerate([('RoomA','RoomA'),('0254','0254'),('254',254),('0xff','0xff'),('255',255),('256','256'),('CustomA','CustomA'),('Customa','Customa')]):
                # Distinct database identities may differ only by case even
                # when the host output filesystem is case-insensitive.
                output=tmp_path/('network-'+str(index)+'.html')
                result,call=cli(relay,evidence['calls'],'database-document','--project','//DOCREST',
                               '--generated-at',DATA['generated_at'],'--network',selector,'--output',output)
                helpers.read_only(call)
                assert result['networks']==[identity]
                assert result['output_complete'] and not result['native_database_mutated']
                assert not result['network_open_requested'] and not result['physical_programming_loaded']
                assert not result['project_save_requested']
                if selector=='RoomA':literals(kind,output.read_bytes(),result)
                assert helpers.snapshot(owner)==before
            for selector in ['rooma','0xfe']:
                output=tmp_path/(selector+'-absent.html')
                result,call=cli(relay,evidence['calls'],'database-document','--project','//DOCREST',
                               '--network',selector,'--output',output,expected=1)
                helpers.read_only(call)
                assert 'absent' in result['error'] and not output.exists()
                assert helpers.snapshot(owner)==before
            # The exact exported snapshot exercises the public offline path.
            source=tmp_path/'saved-native.xml';source.write_text(before)
            output=tmp_path/'saved-native.html'
            command=[sys.executable,'-m','cbus_toolkit','project','document',str(source),'--native-xml',
                     '--network','RoomA','--generated-at',DATA['generated_at'],'--output',str(output)]
            completed=subprocess.run(command,capture_output=True,text=True,timeout=30)
            assert completed.returncode==0,(completed.stdout,completed.stderr)
            literals(kind,output.read_bytes(),json.loads(completed.stdout))
            assert source.read_text()==before and helpers.snapshot(owner)==before
            evidence['offline_call']={'argv':command,'returncode':completed.returncode,
                                      'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                                      'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
