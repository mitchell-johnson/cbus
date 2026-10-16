"""Ordered parent Add histories through public CLI and owned Rust services."""
from contextlib import contextmanager
import hashlib
import json
import sys
import uuid
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.edlt import _render
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from cbus_toolkit.file_transfer import prepare_upload, upload
from test_cgate_barcode_database_interop import FaultGate, cli, graph, selected_binary
from test_cgate_named_database_interop import (
    RecordedGate, associated_evidence, associated_work, no_contact_trap, owned_backend,
)
from test_cgate_edlt_scene_add_dialog_interop import snapshot
from test_edlt_parent_add_dialog import NamedClient, widget, oid
from test_edlt_parent_cache_panels import fixture

BACKENDS = [('cgate-mock', 'CBUS_CGATE_MOCK_BIN'), ('cmqttd', 'CBUS_CMQTTD_BIN')]
CASES = [
    {'id': 'corridor-and-activation', 'ops': [
        {'op':'add-corridor-dialog','field':'link_group','name':'Link'},
        {'op':'add-corridor-dialog','field':'office_group','name':'Office'},
        {'op':'add-corridor-dialog','field':'corridor_group','name':'Corridor'},
        {'op':'add-activation-group-dialog','name':'New trigger'},
        {'op':'add-activation-action-dialog','name':'First action'},
        {'op':'add-activation-action-dialog','name':'Second action'}],
     'groups': [(56,1,'Link'),(56,3,'Office'),(56,4,'Corridor'),(202,0,'New trigger')],
     'levels': [(0,0,'First action'),(0,1,'Second action')],
     'pp': {'CorridorLinkingLinkGroup':[1], 'CorridorLinkingOfficeGroup':[3],
            'CorridorLinkingCorridorGroup':[4], 'ProximityGroup':[0], 'ProximityLevel':[1]}},
    {'id':'cancel-repeat', 'ops': [
        {'op':'add-corridor-dialog','field':'link_group','cancel':True},
        {'op':'add-corridor-dialog','field':'link_group','name':'First'},
        {'op':'add-corridor-dialog','field':'link_group','name':'Second'},
        {'op':'add-activation-action-dialog','cancel':True}],
     'groups': [(56,1,'First'),(56,3,'Second')], 'levels':[],
     'pp': {'CorridorLinkingLinkGroup':[3], 'ProximityGroup':[7], 'ProximityLevel':[0]}},
    {'id':'preceding-enable', 'disabled':True, 'ops': [
        {'op':'activation','wake_mode':'trigger-event','group':7},
        {'op':'add-activation-action-dialog','name':'Enabled action'}],
     'groups':[], 'levels':[(7,1,'Enabled action')],
     'pp':{'ProximityMode':[3], 'ProximityGroup':[7], 'ProximityLevel':[1]}},
    {'id':'scene-interleave', 'ops': [
        {'op':'add-activation-group-dialog','name':'Parent group'},
        {'op':'add-activation-action-dialog','name':'Parent action'},
        {'op':'scene-manager','operations':[
            {'op':'set-trigger','scene':1,'group':0},
            {'op':'add-action-dialog','scene':1,'name':'Scene action'}]},
        {'op':'add-activation-action-dialog','name':'Later parent action'}],
     'groups':[(202,0,'Parent group')],
     'levels':[(0,0,'Parent action'),(0,1,'Scene action'),(0,2,'Later parent action')],
     'pp':{'ProximityGroup':[0], 'ProximityLevel':[2]}},
]

