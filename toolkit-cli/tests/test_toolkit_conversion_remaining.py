"""Synthetic complete fresh-model profiles and independent literal conversions."""
from argparse import Namespace
from dataclasses import replace
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
from cbus_toolkit import toolkit_conversion_remaining as family
from cbus_toolkit import toolkit_conversion_tweakers as tweaks
from cbus_toolkit.toolkit_tweaker_workflow import prepare
from cbus_toolkit.unitspec import UnitSpecStore
ROOT = Path(__file__).resolve().parents[2]
VECTOR = json.loads((ROOT/'rust/testdata/vectors/toolkit_conversion_remaining.json').read_text())
PAIRS = [(s,t) for (s,t),c in tweaks.REGISTRY.items() if family.handles(c,s,t)]


def profile_files(directory, source, target):
    """Public invented defaults for all constructor fields; no vendor bytes."""
    directory.mkdir(parents=True,exist_ok=True)
    source_values = {}
    for unit_type,is_source in ((source,True),(target,False)):
        filename,declared = family.specification(unit_type)
        fw = family.unit_firmware(unit_type)
        names = dict(family.ATTRIBUTES[unit_type])
        shapes = {n:('int',1,8) for n in names if n not in ('FirmwareVersion','State','SerialNo','UnitType')}
        shapes.update(Application=('int',2,8),UnitName=('sixbit',8,6),Project=('sixbit',8,6))
        if unit_type in family.DALI_TYPES:
            shapes.update(Burden=('bit',1,8),ClockGenEnable=('bit',1,8))
        elif unit_type == 'SENLL':
            shapes.update({n:('bit',1,8) for n in ('LearnAnyApp','LearnMode','LearnedFlag')})
            shapes['IndicatorFunction']=('int',1,2)
        elif unit_type == 'SENPILL':
            shapes.pop('IndicatorFunction',None);shapes.pop('IndicatorBrightness',None)
            shapes.update(GroupAddress=('int',8,8),DisableIR=('bit',1,8),
                **{n:('bit',1,8) for n in ('LearnAnyApp','LearnMode','LearnedFlag')})
        else:
            shapes.update(GroupAddress=('int',9 if unit_type in family.NEO_TYPES else 4 if unit_type in family.PIR_TYPES else 8,8),
                IndicatorFunction=('int',8 if unit_type in family.NEO_TYPES else 1 if unit_type in family.PIR_TYPES else 4,2),
                **{n:('bit',1,8) for n in ('LearnAnyApp','LearnMode','LearnedFlag')})
            if unit_type in family.NEO_TYPES: shapes['SecondApplicationBlocks']=('int',1,8)
        root=ET.Element('UnitSpecification')
        for key,value in (('Type',declared),('MinVersion','0'),('MaxVersion','9'),('MemorySize','4096')):
            ET.SubElement(root,key).text=value
        params=ET.SubElement(root,'Parameters')
        values={}
        for index,(name,(kind,size,width)) in enumerate(shapes.items()):
            default='TARGET' if name=='UnitName' else 'WFTEST' if name=='Project' else ' '.join(['3' if name=='IndicatorFunction' else '0']*size)
            p=ET.SubElement(params,'Param')
            for key,value in (('Name',name),('Type',kind),('Address',str(index*32)),('ArraySize',str(size)),('BitSize',str(width)),('DefaultValue',default)):
                ET.SubElement(p,key).text=value
            values[name]=default
        (directory/filename).write_bytes(ET.tostring(root))
        if is_source:source_values=values
    source_values.update({n:v for n,v in dict(Application='56 202',UnitAddress='20',UnitName='SOURCE',ClockGenEnable='1',
        IndicatorBrightness='17',LearnMode='0',LearnAnyApp='1',LearnedFlag='1').items() if n in source_values})
    if source in family.NEO_TYPES:
        source_values.update(GroupAddress='10 11 12 13 14 15 16 17 18',SecondApplicationBlocks='5',
            IndicatorFunction='0 1 2 3 0 1 2 3')
    elif source in family.PIR_TYPES:
        source_values.update(GroupAddress='10 11 12 13',IndicatorFunction='0',
            EEPROMLevelStore='1',InfraRedBank='3',LightIndex='17',LightLevel='19',LightLevelStore1='20',LightLevelStore2='21',
            LRCommand='99',BlockAllocation='255',IndicatorBlockAssignment='17',EnableGroupAddress='77',EnableGroupLogic='1')
    elif source == 'SENLL':
        source_values.update(TargetLUX='123',Hystersis='21',LevelGroupAddress='77',OnOffGroupAddress='78',EnableGroupAddress='79',IndicatorFunction='2')
    elif source == 'SENPILL':
        source_values.update(GroupAddress='10 11 12 13 14 15 16 17',DisableIR='1',PECTargetLux='101',PECMarginLux='12',PECEnablerGroup='79',
            **{n:'17' for n in family.JOIN_FIELDS})
    catalog=ET.Element('CBusUnits');units=ET.SubElement(catalog,'Units')
    for unit_type in dict.fromkeys((source,target)):
        unit=ET.SubElement(units,'Unit');ET.SubElement(unit,'CatalogNumber').text='SYNTHETIC'
        rev=ET.SubElement(ET.SubElement(unit,'FirmwareRevisions'),'Revision')
        for name,value in (('UnitType',unit_type),('MinVersion',family.unit_firmware(unit_type)),
                          ('MaxVersion',family.unit_firmware(unit_type)),('UnitSpecName',family.specification(unit_type)[0]),('IsDefault','true')):
            ET.SubElement(rev,name).text=value
    (directory/'cbusunits.xml').write_bytes(ET.tostring(catalog))
    return {'source_spec':family.specification(source)[0],'target_spec':family.specification(target)[0],
        'source_firmware':family.unit_firmware(source),'firmware':family.unit_firmware(target),'source_values':source_values}


