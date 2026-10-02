"""Text-only Language bridge with owned in-memory XML; no connections."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from xml.dom import minidom

import pytest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_language_add_dialog import (initialise, native_inventory,
    project, replace_native_rows)
from cbus_toolkit.edlt_parent_metadata import _snapshot
from cbus_toolkit.edlt_parent_transaction import _NativeLanguageBinding
from cbus_toolkit.edlt_scene_language_initializer import (issue_language_initializer,
    check_language_initializer, _facts)
from cbus_toolkit.edlt_scene_metadata import resolve_native_scene_metadata
from tests.test_edlt_parent_scene_inventory import source

LITERALS = json.loads((Path(__file__).resolve().parents[1]/
    'research/fixtures/edlt-scene-language-vectors.json').read_bytes())['fixture']
UNIT = '//TEST/254/p/20'


def node(document, name, value):
    result = document.createElement(name)
    result.appendChild(document.createTextNode(value))
    return result


def language_source(*, reset=False, encoded_declaration=False):
    parent, client, _case = source(reset=reset)
    engine = parent._editor('scene-manager')
    document = minidom.parseString(client.xml())
    network = document.getElementsByTagName('Network')[0]
    network.appendChild(node(document, 'OID', '00000000-0000-0000-0000-000000899999'))
    collection = document.createElement('Languages')
    collection.appendChild(node(document, 'OID', '00000000-0000-0000-0000-000000900000'))
    for index, row in enumerate(LITERALS['initial_rows']):
        child = document.createElement('Language')
        for key, value in (('OID',f'00000000-0000-0000-0000-{900001+index:012d}'),
                           ('ID',str(row['id'])), ('TagValue',row['tag_value'])):
            child.appendChild(node(document, key, value))
        collection.appendChild(child)
    network.appendChild(collection)
    # Independent literal text variants, under both old and current default.
    for level in document.getElementsByTagName('Level'):
        existing = [n for n in level.childNodes if n.nodeType==n.ELEMENT_NODE and n.tagName=='TagsDLT']
        for child in existing: level.removeChild(child)
        tags = document.createElement('TagsDLT')
        for language, name_key in ((1,'current_labels'),(2,'old_labels')):
            for variant, text in enumerate(LITERALS[name_key], 1):
                tag = document.createElement('TagDLT')
                for field,value in (('LanguageID',str(language)),('FlavourID',str(variant)),
                                    ('TagType','TEXT'),('TagValue',text)):
                    tag.appendChild(node(document,field,value))
                tags.appendChild(tag)
        level.appendChild(tags)
    network.appendChild(document.createComment('unrelated comment preserved'))
    opaque=document.createElementNS('urn:owned:test','o:Opaque')
    opaque.setAttribute('xmlns:o','urn:owned:test'); opaque.setAttribute('xml:space','preserve')
    opaque.appendChild(document.createTextNode('  exact opaque whitespace  '))
    network.appendChild(opaque)
    text=document.toxml()
    if encoded_declaration:
        text=text.replace('<?xml version="1.0" ?>', '<?xml version="1.0" encoding="utf-8"?>', 1)
    values=engine.snapshot(client.values)
    initializer=resolve_native_scene_metadata(text,UNIT,values,engine,
        [{'op':'get-selector-view','scene':1}]).cache._inventory_timeline
    return parent,engine,client,text,values,initializer


def lower(text,engine,operations):
    _network,collection,rows=native_inventory(text,UNIT)
    first=next(row for row in operations if row['op']=='add-language-dialog')
    state=initialise(rows,first['preferences']); mutations=[]; next_key=0
    for index,operation in enumerate(operations,1):
        if operation['op']!='add-language-dialog': continue
        state,receipt=project(state,operation)
        for identifier in [row.identifier for row in state.rows if row.oid is None]:
            key=f'@language-{next_key}';next_key+=1
            state=replace(state,rows=tuple(replace(row,oid=key)
                if row.oid is None and row.identifier==identifier else row for row in state.rows))
            for row in receipt['created_rows']:
                if row['oid'] is None and row['id']==identifier:row['oid']=key
        receipt.update(rows_after=[row.as_dict() for row in state.rows],operation=index)
        projected=(text if state.rows==rows else
                   replace_native_rows(text,UNIT,state.rows,collection_oid=collection or '@languages'))
        images,labels=_facts(_snapshot(projected,UNIT,engine))
        mutations.append(_NativeLanguageBinding(op='parent-language-binding',receipt=receipt,
            group_images=images,level_labels=labels))
    return projected,tuple(mutations)


def operation(ids=(1,),cancel=False):
    return {'op':'add-language-dialog','selected_ids':list(ids),'cancel':cancel,
            'preferences':'registered-defaults'}


def bridge(data,operations=None):
    _parent,engine,_client,text,values,initializer=data
    operations=operations or [operation()]
    projected,mutations=lower(text,engine,operations)
    result=issue_language_initializer(initializer,original_xml=text,projected_xml=projected,
        unit=UNIT,editor=engine,original_values=values,operations=operations,mutations=mutations)
    return result,projected,mutations


def test_changed_default_keeps_all_eight_original_label_owners_and_current_text():
    data=language_source();result,_projected,_mutations=bridge(data)
    engine,initializer=data[1],data[5]
    cursor=initializer.start(initializer._template,source_values=data[4],owner=engine._owner)
    assert result.refresh_count==1
    assert result.initial_scene_bindings==initializer._initial_scene_bindings
    for slot in range(1,9):
        assert result.initial_scene_labels(slot) is cursor.initial_scene_labels(slot)
    labels=next(row.labels for row in result.projected_label_template if (row.group,row.action)==(42,7))
    assert [row.name for row in result.initial_scene_labels(1)]==LITERALS['old_labels']
    assert [row.name for row in labels]==LITERALS['current_labels']
    assert all(a is not b for a,b in zip(result.initial_scene_labels(1),labels))
    assert data[2].commands==[]


@pytest.mark.parametrize('op',[operation(cancel=True),operation((1,2))],ids=['cancel','noop'])
def test_cancel_or_same_rows_has_no_refresh(op):
    data=language_source(); result,_p,_m=bridge(data,[op])
    assert result.refresh_count==0
    assert [row.name for row in result.initial_scene_labels(1)]==LITERALS['old_labels']
    assert [row.name for row in result.projected_label_template[0].labels]==LITERALS['old_labels']


@pytest.mark.parametrize('fault',['raw','foreign','pp','xml','receipt','future','scene'])
def test_raw_foreign_stale_and_unrelated_projection_refuse(fault):
    data=language_source(); _parent,engine,_client,text,values,initializer=data
    operations=[operation()]; projected,mutations=lower(text,engine,operations)
    if fault=='raw':mutations=tuple(dict(row) for row in mutations)
    if fault=='foreign':engine=type(engine)(engine.spec)
    if fault=='pp':values={**values,'PrimaryApplication':(57,)}
    if fault=='xml':projected=projected.replace('exact opaque whitespace','tampered opaque text')
    if fault=='scene':
        document=minidom.parseString(projected)
        parameter=next(row for row in document.getElementsByTagName('PP')
                       if row.getAttribute('Name')=='Scene1StartAddress')
        parameter.setAttribute('Value','5' if parameter.getAttribute('Value')!='5' else '10')
        projected=document.toxml()
    if fault=='receipt':
        changed=deepcopy(dict(mutations[0]));changed['receipt']['default_after']=2
        mutations=(_NativeLanguageBinding(changed),)
    if fault=='future':operations.append(operation((1,2)))
    with pytest.raises((EdltError,ValueError)):
        issue_language_initializer(initializer,original_xml=text,projected_xml=projected,
            unit=UNIT,editor=engine,original_values=values,operations=operations,mutations=mutations)


@pytest.mark.parametrize('kind',['FONT','DYNAMIC','ICON','Image','DLTP'])
def test_image_profiles_refuse_before_receipt_projection(kind):
    data=language_source();_parent,engine,_client,text,values,initializer=data
    if kind in ('Image','DLTP'):
        projected=text.replace('</Network>',f'<{kind}/></Network>')
    else:projected=text.replace('<TagType>TEXT</TagType>',f'<TagType>{kind}</TagType>',1)
    with pytest.raises(EdltError,match='text-only|Image/DLTP'):
        issue_language_initializer(initializer,original_xml=text,projected_xml=projected,
            unit=UNIT,editor=engine,original_values=values,operations=[operation()],mutations=(_NativeLanguageBinding({}),))


def test_public_receipt_cannot_recreate_capability_and_mutation_is_detected():
    data=language_source(); result,projected,_m=bridge(data)
    with pytest.raises(EdltError,match='foreign|serialized'):
        check_language_initializer(result.as_dict())
    with pytest.raises(EdltError,match='provenance'):
        check_language_initializer(result,projected_xml=projected+'\n')
    forged=replace(result,refresh_count=0)
    with pytest.raises(EdltError,match='modified'):
        check_language_initializer(forged)


def test_repeated_changed_then_canceled_prefix_reprojects_exactly():
    data=language_source(); result,_p,_m=bridge(data,[operation(),operation((1,2),cancel=True)])
    assert result.refresh_count==1
    assert result.as_dict()['binding']['default_after']==1
    assert len(result.as_dict()['binding']['language_receipts'])==2


def test_static_proof_binds_default_before_reload_and_no_executed_original():
    proof=json.loads((Path(__file__).resolve().parents[1]/'research/fixtures/edlt-scene-language-static.json').read_bytes())
    assert len(proof['managed_method_spans'])==12
    assert len(proof['static_checks'])+len(proof['retained_refresh_bridge_checks'])==11
    assert proof['contract']['default_before_labels'] is True
    assert proof['contract']['original_instructions_executed'] is False
    assert proof['contract']['implicit_callback_schedule_verified'] is False


@pytest.mark.parametrize('identifier',[0,1],ids=['duplicate-default','duplicate-real-language'])
def test_duplicate_native_languages_remain_refused(identifier):
    data=language_source();_parent,engine,_client,text,values,initializer=data
    projected,mutations=lower(text,engine,[operation()])
    document=minidom.parseString(projected)
    collection=document.getElementsByTagName('Languages')[0]
    existing=next(row for row in collection.getElementsByTagName('Language')
                  if row.getElementsByTagName('ID')[0].firstChild.data==str(identifier))
    collection.appendChild(existing.cloneNode(True))
    with pytest.raises(ValueError,match='duplicate'):
        issue_language_initializer(initializer,original_xml=text,projected_xml=document.toxml(),
            unit=UNIT,editor=engine,original_values=values,operations=[operation()],mutations=mutations)


def test_new_text_language_row_has_one_explicit_refresh_and_no_default_guess():
    data=language_source(); result,_p,_m=bridge(data,[operation((1,2,74))])
    receipt=result.as_dict()['binding']['language_receipts'][0]
    assert receipt['created_rows']==[{'id':74,'tag_value':'French','oid':'@language-0'}]
    assert result.refresh_count==1
    assert result.as_dict()['binding']['default_after']==2
    assert [row.name for row in result.projected_label_template[0].labels]==LITERALS['old_labels']
