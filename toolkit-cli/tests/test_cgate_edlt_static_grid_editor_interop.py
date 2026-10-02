"""Retained grid editor histories through public CLI and owned Rust services."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit.programming import Programmer
import test_cgate_edlt_parent_add_dialog_interop as parent
from test_cgate_barcode_database_interop import FaultGate, graph
from test_cgate_edlt_scene_add_dialog_interop import snapshot

VECTOR=Path(__file__).resolve().parents[2]/'rust/testdata/vectors/cgate_edlt_static_grid_editor_wire.json'
FACTS=json.loads(VECTOR.read_text());BACKENDS=parent.BACKENDS


def tree(value):
    return ET.fromstring(value,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))


@contextmanager
def journey(backend,variable,tmp_path,case):
    try:
        with parent.journey(backend,variable,tmp_path,{}) as data:
            owner,relay,evidence,specs,endpoint=data
            evidence.update(format='cbus-edlt-static-grid-editor-owned-v1',
                vector_sha256=hashlib.sha256(VECTOR.read_bytes()).hexdigest())
            assert owner.command('DBADDSAFE //TEST/254/56 Group 12 Lighting').code==301
            if case.get('seed_rows'):
                with Programmer(owner).load('//TEST/254','/db//TEST/254/p/20') as session:
                    for index,encoded in case['seed_rows'].items():
                        raw=bytes.fromhex(encoded);assert len(raw)==64
                        assert session.set('StaticTextString'+index,' '.join(map(str,raw))).code==200
                    assert session.save_to_source().code==200
            assert owner.command('PROJECT SAVE TEST').code==200
            before=snapshot(owner)
            evidence['snapshots']={'before':before}
            yield owner,relay,evidence,specs,endpoint,before
    finally:
        evidence_path=tmp_path/'parent-add-evidence.json'
        if evidence_path.exists():evidence_path.rename(tmp_path/'static-grid-editor-evidence.json')


def check(before,after,case,call):
    old,new=tree(before),tree(after)
    baseline,actual=parent.values(old),parent.values(new)
    for index,encoded in case['final_rows'].items():
        assert bytes(actual['StaticTextString'+index])==bytes.fromhex(encoded).ljust(64,b'\0')
    for index in case.get('unchanged_seed_rows',[]):
        assert actual['StaticTextString'+str(index)]==baseline['StaticTextString'+str(index)]
    if 'scene_name_index' in case:
        assert actual['Scene1StartAddress']==[0]
        assert actual['SceneBucket'][case['scene_name_byte_offset']]==case['scene_name_index']
    assert (actual['Widget6WidgetType'],actual['Widget6WidgetByteValue1'],actual['Widget6WidgetByteValue2'])==([12],[42],[1])
    # Independent retained Measurement default record, with explicit device/channel.
    for offset,value in enumerate((42,1,2,1,0,0,0,0,0,255,255,135,64),1):
        assert actual[f'Widget6WidgetByteValue{offset}']==[value]
    allowed={'OverallCRC','GlobalParameterCRC','WidgetsCRC','StaticTextCRC','ScenesCheckSum','SceneBucket','WidgetGroups',
             'Widget6WidgetType',*[f'Widget6WidgetByteValue{i}' for i in range(1,14)]}
    allowed.update('StaticTextString'+index for index in case['final_rows'])
    if 'widget_label_index' in case:
        assert actual['Widget7WidgetByteValue13']==[case['widget_label_index']]
        assert actual['Widget7WidgetType']==[2]
        expected={1:48,2:2,3:1,6:12,7:15,8:16,9:1,10:255,11:255,12:25,13:case['widget_label_index']}
        for offset,value in expected.items():
            assert actual[f'Widget7WidgetByteValue{offset}']==[value]
        for offset in (4,5):
            assert actual[f'Widget7WidgetByteValue{offset}']==baseline[f'Widget7WidgetByteValue{offset}']
        assert actual['StaticTextString63']==baseline['StaticTextString63']
        allowed.update({'Widget7WidgetType','Widget8WidgetType',*[f'Widget7WidgetByteValue{i}' for i in range(1,14)]})
    changed={name for name in actual if actual[name]!=baseline[name]}
    assert changed<=allowed,changed-allowed
    unit=new.find("Project/Network/Unit[Address='20']")
    old_unit=old.find("Project/Network/Unit[Address='20']")
    for node in unit.findall('PP'):
        if node.get('Name') in allowed:
            node.set('Value',old_unit.find("PP[@Name='"+node.get('Name')+"']").get('Value'))
    assert graph(ET.tostring(new,encoding='unicode'))==graph(before)
    commands=call['commands']
    assert not any(c.startswith(('DBADD','DBSET','DBDELETE')) for c in commands)
    assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands)==1
    assert commands.count('PROJECT SAVE TEST')==2
    assert commands.count('PROJECT COPY TEST PABACKUP')==1
    assert commands.count('PROJECT CLOSE TEST')==1 and commands.count('PROJECT LOAD TEST')==1
    for index,c in enumerate(commands):
        if c.startswith(('PP SET ','PP SAVE_TO_SOURCE ','PROJECT SAVE ','PROJECT CLOSE ','PROJECT LOAD ')):
            assert call['statuses'][index]==200


def check_scene_name_result(result,case):
    if 'scene_name_index' not in case:
        return
    plan=result.get('plan',result)['parent_transaction']
    rows=[row for row in plan['operation_results']
          if row['format']=='cbus-edlt-parent-scene-manager-operation-v1']
    assert len(rows)==1
    nested=rows[0]['nested_operation_results']
    assert len(nested)==1
    allocations=(nested[0]['static_text_allocation'],
                 rows[0]['composition']['static_text']['allocations'][0])
    for allocation in allocations:
        assert allocation['text']==case['scene_name_text']
        assert allocation['reused'] is True
        assert allocation['index']==case['scene_name_index']


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
@pytest.mark.parametrize('case',FACTS['cases'],ids=lambda row:row['id'])
def test_public_static_grid_history_preview_apply_and_preservation(backend,variable,case,tmp_path):
    with journey(backend,variable,tmp_path,case) as (owner,relay,evidence,specs,_endpoint,before):
        preview,read=parent.invoke(relay,evidence,specs,tmp_path,case,dry_run=True)
        check_scene_name_result(preview,case)
        assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT SAVE','PROJECT COPY','PP SET','PP SAVE')) for c in read['commands'])
        assert snapshot(owner)==before
        result,call=parent.invoke(relay,evidence,specs,tmp_path,case)
        assert result['saved'] and result['target_project_save_confirmed'] and result['persistence_verified']
        check_scene_name_result(result,case)
        after=snapshot(owner);check(before,after,case,call)
        evidence['snapshots']['after']=after


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
def test_public_pending_cell_close_refuses_without_write(backend,variable,tmp_path):
    case=FACTS['pending_close_refusal']
    with journey(backend,variable,tmp_path,case) as (owner,relay,evidence,specs,_endpoint,before):
        result,call=parent.invoke(relay,evidence,specs,tmp_path,case,expected=1)
        assert 'Pending static cell close' in str(result)
        assert not any(c.startswith(('DBADD','DBSET','DBDELETE','PROJECT SAVE','PROJECT COPY','PP SET','PP SAVE')) for c in call['commands'])
        assert snapshot(owner)==before


@pytest.mark.parametrize('backend,variable',BACKENDS,ids=('mock','daemon'))
def test_public_static_grid_lost_successful_save_is_not_replayed(backend,variable,tmp_path):
    case=FACTS['cases'][0]
    with journey(backend,variable,tmp_path,case) as (owner,_relay,evidence,specs,endpoint,before):
        with FaultGate(endpoint,'PP SAVE_TO_SOURCE','drop') as fault:
            result,call=parent.invoke(fault,evidence,specs,tmp_path,case,expected=1,complete=False)
            assert fault.matches==1
            commands=call['commands'];save=next(i for i,c in enumerate(commands) if c.startswith('PP SAVE_TO_SOURCE '))
            assert sum(c.startswith('PP SAVE_TO_SOURCE ') for c in commands)==1
            assert not any(c.startswith(('PP SET','PP SAVE','PROJECT SAVE','PROJECT CLOSE','PROJECT LOAD','DBDELETE')) for c in commands[save+1:])
            rows=[row for row in fault.evidence() if row.get('fault')]
            assert len(rows)==1
            assert bytes.fromhex(rows[0]['lost_backend_terminal_hex']).decode()==f"[{rows[0]['fault']['tag']}] 200 OK\r\n"
            assert 'uncertain' in str(result).lower()
            evidence['lost_save_wires']=fault.evidence()
        actual=parent.values(tree(snapshot(owner)))
        assert actual['StaticTextString3'][:10]==list(b'Committed\0')
        assert actual['StaticTextString4'][:8]==list(b'Focused\0')