def arguments(directory,source,target,**changes):
    p=profile_files(directory,source,target)
    return Namespace(**({'source':'//WFTEST/11/p/20','source_type':source,'target_type':target,
        'source_spec':p['source_spec'],'target_spec':p['target_spec'],'spec_dir':directory,
        'firmware':p['firmware'],'catalog_number':'SYNTHETIC','target_address':21,'tag_name':'Replacement',
        'apply':False,'exclusive_project':False,'expect_plan_sha256':None,'auth_token_file':None}|changes))


def test_every_new_registered_pair_has_creation_and_replacement_admission(tmp_path):
    from cbus_toolkit.toolkit_tweaker_lifecycle import prepare as replace_prepare
    assert len(PAIRS)==36
    for source,target in PAIRS:
        a=arguments(tmp_path/(source+'-'+target),source,target)
        p=prepare(a)
        assert p.source_type==source and p.target_type==target and p.spec_pins
        a.backup_project='BACKUP';a.journal=None
        assert replace_prepare(a).creation.target_type==target


@pytest.mark.parametrize('case',VECTOR['cases'],ids=lambda c:c['id'])
def test_literal_hooks_and_default_preservation(case,tmp_path):
    p=profile_files(tmp_path,case['source'],case['target']);p['source_values'].update(case.get('source_values',{}))
    spec=UnitSpecStore(tmp_path).load(p['target_spec'])
    plan=tweaks.plan_writes(case['source'],case['target'],p['source_values'],set(spec.parameters),target_firmware=p['firmware'])
    actual=tweaks.expected_values(spec,spec.defaults(),plan)
    for name,value in case['expected'].items(): assert actual[name]==tuple(value),(name,plan.as_dict())
    for name in case.get('not_written',[]): assert name not in [n for n,_,_ in plan.writes]
    for name,value in case.get('literal_writes',{}).items():
        assert [(n,v) for n,v,_ in plan.writes if n==name]==[(name,value)]
    assert plan.model_context['fresh_target_model'] is True
    assert plan.model_context['source_firmware']==p['source_firmware']