CASES.extend([
    {'id':'initial-scene-getter','initial_scene':True,'ops':[
        {'op':'add-activation-action-dialog','name':'After initial getter'}],
     'groups':[], 'levels':[(7,1,'Action Selector 1'),(7,3,'After initial getter')],
     'pp':{'ProximityLevel':[3],'SceneCount':[8]}},
    {'id':'corridor-future-absence','missing_office':True,'ops':[
        {'op':'add-corridor-dialog','field':'link_group','address':99,'name':'Fresh link'}],
     'groups':[(56,99,'Fresh link')], 'levels':[],
     'pp':{'CorridorLinkingLinkGroup':[99],'CorridorLinkingOfficeGroup':[255]}},
    {'id':'application-switch-future-absence','application_switch':True,'ops':[
        {'op':'applications','edits':[{'field':'secondary','address':255},{'field':'primary','address':57}]},
        {'op':'add-corridor-dialog','field':'link_group','address':1,'name':'New link'},
        {'op':'add-dialog','field':'QuickStatusGroup','address':99,'name':'Future status'}],
     'groups':[(57,1,'New link'),(57,99,'Future status')], 'levels':[],
     'pp':{'PrimaryApplication':[57],'SecondaryApplication':[255],'Application':[57,255],
           'CorridorLinkingLinkGroup':[1],'CorridorLinkingOfficeGroup':[255],'QuickStatusGroup':[99]}}

])


