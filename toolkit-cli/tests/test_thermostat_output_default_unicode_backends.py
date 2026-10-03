"""Reachable ASCII defaults in complete synthetic Unicode inventories.

Private next-chunk definitions only until an owning backend phase runs. No
arbitrary Unicode default, host sorting, original provider or physical claim.
"""
from contextlib import contextmanager
from copy import deepcopy
import re
from xml.etree import ElementTree as ET
import pytest
from test_cgate_barcode_database_interop import FaultGate,graph
import test_thermostat_output_edit_backends as edits

adds,outputs,refs=edits.adds,edits.outputs,edits.refs
BACKENDS=edits.BACKENDS
PROJECT,BACKUP=edits.PROJECT,edits.BACKUP

BASE_CASE={
 'unit_type':'PC_TSA5','groups':{56:[20,30,31,32,33,40,255],172:[1],203:[]},
 'group_tags':{56:{20:'[cg01] g (fan)',30:'Original output Ω',31:'É',32:'ω',33:'STRASSE',40:'Unrelated Ω'}},
 'seed':{'CoolFanLowOutput':42,'HeatStage1Output':30,'RemoteSetbackControlSource':1,
         'RemoteSetbackOnGroup':20,'RemoteSetbackOffGroup':255},
 'history':[edits.edit('CoolFanLowOutput')],
 'existing_value':'oops','changed':{'CoolFanLowOutput':20},'operations':[],'renames':[],'creates':[],
}
CASES={
 'unique-ASCII-default-reuse-then-omitted-Edit':deepcopy(BASE_CASE),
 'missing-ASCII-default-create-amid-Unicode':deepcopy(BASE_CASE)|{
   'group_tags':{56:BASE_CASE['group_tags'][56]|{20:'User fan Ω'}},
   'history':[edits.edit('HeatStage1Output','cancel')],'changed':{},
   'operations':[('create',56,42,'[CG01] G (fan)')],'creates':[(56,42,'[CG01] G (fan)')]},
 'distinct-Unicode-Edits-after-ASCII-default-reuse':deepcopy(BASE_CASE)|{
   'history':[edits.edit('HeatStage1Output',name='é'),edits.edit('HeatStage1Output',name='Ω'),edits.edit('HeatStage1Output',name='straße')],
   'renames':[(1,'HeatStage1Output',56,30,'Original output Ω','é'),
              (2,'HeatStage1Output',56,30,'é','Ω'),(3,'HeatStage1Output',56,30,'Ω','straße')]},
 'programmable-damper-ASCII-default-reuse-amid-Unicode':deepcopy(BASE_CASE)|{
   'group_tags':{56:BASE_CASE['group_tags'][56]|{20:'[cg01] damper zone 1'}},
   'seed':BASE_CASE['seed']|{'CoolFanLowOutput':255,'DamperZone1Output':42,'InternalPlantZones':3},
   'history':[edits.edit('DamperZone1Output')],'changed':{'DamperZone1Output':20}},
}
REFUSALS={
 'ambiguous-ASCII-default-still-refused':deepcopy(BASE_CASE)|{
   'group_tags':{56:BASE_CASE['group_tags'][56]|{31:'[CG01] G (FAN)'}},
   'error_contains':'Generated output group name is ambiguous'},
 'ASCII-duplicate-Edit-still-refused':deepcopy(BASE_CASE)|{
   'group_tags':{56:BASE_CASE['group_tags'][56]|{31:'ALPHA'}},
   'history':[edits.edit('HeatStage1Output',name='alpha')],'error_contains':'2203'},
}
QUOTED={'é':'"é"','Ω':'"Ω"','straße':'"straße"'}


@contextmanager
def journey(backend,variable,tmp_path,name,case):
    try:
        with adds.journey(backend,variable,tmp_path,name,case) as data:
            owner,relay,evidence,specs,endpoint=data
            evidence['format']='cbus-thermostat-ASCII-default-owned-v1'
            before=outputs.parse(evidence['before_xml'])
            assert outputs.group_at(before,56,40).findtext('TagName')=='Unrelated Ω'
            assert outputs.group_at(before,56,20).find("Level[Address='7']").get('Value')=='oops'
            assert len(evidence['before_parameters'])==109
            yield data
    finally:
        original=tmp_path/'thermostat-output-add-evidence.json'
        if original.exists():original.rename(tmp_path/'thermostat-ASCII-default-evidence.json')


