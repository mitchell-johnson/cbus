"""Reachable ASCII defaults with Unicode inventory; no arbitrary Unicode defaults.

Direct comparator probes are separately qualified. Every workflow uses source
plant/installation constants and preserves existing optional Level.Value text.
"""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree as ET

import pytest
from cbus_toolkit.edlt_add_dialog import _upper
from cbus_toolkit.thermostat_output_groups import OutputGroupModel
from cbus_toolkit.thermostat_remote_references import (
    RemoteGroup, snapshot_project, validate_remote_plan, verify_project_preservation)
from cbus_toolkit.thermostat_settings import NativeThermostatSettings
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
import test_thermostat_output_edit as edits
import test_thermostat_output_add_native as scripted
from test_thermostat_output_groups import raw_values, seed, materialize
from test_thermostat_remote_references import PATH, oid


@pytest.fixture
def fixture():
    case=edits.OutputEditTests(methodName='runTest');case.setUp()
    try:yield case
    finally:case.doCleanups()


def source(value, *, kind='PC_TSA5', duplicate=False):
    raw=raw_values(CoolFanLowOutput=42,HeatStage1Output=41,
        RemoteSetbackControlSource=1,RemoteSetbackOnGroup=41,RemoteSetbackOffGroup=255)
    groups={255:'<Unused>',41:'User heating Ω',50:'[cg07] g (fan)',
            31:'É',32:'ω',33:'STRASSE',34:'Unrelated Ω'}
    if duplicate:groups[51]='[CG07] G (FAN)'
    root=ET.fromstring(seed(kind,raw,{56:groups,172:{7:'Zone'},203:{}}))
    root.find('./Project/TagName').text='Thermostat Unicode inventory'
    for group in root.findall("./Project/Network/Application[Address='56']/Group"):
        for level in group.findall('Level'):
            level.attrib.pop('Value',None)
            if value is not None:level.set('Value',value)
    return raw,ET.tostring(root,encoding='unicode')


def plan(fixture,value,history=(),*,kind='PC_TSA5',duplicate=False,prompts=None):
    raw,xml=source(value,kind=kind,duplicate=duplicate)
    return fixture.plan(history,kind=kind,raw=raw,xml=xml,prompts=prompts)


def preserve(p,fixture):
    root,receipts=materialize(p)
    assert verify_project_preservation(p.project_xml,ET.tostring(root,encoding='unicode'),PATH,
        changed_parameters=p.expected,created_oids=receipts,graph_operations=p.graph_operations)['preserved']
    old={level.findtext('OID'):level for level in ET.fromstring(p.project_xml).iter('Level')}
    new={level.findtext('OID'):level for level in root.iter('Level')}
    for identity,level in old.items():assert ET.tostring(new[identity])==ET.tostring(level)
    assert validate_remote_plan(fixture.store,p)==p
    return root


@pytest.mark.parametrize('kind',['PC_TSA','PC_TSA5','PC_TSB','PC_TSB5'])
@pytest.mark.parametrize('value',[None,'oops'])
def test_ordinary_ascii_default_reuses_unique_peer_amid_unicode_and_opaque_values(fixture,kind,value):
    p=plan(fixture,value,kind=kind)
    assert p.output_expected['CoolFanLowOutput']==50
    assert p.as_dict()['output_projection']['resolved_references']['CoolFanLowOutput']['identity']==oid('group:56:50')
    assert not p.creations and not p.renames and not p.level_creations
    assert {row['name']:row['after'] for row in p.changed_parameters}=={'CoolFanLowOutput':50}
    assert p.as_dict()['resolved_roles']['setback_on']['identity']==oid('group:56:41')
    rows=[row for row in p.as_dict()['getters'] if row['getter']=='FindExistingGroup']
    assert rows==[dict(getter='FindExistingGroup',role='CoolFanLow',application=56,
                       name='[CG07] G (fan)',identity=oid('group:56:50'))]
    preserve(p,fixture)


