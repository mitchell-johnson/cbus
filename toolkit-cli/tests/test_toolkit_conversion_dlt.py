"""DLT conversion rules using public synthetic PP layouts and literal oracles."""
from argparse import Namespace
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from cbus_toolkit import toolkit_conversion_dlt as dlt
from cbus_toolkit import toolkit_conversion_tweakers as tweaks
from cbus_toolkit.toolkit_tweaker_workflow import prepare
from cbus_toolkit.unitspec import UnitSpecStore
ROOT = Path(__file__).resolve().parents[2]
VECTOR = json.loads((ROOT / 'rust/testdata/vectors/toolkit_conversion_dlt.json').read_text())
PAIRS = [(s,t) for (s,t),c in tweaks.REGISTRY.items() if c in dlt.TWEAKERS and (s,t) not in tweaks.PAIR_REFUSALS]


def profile_files(directory, source, target):
    """Public synthetic defaults; never copied from vendor specifications."""
    directory.mkdir(parents=True, exist_ok=True)
    values = {}
    for unit_type,is_source in ((source,True),(target,False)):
        filename,declared = dlt.specification(unit_type)
        fw = dlt.source_firmware(unit_type) if is_source else dlt.TARGET_FIRMWARE
        classic = unit_type in dlt.CLASSIC_TYPES
        shapes = {'Application':('int',2,8),'UnitAddress':('int',1,8),'UnitName':('sixbit',8,6),'Project':('sixbit',8,6),
            'GroupAddress':('int',8 if classic else 9,8),'IndicatorFunction':('int',4 if classic else 8,2),
            'IndicatorBrightness':('int',1,8),**{n:('bit',1,8) for n in ('LearnMode','LearnAnyApp','LearnedFlag')}}
        if not classic:
            shapes.update(FirstKeyThrowAway=('bit',1,8),KeyDisableGroup=('int',1,8),KeyDisableGroupInvert=('bit',1,8))
            if unit_type not in dlt.DLT_TYPES:
                shapes.update({n:('bit',1,8) for n in ('EnableNightlightOnPCx','EnableNightlightOnPA6')})
        if unit_type in dlt.DLT_TYPES:
            shapes.update(EnablePageFallback=('bit',1,8),IndicatorMode=('int',1,2),
                EnableNightlightOnToggleKey=('bit',1,8),EnableNightlightOnUserKeys=('bit',1,8),
                LabelFlavourLSB=('int',8,1),LabelFlavourMSB=('int',8,1))
        root = ET.Element('UnitSpecification')
        for key,value in (('Type',declared),('MinVersion',fw),('MaxVersion',fw),('MemorySize','2048')):
            ET.SubElement(root,key).text = value
        params = ET.SubElement(root,'Parameters')
        for index,(name,(kind,count,width)) in enumerate(shapes.items()):
            default = ('TARGET' if name == 'UnitName' else 'WFTEST' if name == 'Project' else
                ' '.join(['1' if name in ('LabelFlavourLSB','LabelFlavourMSB','EnablePageFallback','IndicatorMode') else '0']*count))
            p = ET.SubElement(params,'Param')
            for key,value in (('Name',name),('Type',kind),('Address',str(index*16)),('ArraySize',str(count)),('BitSize',str(width)),('DefaultValue',default)):
                ET.SubElement(p,key).text = value
            if is_source: values[name] = default
        (directory/filename).write_bytes(ET.tostring(root))
    values.update(UnitAddress='20',UnitName='SOURCE',Application='56 255',
        GroupAddress='0 10 254 255 173 81 82 83'+('' if source in dlt.CLASSIC_TYPES else ' 84'),
        IndicatorFunction='0 1 2 3'+('' if source in dlt.CLASSIC_TYPES else ' 3 2 1 0'),
        IndicatorBrightness='2',LearnMode='1',LearnAnyApp='0',LearnedFlag='1')
    if source not in dlt.CLASSIC_TYPES:
        values.update(FirstKeyThrowAway='1',KeyDisableGroup='17',KeyDisableGroupInvert='1')
        if source not in dlt.DLT_TYPES: values.update(EnableNightlightOnPCx='1',EnableNightlightOnPA6='0')
        else: values.update(EnablePageFallback='0',IndicatorMode='2',EnableNightlightOnToggleKey='1',
            EnableNightlightOnUserKeys='1',LabelFlavourLSB='1 0 1 0 1 0 1 0',LabelFlavourMSB='0 1 0 1 0 1 0 1')
    catalog = ET.Element('CBusUnits')
    for unit_type in dict.fromkeys((source,target)):
        for number in ('SYNTHETIC','TARGET'):
            unit = ET.SubElement(catalog,'Unit');ET.SubElement(unit,'CatalogNumber').text=number
            rev = ET.SubElement(ET.SubElement(unit,'Revisions'),'Revision')
            for name,value in (('UnitType',unit_type),('MinVersion',dlt.source_firmware(unit_type)),
                ('MaxVersion',dlt.source_firmware(unit_type)),('UnitSpecName',dlt.specification(unit_type)[0]),('IsDefault','true')):
                ET.SubElement(rev,name).text=value
    (directory/'cbusunits.xml').write_bytes(ET.tostring(catalog))
    return {'source_spec':dlt.specification(source)[0],'target_spec':dlt.specification(target)[0],
        'source_firmware':dlt.source_firmware(source),'firmware':dlt.TARGET_FIRMWARE,'source_values':values}