@pytest.mark.parametrize('source,target',[('KEYC4','KEY4'),('PC_DAL2C','PC_DAL2'),('SENPIROA','SENPIRSS'),('SENLL','SENPILL'),('SENPILL','SENPILL')])
def test_exact_firmware_shape_and_alias_refusals_are_local(source,target,tmp_path):
    a=arguments(tmp_path,source,target,firmware='9.0.00')
    with pytest.raises(ValueError,match='firmware'):prepare(a)
    a.firmware=family.unit_firmware(target)
    path=tmp_path/a.source_spec;tree=ET.fromstring(path.read_bytes())
    next(p for p in tree.find('Parameters') if p.findtext('Name')=='Application').find('ArraySize').text='1'
    path.write_bytes(ET.tostring(tree))
    with pytest.raises(tweaks.TweakerConversionError,match='Application'):prepare(a)


@pytest.mark.parametrize('name,value',[('Application','56'),('Application','56 202 7'),('Application','255 202'),
    ('GroupAddress','1 2 3'),('SecondApplicationBlocks','256'),('SecondApplicationBlocks','-1')])
def test_unestablished_neo_model_refuses(name,value,tmp_path):
    p=profile_files(tmp_path,'KEYC4','KEY4');p['source_values'][name]=value
    with pytest.raises(tweaks.TweakerConversionError):
        tweaks.plan_writes('KEYC4','KEY4',p['source_values'],set(UnitSpecStore(tmp_path).load(p['target_spec']).parameters),target_firmware=p['firmware'])


def test_pir_constructor_lacks_classic_gav_subclass_and_has_exact_tail():
    assert [n for n,_ in family.PIR_ATTRIBUTES][-2:]==['EnableGroupAddress','EnableGroupLogic']
    assert 'GAVBroadcastFlag' not in dict(family.PIR_ATTRIBUTES)
    assert len(family.PIR_ATTRIBUTES)==36


def test_dali_noncommon_constructor_fields_retain_target_defaults(tmp_path):
    p=profile_files(tmp_path,'PC_DAL2','PC_DAL2C');spec=UnitSpecStore(tmp_path).load(p['target_spec'])
    plan=tweaks.plan_writes('PC_DAL2','PC_DAL2C',p['source_values'],set(spec.parameters),target_firmware=p['firmware'])
    assert [n for n,_,_ in plan.writes]==['Application','Project','UnitAddress','UnitName','ClockGenEnable']
    assert 'Burden' not in [n for n,_,_ in plan.writes]
    assert all(n not in [n for n,_,_ in plan.writes] for n,_ in family.DALI_ATTRIBUTES[len(family.PCI_ATTRIBUTES):])


def test_empty_pir_source_field_preserves_target_defaults_after_learning_hook(tmp_path):
    p=profile_files(tmp_path,'SENPIROA','SENPIRSS');p['source_values'].update(GroupAddress='',LearnMode='')
    spec=UnitSpecStore(tmp_path).load(p['target_spec'])
    plan=tweaks.plan_writes('SENPIROA','SENPIRSS',p['source_values'],set(spec.parameters),target_firmware=p['firmware'])
    assert 'GroupAddress' not in [n for n,_,_ in plan.writes]
    assert next(v for n,v,_ in plan.writes if n=='LearnMode')==''


def test_empty_sensor_renamed_field_does_not_clear_mutability(tmp_path):
    p=profile_files(tmp_path,'SENLL','SENPILL');p['source_values']['EnableGroupAddress']=''
    spec=UnitSpecStore(tmp_path).load(p['target_spec'])
    plan=tweaks.plan_writes('SENLL','SENPILL',p['source_values'],set(spec.parameters),target_firmware=p['firmware'])
    assert next(v for n,v,_ in plan.writes if n=='PECEnablerGroup')==''
    assert tweaks.expected_values(spec,spec.defaults(),plan)['PECEnablerGroup']==(0,)


def test_multisensor_constructor_core_neo_bank_rename_and_absent_neopro_fields():
    fields=dict(family.MULTI_ATTRIBUTES)
    assert len(family.MULTI_ATTRIBUTES)==87
    assert 'IRBank' in fields and 'InfraRedBank' not in fields
    assert 'SecondApplicationBlocks' not in fields and 'NightlightColour' not in fields
