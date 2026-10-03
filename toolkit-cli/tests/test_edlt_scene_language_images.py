"""Byte-backed image variants preserve exact old/current Language epochs."""
from dataclasses import replace
from xml.dom import minidom

import pytest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_parent_metadata import _snapshot, plan_native_parent_metadata
from cbus_toolkit.edlt_parent_transaction import _NativeLanguageBinding
from cbus_toolkit.edlt_scene_language_initializer import (issue_language_initializer,
    check_language_initializer, _facts)
from cbus_toolkit.edlt_scene_metadata import resolve_native_scene_metadata
from cbus_toolkit.edlt_language_add_dialog import (native_inventory, initialise, project,
    replace_native_rows)
from cbus_toolkit.edlt_scene_label_images import parse_project_images, load_decoded_dltp_index
from tests.test_edlt_scene_label_images import bmp, export_bytes, sha
from tests.test_edlt_scene_language_initializer import language_source, UNIT, operation
from tests.test_edlt_parent_scene_language import scene_result
from tests.test_edlt_parent_add_dialog import widget


from pathlib import Path
import json

VECTORS=json.loads((Path(__file__).resolve().parents[1]/
    'research/fixtures/edlt-scene-language-images-vectors.json').read_bytes())
PROFILES={row['kind']:(row['old_name'],row['new_name']) for row in VECTORS['language_cases']}


def image_source(tmp_path, kind='FONT', *, reset=False, reverse=False):
    data=list(language_source(reset=reset)); parent,engine,client,text,values,_old=data
    raw=export_bytes('TEST'); images=parse_project_images(raw,expected_sha256=sha(raw))
    directory=tmp_path/'Images'/'DLTP'; directory.mkdir(parents=True)
    index=b'1,Owned symbol,one.bmp\n';(directory/'Index.txt').write_bytes(index)
    (directory/'one.bmp').write_bytes(bmp(1))
    dltp=load_decoded_dltp_index(tmp_path,expected_sha256=sha(index))
    inputs={'project_images':images,'dltp_index':dltp}
    old,new=PROFILES[kind]
    if reverse: old,new=new,old
    document=minidom.parseString(text)
    # Every native Level has independently specified first variant image facts.
    for level in document.getElementsByTagName('Level'):
        for tag in level.getElementsByTagName('TagDLT'):
            if tag.getElementsByTagName('FlavourID')[0].firstChild.data!='1':continue
            language=tag.getElementsByTagName('LanguageID')[0].firstChild.data
            tag.getElementsByTagName('TagType')[0].firstChild.data=kind
            tag.getElementsByTagName('TagValue')[0].firstChild.data=new if language=='1' else old
    text=document.toxml()
    initializer=resolve_native_scene_metadata(text,UNIT,values,engine,
        [{'op':'get-selector-view','scene':1}],**inputs).cache._inventory_timeline
    return (parent,engine,client,text,values,initializer),inputs,(old,new)


def image_bridge(data, inputs, ops=None):
    ops=ops or [operation()]; engine=data[1]; text=data[3]
    _network,collection,rows=native_inventory(text,UNIT)
    state=initialise(rows,ops[0]['preferences']); mutations=[]
    for number,op in enumerate(ops,1):
        state,receipt=project(state,op)
        assert all(row.oid is not None for row in state.rows)
        receipt.update(rows_after=[row.as_dict() for row in state.rows],operation=number)
        projected=(text if state.rows==rows else
                   replace_native_rows(text,UNIT,state.rows,collection_oid=collection))
        groups,labels=_facts(_snapshot(projected,UNIT,engine,**inputs))
        mutations.append(_NativeLanguageBinding(op='parent-language-binding',
            receipt=receipt,group_images=groups,level_labels=labels))
    bridge=issue_language_initializer(data[5],original_xml=text,projected_xml=projected,
        unit=UNIT,editor=engine,original_values=data[4],operations=ops,
        mutations=tuple(mutations),**inputs)
    return bridge,projected,tuple(mutations)


