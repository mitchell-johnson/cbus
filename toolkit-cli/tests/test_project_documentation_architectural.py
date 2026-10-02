"""Independent literal architectural bodies, native usage and bounded loaders."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_architectural as body
from cbus_toolkit import project_documentation_architectural_loader as loader
from cbus_toolkit import project_documentation_architectural_usage as usage

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'research/fixtures/project-documentor-architectural-literal.json'
PROOF = ROOT / 'research/fixtures/project-documentor-architectural-static.json'
CASES = json.loads(VECTOR.read_text())['cases']


def unit(row=None, **changes):
    row = row or CASES[0]
    pp = deepcopy(row['parameters'])
    pp.update(changes)
    return doc.Unit(row['address'],row['id'],row['unit_type'],'','',row['firmware'],'',{
        k:v if isinstance(v,str) else ' '.join(map(str,v)) for k,v in pp.items() if v is not None}, {})


def network():
    raw = json.loads(VECTOR.read_text())['network']
    return doc.Network(raw['address'],raw['name'],'','',[
        doc.Application(a['address'],a['name'],'',[doc.Group(g['address'],g['name'],'',[
            doc.Level(l['address'],l['name'],l['value']) for l in g['levels']]) for g in a['groups']])
        for a in raw['applications']],[])


@pytest.mark.parametrize('row',CASES,ids=lambda row:row['id'])
def test_exact_literal_body_and_immutable_inputs(row):
    u,net = unit(row),network()
    before = deepcopy((u,net))
    assert body.architectural_body_lines(net,u)==row['body_lines']
    out = doc._Writer()
    assert body.document_architectural(out,net,u)=='recovered'
    assert out.lines[-len(row['body_lines']):]==row['body_lines']
    assert not out.unrecovered and (u,net)==before


@pytest.mark.parametrize('row',CASES,ids=lambda row:row['id'])
def test_literal_group_and_action_identity(row):
    u=unit(row)
    for p in row['group_usage']:
        actual=usage.architectural_group_usage(u,p['application'],p['group'],p['kind'])
        assert actual.status=='recovered',actual.missing
        assert actual.html==p['html']
    for p in row['actions']:
        actual=usage.architectural_action_selector_usage(u,p['application'],p['group'],p['address'],p['value'])
        assert actual.status=='recovered',actual.missing
        assert actual.html==p['html']


@pytest.mark.parametrize('level,line,expected',[(0,240,0),(25,240,51),(29,240,56),(33,240,60),
                                             (27,240,54),(26,240,52),(190,240,224),(230,240,238),
                                             (255,270,270),(255,0,0),(255,65535,65535)])
def test_fixed_rms_table_interpolation_and_scaling(level,line,expected):
    assert loader.rms_voltage(level,line)==expected


@pytest.mark.parametrize('word,expected',[(0,(0,0,0,0)),(65,(0,0,1,5)),(0x4007,(0,0,1,10)),
                                         (0x8002,(0,0,2,0)),(0x3fff,(0,4,33,3)),
                                         (0x7fff,(1,21,30,30)),(0xbfff,(11,9,3,0)),
                                         (0xc001,(0,0,0,0)),(0xffff,(0,0,0,0))])
def test_all_packed_fade_units(word,expected):
    assert loader.cross_fade_parts(word)==expected


@pytest.mark.parametrize('raw,expected',[(0,0),(1,1),(127,128),(128,129),(200,201),(254,255),(255,255)])
def test_scene_254_scale_before_percent(raw,expected):
    assert loader.scene_level(raw)==expected


def test_sparse_all_128_slots_and_first_channel_wins():
    scenes=loader.architectural_scenes(unit())
    assert [s.slot for s in scenes]==[1,33,128]
    assert [s.name for s in scenes]==['Evening <one>','New Scene','Final']
    assert [(c.group,c.fade,c.target,c.inhibit) for c in scenes[0].channels]==[(1,1,128,0),(1,15,255,0)]
    assert [(c.group,c.fade,c.target,c.inhibit) for c in scenes[0].groups]==[(1,1,128,0)]
    assert [(c.group,c.fade,c.target,c.inhibit) for c in scenes[2].groups]==[(1,258,25,0),(255,60,255,7)]


def test_same_group_duplicate_channels_keep_dmx_usage_duplicates():
    u=unit(DMXDisableOperation=[0,0,0])
    assert usage.architectural_group_usage(u,56,1,'input').html == 'DMX Disable Update C-Bus Level<br/>DMX Disable Update C-Bus Level<br/>Scene 1<br/>Scene 2<br/>Scene 3'
    u.parameters['DMXModeEnabled']='1'
    assert usage.architectural_group_usage(u,56,1,'input').html == 'Scene 1<br/>Scene 2<br/>Scene 3'


def test_special_channels_do_not_invent_prepared_groups_or_halogen_scene_selector():
    u=unit(SceneUsed=[0]*128,TriggerErrorGroup=[255])
    assert usage.architectural_group_usage(u,56,1,'input').html=='DMX Disable Update C-Bus Level'
    assert usage.architectural_action_selector_usage(u,202,6,9,88).html==''
    assert 'Halogen Clean</td>' in ''.join(body.architectural_body_lines(network(),u))


def test_little_endian_dmx_word_and_current_mask_gate():
    u=unit(CASES[1],DMXChannelMapping=[2,1,0,2,255,255,1,0,1,0,1,0],DMXChannelMaskCurrent=[1,0,1,0,1,0])
    assert loader.architectural_data(u)['dmx']==(258,0,65535,0,1,0)


def test_unconsumed_curve_points_and_channel_output_alias_do_not_affect_body():
    u=unit(DimmingCurveAX=None,DimmingCurveAY=None,DimmingCurveBX=None,DimmingCurveBY=None,ChannelOutputGroups=[44,45,46])
    assert body.architectural_body_lines(network(),u)==CASES[0]['body_lines']


def test_exact_38_utf16_name_units_and_source_trim():
    data=loader.architectural_scenes(unit(Scene001Name=' \t\v'+('x'*36)+'😀'+' tail\r\n'))
    assert data[0].name == 'x'*36+'😀'
    with pytest.raises(ValueError,match='split-surrogate'):
        loader.architectural_scenes(unit(Scene001Name='x'*37+'😀'))


def test_nonzero_boolean_bytes_normalize_before_mask_inversion():
    data=loader.architectural_data(unit(ChannelMask1=[255,2,0],DMXChannelMask1=[255,2,0]))
    assert data['cbus_masks'][0] == (False,False,True)
    assert data['dmx_masks'][0] == (True,True,False)


@pytest.mark.parametrize('row', CASES, ids=lambda row: row['id'])
def test_last_sparse_scene_scales_every_factory_channel_count(row):
    count = loader.PROFILES[row['unit_type']][1]
    raw = [6, 9] + [0, 0, 254, 0] * count
    u = unit(row, SceneUsed=[0]*127+[1], SceneHasName=[0]*128,
             SceneNormal=[1]*128, SceneUsesRampRate=[0]*128, Scene128Data=raw,TriggerErrorGroup=[255])
    scenes = loader.architectural_scenes(u)
    assert len(scenes) == 1 and scenes[0].slot == 128 and scenes[0].name == 'New Scene'
    assert [c.channel for c in scenes[0].channels] == list(range(count))
    assert all((c.target,c.fade,c.inhibit) == (255,0,0) for c in scenes[0].channels)
    assert usage.architectural_action_selector_usage(u,202,6,9,88).html == '<li />Triggers Scene 1'


def test_existing_selector_address255_is_not_an_unused_trigger_group():
    u = unit(TriggerErrorAcSel=[255], TriggerErrorClearAcSel=[255])
    pp = CASES[0]['parameters']['Scene001Data'][:]
    pp[1] = 255
    u.parameters['Scene001Data'] = ' '.join(map(str, pp))
    net = network()
    net.application(202).group(6).levels.append(doc.Level(255, 'Explicit selector255', 9))
    assert usage.architectural_action_selector_usage(u,202,6,255,9).html == '<li />Trigger Error Report<li />Trigger Error Report Clear<li />Triggers Scene 1'
    assert '<a href="#254_202_6_255">Explicit selector255</a>' in ''.join(body.architectural_body_lines(net,u))
    u.parameters['TriggerErrorGroup'] = '255'
    assert usage.architectural_action_selector_usage(u,202,255,0,0).html == ''


def test_empty_scene_and_unused_control_fields_are_not_consumed():
    u = unit(CASES[1], SceneHasName=None,SceneNormal=None,SceneUsesRampRate=None,
             FanKickstartTime=None,ChannelMask1=None,ChannelMask2=None,ChannelMask3=None,ChannelMask4=None,
             DMXOnFadeTime=None,DMXOffFadeTime=None,DMXDisableOperation=None,DMXDisableRampRate=None,
             HalogenCleanActionSelector=None,HalogenFadeOn=None,HalogenCleanDuration=None,CBusLossFadeTime=None)
    assert body.architectural_body_lines(network(),u) == CASES[1]['body_lines']


def test_integer_special_durations_are_not_byte_truncated():
    lines = body.architectural_body_lines(network(),unit(CBusLossFadeTime=[300],HalogenFadeOn=[512],HalogenCleanDuration=[1024]))
    assert '<td>300 s</td>' in ''.join(lines)
    assert '<td>512 s</td><td>1024 m</td>' in ''.join(lines)
    with pytest.raises(ValueError,match='HalogenCleanDuration'):
        body.architectural_body_lines(network(),unit(HalogenCleanDuration=[65536]))


@pytest.mark.parametrize('field',['Application','GroupAddress','DimmingCurve','MinDimmingLevel','MaxDimmingLevel',
                                  'ChannelMaxLevelA','NominalLineVoltage','TurnOnThreshold','ChannelEnableGroup',
                                  'DMXEnableGroup','DMXChannelMapping','LogicGA13Associations','LogicFunction','SceneUsed',
                                  'SceneHasName','SceneNormal','SceneUsesRampRate','Scene033Data','Scene128Name',
                                  'SceneDryContact1','HalogenCleanTriggerGroup','DMXChannelMask1','ChannelMask1'])
def test_consumed_absence_is_explicit_and_body_atomic(field):
    u=unit(**{field:None})
    with pytest.raises(ValueError,match=field):body.architectural_body_lines(network(),u)
    out=doc._Writer()
    assert body.document_architectural(out,network(),u)=='partial'
    assert out.unrecovered and not any('Special Scenes' in s for s in out.lines)


@pytest.mark.parametrize('field,value',[('ChannelMask1',[-1,0,0]),('DimmingCurve',[-1,0,0]),
                                        ('SceneUsed',[0]*127),('DMXDisableRampRate',[0,16,15]),
                                        ('NominalLineVoltage',[65536]),('Scene001Data',[6,9,16,0,127,0,15,0,254,0,0,0,0,8])])
def test_invalid_consumed_domains_refuse(field,value):
    with pytest.raises(ValueError):body.architectural_body_lines(network(),unit(**{field:value}))


@pytest.mark.parametrize('firmware',['','oops','10','-1','2147483648'])
def test_unproved_firmware_refuses(firmware):
    u=unit();u.firmware=firmware
    assert usage.architectural_group_usage(u,56,1,'output').status=='unrecovered'
    assert usage.architectural_action_selector_usage(u,202,6,9,88).status=='unrecovered'


def test_missing_native_link_refuses_instead_of_auto_creation():
    net=network();net.application(202).group(6).levels=[]
    with pytest.raises(ValueError,match='Level 9'):body.architectural_body_lines(net,unit())
    net=network();net.application(56).groups=[g for g in net.application(56).groups if g.address!=2]
    with pytest.raises(ValueError,match='Group 2'):body.architectural_body_lines(net,unit())


def test_consumption_is_scoped_for_early_empty_actions():
    u=unit(SceneUsed=[0]*128,TriggerErrorGroup=[255],GroupAddress=None,SceneHasName=None,SceneNormal=None)
    assert usage.architectural_action_selector_usage(u,202,6,9,88).html==''
    assert usage.architectural_action_selector_usage(u,56,6,9,88).status=='recovered'
    assert usage.architectural_group_usage(u,202,6,'other').status=='recovered'


def test_source_proof_pins_owned_producers_without_original_execution():
    proof=json.loads(PROOF.read_text())
    assert proof['original_executed'] is False and proof['original_generated_page_comparison']=='not_obtained'
    assert all(proof['checks'].values()) and len(proof['profiles'])==4
    for name,digest in proof['model_module_sha256'].items():
        path=ROOT/'src/cbus_toolkit'/name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