def arguments(directory,source,target,**changes):
    p=profile_files(directory,source,target)
    return Namespace(**({'source':'//WFTEST/11/p/20','source_type':source,'target_type':target,
        'source_spec':p['source_spec'],'target_spec':p['target_spec'],'spec_dir':directory,
        'firmware':p['firmware'],'catalog_number':'SYNTHETIC','target_address':21,'tag_name':'Replacement',
        'apply':False,'exclusive_project':False,'expect_plan_sha256':None,'auth_token_file':None}|changes))


def test_every_recovered_dlt_registration_has_a_concrete_public_profile(tmp_path):
    from cbus_toolkit.toolkit_tweaker_lifecycle import prepare as prepare_replace
    assert len(PAIRS)==120
    for source,target in PAIRS:
        p=prepare(arguments(tmp_path/(source+'-'+target),source,target))
        assert p.source_type==source and p.target_type==target and p.spec_pins and p.firmware=='2.1.00'
        args=arguments(tmp_path/(source+'-'+target),source,target,backup_project='BACKUP',journal=None)
        replaced=prepare_replace(args)
        assert replaced.creation.source_type==source and replaced.creation.target_type==target
    assert sum(c in dlt.TWEAKERS for c in tweaks.REGISTRY.values())==132
    for target in ('KEYDL4','KEYML5','KEYBL5'):
        with pytest.raises(tweaks.TweakerRefused,match='factory/model'): tweaks.admitted('KEYM6',target)
        for source in ('KEYBIR2','KEYBIR4','KEYBIR6'):
            with pytest.raises(tweaks.TweakerRefused,match='specification identity'): tweaks.admitted(source,target)


@pytest.mark.parametrize('case',VECTOR['cases'],ids=lambda row:row['id'])
def test_literal_dlt_transform_and_fresh_default_tail(case,tmp_path):
    p=profile_files(tmp_path,case['source'],case['target']);p['source_values'].update(case.get('source_values',{}))
    spec=UnitSpecStore(tmp_path).load(p['target_spec'])
    plan=tweaks.plan_writes(case['source'],case['target'],p['source_values'],set(spec.parameters),target_firmware='2.1.00')
    expected=tweaks.expected_values(spec,{n:p.default for n,p in spec.parameters.items()},plan)
    for name,value in case['expected'].items(): assert expected[name]==tuple(value),(name,plan.as_dict())
    for name in case.get('not_written',[]): assert name not in [n for n,_,_ in plan.writes]
    for name,value in case.get('literal_writes',{}).items():
        assert [(n,v) for n,v,_ in plan.writes if n==name]==[(name,value)]
    assert plan.model_context['inherited_conversion_hooks_called'] is False
    assert plan.model_context['source_firmware']==p['source_firmware']


def test_constructor_duplicate_order_is_retained_without_nightlight_colour(tmp_path):
    p=profile_files(tmp_path,'KEYB2','KEYBL5')
    plan=tweaks.plan_writes('KEYB2','KEYBL5',p['source_values'],set(UnitSpecStore(tmp_path).load(p['target_spec']).parameters),target_firmware='2.1.00')
    names=[n for n,_,_ in plan.writes]
    assert names.count('KeyDisableGroup')==names.count('KeyDisableGroupInvert')==2
    first,second=[i for i,n in enumerate(names) if n=='KeyDisableGroup']
    assert names[first:first+2]==names[second:second+2]==['KeyDisableGroup','KeyDisableGroupInvert']
    assert first<names.index('EnableNightlightOnToggleKey')<second<names.index('LabelFlavourLSB')
    assert 'NightlightColour' not in dict(dlt.DLT_ATTRIBUTES)


