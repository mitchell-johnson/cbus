"""Source-established static/language parent histories through owned services."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import uuid
from xml.etree import ElementTree as ET
import pytest
import test_cgate_edlt_parent_add_dialog_interop as parent
from test_cgate_barcode_database_interop import FaultGate, cli, graph
from test_cgate_edlt_scene_add_dialog_interop import snapshot

VECTOR=Path(__file__).resolve().parents[2]/'rust/testdata/vectors/cgate_edlt_static_language_add_wire.json'
FACTS=json.loads(VECTOR.read_text());CASES=FACTS['cases'];BACKENDS=parent.BACKENDS

def tree(text):
    return ET.fromstring(text,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))

def rows(text):
    collection=tree(text).find('Project/Network/Languages')
    return [] if collection is None else [(int(r.findtext('ID')),r.findtext('TagValue') or '',r.findtext('OID')) for r in collection.findall('Language')]

@contextmanager
def journey(backend,variable,tmp_path,case):
    with parent.journey(backend,variable,tmp_path,case) as value:
        owner,relay,evidence,specs,endpoint=value
        evidence.update(format='cbus-edlt-static-language-add-owned-v1',vector_sha256=hashlib.sha256(VECTOR.read_bytes()).hexdigest())
        if not case.get('absent'):
            network_oid=tree(snapshot(owner)).findtext('Project/Network/OID')
            assert owner.command('DBADD !'+network_oid+' Languages').code==301
            for identifier,name in [(0,'0' if case.get('zero_default') else '8'),(1,'custom English'),(8,'custom NZ')]:
                response=owner.command('DBADD !'+network_oid+'/Languages Language');assert response.code==301
                identity=re.fullmatch('OID=([0-9a-fA-F-]{36})',response.final.removeprefix('301 '))[1]
                assert owner.command(f'DBSET !{identity}/ID {identifier}').code==200
                assert owner.command(f'DBSET !{identity}/TagValue {name}').code==200
        if case.get('lexical_ids'):
            document=tree(snapshot(owner));network=document.find('Project/Network')
            collection=network.find('Languages');collection.findall('Language')[1].find('ID').text='+001'
            for identifier,name in [('0001','second English'),('-0001','unknown')]:
                row=ET.SubElement(collection,'Language')
                for field,value in [('OID',str(uuid.uuid4())),('ID',identifier),('TagValue',name)]:
                    ET.SubElement(row,field).text=value
            assert owner.command_document('DBSETXML //TEST/254',ET.tostring(network,encoding='unicode')).code==301
        assert owner.command('PROJECT SAVE TEST').code==200
        before=snapshot(owner);evidence['snapshots']={'before':before}
        yield owner,relay,evidence,specs,endpoint,before
    (tmp_path/'parent-add-evidence.json').rename(tmp_path/'static-language-add-evidence.json')

def invoke(relay,evidence,specs,tmp_path,case,*,dry_run=False,expected=0,complete=True,connections=1):
    operations=tmp_path/'operations.json';operations.write_text(json.dumps([*case['ops'],parent.widget()]))
    preferences=tmp_path/'preferences.json';preferences.write_text(json.dumps({
        'format':'cbus-edlt-display-preferences-v1','registry_key_present':True,'values':{}}))
    argv=['unit','--lock-address','//TEST/254',
          '--source','/db//TEST/254/p/20']
    if dry_run:argv.append('--dry-run')
    argv.extend(['edlt-parent-transaction','--spec-dir',str(specs),'--auto-metadata',
                 '--exclusive-project','--operations',str(operations),'--display-preferences',str(preferences)])
    if not dry_run:argv.extend(['--backup-project','PABACKUP'])
    return cli(relay,evidence['calls'],*argv,expected=expected,complete=complete,
               connections=connections,process_timeout=90)


def inspect(before,after,case,call):
    old,new=tree(before),tree(after);actual=rows(after)
    assert [r[0] for r in actual]==case['ids'];assert [r[1] for r in actual]==case['names']
    original={identity:(i,name) for i,name,identity in rows(before)}
    for identifier,name,identity in actual:
        if identity in original:
            assert identifier==original[identity][0]
            if identifier:assert name==original[identity][1]
        else:assert str(uuid.UUID(identity))==identity and identity not in before
    assert len({r[2] for r in actual})==len(actual)
    commands=call['commands'];additions=[i for i,c in enumerate(commands) if c.startswith('DBADD !')]
    assert len(additions)==case['created'];assert sum(c.startswith('DBDELETE !') for c in commands)==case['deleted']
    for index in additions:
        assert call['statuses'][index]==301
        identity=re.fullmatch('OID=([0-9a-fA-F-]{36})',call['terminals'][index])[1]
        assert str(uuid.UUID(identity))==identity and identity not in before
        assert f'DBGET !{identity}/OID' in commands
    for index,c in enumerate(commands):
        if c.startswith(('DBSET !','DBDELETE !')):assert call['statuses'][index]==200
    if case.get('lexical_ids'):
        before_rows=tree(before).findall('Project/Network/Languages/Language')
        after_rows=tree(after).findall('Project/Network/Languages/Language')
        alias_oids={r.findtext('OID'):r.findtext('ID') for r in before_rows
                    if r.findtext('ID') in ('+001','0001')}
        for identity,spelling in alias_oids.items():
            assert next(r for r in after_rows if r.findtext('OID')==identity).findtext('ID')==spelling
            assert not any(c.startswith('DBSET !'+identity+'/') for c in commands)
    assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands)==1
    assert commands.count('PROJECT SAVE TEST')==2;assert commands.count('PROJECT COPY TEST PABACKUP')==1
    assert commands.count('PROJECT CLOSE TEST')==1;assert commands.count('PROJECT LOAD TEST')==1
    pp,baseline=parent.values(new),parent.values(old)
    for index,prefix in case['static'].items():assert bytes(pp['StaticTextString'+index])==bytes.fromhex(prefix).ljust(64,b'\0')
    for name,expected in case['pp'].items():assert pp[name]==expected
    assert (pp['Widget6WidgetType'],pp['Widget6WidgetByteValue1'],pp['Widget6WidgetByteValue2'])==([12],[42],[1])
    allowed={'OverallCRC','GlobalParameterCRC','WidgetsCRC','StaticTextCRC','WidgetGroups','SceneBucket','ScenesCheckSum'}|set(case['pp'])
    allowed.update('StaticTextString'+index for index in case['static'])
    allowed.update(['Widget6WidgetType',*[f'Widget6WidgetByteValue{i}' for i in range(1,14)]])
    if any(op['op']=='lighting' for op in case['ops']):
        assert pp['Widget8WidgetType']==[255]
        allowed.update(['Widget8WidgetType','Widget7WidgetType',*[f'Widget7WidgetByteValue{i}' for i in range(1,14)]])
    if case.get('levels'):allowed.update(f'Scene{i}StartAddress' for i in range(1,9))
    changed={name for name in pp if pp[name]!=baseline[name]};assert changed<=allowed,changed-allowed
    network,old_network=new.find('Project/Network'),old.find('Project/Network')
    for group,address,name in case.get('levels',[]):
        parent_node=network.find(f"Application[Address='202']/Group[Address='{group}']");node=parent_node.find(f"Level[Address='{address}']")
        assert node is not None and node.findtext('TagName')==name and node.get('Value')==str(address)
        assert node.findtext('OID') not in before;parent_node.remove(node)
    new_collection,old_collection=network.find('Languages'),old_network.find('Languages')
    if old_collection is None:network.remove(new_collection)
    else:
        assert new_collection.findtext('OID')==old_collection.findtext('OID')
        index=list(network).index(new_collection);network.remove(new_collection);network.insert(index,deepcopy(old_collection))
    for node in network.find("Unit[Address='20']").findall('PP'):
        if node.get('Name') in allowed:node.set('Value',old_network.find("Unit[Address='20']/PP[@Name='"+node.get('Name')+"']").get('Value'))
    assert graph(ET.tostring(new,encoding='unicode'))==graph(before)

@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_public_static_language_parent_complete_history(backend,variable,case,tmp_path):
    with journey(backend,variable,tmp_path,case) as (owner,relay,evidence,specs,_endpoint,before):
        _preview,call=invoke(relay,evidence,specs,tmp_path,case,dry_run=True)
        assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT COPY','PROJECT SAVE','PP SAVE')) for c in call['commands'])
        assert snapshot(owner)==before
        final,call=invoke(relay,evidence,specs,tmp_path,case)
        assert final['saved'] and final['target_project_save_confirmed'] and final['persistence_verified']
        after=snapshot(owner);inspect(before,after,case,call)
        for command in ('PROJECT SAVE TEST','PROJECT CLOSE TEST','PROJECT LOAD TEST'):assert owner.command(command).code==200
        assert graph(snapshot(owner))==graph(after);evidence['snapshots']['after']=after

@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
@pytest.mark.parametrize('stage',FACTS['lost_stages'],ids=lambda s:s['id'])
def test_public_static_language_lost_success_stops_without_replay(backend,variable,stage,tmp_path):
    with journey(backend,variable,tmp_path,CASES[0]) as (owner,_relay,evidence,specs,endpoint,before):
        with FaultGate(endpoint,stage['prefix'],'drop') as fault:
            _result,call=invoke(fault,evidence,specs,tmp_path,CASES[0],expected=1,complete=False)
            assert fault.matches==1;wire=[r for r in fault.evidence() if r.get('fault')];assert len(wire)==1
            retained=bytes.fromhex(wire[0]['lost_backend_terminal_hex']).decode()
            assert retained.startswith('['+wire[0]['fault']['tag']+'] '+str(stage['status'])+' ')
            selected=wire[0]['fault']['command'];assert call['commands'].count(selected)==1
            index=call['commands'].index(selected);assert call['statuses'][index] is None
            assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT SAVE','PP SAVE')) for c in call['commands'][index+1:])
            evidence['lost_success_wires']=fault.evidence();evidence['snapshots']['after_unknown']=snapshot(owner)

@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
def test_public_static_language_invalid_history_never_writes(backend,variable,tmp_path):
    with journey(backend,variable,tmp_path,CASES[0]) as (owner,relay,evidence,specs,_endpoint,before):
        invalid=[{'op':'add-language-dialog','preferences':'registered-defaults','selected_ids':[8]},
                 {'op':'add-language-dialog','preferences':'registered-defaults','selected_ids':[0,1]},
                 {'op':'add-language-dialog','selected_ids':[1,8]},
                 {'op':'static-text-dialog','edits':[{'index':64,'text':'bad'}]},
                 {'op':'static-text-dialog','edits':[{'index':0,'text':'bad'}],'cancel':True}]
        for number,operation in enumerate(invalid):
            # English locking consumes the loaded cache; malformed schemas
            # now refuse in the public CLI preflight without opening TCP.
            _result,call=invoke(relay,evidence,specs,tmp_path,{'ops':[operation]},
                dry_run=True,expected=1,connections=1 if number==0 else 0)
            assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT COPY','PROJECT SAVE','PP SAVE')) for c in call['commands'])
            assert snapshot(owner)==before

@pytest.mark.parametrize('auth',('missing','wrong'))
def test_public_static_language_authentication_stops_before_write(auth,tmp_path,monkeypatch):
    token='owned-static-language-token-0123456789abcdef';path=tmp_path/'owned-auth.token';path.write_text(token+'\n');path.chmod(0o600)
    original_backend,original_provision=parent.owned_backend,parent.provision
    @contextmanager
    def authenticated_backend(*args,**kwargs):
        with original_backend(*args,auth_file=path,**kwargs) as result:yield result
    def authenticated_provision(owner,*args,**kwargs):
        assert owner.command('LOGIN '+token).code==200
        return original_provision(owner,*args,**kwargs)
    monkeypatch.setattr(parent,'owned_backend',authenticated_backend);monkeypatch.setattr(parent,'provision',authenticated_provision)
    with journey('cmqttd','CBUS_CMQTTD_BIN',tmp_path,CASES[0]) as (owner,relay,evidence,specs,_endpoint,before):
        if auth=='missing':_result,call=invoke(relay,evidence,specs,tmp_path,CASES[0],expected=1)
        else:_result,call=cli(relay,evidence['calls'],'exec','LOGIN wrong-owned-token',expected=1)
        assert 420 in call['statuses']
        assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT COPY','PP SAVE')) for c in call['commands'])
        for index,command in enumerate(call['commands']):
            if command.startswith('PROJECT SAVE'):
                assert call['statuses'][index]==420
                assert not call['commands'][index+1:]
        assert snapshot(owner)==before;assert token not in json.dumps(evidence['calls'])