def preserve(before,after,case,*,lost=False):
    old,new=outputs.parse(before),outputs.parse(after)
    renames=case['renames'][:1] if lost else case['renames']
    final={(app,address):name for _position,_parameter,app,address,_old,name in renames}
    for key,name in final.items():
        expected=outputs.group_at(old,*key);actual=outputs.group_at(new,*key)
        assert actual.findtext('OID')==expected.findtext('OID') and actual.findtext('TagName')==name
        actual.find('TagName').text=expected.findtext('TagName')
    old_levels={n.findtext('OID'):n for n in old.iter('Level')}
    new_levels={n.findtext('OID'):n for n in new.iter('Level')}
    assert old_levels.keys()<=new_levels.keys()
    assert all(ET.tostring(n)==ET.tostring(new_levels[identity]) for identity,n in old_levels.items())
    created=refs.assert_preserved(before,ET.tostring(new,encoding='unicode'),
        {'changed':{} if lost else case['changed'],'creates':case['creates']})
    return created


def assert_plan(preview,case):
    assert {r['name']:r['after'] for r in preview['changed_parameters']}==case['changed']
    assert preview['pp_save_count']==int(bool(case['changed']))
    assert preview['target_project_save_count']==1 and preview['apply_would_mutate'] is True
    remote=preview['remote_references'];projection=preview['output_projection']
    assert remote['output_operations']==case['history']
    assert [(r['application'],r['address'],r['name']) for r in remote['planned_creations']]==case['creates']
    assert [(r['application'],r['address'],r['previous_name'],r['name']) for r in remote['planned_renames']]==[
        (app,address,old,new) for _position,_parameter,app,address,old,new in case['renames']]
    assert remote['planned_level_creations']==[]
    field='DamperZone1Output' if 'damper' in case.get('_name','') else 'CoolFanLowOutput'
    if case['creates']:assert projection['resolved_references'][field]['address']==42
    else:assert projection['resolved_references'][field]['address']==20
    return remote


