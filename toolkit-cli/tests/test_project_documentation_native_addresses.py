"""Literal catalogue identities, explicit physical references and exact selection."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit.project import ProjectError
from cbus_toolkit.project_documentation_native import (
    build_native_model, native_network_address, native_network_number, native_network_report_address,
)
from cbus_toolkit.project_documentation_thermostat import thermostat_data, thermostat_lines
from cbus_toolkit.project_documentation_wireless import _gateway_lines

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'research/fixtures/project-documentor-native-addresses-literal.json'
DATA = json.loads(VECTOR.read_text())


def parsed(kind='thermostat', edit=None):
    root = ET.fromstring(DATA['snapshots'][kind])
    if edit:
        edit(root.find('Project'))
    raw = ET.tostring(root)
    return build_native_model(raw), raw


@pytest.mark.parametrize('value,expected', [
    ('0',0), ('254',254), ('255',255), ('0254','0254'), ('256','256'),
    ('0xff','0xff'), ('CustomA','CustomA'), ('Customa','Customa'),
    ('Room_A-1.2','Room_A-1.2'), ('Named network','Named network'), ('日本語','日本語'),
])
def test_exact_database_address_lexemes(value, expected):
    assert native_network_address(value) == expected
    assert type(native_network_address(value)) is type(expected)


@pytest.mark.parametrize('value,expected', [
    ('NA',0),('na',255),('0254',254),('256',256),('CustomA',255),
    ('0xff',255),('xFE',254),('$100',256),('+254',254),('   000254',254),
    ('254 ',255),('2147483647',2147483647),('-2147483648',-2147483648),
    ('2147483648',255),('-2147483649',255),('$FFFFFFFF',-1),
    ('-$FFFFFFFF',1),('$80000000',-2147483648),('0x100000000',255),
    ('0'*10000+'254',254),('$'+'0'*10000+'FFFFFFFF',-1),
])
def test_source_address_integer_projection_is_separate_from_exact_identity(value,expected):
    assert native_network_report_address(value)==expected
    assert native_network_address(value)==(254 if value=='254' else value)


@pytest.mark.parametrize('value', ['', 'bad/path', 'bad\nname', 'bad\x00name', True, None])
def test_invalid_database_address_components_refuse(value):
    with pytest.raises(ProjectError):
        native_network_address(value)


@pytest.mark.parametrize('selector',['bad/path','bad\nname',True,256])
def test_native_manager_invalid_direct_selector_refuses_before_any_connection(selector,tmp_path):
    from cbus_toolkit.native_project_documentation import live
    def no_connection(*args,**kwargs):raise AssertionError('Unexpected connection')
    args=SimpleNamespace(project='//DOCREST',host='127.0.0.1',port=None,timeout=15,
                         network=selector,output=tmp_path/'never.html',generated_at=None,catalog=None)
    with pytest.raises((ValueError,ProjectError)):
        live(args,no_connection,None)
    assert not args.output.exists()


@pytest.mark.parametrize('value,expected', [('0',0),('253',253),('255',255),('0xff',255),('0XFE',254),('0x2A',42)])
def test_explicit_number_decimal_and_captured_hex_profiles(value, expected):
    assert native_network_number(value) == expected


@pytest.mark.parametrize('value', ['', '0254', '256', '-1', 'oops', '0x100'])
def test_unproved_raw_number_states_refuse_without_default(value):
    with pytest.raises(ProjectError):
        native_network_number(value)


def test_retained_original_materialization_preserves_all_named_and_lexical_identities():
    fixture = ROOT.parent / 'rust/testdata/fixtures/native_cgate_net_save_db_materialization.json'
    receipt = json.loads(fixture.read_text())
    row = next(x for x in receipt['commands'] if x['label']=='project-save1')
    raw = '\n'.join(x.split('347-',1)[1] for x in row['response'] if '347-' in x).encode()
    model = build_native_model(raw)
    addresses = {str(n.identity): n for n in model.networks}
    for address in ['42','0254','254','256','255','0xff','CustomA','Customa','Duplicates']:
        assert str(addresses[address].identity)==address
        assert addresses[address].address=={'42':42,'0254':254,'254':254,'256':256}.get(address,255)
        assert addresses[address].network_number == (254 if address=='254' else 255)
    assert addresses['0254'] is not addresses['254']
    assert addresses['CustomA'] is not addresses['Customa']
    assert model.digest==hashlib.sha256(raw).hexdigest()


def test_number_absence_and_unconsumed_duplicates_remain_independent():
    model,_ = parsed()
    assert model.by_address['Unknown'].network_number is None
    assert model.by_address['0xff'].network_number == model.by_address[255].network_number ==255
    assert (model.by_address['RoomA'].identity,model.by_address['RoomA'].address,model.by_address['RoomA'].network_number)==('RoomA',255,7)
    assert (model.by_address['0254'].identity,model.by_address['0254'].address,model.by_address['0254'].network_number)==('0254',254,42)
    original = deepcopy(model)
    local=model.by_address['RoomA'];u=local.units[0]
    assert thermostat_lines(local,thermostat_data(u),model=model)==DATA['thermostat_body_lines']
    assert model==original


def test_render_literal_anchors_action_identity_and_exact_header_address():
    model,raw=parsed();text,result=doc.render(model,generated=datetime(2026,10,3,12),networks=['RoomA'])
    for line in DATA['literal_anchors']:
        assert line in text
    group=model.by_address['RoomA'].applications[0].groups[0]
    assert (group.levels[0].address,group.levels[0].value)==(3,42)
    assert 'name="255_202_7_42"' not in text
    assert 'Network Number: 7</br>' not in text
    assert result['networks']==['RoomA']
    assert result['units']==[{'network':'RoomA','unit':10,'unit_type':'PC_TSB',
                             'documentor':'TThermostatDocumentor','status':'recovered'}]
    assert model.digest==hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('selector,identity', [('RoomA','RoomA'),('0254','0254'),('254',254),('0xff','0xff'),('255',255),(254,254)])
def test_native_selector_uses_exact_identity_not_physical_number(selector,identity):
    model,_=parsed()
    assert doc.resolve_report_network_selector(model,selector)==identity


@pytest.mark.parametrize('selector',['rooma','0xfe','7','0x2a','CUSTOMA'])
def test_absent_exact_selector_does_not_create_alias(selector):
    model,_=parsed()
    with pytest.raises(ProjectError,match='absent'):
        doc.resolve_report_network_selector(model,selector)


@pytest.mark.parametrize('failure',['duplicate-target','missing-target-number'])
def test_consumed_thermostat_number_refuses_ambiguous_or_unproved_resolution(failure):
    def edit(project):
        target=next(n for n in project.findall('Network') if n.findtext('Address')=='0254')
        if failure=='duplicate-target':
            other=next(n for n in project.findall('Network') if n.findtext('Address')=='42')
            other.find('NetworkNumber').text='42'
        else:
            target.remove(target.find('NetworkNumber'))
    model,_=parsed(edit=edit);local=model.by_address['RoomA'];u=local.units[0]
    with pytest.raises(ValueError,match='NetworkNumber'):
        thermostat_lines(local,thermostat_data(u),model=model)
    text,result=doc.render(model,generated=datetime(2026,10,3,12),networks=['RoomA'])
    assert result['units'][0]['status']=='partial'
    assert 'Master Unit: <a href="#42_unit_10"' not in text


def test_gateway_uses_numbers_and_source_numeric_anchors_despite_unrelated_unknowns():
    model,_=parsed('wireless');local=model.by_address['RoomA']
    gateway=next(u for u in local.units if u.unit_type=='WGATE5N')
    assert _gateway_lines(local,gateway,model.networks)==DATA['wireless_body_lines']['2']
    text,result=doc.render(model,generated=datetime(2026,10,3,12),networks=['RoomA'])
    for key,lines in DATA['wireless_body_lines'].items():
        assert '\r\n'.join(lines)+'\r\n' in text
    assert all(x['status']=='recovered' for x in result['units'])
    assert 'Adjacent Network: <a href="#2">Misleading address' not in text


@pytest.mark.parametrize('failure',['duplicate-adjacent','duplicate-route','missing-adjacent'])
def test_gateway_refuses_only_consumed_ambiguous_or_unproved_numbers(failure):
    def edit(project):
        if failure=='missing-adjacent':
            target=next(n for n in project.findall('Network') if n.findtext('Address')=='0254')
            target.remove(target.find('NetworkNumber'))
        else:
            other=next(n for n in project.findall('Network') if n.findtext('Address')=='2')
            other.find('NetworkNumber').text='2' if failure=='duplicate-adjacent' else '4'
    model,_=parsed('wireless',edit);local=model.by_address['RoomA']
    u=next(u for u in local.units if u.unit_type=='WGATE5N')
    with pytest.raises(ValueError,match='NetworkNumber'):
        _gateway_lines(local,u,model.networks)


def test_native_duplicate_scalar_and_exact_address_collisions_still_refuse():
    raw=DATA['snapshots']['thermostat']
    for changed in [raw.replace('<Address>RoomA</Address>','<Address>RoomA</Address><Address>RoomA</Address>',1),
                    raw.replace('<Address>0254</Address>','<Address>RoomA</Address>',1),
                    raw.replace('<NetworkNumber>7</NetworkNumber>','<NetworkNumber>7</NetworkNumber><NetworkNumber>7</NetworkNumber>',1)]:
        with pytest.raises(ProjectError):build_native_model(changed.encode())


def test_current_static_receipt_pins_independent_identities_and_numeric_source_accessors():
    proof=json.loads((ROOT/'research/fixtures/project-documentor-native-addresses-static.json').read_text())
    assert proof['format']=='cbus-documentor-native-address-source-v1'
    assert proof['original_executed'] is False
    assert len(proof['checks'])==22 and all(proof['checks'].values())
    assert len(proof['method_spans'])==12
    assert proof['literal_disclosure']=={'compiler_coordinate_literals_omitted':0,'original_instruction_bytes_embedded':False}
    for name,value in proof['supporting_module_sha256'].items():
        assert hashlib.sha256((ROOT/'src/cbus_toolkit'/name).read_bytes()).hexdigest()==value
    assert proof['extractor_sha256']==hashlib.sha256((ROOT/'research/project_documentor_native_addresses_static.py').read_bytes()).hexdigest()
    evidence=proof['native_address_evidence']
    assert evidence['retained_execution_only'] is True
    assert hashlib.sha256((ROOT.parent/evidence['path']).read_bytes()).hexdigest()==evidence['sha256']


@pytest.mark.skipif(not os.environ.get('CBUS_TOOLKIT_EXE'),reason='Supply explicit pinned EXE/MAP for read-only static regeneration; no original instructions run')
def test_optional_explicit_pinned_static_extraction_matches_current_receipt():
    from research.project_documentor_native_addresses_static import inspect
    exe=Path(os.environ['CBUS_TOOLKIT_EXE'])
    proof=json.loads((ROOT/'research/fixtures/project-documentor-native-addresses-static.json').read_text())
    assert inspect(exe,Path(os.environ.get('CBUS_TOOLKIT_MAP',exe.with_suffix('.map'))))==proof