@pytest.mark.parametrize('kind',PROFILES)
@pytest.mark.parametrize('setter',[False,True],ids=['getter-old','setter-current'])
def test_byte_backed_families_keep_old_bindings_and_adopt_current_only_at_setter(tmp_path,kind,setter):
    data,inputs,names=image_source(tmp_path,kind)
    capability,projected,_mutations=image_bridge(data,inputs)
    ops=([{'op':'set-action','scene':1,'action':7}] if setter else [])
    ops.append({'op':'get-selector-view','scene':1})
    metadata=resolve_native_scene_metadata(projected,UNIT,data[4],data[1],ops,
        _initialization_timeline=capability,**inputs)
    engine=data[1];state=engine.load(data[4],metadata=metadata.cache)
    old=capability.initial_scene_labels(1)
    assert state.scenes[0].dynamic_labels is old
    assert (old[0].name,old[0].image_present)==(names[0],False)
    outcome=engine.edit(state,operations=metadata.operations)
    actual=outcome.state.scenes[0].dynamic_labels
    assert (actual[0].name,actual[0].image_present)==(names[1] if setter else names[0],setter)
    assert (actual is old)==(not setter)
    assert capability.refresh_count==1
    assert metadata.as_dict()['project_images_loaded'] is True
    assert metadata.as_dict()['toolkit_dltp_index']['images_decoded'] is True
    assert data[2].commands==[]


@pytest.mark.parametrize('kind',PROFILES)
def test_changed_default_can_remove_an_image_without_rewriting_old_objects(tmp_path,kind):
    data,inputs,names=image_source(tmp_path,kind,reverse=True)
    capability,_projected,_mutations=image_bridge(data,inputs)
    old=capability.initial_scene_labels(1)
    current=next(row.labels for row in capability.projected_label_template if (row.group,row.action)==(42,7))
    assert (old[0].name,old[0].image_present)==(names[0],True)
    assert (current[0].name,current[0].image_present)==(names[1],False)
    assert all(a is not b for a,b in zip(old,current))


@pytest.mark.parametrize('op',[operation(cancel=True),operation((1,2))],ids=['cancel','noop'])
def test_image_cancel_noop_preserve_original_object_identity_and_generation(tmp_path,op):
    data,inputs,_names=image_source(tmp_path)
    capability,projected,_mutations=image_bridge(data,inputs,[op])
    assert projected==data[3] and capability.refresh_count==0
    metadata=resolve_native_scene_metadata(projected,UNIT,data[4],data[1],
        [{'op':'get-selector-view','scene':1}],_initialization_timeline=capability,**inputs)
    assert metadata.cache._inventory_timeline._initial.refresh_generation==data[5]._initial.refresh_generation
    state=data[1].load(data[4],metadata=metadata.cache)
    assert state.scenes[0].dynamic_labels is capability.initial_scene_labels(1)


@pytest.mark.parametrize('setter',[False,True],ids=['valid-getter','explicit-refresh'])
def test_native_image_parent_prior_language_keeps_causal_epoch(tmp_path,setter):
    data,inputs,names=image_source(tmp_path)
    children=([{'op':'set-action','scene':1,'action':7}] if setter else [])
    children.append({'op':'get-selector-view','scene':1})
    plan=plan_native_parent_metadata(data[3],UNIT,data[0].snapshot(data[2].values),data[0],
        [operation(),{'op':'scene-manager','operations':children},widget()],**inputs)
    view=scene_result(plan)['nested_operation_results'][-1]['view']
    assert (view['dynamic_labels'][0]['name'],view['dynamic_labels'][0]['image_present'])==(names[1] if setter else names[0],setter)
    assert plan.as_dict()['project_images_loaded'] is True
    assert plan.as_dict()['project_image_export']['export_sha256']==inputs['project_images'].export_sha256
    assert plan.parent_plan.as_dict()['execution_counts']['terminal_crc_passes']==1
    assert data[2].commands==[]


def test_later_image_language_does_not_leak_into_earlier_scene_receipt(tmp_path):
    data,inputs,names=image_source(tmp_path)
    result=plan_native_parent_metadata(data[3],UNIT,data[0].snapshot(data[2].values),data[0],
        [{'op':'scene-manager','operations':[{'op':'get-selector-view','scene':1}]},operation(),widget()],**inputs)
    row=scene_result(result)['nested_operation_results'][-1]['view']['dynamic_labels'][0]
    assert (row['name'],row['image_present'])==(names[0],False)
    assert result.scene_metadata.cache._inventory_timeline.as_dict()['binding']['language_initializer_sha256'] is None


def test_image_reset_uses_fresh_eight_scene_owners(tmp_path):
    data,inputs,_names=image_source(tmp_path,reset=True)
    ops=[{'op':'reset','active_tab':'widgets','binding_variant':'audited-local-wiring','dirty_parameters':['UnitAddress']},
        operation(),{'op':'scene-manager','operations':[{'op':'get-selector-view','scene':1}]},widget()]
    result=plan_native_parent_metadata(data[3],UNIT,data[0].snapshot(data[2].values),data[0],ops,**inputs)
    assert result.scene_metadata.cache._inventory_timeline._initial_scene_bindings==((255,-1,0),)*8
    assert scene_result(result)['nested_operation_results'][-1]['view']['dynamic_labels']==[]


