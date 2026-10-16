"""Issue96 stays Address-based through Edit and shared Select/Add/Edit histories."""
from dataclasses import replace
import json
from xml.etree import ElementTree as ET
import pytest
from cbus_toolkit.thermostat_remote_references import (
    plan_remote_references,snapshot_project,validate_remote_plan,verify_project_preservation)
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
import test_thermostat_output_edit as edits
from test_thermostat_output_add import add,select
from test_thermostat_output_groups import raw_values,seed,materialize
from test_thermostat_remote_references import PATH,oid
@pytest.fixture
def fixture():
    case=edits.OutputEditTests(methodName="runTest");case.setUp()
    try:yield case
    finally:case.doCleanups()
def source(value,unrelated=None):
    raw=raw_values(HeatStage1Output=20,CoolStage1Output=20,
        RemoteSetbackControlSource=1,RemoteSetbackOnGroup=20,RemoteSetbackOffGroup=255)
    root=ET.fromstring(seed("PC_TSA5",raw,{56:{20:"Alpha",30:"Beta",255:"<Unused>"},172:{7:"Zone"},203:{}}))
    root.find("./Project/TagName").text="Thermostat Project"
    for address,v in ((20,value),(30,unrelated)):
        row=root.find("./Project/Network/Application[Address='56']/Group[Address='"+str(address)+"']/Level")
        row.attrib.pop("Value",None)
        if v is not None:row.set("Value",v)
    return raw,ET.tostring(root,encoding="unicode")
def plan(fixture,value,history,*,unrelated=None,prompts=None):
    raw,xml=source(value,unrelated)
    return fixture.plan(history,raw=raw,xml=xml,prompts=prompts)
def preserved(p):
    root,receipts=materialize(p)
    assert verify_project_preservation(p.project_xml,ET.tostring(root,encoding="unicode"),PATH,
        changed_parameters=p.expected,created_oids=receipts,graph_operations=p.graph_operations)["preserved"]
    return root,receipts
@pytest.mark.parametrize("value",[None,"oops","","0x07","007","256"])
def test_shared_used_and_unrelated_existing_Values_remain_opaque_after_Edit(fixture,value):
    p=plan(fixture,value,[edits.edit("CoolStage1Output",name="Edited  shared"),
                         edits.edit("HeatStage1Output",outcome="cancel")],unrelated="not-a-byte")
    assert not p.pp_mutation_required and not p.creations and not p.level_creations
    assert [(r.identity,r.previous_name,r.name) for r in p.renames]==[
        (oid("group:56:20"),"Alpha","Edited  shared")]
    groups={g.address:g for a in p.graph.applications if a.address==56 for g in a.groups}
    assert groups[20].levels[0].value==value and groups[30].levels[0].value=="not-a-byte"
    view=p.as_dict()
    assert view["resolved_roles"]["setback_on"]["identity"]==oid("group:56:20")
    for name in ("HeatStage1Output","CoolStage1Output"):
        assert view["output_projection"]["resolved_references"][name]["name"]=="Edited  shared"
    root,_=preserved(p)
    for address,expected in ((20,value),(30,"not-a-byte")):
        level=root.find("./Project/Network/Application[Address='56']/Group[Address='"+str(address)+"']/Level")
        assert ("Value" in level.attrib)==(expected is not None)
        assert level.get("Value")==expected
    assert validate_remote_plan(fixture.store,p)==p
@pytest.mark.parametrize("value",[None,"oops"])
def test_unchanged_accept_and_cancel_consume_no_existing_Level_value(fixture,value):
    for history in ([edits.edit(name="Alpha")],[edits.edit(outcome="cancel")],[edits.edit()]):
        p=plan(fixture,value,history,unrelated=None)
        assert not p.apply_would_mutate and not p.graph_operations
        assert validate_remote_plan(fixture.store,p)==p
        preserved(p)
@pytest.mark.parametrize("value",[None,"oops"])
def test_causal_select_add_edit_reselection_keeps_shared_opaque_level(fixture,value):
    history=[edits.edit("CoolStage1Output",name="Temporary"),select("HeatStage1Output",30),
        add("HeatStage1Output",name="Fresh"),edits.edit("HeatStage1Output",name="Edited issued"),
        select("HeatStage1Output",20),edits.edit("HeatStage1Output",name="Final shared")]
    p=plan(fixture,value,history,unrelated="opaque unrelated")
    assert [(r.action,r.address) for r in p.graph_operations]==[
        ("rename",20),("create",0),("rename",0),("rename",20)]
    assert [(r.identity,r.previous_name,r.name) for r in p.renames]==[
        (oid("group:56:20"),"Alpha","Temporary"),
        ("planned-group:56:0","Fresh","Edited issued"),
        (oid("group:56:20"),"Temporary","Final shared")]
    assert not p.pp_mutation_required
    assert p.as_dict()["output_projection"]["resolved_references"]["CoolStage1Output"]["name"]=="Final shared"
    root,_=preserved(p)
    assert root.find("./Project/Network/Application[Address='56']/Group[Address='20']/Level").get("Value")==value
    assert validate_remote_plan(fixture.store,p)==p
def test_value_freshness_and_whole_graph_preservation_still_reject_unowned_changes(fixture):
    p=plan(fixture,"oops",[edits.edit(name="Edited")],unrelated=None)
    raw,xml=source("changed",None)
    assert snapshot_project(xml,PATH).fingerprint!=p.graph.fingerprint
    with pytest.raises(ThermostatTemplateError):
        validate_remote_plan(fixture.store,replace(p,project_xml=xml))
    root,receipts=preserved(p)
    root.find("./Project/Network/Application[Address='56']/Group[Address='30']/Level").set("Value","7")
    with pytest.raises(ThermostatTemplateError):
        verify_project_preservation(p.project_xml,ET.tostring(root,encoding="unicode"),PATH,
            changed_parameters=p.expected,created_oids=receipts,graph_operations=p.graph_operations)
@pytest.mark.parametrize("value",[None,"oops"])
def test_accepted_optional_Level_creation_keeps_existing_Value_and_new_values_strict(fixture,value):
    p=plan(fixture,value,[edits.edit(name="Renamed used")],prompts={"setback":"accept","schedule":"decline"})
    assert len(p.level_creations)==30
    assert [r.address for r in p.level_creations]==[n for n in range(1,32) if n!=7]
    assert all(type(r.value) is int and r.value==r.address for r in p.level_creations)
    assert next(g for a in p.graph.applications if a.address==56 for g in a.groups if g.address==20).levels[0].value==value
    assert validate_remote_plan(fixture.store,p)==p
    for bad in ("oops",None,256,True):
        altered=replace(p,level_creations=(replace(p.level_creations[0],value=bad),*p.level_creations[1:]))
        with pytest.raises(ThermostatTemplateError):
            validate_remote_plan(fixture.store,altered)