def provision(owner, work, trap, spec, *, disabled=False, initial_scene=False, missing_office=False, application_switch=False):
    model=NamedClient(spec)
    model.values.update(ProximityMode='1' if disabled else '3', ProximityGroup='7',
                        ProximityLevel='0', CorridorLinkingLinkGroup='0')
    model.applications[56]['groups']={
        0:dict(oid=oid(500),tag='Zulu',levels=()),
        2:dict(oid=oid(502),tag='Alpha',levels=())}
    model.applications[202]['groups']={7:dict(oid=oid(207),tag='Existing trigger',
        levels=(0,2),level_names={0:'Existing action',2:'Other action'})}
    model.applications[203]={'oid':oid(903),'tag':'Enable Control','groups':{}}
    if application_switch:
        model.applications[56]['groups'][99]=dict(oid=oid(599),tag='Old Office',levels=())
        model.applications[57]=dict(oid=oid(570),tag='Secondary lighting',
            groups={0:dict(oid=oid(571),tag='Existing',levels=())})
    editor=EdltParentTransaction(spec)
    model.values={name:_render(value) for name,value in editor.snapshot(model.values).items()}
    # Establish an already initialized retained parent fixture. This supplies
    # input state only; all Add output and preservation oracles below remain
    # independent literals. Device41/channel2 makes the later edit observable.
    initial=plan_native_parent_metadata(model.xml(),'//TEST/254/p/20',
        editor.snapshot(model.values),editor,
        ({'op':'activation'}, {'op':'measurement','page':1,'position':1,'device_id':41,'channel':2}))
    prepared={**initial.parent_plan.expected,**initial.parent_plan.changes}
    model.values={name:_render(value) for name,value in prepared.items()}
    if initial_scene:
        model.values.update(SceneBucket=' '.join(map(str,[2,0,7,1,255]+[255]*227)),
            Scene1StartAddress='0',SceneCount='1',ProximityMode='3',ProximityGroup='7',ActivityDuration='30')
    if missing_office or application_switch:model.values['CorridorLinkingOfficeGroup']='99'
    root=ET.fromstring(model.xml());ET.SubElement(root,'DBVersion').text='2.3'
    project=root.find('Project');ET.SubElement(project,'OID').text=str(uuid.uuid4())
    network=project.find('Network');network.remove(network.find('InterfaceType'))
    ET.SubElement(network,'OID').text=str(uuid.uuid4())
    ET.SubElement(network,'NetworkNumber').text='254'
    ET.SubElement(network,'TagName').text='Closed parent Add network'
    for application in network.findall('Application'):
        application.remove(application.find('Description'))
        for group in application.findall('Group')+application.findall('NetVar'):
            group.remove(group.find('Notes'))
            if group.tag=='NetVar':group.remove(group.find('TagsDLT'))
            for level in group.findall('Level'):
                ET.SubElement(level,'TagsDLT')
    interface=ET.SubElement(network,'Interface')
    for name,value in [('OID',str(uuid.uuid4())),('InterfaceType','cni'),('InterfaceAddress',trap)]:
        ET.SubElement(interface,name).text=value
    ET.SubElement(network.find('Unit'),'UnitName').text='KEYGL5'
    path=work/'parent-add-synthetic.xml';path.write_bytes(ET.tostring(root))
    for command in ('FILE MKDIR Projects','FILE MKDIR Projects/archived'):
        assert owner.command(command).code==200
    assert upload(prepare_upload('Projects/archived/'+path.name,path),owner)['upload_completed']
    for command in ('PROJECT RESTORE TEST '+path.name,'PROJECT USE TEST','PROJECT SAVE TEST'):
        assert owner.command(command).code==200
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def journey(backend, variable, tmp_path, case):
    binary=selected_binary(variable);work=associated_work(tmp_path,'owned')
    specs=tmp_path/'synthetic-specs';specs.mkdir();spec=fixture()
    root=ET.Element('UnitSpecification')
    for name,value in [('Type','KEYGL5'),('MinVersion','5.5.00'),('MaxVersion','5.5.00'),('MemorySize','16384')]:
        ET.SubElement(root,name).text=value
    parameters=ET.SubElement(root,'Parameters')
    for parameter in spec.parameters.values():
        node=ET.SubElement(parameters,'Param')
        for name,value in parameter.fields.items():ET.SubElement(node,name).text=value
    path=specs/'KEYGL5.xml';path.write_bytes(ET.tostring(root))
    flag='--unitspec' if backend=='cgate-mock' else '--cgate-unitspec'
    evidence={'format':'cbus-parent-add-owned-v1','backend':backend,
        'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
        'specification_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'original_execution':False,'physical_acceptance':False,'calls':[],'processes':[]}
    relay=None
    try:
        with no_contact_trap() as trap,owned_backend(backend, binary, work, extra_args=(flag, specs)) as (endpoint,record):
            evidence['processes'].append(record)
            with CGateClient(*endpoint,timeout=15) as owner,RecordedGate(endpoint) as relay:
                evidence['fixture_sha256']=provision(owner,work,trap,spec,disabled=case.get('disabled',False),
                    initial_scene=case.get('initial_scene',False),missing_office=case.get('missing_office',False),
                    application_switch=case.get('application_switch',False))
                yield owner,relay,evidence,specs,endpoint
        evidence['closed_graph_trap_contacts']=0
    finally:
        if relay is not None:evidence['wires']=relay.evidence()
        associated_evidence(tmp_path/'parent-add-evidence.json',evidence)


def invoke(relay,evidence,specs,tmp_path,case,*,dry_run=False,expected=0,complete=True):
    ops=tmp_path/'operations.json';ops.write_text(json.dumps([*case['ops'],widget()]))
    prefs=tmp_path/'preferences.json';prefs.write_text(json.dumps({
        'format':'cbus-edlt-display-preferences-v1','registry_key_present':True,'values':{}}))
    argv=['unit','--lock-address','//TEST/254','--source','/db//TEST/254/p/20']
    if dry_run:argv.append('--dry-run')
    argv.extend(['edlt-parent-transaction','--spec-dir',specs,'--auto-metadata','--exclusive-project',
                 '--operations',ops,'--display-preferences',prefs])
    if not dry_run:argv.extend(['--backup-project','PABACKUP'])
    return cli(relay,evidence['calls'],*argv,expected=expected,complete=complete)


def values(root):
    node=root.find("./Project/Network/Unit[Address='20']")
    return {p.get('Name'):[int(t,0) for t in p.get('Value').split()] for p in node.findall('PP')}


def inspect_result(before,after,case,commands):
    old,new=ET.fromstring(before),ET.fromstring(after)
    pp=values(new)
    for name,expected in case['pp'].items():assert pp[name]==expected
    assert (pp['Widget6WidgetType'],pp['Widget6WidgetByteValue1'],pp['Widget6WidgetByteValue2'])==([12],[42],[1])
    assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands)==1
    assert commands.count('PROJECT SAVE TEST')==2
    saves=[i for i,c in enumerate(commands) if c=='PROJECT SAVE TEST']
    assert saves[0]<commands.index('PROJECT COPY TEST PABACKUP')<saves[1]
    assert commands.count('PROJECT COPY TEST PABACKUP')==1
    new_network=new.find('Project/Network');old_network=old.find('Project/Network')
    issued=[]
    for app,address,name in case['groups']:
        group=new_network.find(f"Application[Address='{app}']/Group[Address='{address}']")
        assert group is not None and group.findtext('TagName')==name
        issued.append(group.findtext('OID'))
    for group,address,name in case['levels']:
        node=new_network.find(f"Application[Address='202']/Group[Address='{group}']/Level[Address='{address}']")
        assert node is not None and node.findtext('TagName')==name and node.get('Value')==str(address)
        issued.append(node.findtext('OID'))
        # Existing parent Level additions are independent of Group creation.
        if (202,group) not in [(a,g) for a,g,_n in case['groups']]:
            new_network.find(f"Application[Address='202']/Group[Address='{group}']").remove(node)
    assert len(issued)==len(set(issued)) and all(x and x not in before for x in issued)
    assert sum(c.startswith('DBADDSAFE ') for c in commands)==len(issued)
    for app,address,_name in case['groups']:
        parent=new_network.find(f"Application[Address='{app}']")
        parent.remove(parent.find(f"Group[Address='{address}']"))
    # Exact original fields are preserved except the independently named owning
    # parent panels, Measurement record and their established terminal CRCs.
    allowed=set(case['pp'])|{'SceneBucket','ScenesCheckSum','WidgetGroups','OverallCRC',
        'GlobalParameterCRC','WidgetsCRC','StaticTextCRC'}
    allowed.update({'Widget6WidgetType',*[f'Widget6WidgetByteValue{i}' for i in range(1,14)]})
    original=values(old)
    changed={name for name in pp if pp[name]!=original[name]}
    assert changed<=allowed,changed-allowed
    for node in new_network.find("Unit[Address='20']").findall('PP'):
        if node.get('Name') in allowed:
            source=old_network.find("Unit[Address='20']/PP[@Name='"+node.get('Name')+"']")
            node.set('Value',source.get('Value'))
    assert graph(ET.tostring(new,encoding='unicode'))==graph(before)


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_public_parent_add_history_one_save_and_full_preservation(backend,variable,case,tmp_path):
    with journey(backend,variable,tmp_path,case) as (owner,relay,evidence,specs,_endpoint):
        before=snapshot(owner)
        preview,call=invoke(relay,evidence,specs,tmp_path,case,dry_run=True)
        assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT COPY','PROJECT SAVE','PP SAVE')) for c in call['commands'])
        assert snapshot(owner)==before
        final,call=invoke(relay,evidence,specs,tmp_path,case)
        assert final['saved'] and final['target_project_save_confirmed'] and final['persistence_verified']
        after=snapshot(owner);inspect_result(before,after,case,call['commands'])
        evidence['snapshots']={'before':before,'after':after}


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
def test_public_parent_add_lost_save_success_is_not_replayed(backend,variable,tmp_path):
    case=CASES[0]
    with journey(backend,variable,tmp_path,case) as (owner,_relay,evidence,specs,endpoint):
        with FaultGate(endpoint,'PP SAVE_TO_SOURCE','drop') as fault:
            _result,call=invoke(fault,evidence,specs,tmp_path,case,expected=1,complete=False)
            assert fault.matches==1 and sum(c.startswith('PP SAVE_TO_SOURCE ') for c in call['commands'])==1
            saved_index=next(i for i,c in enumerate(call['commands']) if c.startswith('PP SAVE_TO_SOURCE '))
            assert not any(c.startswith(('PROJECT SAVE ','PROJECT CLOSE ','PROJECT LOAD ','DBDELETE ')) for c in call['commands'][saved_index+1:])
            assert call['commands'].count('PROJECT SAVE TEST')==1
            rows=[r for r in fault.evidence() if r.get('fault')]
            assert len(rows)==1 and bytes.fromhex(rows[0]['lost_backend_terminal_hex']).decode()=='['+rows[0]['fault']['tag']+'] 200 OK\r\n'
            evidence['lost_save_wires']=fault.evidence()
        # Successful backend save remains observable; the CLI did not roll back
        # or replay after its terminal receipt was lost.
        assert values(ET.fromstring(snapshot(owner)))['ProximityLevel']==[1]