def test_image_language_does_not_discard_pending_name(tmp_path):
    data,inputs,_names=image_source(tmp_path)
    ops=[operation(),{'op':'scene-manager','operations':[
        {'op':'scene-name-control','scene':1,'events':[{'event':'input','text':'Pending name'}]},
        {'op':'scene-selector-control','scene':1,'events':[{'event':'scene-current-changed','current':True}]}]},widget()]
    with pytest.raises(ValueError,match='pending|Pending|uncommitted'):
        plan_native_parent_metadata(data[3],UNIT,data[0].snapshot(data[2].values),data[0],ops,**inputs)


@pytest.mark.parametrize('fault',['project-omitted','dltp-omitted','raw-project','same-flags-different-bytes','foreign-project'])
def test_image_initializer_binds_actual_bytes_and_requires_provider_inputs(tmp_path,fault):
    data,inputs,_names=image_source(tmp_path,'ICON' if fault=='dltp-omitted' else 'FONT')
    capability,projected,mutations=image_bridge(data,inputs)
    bad=dict(inputs)
    if fault=='project-omitted':bad['project_images']=None
    if fault=='dltp-omitted':bad['dltp_index']=None
    if fault=='raw-project':bad['project_images']=inputs['project_images'].evidence()
    if fault=='same-flags-different-bytes':
        raw=export_bytes('TEST',entries=[('TEST-DLTD-Pic0001.bmp',bmp(red=False)),('TEST-DLTD-Pic0001.extra.bmp',bmp())])
        bad['project_images']=parse_project_images(raw,expected_sha256=sha(raw))
    if fault=='foreign-project':
        raw=export_bytes('OTHER');bad['project_images']=parse_project_images(raw,expected_sha256=sha(raw))
    with pytest.raises((EdltError,ValueError)):
        check_language_initializer(capability,**bad)
    with pytest.raises((EdltError,ValueError)):
        resolve_native_scene_metadata(projected,UNIT,data[4],data[1],
            [{'op':'get-selector-view','scene':1}],_initialization_timeline=capability,**bad)
    with pytest.raises((EdltError,ValueError)):
        issue_language_initializer(data[5],original_xml=data[3],projected_xml=projected,
            unit=UNIT,editor=data[1],original_values=data[4],operations=[operation()],mutations=mutations,**bad)


def test_consumed_existing_level_extends_original_image_epoch_from_original_xml(tmp_path):
    data,inputs,names=image_source(tmp_path)
    capability,projected,_mutations=image_bridge(data,inputs)
    metadata=resolve_native_scene_metadata(projected,UNIT,data[4],data[1],[
        {'op':'set-trigger','scene':1,'group':43},{'op':'set-action','scene':1,'action':7},
        {'op':'get-selector-view','scene':1}],_initialization_timeline=capability,**inputs)
    old=next(row for row in metadata.cache._inventory_timeline.label_template_at(0)
        if (row.group,row.action)==(43,7))
    assert (old.labels[0].name,old.labels[0].image_present)==(names[0],False)
    assert metadata.creations==()


@pytest.mark.parametrize('field',['projected_label_template','refresh_count'])
@pytest.mark.parametrize('copied',[False,True],ids=['original-seal','copied-seal'])
def test_language_initializer_issuance_rejects_payload_rebinding(tmp_path,field,copied):
    import copy
    data,inputs,_names=image_source(tmp_path)
    value,_projected,_mutations=image_bridge(data,inputs)
    changes={field:() if field=='projected_label_template' else 0}
    if copied:changes['_seal']=copy.copy(value._seal)
    forged=replace(value,**changes)
    with pytest.raises(AttributeError):forged._seal.fingerprint=forged.fingerprint
    with pytest.raises(EdltError,match='foreign|modified'):
        check_language_initializer(forged,**inputs)
    check_language_initializer(value,**inputs)


def test_language_initializer_owner_mutation_cannot_reissue_capability(tmp_path):
    data,inputs,_names=image_source(tmp_path)
    value,_p,_m=image_bridge(data,inputs)
    value._seal.owner=object()
    with pytest.raises(EdltError,match='foreign|owner|modified'):
        check_language_initializer(value,**inputs)