@pytest.mark.parametrize('value',[None,'oops'])
def test_lookup_then_omitted_accepted_Edit_preserves_reused_name(fixture,value):
    p=plan(fixture,value,[edits.edit('CoolFanLowOutput')])
    assert p.output_expected['CoolFanLowOutput']==50 and not p.graph_operations
    receipt,=p.as_dict()['output_projection']['edit_dialogs']
    assert receipt['name']=='[cg07] g (fan)' and not receipt['changed']
    assert receipt['identity']==oid('group:56:50')
    preserve(p,fixture)


@pytest.mark.parametrize('value',[None,'oops'])
def test_missing_ASCII_default_creates_at_requested_address_amid_Unicode(fixture,value):
    raw,xml=source(value)
    root=ET.fromstring(xml)
    root.find("./Project/Network/Application[Address='56']/Group[Address='50']/TagName").text='User fan Ω'
    p=fixture.plan((),raw=raw,xml=ET.tostring(root,encoding='unicode'))
    assert [(r.kind,r.application,r.address,r.name) for r in p.creations]==[
        ('Group',56,42,'[CG07] G (fan)')]
    assert not p.renames and not p.level_creations and not p.pp_mutation_required
    assert p.output_expected['CoolFanLowOutput']==42
    assert p.as_dict()['output_projection']['resolved_references']['CoolFanLowOutput']['identity']=='planned-group:56:42'
    preserve(p,fixture)


@pytest.mark.parametrize('value',[None,'oops'])
def test_programmable_damper_reuses_actual_ASCII_default_amid_Unicode(fixture,value):
    raw,xml=source(value)
    raw.update(CoolFanLowOutput='255',DamperZone1Output='42')
    root=ET.fromstring(xml)
    for pp in root.findall('./Project/Network/Unit/PP'):
        if pp.get('Name') in raw:pp.set('Value',raw[pp.get('Name')])
    root.find("./Project/Network/Application[Address='56']/Group[Address='50']/TagName").text='[cg07] damper zone 1'
    p=fixture.plan((),raw=raw,xml=ET.tostring(root,encoding='unicode'))
    assert p.output_expected['DamperZone1Output']==50
    assert not p.creations and not p.renames and not p.level_creations
    assert {r['name']:r['after'] for r in p.changed_parameters}=={'DamperZone1Output':50}
    preserve(p,fixture)


@pytest.mark.parametrize('value',[None,'oops'])
def test_loaded_unicode_inventory_then_three_distinct_unicode_Edit_names(fixture,value):
    history=[edits.edit(name='é'),edits.edit(name='Ω'),edits.edit(name='straße')]
    p=plan(fixture,value,history)
    assert [(row.identity,row.previous_name,row.name) for row in p.renames]==[
        (oid('group:56:41'),'User heating Ω','é'),
        (oid('group:56:41'),'é','Ω'),(oid('group:56:41'),'Ω','straße')]
    assert not p.creations and not p.level_creations
    root=preserve(p,fixture)
    actual={g.findtext('Address'):g.findtext('TagName') for g in root.findall("./Project/Network/Application[Address='56']/Group")}
    assert actual['31']=='É' and actual['32']=='ω' and actual['33']=='STRASSE'
    assert actual['34']=='Unrelated Ω' and actual['41']=='straße'


@pytest.mark.parametrize('kind',['PC_TSA','PC_TSA5','PC_TSB','PC_TSB5'])
def test_multiple_ASCII_equivalent_default_peers_still_refuse(fixture,kind):
    with pytest.raises(ThermostatTemplateError,match='Generated output group name is ambiguous'):
        plan(fixture,'oops',kind=kind,duplicate=True)