def assert_wire(call,before,case,*,lost=False):
    if case['creates']:
        outputs.assert_graph_wire(call,before,case)
    else:
        expected=[]
        for _position,_parameter,app,address,old,name in (case['renames'][:1] if lost else case['renames']):
            identity=outputs.group_at(outputs.parse(before),app,address).findtext('OID')
            command='DBSET !'+identity+'/TagName '+QUOTED[name]
            index=call['commands'].index(command)
            assert call['commands'][index-2:index]==['DBGET !'+identity+'/OID','DBGET !'+identity+'/TagName']
            assert call['statuses'][index-2:index]==[342,342]
            assert call['terminals'][index-2:index]==['!'+identity+'/OID='+identity,'!'+identity+'/TagName='+old]
            assert call['statuses'][index]==(None if lost else 200)
            expected.append(command)
        assert [c for c in call['commands'] if c.startswith(('DBADD','DBSET','DBDELETE'))]==expected


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=['mock','daemon'])
@pytest.mark.parametrize('name',list(CASES))
def test_public_ASCII_default_load_and_Edit_preserve_Unicode_and_opaque_Values(backend,variable,name,tmp_path):
    case=deepcopy(CASES[name])|{'_name':name}
    with journey(backend,variable,tmp_path,name,case) as (owner,relay,evidence,specs,_):
        preview,preview_call=adds.settings_cli(relay,evidence,specs,case,action='preview')
        assert_plan(preview,case);outputs.assert_no_mutation(preview_call)
        assert refs.document(owner)==evidence['before_xml'] and refs.parameters(owner)==evidence['before_parameters']
        result,call=adds.settings_cli(relay,evidence,specs,case)
        assert result['complete'] and result['persistence_verified']
        assert result['plan']=={k:v for k,v in preview.items() if k!='scope'}
        assert_wire(call,evidence['before_xml'],case)
        commands=call['commands']
        assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands)==int(bool(case['changed']))
        assert commands.count('PROJECT SAVE '+PROJECT)==2
        assert commands.count('PROJECT COPY '+PROJECT+' '+BACKUP)==1
        assert commands.count('PROJECT CLOSE '+PROJECT)==commands.count('PROJECT LOAD '+PROJECT)==1
        first=next(i for i,c in enumerate(commands) if c.startswith(('DBADD','DBSET','PP SET ','PP SAVE')))
        assert commands.index('PROJECT COPY '+PROJECT+' '+BACKUP)<first
        after,actual=refs.document(owner),refs.parameters(owner)
        refs.assert_values(evidence['before_parameters'],actual,case['changed'])
        created=preserve(evidence['before_xml'],after,case)
        for verb in ('SAVE','CLOSE','LOAD','USE'):assert owner.command('PROJECT '+verb+' '+PROJECT).code==200
        reopened,fresh=refs.document(owner),refs.parameters(owner)
        assert fresh==actual and graph(reopened)==graph(after)
        preserve(evidence['before_xml'],reopened,case)
        evidence.update(preview=preview,result=result,after_xml=after,reopened_xml=reopened,
          after_parameters=actual,reopened_parameters=fresh,preservation_verified=True,
          independent_reopen=True,created_oids=created)


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=['mock','daemon'])
@pytest.mark.parametrize('name',list(REFUSALS))
def test_public_ASCII_ambiguity_and_duplicate_Edit_refuse_before_backup(backend,variable,name,tmp_path):
    case=REFUSALS[name]
    with journey(backend,variable,tmp_path,name,case) as (owner,relay,evidence,specs,_):
        result,call=adds.settings_cli(relay,evidence,specs,case,expected=1)
        assert case['error_contains'] in result['error']
        assert not result['thermostat_template_evidence']['outcome_uncertain']
        outputs.assert_no_mutation(call)
        assert refs.document(owner)==evidence['before_xml'] and refs.parameters(owner)==evidence['before_parameters']
        evidence.update(result=result,after_xml=refs.document(owner),after_parameters=refs.parameters(owner),refusal_before_backup=True)


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=['mock','daemon'])
def test_public_ASCII_default_snapshot_keeps_unrelated_opaque_Value_freshness(backend,variable,tmp_path):
    case=CASES['unique-ASCII-default-reuse-then-omitted-Edit']
    with journey(backend,variable,tmp_path,'stale-unrelated-opaque-Value',case) as (owner,_relay,evidence,specs,endpoint):
        level=outputs.group_at(outputs.parse(evidence['before_xml']),56,40).find("Level[Address='7']")
        identity=level.findtext('OID')
        def mutate():assert owner.command('DBSETSAFE !'+identity+'/Value changed opaque').code==200
        with FaultGate(endpoint,'PROJECT USE','change',occurrence=4,callback=mutate) as fault:
            result,call=adds.settings_cli(fault,evidence,specs,case,expected=1)
            assert fault.matches>=4 and any(r.get('controlled_change_completed') for r in fault.rows)
        evidence['fault_wires']=fault.evidence()
        assert 'changed since planning' in result['error'] and not result['thermostat_template_evidence']['outcome_uncertain']
        outputs.assert_no_mutation(call)
        after=refs.document(owner);expected=outputs.parse(evidence['before_xml'])
        expected_level=next(n for n in expected.iter('Level') if n.findtext('OID')==identity)
        expected_level.set('Value','changed opaque')
        assert graph(after)==graph(ET.tostring(expected,encoding='unicode'))
        assert refs.parameters(owner)==evidence['before_parameters']
        evidence.update(result=result,after_xml=after,after_parameters=refs.parameters(owner),controlled_change=dict(oid=identity,field='Value',before='oops',after='changed opaque'))


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=['mock','daemon'])
def test_public_ASCII_default_then_lost_quoted_Unicode_Edit_never_replays(backend,variable,tmp_path):
    case=CASES['distinct-Unicode-Edits-after-ASCII-default-reuse']
    with journey(backend,variable,tmp_path,'lost-quoted-Unicode-Edit',case) as (owner,_relay,evidence,specs,endpoint):
        with FaultGate(endpoint,'DBSET','drop') as fault:
            result,call=adds.settings_cli(fault,evidence,specs,case,expected=1,complete=False)
        assert fault.matches==1;wires=fault.evidence();evidence['fault_wires']=wires
        state=result['thermostat_template_evidence']
        assert not state['complete'] and state['outcome_uncertain'] and state['graph_mutation_outcome_uncertain']
        assert state['automatic_retries']==0 and state['rollback_performed'] is False
        assert not state['pp_save_attempted'] and not state['target_save_attempted']
        assert_wire(call,evidence['before_xml'],case,lost=True)
        assert call['commands'][-1].startswith('DBSET !') and call['statuses'][-1] is None
        assert call['commands'].count(call['commands'][-1])==1
        assert not any(c.startswith(('PP SAVE','PROJECT CLOSE ','PROJECT LOAD ')) for c in call['commands'])
        assert call['commands'].count('PROJECT SAVE '+PROJECT)==1
        lost=[w for w in wires if 'lost_backend_terminal_hex' in w];assert len(lost)==1
        terminal=bytes.fromhex(lost[0]['lost_backend_terminal_hex'])
        assert re.fullmatch(rb'\[[^]]+\] 200 OK\.\r\n',terminal)
        assert terminal in bytes.fromhex(lost[0]['backend_response_hex']) and terminal not in bytes.fromhex(lost[0]['response_hex'])
        after,actual=refs.document(owner),refs.parameters(owner)
        assert actual==evidence['before_parameters'];preserve(evidence['before_xml'],after,case,lost=True)
        evidence.update(result=result,after_xml=after,after_parameters=actual,
          mutation_response_lost=True,replay_count=0,independent_reopen=False,preservation_verified=True)