@pytest.mark.parametrize('source',['KEY4','KEYM2','KEYEIR4','KEYML5'])
def test_profile_firmware_and_shape_refusals_are_local(source,tmp_path):
    a=arguments(tmp_path,source,'KEYDL4',firmware='2.1.01')
    with pytest.raises(ValueError): prepare(a)
    a.firmware='2.1.00';path=tmp_path/a.target_spec;tree=ET.fromstring(path.read_bytes())
    next(p for p in tree.find('Parameters') if p.findtext('Name')=='LabelFlavourLSB').find('ArraySize').text='7'
    path.write_bytes(ET.tostring(tree))
    with pytest.raises(tweaks.TweakerConversionError,match='LabelFlavourLSB'): prepare(a)


@pytest.mark.parametrize('name,value',[('IndicatorBrightness','256'),('FirstKeyThrowAway','2'),('EnableNightlightOnPCx','oops'),('IndicatorBrightness','1 2')])
def test_unrepresentable_source_model_refuses_before_mutation(name,value,tmp_path):
    p=profile_files(tmp_path,'KEYB2','KEYBL5');p['source_values'][name]=value
    with pytest.raises(tweaks.TweakerConversionError,match='DLT source'):
        tweaks.plan_writes('KEYB2','KEYBL5',p['source_values'],set(UnitSpecStore(tmp_path).load(p['target_spec']).parameters),target_firmware='2.1.00')


def test_empty_aligned_dlt_fields_keep_defaults_even_after_literal_assignment(tmp_path):
    p=profile_files(tmp_path,'KEYML5','KEYDL4')
    p['source_values'].update(LabelFlavourLSB='',LearnMode='',FirstKeyThrowAway='')
    spec=UnitSpecStore(tmp_path).load(p['target_spec'])
    plan=tweaks.plan_writes('KEYML5','KEYDL4',p['source_values'],set(spec.parameters),target_firmware='2.1.00')
    writes=[n for n,_,_ in plan.writes]
    assert 'LabelFlavourLSB' not in writes and 'LearnMode' not in writes and 'FirstKeyThrowAway' not in writes
    values=tweaks.expected_values(spec,{n:p.default for n,p in spec.parameters.items()},plan)
    assert values['LabelFlavourLSB']==(1,)*8 and values['LearnMode']==(0,) and values['FirstKeyThrowAway']==(0,)


@pytest.mark.parametrize('name',['EnableNightlightOnPCx','EnableNightlightOnPA6'])
def test_dlt_model_rejects_unrecovered_extra_nightlight_fields(name,tmp_path):
    args=arguments(tmp_path,'KEYML5','KEYDL4')
    path=tmp_path/args.source_spec
    tree=ET.fromstring(path.read_bytes())
    field=ET.SubElement(tree.find('Parameters'),'Param')
    for key,value in (('Name',name),('Type','bit'),('Address','1600'),('ArraySize','1'),('BitSize','8'),('DefaultValue','1')):
        ET.SubElement(field,key).text=value
    path.write_bytes(ET.tostring(tree))
    with pytest.raises(tweaks.TweakerConversionError,match='source model PP field '+name): prepare(args)


def test_registry_duplicate_exception_is_exact_and_other_agents_remain_strict():
    import sys
    from copy import deepcopy
    sys.path.insert(0,str(ROOT/'toolkit-cli/research'))
    from toolkit_conversion_tweaker_registry import build,validate
    import tempfile
    current=json.loads((ROOT/'toolkit-cli/research/fixtures/toolkit-conversion-tweaker-registry.json').read_text())
    with tempfile.TemporaryDirectory() as folder:
        rows=Path(folder)/'rows.tsv'
        rows.write_text(''.join('\t'.join([r['call_va'],r['source'],r['target'],r['tweaker_class']])+'\n' for r in current['registrations']))
        receipt=build(rows)
    assert validate(receipt)==[]
    assert sum(r['decision']=='admitted' for r in receipt['registrations'])==243
    assert receipt['source_admitted_classes']==['TTweakerDLT','TTweakerKeyToDLT']
    assert all(c not in receipt['native_accepted_classes'] for c in receipt['source_admitted_classes'])
    for name in ('TCBusDynamicLabelInputCGateAgent','TDinRailOutputCGateAgent'):
        bad=deepcopy(receipt)
        bad['agents'][name]['attributes'].append(['UnrelatedDuplicate',True])
        bad['agents'][name]['attributes'].append(['UnrelatedDuplicate',True])
        assert 'duplicate agent attribute in '+name in validate(bad)