@pytest.mark.parametrize('left,right',[('é','É'),('Ω','ω'),('straße','STRASSE')])
def test_direct_source_comparator_keeps_non_ASCII_distinctions(left,right):
    # Synthetic requested label exercises the comparator, not a reachable
    # public plant/installation default. Actual default strings are ASCII.
    rows=[RemoteGroup(56,n,oid('direct:'+str(n)),' '+name,'Group','')
          for n,name in enumerate((left,right))]
    model=OutputGroupModel.__new__(OutputGroupModel)
    model.application=56;model.prefix=''
    model.resolver=SimpleNamespace(live={(56,r.address):r for r in rows},getters=[],create=Mock())
    assert _upper(left)!=_upper(right)
    assert model._default(None,10,left,'synthetic-comparator') is rows[0]
    assert model._default(None,10,right,'synthetic-comparator') is rows[1]
    model.resolver.create.assert_not_called()


def test_existing_address_branch_keeps_ordinary_rename_semantics():
    existing=RemoteGroup(56,41,oid('existing'),'User Ω','Group','')
    model=OutputGroupModel.__new__(OutputGroupModel);model.application=56;model.prefix='[CG07]'
    renamed=replace(existing,name='[CG07] G (fan)')
    model.resolver=SimpleNamespace(rename=Mock(return_value=renamed))
    assert model._default(existing,41,'G (fan)','CoolFanLow') is renamed
    model.resolver.rename.assert_called_once_with(existing,'[CG07] G (fan)','CoolFanLow')


def test_lookup_whole_graph_freshness_does_not_ignore_unrelated_unicode_or_Value(fixture):
    p=plan(fixture,'oops')
    for target,change in [('TagName','Unrelated changed Ω'),('Value','changed opaque')]:
        root=ET.fromstring(p.project_xml)
        group=root.find("./Project/Network/Application[Address='56']/Group[Address='34']")
        if target=='TagName':group.find('TagName').text=change
        else:group.find('Level').set('Value',change)
        xml=ET.tostring(root,encoding='unicode')
        assert snapshot_project(xml,PATH).fingerprint!=p.graph.fingerprint
        with pytest.raises(ThermostatTemplateError):validate_remote_plan(fixture.store,replace(p,project_xml=xml))


@pytest.mark.parametrize('value',[None,'oops'])
def test_optional_new_levels_strict_existing_values_opaque_after_lookup(fixture,value):
    p=plan(fixture,value,prompts={'setback':'accept','schedule':'decline'})
    assert len(p.level_creations)==30
    assert all(type(row.value) is int and row.value==row.address for row in p.level_creations)
    used=next(g for a in p.graph.applications if a.address==56 for g in a.groups if g.address==41)
    assert used.levels[0].value==value
    assert validate_remote_plan(fixture.store,p)==p
    for bad in (None,'oops',True,256):
        with pytest.raises(ThermostatTemplateError):
            validate_remote_plan(fixture.store,replace(p,level_creations=(replace(p.level_creations[0],value=bad),*p.level_creations[1:])))


@pytest.mark.parametrize('value',[None,'oops'])
def test_lookup_then_native_quoted_Edit_does_not_read_Level_values(fixture,value):
    p=plan(fixture,value,[edits.edit('CoolFanLowOutput',name='Renamed Ω')])
    row,=p.renames;assert row.identity==oid('group:56:50')
    script=[('DBGET !'+row.identity+'/OID',scripted.identity('!'+row.identity,row.identity)),
        ('DBGET !'+row.identity+'/TagName',scripted.reply(342,'342 !'+row.identity+'/TagName=[cg07] g (fan)')),
        ('DBSET !'+row.identity+'/TagName "Renamed Ω"',scripted.reply(200,'200 OK.'))]
    client=scripted.ScriptedClient(fixture,script)
    manager=NativeThermostatSettings(client,fixture.store);manager._start('private-ASCII-default-scripted')
    assert manager._create_references(SimpleNamespace(network=PATH.rsplit('/p/',1)[0],remote=p))=={}
    assert not client.script and client.commands==[command for command,_ in script]
    assert all('/Value' not in command and '/Level' not in command for command in client.commands)
    assert manager.last_evidence['renames'][0]['confirmed']
    preserve(p,fixture)
